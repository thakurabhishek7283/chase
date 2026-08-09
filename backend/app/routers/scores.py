r"""What a resume scores against a job — for any resume, tailored ones included.

Two endpoints, and the split between them is the whole design:

    GET   /resumes/{id}/scores      free — every stored score for this document
    POST  /resumes/{id}/scores      one model call, and only when it must be

The GET is what the resume screen opens on. It is a single indexed read that
returns every version's standing at once, so a page showing five tailored
versions costs one query rather than five model calls, and it never blocks on a
provider.

The POST is the only thing here that can be slow, and it declines to be whenever
it can: a stored score whose `content_hash` still matches the document is
returned as it is. `refresh` overrides that, for the case the cache cannot see —
the *job description* changing under a score that is otherwise current.

Scoring is deliberately available on a tailored child. "What does the version I
just produced actually score?" is the question the whole tailoring flow exists to
answer, and for most of this app's life there was no way to ask it.
"""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.ai.score import score_resume
from app.deps import (
    CurrentUser,
    SessionDep,
    require_llm_key,
    require_owned_resume,
    require_visible_job_profile,
)
from app.models.resume import Resume
from app.models.score import ResumeScore
from app.schemas.score import ScoreRead, ScoreRequest
from app.services import scoring
from app.services.resume_text import readable_text

router = APIRouter(prefix="/resumes", tags=["scores"])


def _out(score: ResumeScore, resume: Resume, *, computed: bool = False) -> ScoreRead:
    return ScoreRead(
        id=score.id,
        resume_id=score.resume_id,
        job_profile_id=score.job_profile_id,
        match_score=score.match_score,
        summary=score.summary,
        matched_keywords=list(score.matched_keywords),
        missing_keywords=list(score.missing_keywords),
        stale=scoring.is_stale(score, resume),
        computed=computed,
        updated_at=score.updated_at,
    )


@router.get("/{resume_id}/scores", response_model=list[ScoreRead])
async def list_scores(
    resume_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[ScoreRead]:
    """Every score already known for this resume. Free, and never scores anything.

    A resume with no stored score comes back as an empty list rather than a 404:
    "nobody has scored this yet" is an ordinary state, not a missing resource.
    """
    resume = await require_owned_resume(session, resume_id, user)
    return [_out(score, resume) for score in await scoring.scores_for(session, resume.id)]


@router.post("/{resume_id}/scores", response_model=ScoreRead)
async def score_against_job(
    resume_id: uuid.UUID, data: ScoreRequest, session: SessionDep, user: CurrentUser
) -> ScoreRead:
    """Score this resume against one job, reusing a current answer if there is one.

    The cheap counterpart to a review: no outline goes to the model and no
    patches come back, so this is a fraction of a review's cost and latency. Ask
    for a review instead when the point is to *change* the document.
    """
    resume = await require_owned_resume(session, resume_id, user)
    job = await require_visible_job_profile(session, data.job_profile_id, user)

    cached = await scoring.score_for(session, resume.id, job.id)
    if cached is not None and not data.refresh and not scoring.is_stale(cached, resume):
        return _out(cached, resume)

    # Checked here rather than at the top: a cache hit is worth serving on a
    # deployment with no model configured at all.
    require_llm_key()
    result = await score_resume(readable_text(resume), job.description, job.position_title)
    stored = await scoring.record(
        session, resume=resume, job_profile_id=job.id, result=result
    )
    return _out(stored, resume, computed=True)


@router.delete("/{resume_id}/scores/{job_profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def forget_score(
    resume_id: uuid.UUID, job_profile_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> None:
    """Drop a stored score. The next look at this pair will have to earn one."""
    resume = await require_owned_resume(session, resume_id, user)
    score = await scoring.score_for(session, resume.id, job_profile_id)
    if score is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No score to forget")
    await session.delete(score)
    await session.commit()
