import uuid

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from sqlmodel import select

from app.core.config import get_settings
from app.deps import SessionDep
from app.embeddings import EmbeddingError, get_embedding_provider
from app.models.company import Company
from app.models.job_profile import JobProfile
from app.models.user import User
from app.schemas.matching import JobMatch, ReindexSummary, ResumeParseResult
from app.services import matching
from app.services.pdf_parser import PdfParseError, extract_text, to_markdown

router = APIRouter(tags=["matching"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/resumes/parse-pdf", response_model=ResumeParseResult)
async def parse_resume_pdf(file: UploadFile = File(...)) -> ResumeParseResult:
    """Extract Markdown text from a resume PDF without persisting anything.

    Kept separate from resume creation so the client can show the user what was
    extracted and let them correct it before saving.
    """
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit.",
        )
    try:
        text = extract_text(data)
    except PdfParseError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    markdown = to_markdown(text)
    return ResumeParseResult(
        filename=file.filename or "resume.pdf",
        character_count=len(markdown),
        content_markdown=markdown,
    )


@router.post("/matching/reindex", response_model=ReindexSummary)
async def reindex_embeddings(session: SessionDep) -> ReindexSummary:
    """(Re)embed every job profile and user career goal.

    Idempotent — entities whose source text and provider are unchanged are
    skipped without spending an embedding call.
    """
    settings = get_settings()
    try:
        provider = get_embedding_provider()
    except EmbeddingError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    jobs = (await session.exec(select(JobProfile))).all()
    users = (await session.exec(select(User))).all()

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
    limit: int = Query(default=10, ge=1, le=50),
) -> list[JobMatch]:
    """Rank job profiles by semantic similarity to the user's career goals.

    This is the "companies you should chase" query from the blueprint.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
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
    jobs = {
        job.id: job
        for job in (await session.exec(select(JobProfile).where(JobProfile.id.in_(job_ids)))).all()  # type: ignore[attr-defined]
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
