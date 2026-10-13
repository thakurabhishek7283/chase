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


# --- OpenAI-compatible provider ---------------------------------------------

AZURE_URL = "https://example.cognitiveservices.azure.com/openai/v1"


def _openai(**overrides) -> Settings:
    return _settings(
        openai_api_key="test-key",
        openai_base_url=AZURE_URL,
        openai_model="gpt-6.1-sol",
        **overrides,
    )


def test_auto_picks_gemini_unless_openai_is_fully_configured() -> None:
    assert _settings().active_llm_provider == "google"
    assert _settings(openai_api_key="k").active_llm_provider == "google"
    assert _settings(openai_model="m").active_llm_provider == "google"
    assert _openai().active_llm_provider == "openai"


def test_an_explicit_provider_overrides_auto() -> None:
    assert _openai(llm_provider="google").active_llm_provider == "google"
    assert _settings(llm_provider="openai").active_llm_provider == "openai"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", "medium"),
        ("true", "medium"),
        ("High", "high"),
        ("low", "low"),
        ("0", None),
        ("false", None),
        ("", None),
        (None, None),
    ],
)
def test_reasoning_setting_is_normalised(raw, expected) -> None:
    assert _settings(openai_reasoning=raw).openai_reasoning == expected


def test_an_unrecognised_reasoning_value_is_refused_at_load() -> None:
    with pytest.raises(ValueError, match="OPENAI_REASONING"):
        _settings(openai_reasoning="extreme")


def test_resolve_model_builds_a_responses_model_for_the_configured_endpoint(monkeypatch) -> None:
    from pydantic_ai.models.openai import OpenAIResponsesModel

    from app.ai import provider as provider_module

    monkeypatch.setattr(provider_module, "get_settings", lambda: _openai(openai_reasoning="1"))
    model = provider_module.resolve_model()

    assert isinstance(model, OpenAIResponsesModel)
    assert model.model_name == "gpt-6.1-sol"
    assert str(model.client.base_url).startswith(AZURE_URL)
    assert model.settings["openai_reasoning_effort"] == "medium"


def test_resolve_model_sends_no_reasoning_control_when_it_is_off(monkeypatch) -> None:
    from app.ai import provider as provider_module

    monkeypatch.setattr(provider_module, "get_settings", lambda: _openai())
    model = provider_module.resolve_model()

    assert not (model.settings or {}).get("openai_reasoning_effort")


def test_openai_credentials_need_both_a_key_and_a_model(monkeypatch) -> None:
    from app.ai import provider as provider_module

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        provider_module, "get_settings", lambda: _settings(llm_provider="openai", openai_model="m")
    )
    assert not provider_module.has_llm_credentials()

    monkeypatch.setattr(provider_module, "get_settings", lambda: _openai())
    assert provider_module.has_llm_credentials()


def test_the_missing_credentials_hint_names_the_active_providers_variables(monkeypatch) -> None:
    from app.ai import provider as provider_module

    monkeypatch.setattr(provider_module, "get_settings", lambda: _settings())
    assert "GOOGLE_API_KEY" in provider_module.llm_credentials_hint()

    monkeypatch.setattr(
        provider_module, "get_settings", lambda: _settings(llm_provider="openai")
    )
    hint = provider_module.llm_credentials_hint()
    assert "OPENAI_API_KEY" in hint and "OPENAI_MODEL" in hint


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
