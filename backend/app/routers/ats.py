import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from app.ai import ats as ats_engine
from app.ai.autofix import run_autofix
from app.deps import SessionDep, require_llm_key
from app.models.job_profile import JobProfile
from app.models.resume import Resume
from app.schemas.ats import (
    ATSScoreRequest,
    ATSScoreResponse,
    AutofixRequest,
    AutofixResponse,
)

router = APIRouter(prefix="/ats", tags=["ats"])


async def _load_pair(
    session: SessionDep, resume_id: uuid.UUID, job_profile_id: uuid.UUID
) -> tuple[Resume, JobProfile]:
    resume = await session.get(Resume, resume_id)
    if resume is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    job = await session.get(JobProfile, job_profile_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job profile not found")
    return resume, job


@router.post("/score", response_model=ATSScoreResponse)
async def score(data: ATSScoreRequest, session: SessionDep) -> ATSScoreResponse:
    """Score a resume against a job description and return the structured report."""
    require_llm_key()
    resume, job = await _load_pair(session, data.resume_id, data.job_profile_id)

    report = await ats_engine.score_resume(
        resume.content, job.description, job.position_title
    )
    return ATSScoreResponse(
        resume_id=resume.id, job_profile_id=job.id, report=report
    )


@router.post("/autofix", response_model=AutofixResponse)
async def autofix(data: AutofixRequest, session: SessionDep) -> AutofixResponse:
    """Run the LangGraph analyze -> fix -> re-score loop over a resume.

    Optionally persists the improved resume as a tailored child version, which
    is how the blueprint's "dynamic resume versioning" is realised.
    """
    require_llm_key()
    resume, job = await _load_pair(session, data.resume_id, data.job_profile_id)

    result = await run_autofix(
        resume.content,
        job.description,
        job.position_title,
        target_score=data.target_score,
        max_iterations=data.max_iterations,
    )

    saved_id: uuid.UUID | None = None
    if data.save_as_tailored_version:
        # A tailored version always hangs off a master, never off another
        # tailored version — keeps the version tree one level deep.
        master_id = resume.master_resume_id or resume.id
        tailored = Resume(
            user_id=resume.user_id,
            master_resume_id=master_id,
            title=resume.title,
            content_format=resume.content_format,
            content=result.revised_resume_markdown,
            version_label=f"Tailored for {job.position_title}",
            latex_engine=resume.latex_engine,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(tailored)
        await session.commit()
        await session.refresh(tailored)
        saved_id = tailored.id

    return AutofixResponse(
        resume_id=resume.id,
        job_profile_id=job.id,
        saved_resume_id=saved_id,
        result=result,
    )
