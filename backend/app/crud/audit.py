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
    """Best-effort caller address.

    `X-Forwarded-For` is honoured because this app is expected to sit behind a
    reverse proxy, where `request.client` is the proxy and therefore useless.
    It is also trivially spoofable when *not* behind one — which is why it
    lands in an audit note and never in an authorization decision.
    """
    if request is None:
        return None
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.client.host[:45] if request.client else None


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
