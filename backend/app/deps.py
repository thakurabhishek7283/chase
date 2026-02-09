from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def require_llm_key() -> None:
    """Fail fast with a clear message rather than a provider stack trace.

    The message names the variable for the *active* provider, so switching
    `LLM_PROVIDER` to google does not leave users hunting for an Anthropic key.
    """
    from app.ai.provider import has_llm_credentials

    if not has_llm_credentials():
        settings = get_settings()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"This feature needs a {settings.llm_provider} API key. Set "
                f"{settings.llm_env_var} in backend/.env (or the environment) "
                "and restart the server."
            ),
        )
