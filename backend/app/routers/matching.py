import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import select

from app.core.config import get_settings
from app.deps import AdminUser, CurrentUser, SessionDep
from app.embeddings import EmbeddingError, get_embedding_provider
from app.models.company import Company
from app.models.job_profile import JobProfile
from app.models.user import User
from app.schemas.matching import JobMatch, ReindexSummary
from app.services import matching

router = APIRouter(tags=["matching"])


@router.post("/matching/reindex", response_model=ReindexSummary)
async def reindex_embeddings(session: SessionDep, admin: AdminUser) -> ReindexSummary:
    """(Re)embed every approved job profile and user career goal.

    Admin-only: it walks the entire corpus and spends an embedding call per
    changed row, which is not a cost any individual user should be able to
    trigger for the whole instance.

    Idempotent — entities whose source text and provider are unchanged are
    skipped without spending an embedding call.
    """
    settings = get_settings()
    try:
        provider = get_embedding_provider()
    except EmbeddingError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    # Only approved postings are indexed. A pending submission is visible to
    # its contributor alone, so embedding it would surface an unreviewed row in
    # every other user's match list.
    jobs = (await session.exec(select(JobProfile).where(JobProfile.status == "approved"))).all()
    users = (await session.exec(select(User).where(User.is_active))).all()

    try:
        for job in jobs:
            await matching.upsert_embedding(
                session,
                provider,
                settings,
                entity_type="job_profile",
                entity_id=job.id,
                source_text=matching.build_job_profile_text(job),
            )
        indexed_users = 0
        for user in users:
            if not user.career_goals:
                continue
            await matching.upsert_embedding(
                session,
                provider,
                settings,
                entity_type="user_career_goals",
                entity_id=user.id,
                source_text=user.career_goals,
            )
            indexed_users += 1
    except (EmbeddingError, matching.VectorSearchUnavailableError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    return ReindexSummary(job_profiles_indexed=len(jobs), users_indexed=indexed_users)


@router.get("/users/{user_id}/job-matches", response_model=list[JobMatch])
async def job_matches(
    user_id: uuid.UUID,
    session: SessionDep,
    current: CurrentUser,
    limit: int = Query(default=10, ge=1, le=50),
) -> list[JobMatch]:
    """Rank job profiles by semantic similarity to the caller's career goals.

    This is the "companies you should chase" query from the blueprint.

    Self-only — not even admins. Career goals are the most personal field on
    the user record, and matching them is a service to that user rather than
    anything moderation needs. The guard here is therefore *not*
    `require_self_or_admin`: admin is a moderation role in this app, and
    nothing in moderating shared company data requires reading who wants to
    leave their job.
    """
    if user_id != current.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    user = current
    if not user.career_goals:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This user has no career goals set, so there is nothing to match against.",
        )

    settings = get_settings()
    try:
        provider = get_embedding_provider()
        query_vector = await provider.embed_one(user.career_goals)
    except EmbeddingError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    try:
        hits = await matching.find_similar(
            session, query_vector, entity_type="job_profile", limit=limit
        )
    except matching.VectorSearchUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    if not hits:
        return []

    job_ids = [job_id for job_id, _ in hits]
    # Re-filter on approval rather than trusting the index. A posting that was
    # approved when it was embedded may have been rejected since, and the
    # vector table has no idea.
    jobs = {
        job.id: job
        for job in (
            await session.exec(
                select(JobProfile).where(
                    JobProfile.id.in_(job_ids),  # type: ignore[attr-defined]
                    JobProfile.status == "approved",
                )
            )
        ).all()
    }
    company_ids = {job.company_id for job in jobs.values()}
    companies = {
        company.id: company
        for company in (
            await session.exec(select(Company).where(Company.id.in_(company_ids)))  # type: ignore[attr-defined]
        ).all()
    }

    matches: list[JobMatch] = []
    for job_id, similarity in hits:
        job = jobs.get(job_id)
        if job is None:
            continue  # embedding outlived its job profile
        company = companies.get(job.company_id)
        if company is None:
            continue
        matches.append(JobMatch(similarity=similarity, job_profile=job, company=company))
    return matches
