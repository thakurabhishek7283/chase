"""Issuing, rotating, and revoking refresh tokens.

The rotation rule in one place, because getting it subtly wrong is how token
rotation becomes theatre:

* every sign-in starts a **family** and issues its first token;
* redeeming a token marks it used and issues its successor in the same family;
* redeeming a token that is *already used* means two parties hold it, so the
  entire family is revoked — the thief and the victim both lose the session,
  which is the only safe move when the server cannot tell them apart.
"""

import uuid
from datetime import UTC, datetime

from sqlmodel import col, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.session import RefreshToken


async def start_family(
    session: AsyncSession, *, jti: str, user_id: uuid.UUID, expires_at: datetime
) -> RefreshToken:
    """Record the first refresh token of a new sign-in."""
    row = RefreshToken(jti=jti, user_id=user_id, family_id=uuid.uuid4(), expires_at=expires_at)
    session.add(row)
    return row


async def continue_family(
    session: AsyncSession,
    *,
    jti: str,
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    expires_at: datetime,
) -> RefreshToken:
    row = RefreshToken(jti=jti, user_id=user_id, family_id=family_id, expires_at=expires_at)
    session.add(row)
    return row


async def get(session: AsyncSession, jti: str) -> RefreshToken | None:
    return await session.get(RefreshToken, jti)


def mark_used(row: RefreshToken) -> None:
    row.used_at = datetime.now(UTC)


async def revoke_family(session: AsyncSession, family_id: uuid.UUID, reason: str) -> int:
    """Kill every unrevoked token descended from one sign-in.

    A bulk UPDATE rather than a load-and-loop: this runs on the reuse-detection
    path, where the goal is to close the window as fast as possible, and the
    rows are not needed in memory afterwards.
    """
    result = await session.exec(
        update(RefreshToken)
        .where(
            col(RefreshToken.family_id) == family_id,
            col(RefreshToken.revoked_at).is_(None),
        )
        .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
    )
    return int(result.rowcount or 0)


async def revoke_all_for_user(session: AsyncSession, user_id: uuid.UUID, reason: str) -> int:
    """Used by logout-everywhere, password change, and deactivation.

    `users.token_version` already invalidates the tokens cryptographically;
    this closes the rows out too, so the table reflects reality instead of
    accumulating live-looking tokens that no longer work.
    """
    result = await session.exec(
        update(RefreshToken)
        .where(
            col(RefreshToken.user_id) == user_id,
            col(RefreshToken.revoked_at).is_(None),
        )
        .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
    )
    return int(result.rowcount or 0)


async def purge_expired(session: AsyncSession, *, before: datetime | None = None) -> int:
    """Drop rows no token can reference any more.

    Nothing depends on this running — an expired row is already unusable, since
    the JWT's own `exp` is checked first. It exists so the table does not grow
    forever on a long-lived instance.
    """
    cutoff = before or datetime.now(UTC)
    rows = (
        await session.exec(select(RefreshToken).where(col(RefreshToken.expires_at) < cutoff))
    ).all()
    for row in rows:
        await session.delete(row)
    return len(rows)
