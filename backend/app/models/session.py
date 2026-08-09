"""Server-side record of issued refresh tokens.

`users.token_version` already revokes *every* session at once, which is the
right tool for a password change. It cannot express "this one token was
stolen", because it cannot tell two tokens apart — and it cannot notice that a
token was redeemed twice, which is the only signal a server gets that a refresh
token has been copied.

So each refresh token gets a row. Rotation retires the old row and issues a new
one in the same **family**: a chain of tokens descending from one sign-in.
Presenting a token that was already redeemed means two parties hold the same
credential, and since the server cannot tell which one is the legitimate user,
the whole family is revoked and both are forced to sign in again.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Uuid
from sqlmodel import Column, Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RefreshToken(SQLModel, table=True):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        # Reuse detection revokes by family, and expiry sweeps by date; both
        # are frequent enough to be worth an index.
        Index("ix_refresh_tokens_family_id", "family_id"),
        Index("ix_refresh_tokens_expires_at", "expires_at"),
    )

    #: The token's `jti` claim. This is the primary key rather than a surrogate
    #: id: the claim *is* the identity, and one row per jti is exactly the
    #: constraint we want the database to enforce.
    jti: str = Field(max_length=64, primary_key=True)
    #: Cascades: a deleted account's tokens have nothing left to authenticate,
    #: and leaving them behind would block the delete on the FK.
    user_id: uuid.UUID = Field(
        sa_column=Column(
            Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    #: Shared by every token descended from a single sign-in.
    family_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    #: Set when the token is redeemed. A second redemption of the same jti is
    #: the reuse signal.
    used_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    revoked_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    #: Why it was revoked — "rotated", "reuse-detected", or "logout". Kept for
    #: the operator reading the table after an incident, not for the code.
    revoked_reason: str | None = Field(default=None, max_length=32)
    #: Mirrors the JWT's own `exp`, so expired rows can be swept without
    #: decoding every token.
    expires_at: datetime = Field(sa_type=DateTime(timezone=True))
    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))

    @property
    def is_live(self) -> bool:
        """Redeemable right now: never used, never revoked, not expired."""
        if self.used_at is not None or self.revoked_at is not None:
            return False
        expires = self.expires_at
        if expires.tzinfo is None:  # a naive value read back from Postgres
            expires = expires.replace(tzinfo=timezone.utc)
        return expires > datetime.now(timezone.utc)
