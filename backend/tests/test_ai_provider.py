import pytest
from pydantic_ai.exceptions import ModelHTTPError

from app.ai.limits import is_rate_limited, retry_after_seconds, run_agent
from app.core.config import Settings

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


# --- model resolution ---------------------------------------------------------


def test_the_model_identifier_uses_the_gla_prefix() -> None:
    # Pydantic AI addresses the Gemini API as `google-gla`, not `google`.
    assert _settings().llm_model_identifier == "google-gla:gemini-3.5-flash"
    assert _settings(ats_model="gemini-2.5-pro").llm_model_identifier == "google-gla:gemini-2.5-pro"


def test_resolve_model_falls_back_to_an_identifier_without_a_key(monkeypatch) -> None:
    # No credential configured: hand back the string so the SDK can still read
    # the environment, and so importing never requires a key.
    from app.ai import provider as provider_module

    monkeypatch.setattr(provider_module, "get_settings", lambda: _settings())
    assert provider_module.resolve_model() == "google-gla:gemini-3.5-flash"


def test_resolve_model_passes_the_key_to_the_provider(monkeypatch) -> None:
    # The bug this guards: pydantic-settings loads backend/.env into Settings
    # but never exports it, so an env-reading SDK would not see the key.
    from app.ai import provider as provider_module

    monkeypatch.setattr(
        provider_module,
        "get_settings",
        lambda: _settings(ats_model="gemini-3.5-flash", google_api_key="test-key"),
    )
    model = provider_module.resolve_model()

    assert not isinstance(model, str)
    assert model.model_name == "gemini-3.5-flash"


def test_has_llm_credentials_reads_the_environment_too(monkeypatch) -> None:
    from app.ai import provider as provider_module

    monkeypatch.setattr(provider_module, "get_settings", lambda: _settings())
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert not provider_module.has_llm_credentials()

    monkeypatch.setenv("GOOGLE_API_KEY", "from-the-environment")
    assert provider_module.has_llm_credentials()


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
