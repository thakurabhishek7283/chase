"""Writing the audit trail.

One function, deliberately. Every privileged action funnels through `record`
so the shape of a log entry is decided in a single place, and so adding an
audited action is one call rather than a new opinion about what to store.
"""

import uuid
from typing import Any

from fastapi import Request
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.audit import AuditLog
from app.models.user import User


def client_ip(request: Request | None) -> str | None:
    """The caller's address, as seen by the socket — never a request header.

    This feeds the sign-in and registration rate limiters, so it must not be
    something the caller can choose: reading `X-Forwarded-For` here directly
    would let anyone mint a fresh limiter key per request by sending a random
    value. Behind a reverse proxy, uvicorn's `--proxy-headers` rewrites
    `request.client` from that header — but only for peers listed in
    `FORWARDED_ALLOW_IPS`, which is the one place that trust is decided.
    """
    if request is None or request.client is None:
        return None
    return request.client.host[:45]


async def record(
    session: AsyncSession,
    *,
    actor: User | None,
    action: str,
    target: User | None = None,
    target_user_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    """Append one entry. The caller commits.

    Sharing the caller's transaction is the point: an audit row that commits
    separately can survive an action that rolled back, or — worse — be missing
    for one that did not.
    """
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        action=action,
        target_user_id=target.id if target else target_user_id,
        target_email=target.email if target else None,
        detail=detail or {},
        ip_address=client_ip(request),
    )
    session.add(entry)
    return entry
