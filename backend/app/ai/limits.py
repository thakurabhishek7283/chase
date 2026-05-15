"""Survive provider rate limits instead of failing the request.

Gemini's free tier allows 5 requests per minute per model. The autofix loop
spends two calls per iteration and scored tailoring spends three, so a single
`/ats/autofix` or `/latex/tailor` call can exhaust a minute's budget on its own
and 429 halfway through — losing the work already paid for.

Google returns the wait it wants in a `RetryInfo` detail on the error body.
Honouring that number is strictly better than a guessed backoff: it is the
provider telling us exactly when the window reopens. The exponential fallback
only applies when no such hint is present.

This turns a hard failure into a slow success, which is the difference between
"works on a paid key" and "works". It is deliberately *not* a rate limiter —
`ARCHITECTURE.md` §15 still lists per-user spend ceilings as an open gap.
"""

import asyncio
from typing import Any, TypeVar

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError

from app.core.config import get_settings

T = TypeVar("T")


def retry_after_seconds(error: ModelHTTPError) -> float | None:
    """Extract the provider's requested wait, if it gave one.

    Google nests it as `error.details[].retryDelay = '46s'`. The body arrives as
    a dict from the Google SDK but as a string from some providers, so both
    shapes are handled rather than assumed.
    """
    body: Any = getattr(error, "body", None)
    if isinstance(body, dict):
        details = body.get("error", {}).get("details", [])
        for detail in details if isinstance(details, list) else []:
            delay = detail.get("retryDelay") if isinstance(detail, dict) else None
            if isinstance(delay, str) and delay.endswith("s"):
                try:
                    return float(delay[:-1])
                except ValueError:
                    continue
    if isinstance(body, str):
        import re

        match = re.search(r"retryDelay['\"]?:\s*['\"](\d+(?:\.\d+)?)s", body)
        if match:
            return float(match.group(1))
    return None


def is_rate_limited(error: Exception) -> bool:
    return isinstance(error, ModelHTTPError) and error.status_code == 429


async def run_agent(agent: Agent, prompt: str, **kwargs: Any):
    """Run an agent, waiting out rate limits rather than surfacing them.

    Only 429s are retried. Every other error — a bad key, a schema violation, a
    model that does not exist — is a real failure that retrying would only
    delay, so it propagates immediately.
    """
    settings = get_settings()
    attempts = max(1, settings.llm_max_retries + 1)
    last_error: ModelHTTPError | None = None

    for attempt in range(attempts):
        try:
            return await agent.run(prompt, **kwargs)
        except ModelHTTPError as exc:
            if not is_rate_limited(exc) or attempt == attempts - 1:
                raise
            last_error = exc
            hinted = retry_after_seconds(exc)
            # +1s of headroom: the provider's window is measured from its own
            # clock, and waking a hair early just burns another attempt.
            wait = min(
                hinted + 1.0 if hinted is not None else 2.0 ** (attempt + 1),
                settings.llm_retry_max_wait_seconds,
            )
            await asyncio.sleep(wait)

    raise last_error  # pragma: no cover - loop always returns or raises above
