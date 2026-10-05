from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.core.config import get_settings
from app.crud import audit as audit_crud
from app.crud import company as company_crud
from app.crud import job_profile as job_crud
from app.crud import session as session_crud
from app.deps import AdminUser, SessionDep

router = APIRouter(prefix="/admin", tags=["admin"])


class PurgeSummary(BaseModel):
    companies_deleted: int
    job_profiles_deleted: int
    expired_sessions_deleted: int
    older_than: datetime


@router.post("/purge-rejected", response_model=PurgeSummary)
async def purge_rejected(
    session: SessionDep,
    admin: AdminUser,
    request: Request,
    retention_days: int | None = Query(
        default=None,
        ge=0,
        le=3650,
        description="Override the configured retention window, in days.",
    ),
) -> PurgeSummary:
    """Delete rejected companies and job postings past their retention window.

    Also sweeps refresh tokens that have expired. They are already unusable —
    the JWT's own `exp` is checked before the table is consulted — so this is
    housekeeping, folded into the existing cleanup route rather than given a
    cron job of its own.
    """
    settings = get_settings()
    days = retention_days if retention_days is not None else settings.rejected_retention_days
    cutoff = datetime.now(UTC) - timedelta(days=days)

    summary = PurgeSummary(
        companies_deleted=await company_crud.purge_rejected(session, cutoff),
        job_profiles_deleted=await job_crud.purge_rejected(session, cutoff),
        expired_sessions_deleted=await session_crud.purge_expired(session),
        older_than=cutoff,
    )
    await audit_crud.record(
        session,
        actor=admin,
        action="moderation.purge",
        detail={
            "retention_days": days,
            "companies_deleted": summary.companies_deleted,
            "job_profiles_deleted": summary.job_profiles_deleted,
        },
        request=request,
    )
    await session.commit()
    return summary
