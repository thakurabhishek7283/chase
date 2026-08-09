"""Append-only record of privileged actions.

Everything here is an action one account takes *against another* — granting a
role, deactivating an account, deleting one. Those are precisely the actions
that cannot be reconstructed afterwards from the rows they touch: a user whose
role reads `admin` does not say who promoted them, and a deleted account leaves
nothing behind to say who deleted it.

The table is written but never updated or deleted by application code. There is
no API to read it either — an audit log an admin can edit through the same API
they are audited by is decoration. Read it with psql.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Uuid
from sqlmodel import Column, Field, SQLModel

#: The privileged actions worth a permanent record. Kept as a tuple feeding a
#: CHECK constraint, matching how `moderation.py` handles statuses.
AUDIT_ACTIONS: tuple[str, ...] = (
    "user.create",
    "user.delete",
    "user.role_change",
    "user.activate",
    "user.deactivate",
    "moderation.purge",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(
            "action IN ({})".format(", ".join(f"'{a}'" for a in AUDIT_ACTIONS)),
            name="ck_audit_logs_action",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    #: Who acted. `ON DELETE SET NULL` rather than a plain FK: deleting an
    #: account must not be blocked by — nor cascade away — the record of what
    #: that account did. `actor_email` is what keeps the entry readable
    #: afterwards. `target_user_id` carries no FK at all, for the same reason:
    #: the most important thing it points at is a row that no longer exists.
    actor_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    #: Denormalised on purpose. An id alone is useless once the row it points
    #: at is gone, which is exactly the case a delete audit exists to explain.
    actor_email: str | None = Field(default=None, max_length=255)
    action: str = Field(max_length=32, index=True)
    target_user_id: uuid.UUID | None = Field(default=None, index=True)
    target_email: str | None = Field(default=None, max_length=255)
    #: Free-form specifics: the old and new role, the retention window.
    detail: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    ip_address: str | None = Field(default=None, max_length=45)  # fits IPv6
    created_at: datetime = Field(
        default_factory=_utcnow, sa_type=DateTime(timezone=True), index=True
    )
