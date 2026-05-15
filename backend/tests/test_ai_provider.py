import pytest
from pydantic_ai.exceptions import ModelHTTPError

from app.ai.limits import is_rate_limited, retry_after_seconds, run_agent
from app.core.config import Settings
from app.embeddings import build_provider
from app.embeddings.base import EmbeddingError
from app.embeddings.remote import GeminiEmbeddingProvider

RATE_LIMIT_BODY = {
    "error": {
        "code": 429,
        "message": "You exceeded your current quota",
        "status": "RESOURCE_EXHAUSTED",
        "details": [
            {"@type": "type.googleapis.com/google.rpc.Help", "links": []},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "46s"},
        ],
    }
}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


# --- provider selection ------------------------------------------------------


def test_default_provider_is_anthropic() -> None:
    settings = _settings()
    assert settings.llm_provider == "anthropic"
    assert settings.llm_model_identifier == "anthropic:claude-opus-5"
    assert settings.llm_env_var == "ANTHROPIC_API_KEY"


def test_google_provider_uses_the_gla_prefix() -> None:
    # Pydantic AI addresses the Gemini API as `google-gla`, not `google`.
    settings = _settings(llm_provider="google", ats_model="gemini-3.5-flash")
    assert settings.llm_model_identifier == "google-gla:gemini-3.5-flash"
    assert settings.llm_env_var == "GOOGLE_API_KEY"


def test_llm_api_key_follows_the_active_provider() -> None:
    both = {"anthropic_api_key": "sk-ant", "google_api_key": "gk"}
    assert _settings(llm_provider="anthropic", **both).llm_api_key == "sk-ant"
    assert _settings(llm_provider="google", **both).llm_api_key == "gk"


def test_resolve_model_falls_back_to_an_identifier_without_a_key(monkeypatch) -> None:
    # No credential configured: hand back the string so the SDK can still read
    # the environment, and so importing never requires a key.
    from app.ai import provider as provider_module

    monkeypatch.setattr(provider_module, "get_settings", lambda: _settings())
    assert provider_module.resolve_model() == "anthropic:claude-opus-5"


def test_resolve_model_passes_the_key_to_the_provider(monkeypatch) -> None:
    # The bug this guards: pydantic-settings loads backend/.env into Settings
    # but never exports it, so an env-reading SDK would not see the key.
    from app.ai import provider as provider_module

    monkeypatch.setattr(
        provider_module,
        "get_settings",
        lambda: _settings(
            llm_provider="google", ats_model="gemini-3.5-flash", google_api_key="test-key"
        ),
    )
    model = provider_module.resolve_model()

    assert not isinstance(model, str)
    assert model.model_name == "gemini-3.5-flash"


# --- rate-limit handling -----------------------------------------------------


def test_retry_delay_is_read_from_the_providers_own_hint() -> None:
    error = ModelHTTPError(status_code=429, model_name="gemini-3.5-flash", body=RATE_LIMIT_BODY)
    assert retry_after_seconds(error) == 46.0


def test_retry_delay_is_read_from_a_string_body() -> None:
    error = ModelHTTPError(
        status_code=429, model_name="m", body="{'retryDelay': '12s', 'status': 'X'}"
    )
    assert retry_after_seconds(error) == 12.0


def test_retry_delay_is_none_when_the_provider_gives_no_hint() -> None:
    error = ModelHTTPError(status_code=429, model_name="m", body={"error": {"code": 429}})
    assert retry_after_seconds(error) is None


def test_only_429_counts_as_rate_limited() -> None:
    assert is_rate_limited(ModelHTTPError(status_code=429, model_name="m", body={}))
    assert not is_rate_limited(ModelHTTPError(status_code=401, model_name="m", body={}))
    assert not is_rate_limited(ValueError("nope"))


class _FlakyAgent:
    """Raises 429 for the first `failures` calls, then succeeds."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def run(self, prompt: str, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise ModelHTTPError(status_code=429, model_name="m", body=RATE_LIMIT_BODY)
        return "ok"


@pytest.fixture
def no_sleep(monkeypatch):
    """Make the backoff instant so tests do not actually wait 46 seconds."""
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("app.ai.limits.asyncio.sleep", fake_sleep)
    return slept


async def test_run_agent_waits_out_a_rate_limit_and_succeeds(no_sleep, monkeypatch) -> None:
    monkeypatch.setattr("app.ai.limits.get_settings", lambda: _settings(llm_max_retries=3))
    agent = _FlakyAgent(failures=2)

    assert await run_agent(agent, "prompt") == "ok"
    assert agent.calls == 3
    # Honours the provider's 46s hint (plus a second of headroom), rather than
    # guessing a backoff.
    assert no_sleep == [47.0, 47.0]


async def test_run_agent_respects_the_configured_wait_ceiling(no_sleep, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.ai.limits.get_settings",
        lambda: _settings(llm_max_retries=2, llm_retry_max_wait_seconds=5.0),
    )
    await run_agent(_FlakyAgent(failures=1), "prompt")
    assert no_sleep == [5.0]


async def test_run_agent_gives_up_after_the_retry_budget(no_sleep, monkeypatch) -> None:
    monkeypatch.setattr("app.ai.limits.get_settings", lambda: _settings(llm_max_retries=2))
    agent = _FlakyAgent(failures=99)

    with pytest.raises(ModelHTTPError):
        await run_agent(agent, "prompt")
    assert agent.calls == 3  # initial attempt + 2 retries


async def test_run_agent_does_not_retry_a_real_failure(no_sleep, monkeypatch) -> None:
    # A bad key is not going to fix itself; retrying only delays the error.
    monkeypatch.setattr("app.ai.limits.get_settings", lambda: _settings(llm_max_retries=3))

    class Unauthorized:
        calls = 0

        async def run(self, prompt: str, **kwargs):
            Unauthorized.calls += 1
            raise ModelHTTPError(status_code=401, model_name="m", body={})

    with pytest.raises(ModelHTTPError):
        await run_agent(Unauthorized(), "prompt")
    assert Unauthorized.calls == 1
    assert no_sleep == []


# --- Gemini embeddings -------------------------------------------------------


def test_gemini_embedding_provider_is_wired_into_the_factory() -> None:
    provider = build_provider(
        _settings(embedding_provider="gemini", google_api_key="k", embedding_dim=768)
    )
    assert isinstance(provider, GeminiEmbeddingProvider)
    assert provider.dimension == 768


def test_gemini_embedding_provider_requires_a_key() -> None:
    with pytest.raises(EmbeddingError, match="GOOGLE_API_KEY"):
        build_provider(_settings(embedding_provider="gemini"))


def test_truncated_gemini_vectors_are_renormalised() -> None:
    # pgvector's cosine ops assume unit vectors; gemini-embedding-001 does not
    # renormalise when truncated, so the provider must.
    unit = GeminiEmbeddingProvider._unit([3.0, 4.0])
    assert unit == pytest.approx([0.6, 0.8])
    assert sum(v * v for v in unit) == pytest.approx(1.0)


def test_normalising_a_zero_vector_does_not_divide_by_zero() -> None:
    assert GeminiEmbeddingProvider._unit([0.0, 0.0]) == [0.0, 0.0]


async def test_gemini_embedding_provider_returns_nothing_for_no_input() -> None:
    provider = GeminiEmbeddingProvider("k", "gemini-embedding-2", 768)
    assert await provider.embed([]) == []
