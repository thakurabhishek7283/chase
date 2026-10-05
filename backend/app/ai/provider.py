"""Resolve the configured Gemini model into a Pydantic AI model.

The intake, review and revision agents are all model-agnostic — each takes an
injectable `Agent` and never names a vendor. This module is the single place
that decides which model those agents talk to, so a model or credential change
means touching this file and `core/config.py`, not every agent.

**Why the key is passed explicitly rather than left to the environment.**
Pydantic AI will happily read `GOOGLE_API_KEY` from the process environment,
and returning a bare `"google-gla:<model>"` string relies on exactly that. But
`pydantic-settings` loads `backend/.env` into the `Settings` object *without*
exporting anything to `os.environ` — so a key configured the way the README
tells you to configure it would be invisible to the SDK. Handing the credential
to the provider directly closes that gap, and the bare-identifier path is kept
for deployments that really do use environment variables.
"""

import os
from typing import TYPE_CHECKING

from app.core.config import LLM_API_KEY_ENV_VAR, get_settings

if TYPE_CHECKING:
    from pydantic_ai.models import Model


def resolve_model() -> "Model | str":
    """Build the model the agents should use.

    Imports are deferred to call time so the app still imports cleanly when the
    Google SDK is absent or no credentials are present — the routers turn that
    into a 503 with an actionable message rather than an import crash.
    """
    settings = get_settings()

    if not settings.google_api_key:
        # Nothing configured locally: fall back to the identifier and let the
        # SDK pick the credential up from the environment.
        return settings.llm_model_identifier

    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.providers.google import GoogleProvider

    return GoogleModel(settings.ats_model, provider=GoogleProvider(api_key=settings.google_api_key))


def has_llm_credentials() -> bool:
    """True when a Gemini key is configured, from `.env` or the environment."""
    return bool(get_settings().google_api_key or os.environ.get(LLM_API_KEY_ENV_VAR))
