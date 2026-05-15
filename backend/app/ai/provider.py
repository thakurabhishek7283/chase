"""Resolve the configured LLM provider into a Pydantic AI model.

The ATS scorer, the autofix loop, and the LaTeX tailoring agent are all
provider-agnostic — they take an `Agent` and never name a vendor. This module is
the single place that decides which vendor those agents talk to, so adding a
provider means touching this file and the two mappings in `core/config.py`,
not every agent.

**Why the key is passed explicitly rather than left to the environment.**
Pydantic AI will happily read `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` from the
process environment, and returning a bare `"provider:model"` string relies on
exactly that. But `pydantic-settings` loads `backend/.env` into the `Settings`
object *without* exporting anything to `os.environ` — so a key configured the
way the README tells you to configure it would be invisible to the SDK. Handing
the credential to the provider directly closes that gap, and the bare-identifier
path is kept for deployments that really do use environment variables.
"""

from typing import TYPE_CHECKING

from app.core.config import get_settings

if TYPE_CHECKING:
    from pydantic_ai.models import Model


def resolve_model() -> "Model | str":
    """Build the model the agents should use.

    Imports are deferred to call time so the app still imports cleanly when a
    provider's SDK is absent or no credentials are present — the routers turn
    that into a 503 with an actionable message rather than an import crash.
    """
    settings = get_settings()
    identifier = settings.llm_model_identifier
    api_key = settings.llm_api_key

    if not api_key:
        # Nothing configured locally: fall back to the identifier and let the
        # SDK pick the credential up from the environment.
        return identifier

    if settings.llm_provider == "google":
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider

        return GoogleModel(settings.ats_model, provider=GoogleProvider(api_key=api_key))

    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    return AnthropicModel(settings.ats_model, provider=AnthropicProvider(api_key=api_key))


def has_llm_credentials() -> bool:
    """True when the active provider has a usable credential from any source."""
    import os

    settings = get_settings()
    return bool(settings.llm_api_key or os.environ.get(settings.llm_env_var))
