r"""Read, write and age the cached ATS scores.

One rule runs through all of it: **a score is only ever recomputed on request.**
Nothing here scores anything as a side effect of a page load. The resume screen
opens on whatever is stored — one indexed read for every version at once — and a
number that no longer describes the document comes back labelled `stale` rather
than silently refreshed. Refreshing on read would turn opening a resume into an
unbounded row of model calls, which is the exact failure this table prevents.

The other half is that a review's verdict *is* a score. `ai/review` already
judges the document it patches, on the same rules the scorer uses, so `record`
takes either result type and the review path pays nothing extra to keep the
cache warm. That is what makes the common journey cheap: review a master, accept
some patches, finalize, score the child once — and from then on every look at
either document is a database read.
"""

import json
import uuid
from datetime import UTC, datetime

from sqlmodel import col, desc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.schemas import ResumeScoreResult
from app.models.resume import Resume
from app.models.score import ResumeScore
from app.services.latex import document_fingerprint
from app.services.resume_text import slot_config_for


def fingerprint(resume: Resume) -> str:
    """What this resume must still look like for its score to be current.

    The slot config is in here alongside the content because the scorer reads the
    document through it — re-drawing the line between template and content
    changes the text that gets scored without touching a byte of `content`.

    It errs towards stale: `source` and `confirmed` ride along in the serialised
    config even though neither changes what parses. A score wrongly labelled
    stale costs one button press; one wrongly labelled current is a number about
    a document nobody has.
    """
    config = json.dumps(slot_config_for(resume).to_dict(), sort_keys=True)
    return document_fingerprint(resume.content, config)


def is_stale(score: ResumeScore, resume: Resume) -> bool:
    return score.content_hash != fingerprint(resume)


async def scores_for(session: AsyncSession, resume_id: uuid.UUID) -> list[ResumeScore]:
    """Every cached score for one resume, newest first. One indexed read."""
    result = await session.exec(
        select(ResumeScore)
        .where(ResumeScore.resume_id == resume_id)
        .order_by(desc(col(ResumeScore.updated_at)))
    )
    return list(result.all())


async def score_for(
    session: AsyncSession, resume_id: uuid.UUID, job_profile_id: uuid.UUID
) -> ResumeScore | None:
    """The cached score for one pair, if there is one. Hits the unique index."""
    result = await session.exec(
        select(ResumeScore).where(
            ResumeScore.resume_id == resume_id, ResumeScore.job_profile_id == job_profile_id
        )
    )
    return result.first()


async def record(
    session: AsyncSession,
    *,
    resume: Resume,
    job_profile_id: uuid.UUID,
    result: ResumeScoreResult,
    commit: bool = True,
) -> ResumeScore:
    """Store a verdict, replacing any previous one for the same pair.

    Accepts a `ResumeReviewResult` as readily as a `ResumeScoreResult` — it is a
    subclass, and the patches hanging off it are simply not this table's business.

    `commit=False` is for callers already inside a transaction that has more to
    write, which is how `services/review.create_review` folds a review's score
    into the cache without a second commit.
    """
    now = datetime.now(UTC)
    existing = await score_for(session, resume.id, job_profile_id)

    if existing is None:
        existing = ResumeScore(
            user_id=resume.user_id,
            resume_id=resume.id,
            job_profile_id=job_profile_id,
            created_at=now,
        )

    existing.content_hash = fingerprint(resume)
    existing.match_score = result.match_score
    existing.summary = result.summary
    existing.matched_keywords = list(result.matched_keywords)
    existing.missing_keywords = [gap.model_dump() for gap in result.missing_keywords]
    existing.updated_at = now

    session.add(existing)
    if commit:
        await session.commit()
        await session.refresh(existing)
    return existing
