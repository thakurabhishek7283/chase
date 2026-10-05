r"""Review a resume against one job, resolve every patch, then keep the result.

The whole flow in five endpoints, and only three of them cost anything:

    POST   /resumes/{id}/reviews                    one call: score + all patches
    PATCH  /reviews/{id}/patches/{pid}              free — accept or reject
    POST   /reviews/{id}/patches/{pid}/feedback     one call: revise this patch
    GET    /reviews/{id}/preview                    free — deterministic splice
    POST   /reviews/{id}/finalize                   free — writes the child

Accepting, rejecting and rendering never touch the model. That is what makes
working through a review practical: only asking for something *new* costs a
round trip, so a user can flip decisions and re-render as often as they like.

**Nothing renders while a patch is pending.** `services/review.spliced_source`
enforces it in one place so preview and finalize cannot drift apart, and the
rule is what makes "the author reviewed this" a fact rather than a claim.

A tailored version can be reviewed exactly like the master it came from, and
that is how a resume's ATS score gets *improved* rather than merely reported:
the second review reads the tailored document, scores what the first round
actually achieved, and proposes what is still missing. Finalizing it writes a new
version alongside — see `resumes.root_resume_id` for why it is a sibling and not
a grandchild.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlmodel import col, desc, select

from app.ai.patch_revision import revise_patch
from app.ai.review import review_resume
from app.ai.text import strip_code_fence
from app.crud import resume as crud
from app.deps import (
    CurrentUser,
    SessionDep,
    require_llm_key,
    require_owned_resume,
    require_visible_job_profile,
)
from app.models.job_profile import JobProfile
from app.models.resume import Resume
from app.models.review import ResumePatch, ResumeReview
from app.models.user import User
from app.routers.resumes import (
    attachment,
    compile_or_error,
    latex_error_detail,
    root_resume_id,
)
from app.schemas.review import (
    FinalizeRequest,
    FinalizeResponse,
    PatchDecision,
    PatchFeedback,
    PatchRead,
    ReviewCreate,
    ReviewRead,
    ReviewSummary,
)
from app.services import review as review_service
from app.services.latex import (
    LatexErrorCode,
    LatexParseError,
    LatexRenderError,
    StaleEditError,
    TemplateDriftError,
    parse,
)
from app.services.resume_text import readable_text, slot_config_for

router = APIRouter(tags=["reviews"])


# --- loading and shaping -----------------------------------------------------


async def _load_review(session: SessionDep, review_id: uuid.UUID, user: User) -> ResumeReview:
    """A review the caller owns. Non-owners get 404, never 403.

    Same rule as `require_owned_resume`, for the same reason: a review names a
    resume, and confirming that a review id exists confirms that the resume does.
    """
    review = await session.get(ResumeReview, review_id)
    if review is None or review.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    return review


async def _load_patch(
    session: SessionDep, review: ResumeReview, patch_id: uuid.UUID
) -> ResumePatch:
    patch = await session.get(ResumePatch, patch_id)
    if patch is None or patch.review_id != review.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patch not found")
    return patch


def _patch_out(patch: ResumePatch) -> PatchRead:
    return PatchRead.model_validate(patch)


def _review_out(review: ResumeReview, patches: list[ResumePatch]) -> ReviewRead:
    return ReviewRead(
        id=review.id,
        source_resume_id=review.source_resume_id,
        job_profile_id=review.job_profile_id,
        status=review.status,
        match_score=review.match_score,
        summary=review.summary,
        matched_keywords=list(review.matched_keywords),
        missing_keywords=list(review.missing_keywords),
        child_resume_id=review.child_resume_id,
        created_at=review.created_at,
        updated_at=review.updated_at,
        patches=[_patch_out(p) for p in patches],
        pending_count=review_service.pending_count(patches),
    )


def _next_label(job: JobProfile | None, siblings: list[Resume]) -> str:
    """A default label that does not collide with a version already there.

    Improving a tailored resume means reviewing it against the *same* job it was
    tailored for, so the obvious default — "Tailored for Backend Engineer" —
    would name every round identically and make the version list unreadable at
    exactly the moment it starts mattering. Rounds after the first get a `v2`.
    """
    base = f"Tailored for {job.position_title}" if job else "Tailored"
    taken = {version.version_label for version in siblings}
    if base not in taken:
        return base
    number = 2
    while f"{base} v{number}" in taken:
        number += 1
    return f"{base} v{number}"


def _guard_open(review: ResumeReview) -> None:
    """A finalized review is a record, not a workspace."""
    if review.status != "open":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This review has been finalized and its tailored resume already exists. "
                "Start a new review to make further changes."
            ),
        )


# --- creating a review -------------------------------------------------------


@router.post(
    "/resumes/{resume_id}/reviews",
    response_model=ReviewRead,
    status_code=status.HTTP_201_CREATED,
    tags=["reviews"],
)
async def create_review(
    resume_id: uuid.UUID, data: ReviewCreate, session: SessionDep, user: CurrentUser
) -> ReviewRead:
    """Score this resume against one job and propose every change, in one pass.

    The single most expensive call in the app, and the only one this flow makes
    per round. Everything after it — accepting, rejecting, rendering — is free.

    Works on a master and on a tailored version alike. Run against a version, it
    is the "improve this further" call: `match_score` is that version's own ATS
    standing and the patches are what is still left to close.

    The verdict is cached on the way past (`services/review.create_review`), so
    the score this returns is also the one the resume screen will show later
    without asking anybody.
    """
    require_llm_key()
    source = await require_owned_resume(session, resume_id, user)
    job = await require_visible_job_profile(session, data.job_profile_id, user)

    try:
        parsed = parse(source.content, slot_config_for(source))
    except LatexParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=latex_error_detail(
                LatexErrorCode.UNSUPPORTED_LATEX,
                f"This resume can no longer be read with its stored slot config: {exc} "
                "Correct the config on the resume screen, then review again.",
            ),
        ) from exc

    result = await review_resume(parsed, readable_text(source), job.description, job.position_title)
    review = await review_service.create_review(
        session, source=source, parsed=parsed, job_profile_id=job.id, result=result
    )
    patches = await review_service.patches_for(session, review.id)
    return _review_out(review, patches)


@router.get("/resumes/{resume_id}/reviews", response_model=list[ReviewSummary], tags=["reviews"])
async def list_reviews(
    resume_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[ReviewSummary]:
    """Every review of this exact resume, newest first.

    A tailored version's own rounds live on the version, not on its master. That
    is the honest split — a patch names a slot in the document it was proposed
    against — and it keeps this list short enough to read.

    Two queries regardless of how many reviews come back: the rows, then one
    grouped count for every outstanding patch across all of them.
    """
    resume = await require_owned_resume(session, resume_id, user)
    rows = (
        await session.exec(
            select(ResumeReview)
            .where(ResumeReview.source_resume_id == resume.id)
            .order_by(desc(col(ResumeReview.created_at)))
        )
    ).all()

    outstanding = await review_service.pending_counts(session, [review.id for review in rows])
    return [
        ReviewSummary(
            id=review.id,
            job_profile_id=review.job_profile_id,
            status=review.status,
            match_score=review.match_score,
            child_resume_id=review.child_resume_id,
            created_at=review.created_at,
            pending_count=outstanding.get(review.id, 0),
        )
        for review in rows
    ]


@router.get("/reviews/{review_id}", response_model=ReviewRead, tags=["reviews"])
async def get_review(review_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> ReviewRead:
    review = await _load_review(session, review_id, user)
    patches = await review_service.patches_for(session, review.id)
    return _review_out(review, patches)


# --- resolving patches -------------------------------------------------------


@router.patch("/reviews/{review_id}/patches/{patch_id}", response_model=PatchRead, tags=["reviews"])
async def decide_patch(
    review_id: uuid.UUID,
    patch_id: uuid.UUID,
    data: PatchDecision,
    session: SessionDep,
    user: CurrentUser,
) -> PatchRead:
    """Accept or reject one proposal. No model call, so it is instant and free.

    A decision is not final until finalize is: flipping accept to reject and back
    is the expected way to use this, and rejecting simply leaves the master's own
    text in that slot.
    """
    review = await _load_review(session, review_id, user)
    _guard_open(review)
    patch = await _load_patch(session, review, patch_id)

    patch.status = "accepted" if data.action == "accept" else "rejected"
    patch.updated_at = datetime.now(UTC)
    review_service.touch(review)
    session.add(patch)
    session.add(review)
    await session.commit()
    await session.refresh(patch)
    return _patch_out(patch)


@router.post(
    "/reviews/{review_id}/patches/{patch_id}/feedback",
    response_model=PatchRead,
    tags=["reviews"],
)
async def send_patch_back(
    review_id: uuid.UUID,
    patch_id: uuid.UUID,
    data: PatchFeedback,
    session: SessionDep,
    user: CurrentUser,
) -> PatchRead:
    """Ask for this one proposal again, with a brief.

    The narrowest call in the app: one slot, its current text, what was proposed,
    and what the author said about it. Nothing else in the review is re-derived,
    because decisions already made on other patches are work the author would
    have to redo.

    The result comes back `pending` — a revision is a new proposal, and accepting
    it is a separate act.
    """
    require_llm_key()
    review = await _load_review(session, review_id, user)
    _guard_open(review)
    patch = await _load_patch(session, review, patch_id)

    job = await session.get(JobProfile, review.job_profile_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The job profile this review was made against no longer exists.",
        )

    if patch.is_group:
        original = "\n".join(f"- {item}" for item in patch.original_items or [])
        proposed = "\n".join(f"- {item}" for item in patch.proposed_items or [])
    else:
        original = patch.original_latex or ""
        proposed = patch.proposed_latex or ""

    revised = await revise_patch(
        section_heading=patch.section_heading,
        original=original,
        proposed=proposed,
        feedback=data.feedback,
        job_description=job.description,
        position_title=job.position_title,
    )

    if patch.is_group:
        items = [strip_code_fence(item).strip() for item in revised.items if item.strip()]
        if not items:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "The revision came back empty, which would delete this section's "
                    "bullets. Reject the patch instead, or rephrase the feedback."
                ),
            )
        patch.proposed_items = items
    else:
        latex = strip_code_fence(revised.latex).strip()
        if not latex:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "The revision came back empty, which would delete this region. "
                    "Reject the patch instead, or rephrase the feedback."
                ),
            )
        patch.proposed_latex = latex

    patch.feedback = data.feedback
    patch.revision_count += 1
    patch.status = "pending"
    if revised.note:
        patch.reason = revised.note
    patch.updated_at = datetime.now(UTC)
    review_service.touch(review)
    session.add(patch)
    session.add(review)
    await session.commit()
    await session.refresh(patch)
    return _patch_out(patch)


@router.post(
    "/reviews/{review_id}/patches/{patch_id}/revert", response_model=PatchRead, tags=["reviews"]
)
async def revert_patch(
    review_id: uuid.UUID, patch_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> PatchRead:
    """Put back what the review originally proposed, discarding any revisions.

    Free, because the first answer was kept. Without this a feedback round that
    made things worse could only be undone by re-running the whole review.
    """
    review = await _load_review(session, review_id, user)
    _guard_open(review)
    patch = await _load_patch(session, review, patch_id)

    patch.proposed_items = patch.initial_items
    patch.proposed_latex = patch.initial_latex
    patch.feedback = None
    patch.status = "pending"
    patch.updated_at = datetime.now(UTC)
    review_service.touch(review)
    session.add(patch)
    session.add(review)
    await session.commit()
    await session.refresh(patch)
    return _patch_out(patch)


# --- output ------------------------------------------------------------------


async def _splice_or_error(
    session: SessionDep, review: ResumeReview, source: Resume
) -> tuple[str, list[ResumePatch]]:
    """Apply the accepted patches, mapping each failure to its status."""
    try:
        return await review_service.spliced_source(session, review, source)
    except review_service.ReviewIncomplete as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except StaleEditError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{exc} The resume has changed since this review was made, so these "
                "patches no longer describe it. Start a new review."
            ),
        ) from exc
    except TemplateDriftError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    except (LatexParseError, LatexRenderError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=latex_error_detail(LatexErrorCode.UNSUPPORTED_LATEX, str(exc)),
        ) from exc


@router.get("/reviews/{review_id}/preview", tags=["reviews"])
async def preview_review(
    review_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    output: str = Query(default="pdf", pattern="^(pdf|tex)$"),
) -> Response:
    """Render the reviewed resume without keeping it. Free and deterministic."""
    review = await _load_review(session, review_id, user)
    source = await require_owned_resume(session, review.source_resume_id, user)
    tailored, _patches = await _splice_or_error(session, review, source)

    if output == "tex":
        return Response(
            content=tailored,
            media_type="application/x-tex",
            headers=attachment(source.title, "tex"),
        )
    pdf = await compile_or_error(tailored, source.latex_engine, resume_id=source.id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers=attachment(source.title, "pdf", inline=True),
    )


@router.post(
    "/reviews/{review_id}/finalize",
    response_model=FinalizeResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["reviews"],
)
async def finalize_review(
    review_id: uuid.UUID, data: FinalizeRequest, session: SessionDep, user: CurrentUser
) -> FinalizeResponse:
    """Write the reviewed resume as a new version, and close the review.

    The only thing in the app that creates a tailored document, and it cannot run
    until every proposal has a decision on it.

    The new version hangs off the *root* master, not off whatever was reviewed.
    Improving a tailored version therefore produces a sibling of it rather than a
    grandchild — see `resumes.root_resume_id`.
    """
    review = await _load_review(session, review_id, user)
    _guard_open(review)
    source = await require_owned_resume(session, review.source_resume_id, user)
    tailored, patches = await _splice_or_error(session, review, source)

    root_id = root_resume_id(source)
    job = await session.get(JobProfile, review.job_profile_id)
    siblings = await crud.list_resume_versions(session, root_id, user_id=user.id)
    label = data.version_label or _next_label(job, siblings)

    now = datetime.now(UTC)
    child = Resume(
        user_id=source.user_id,
        master_resume_id=root_id,
        title=source.title,
        content=tailored,
        version_label=label,
        # A version renders from its master's template, so it must compile with
        # the master's engine — that is what keeps the two visually identical.
        latex_engine=source.latex_engine,
        latex_slot_config=source.latex_slot_config,
        created_at=now,
        updated_at=now,
    )
    session.add(child)
    await session.flush()

    review.child_resume_id = child.id
    review.status = "finalized"
    review_service.touch(review)
    session.add(review)
    await session.commit()
    await session.refresh(child)

    return FinalizeResponse(
        review_id=review.id,
        child_resume_id=child.id,
        title=child.title,
        version_label=child.version_label,
        accepted_count=sum(1 for p in patches if p.status == "accepted"),
        rejected_count=sum(1 for p in patches if p.status == "rejected"),
    )


@router.delete("/reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["reviews"])
async def delete_review(review_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> None:
    """Discard a review. Its patches go with it; a finalized child does not."""
    review = await _load_review(session, review_id, user)
    await session.delete(review)
    await session.commit()
