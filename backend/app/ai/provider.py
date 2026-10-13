"""Resolve the configured LLM into a Pydantic AI model.

The intake, review and revision agents are all model-agnostic — each takes an
injectable `Agent` and never names a vendor. This module is the single place
that decides which model those agents talk to, so a model or credential change
means touching this file and `core/config.py`, not every agent.

Two backends are supported: Gemini, and any OpenAI-compatible endpoint spoken
to over the Responses API (OpenAI itself, or Azure OpenAI's `/openai/v1` route).
`Settings.active_llm_provider` decides between them.

**Why the key is passed explicitly rather than left to the environment.**
Pydantic AI will happily read `GOOGLE_API_KEY` or `OPENAI_API_KEY` from the
process environment, and returning a bare `"google-gla:<model>"` string relies
on exactly that. But `pydantic-settings` loads `backend/.env` into the
`Settings` object *without* exporting anything to `os.environ` — so a key
configured the way the README tells you to configure it would be invisible to
the SDK. Handing the credential to the provider directly closes that gap, and
the bare-identifier path is kept for deployments that really do use
environment variables.
"""

import os
from typing import TYPE_CHECKING

from app.core.config import LLM_API_KEY_ENV_VAR, OPENAI_API_KEY_ENV_VAR, Settings, get_settings

if TYPE_CHECKING:
    from pydantic_ai.models import Model


def _openai_model(settings: Settings) -> "Model":
    """An OpenAI-compatible model over the Responses API.

    The Responses API is used rather than Chat Completions because it is the
    one reasoning models are served through on Azure's v1 route, and it carries
    the reasoning-effort control.
    """
    if not settings.openai_model:
        raise ValueError("OPENAI_MODEL is not set, so no OpenAI model can be resolved.")

    from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
    from pydantic_ai.providers.openai import OpenAIProvider

    model_settings = None
    if settings.openai_reasoning:
        model_settings = OpenAIResponsesModelSettings(
            openai_reasoning_effort=settings.openai_reasoning
        )

    return OpenAIResponsesModel(
        settings.openai_model,
        provider=OpenAIProvider(
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key or os.environ.get(OPENAI_API_KEY_ENV_VAR),
        ),
        settings=model_settings,
    )


def resolve_model() -> "Model | str":
    """Build the model the agents should use.

    Imports are deferred to call time so the app still imports cleanly when the
    SDKs are absent or no credentials are present — the routers turn that into
    a 503 with an actionable message rather than an import crash.
    """
    settings = get_settings()

    if settings.active_llm_provider == "openai":
        return _openai_model(settings)

    if not settings.google_api_key:
        # Nothing configured locally: fall back to the identifier and let the
        # SDK pick the credential up from the environment.
        return settings.llm_model_identifier

    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.providers.google import GoogleProvider

    return GoogleModel(
        settings.ats_model, provider=GoogleProvider(api_key=settings.google_api_key)
    )


def has_llm_credentials() -> bool:
    """True when the active provider has what it needs, from `.env` or the environment."""
    settings = get_settings()
    if settings.active_llm_provider == "openai":
        has_key = bool(settings.openai_api_key or os.environ.get(OPENAI_API_KEY_ENV_VAR))
        return has_key and bool(settings.openai_model)
    return bool(settings.google_api_key or os.environ.get(LLM_API_KEY_ENV_VAR))


def llm_credentials_hint() -> str:
    """What to set when `has_llm_credentials()` is false, for the 503 the routes return."""
    if get_settings().active_llm_provider == "openai":
        return (
            f"This feature needs an OpenAI-compatible model. Set {OPENAI_API_KEY_ENV_VAR} "
            "and OPENAI_MODEL (and OPENAI_BASE_URL for Azure OpenAI) in backend/.env "
            "(or the environment) and restart the server."
        )
    return (
        f"This feature needs a Gemini API key. Set {LLM_API_KEY_ENV_VAR} in "
        "backend/.env (or the environment) and restart the server."
    )
