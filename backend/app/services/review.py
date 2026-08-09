r"""The lifecycle of a reviewed tailoring: propose, resolve, splice.

Everything here is deliberately boring except one rule, which is the point of
the whole flow: **a child resume exists only once no patch is pending**. Preview
and finalize both refuse while anything is outstanding, so "the author reviewed
this" is a fact the server knows rather than a claim the client makes.

Splicing reuses the pipeline that was already there —
`services/tailoring.apply_tailoring_with_repair`, which parses the source, splices
group and region edits into its own bytes, and verifies the template did not
drift. Accepted patches are just `GroupEdit`/`RegionEdit` by the time they get
there. Rejected and pending patches are simply absent, which leaves the source's
original text in place: rejecting a patch is not an edit, it is the absence of one.

The source may itself be a tailored child. Nothing here needs to care — a child
carries its master's template and slot vocabulary, so it parses, splices and
fingerprints exactly like the document it came from. Only `finalize` in the
router has to know the difference, because that is where the new version has to
be hung off the *root* master rather than off whatever was reviewed.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.review import ProposedPatch, ResumeReviewResult
from app.ai.schemas import ResumeTailoring, TailoredGroup, TailoredRegion
from app.ai.text import strip_code_fence
from app.models.resume import Resume
from app.models.review import ResumePatch, ResumeReview
from app.services import scoring
from app.services.latex import LatexResume, slot_hashes
from app.services.tailoring import apply_tailoring_with_repair


class ReviewIncomplete(RuntimeError):
    """Raised when a review is asked for output while patches are still pending."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean(text: str) -> str:
    """Model-authored LaTeX, with a stray code fence removed if one arrived.

    Structured output makes this unlikely rather than impossible, and a fenced
    fragment reaching the compiler is a failed render for the author.
    """
    return strip_code_fence(text).strip()


def _slot_index(resume: LatexResume) -> dict[str, tuple[str, str, list[str] | None, str | None]]:
    """slot id -> (kind, section heading, original items, original latex).

    Built once per review so each patch can be stored with the text it replaces,
    which is what the review screen shows beside the proposal.
    """
    index: dict[str, tuple[str, str, list[str] | None, str | None]] = {}
    for section in resume.sections:
        for group in section.groups:
            index[group.id] = (
                "group",
                section.heading,
                [bullet.latex for bullet in group.bullets],
                None,
            )
        for region in section.regions:
            index[region.id] = ("region", section.heading, None, region.latex)
    return index


def build_patches(
    review_id: uuid.UUID, resume: LatexResume, proposals: list[ProposedPatch]
) -> list[ResumePatch]:
    """Turn the model's proposals into rows, pairing each with what it replaces.

    A proposal whose slot id is unknown is skipped — `ai/review` already filters
    these, and this is the belt to that braces. A group proposal with no items is
    also skipped: "replace these bullets with nothing" would empty a section, and
    the model has a way to say "leave this alone" already, which is to omit it.
    """
    index = _slot_index(resume)
    rows: list[ResumePatch] = []
    for proposal in proposals:
        entry = index.get(proposal.slot_id)
        if entry is None:
            continue
        kind, heading, original_items, original_latex = entry

        if kind == "group":
            items = [_clean(item) for item in proposal.items if item.strip()]
            if not items:
                continue
            proposed_items, proposed_latex = items, None
        else:
            latex = _clean(proposal.latex)
            if not latex:
                continue
            proposed_items, proposed_latex = None, latex

        rows.append(
            ResumePatch(
                review_id=review_id,
                slot_id=proposal.slot_id,
                slot_kind=kind,
                section_heading=heading,
                original_items=original_items,
                original_latex=original_latex,
                proposed_items=proposed_items,
                proposed_latex=proposed_latex,
                # The model's first answer, kept so a feedback revision can be
                # undone without re-running the review.
                initial_items=proposed_items,
                initial_latex=proposed_latex,
                reason=proposal.reason,
                severity=proposal.severity,
            )
        )
    return rows


async def create_review(
    session: AsyncSession,
    *,
    source: Resume,
    parsed: LatexResume,
    job_profile_id: uuid.UUID,
    result: ResumeReviewResult,
) -> ResumeReview:
    """Persist a model verdict as an open review with one row per proposal.

    The verdict also lands in the score cache, in the same transaction. A review
    scores the document it patches on the rules the scorer uses, so paying a
    second model call to learn what we were just told would be indefensible —
    and it means reviewing a tailored child leaves that child's ATS score on
    screen for free, which is the point of being able to review one at all.
    """
    review = ResumeReview(
        user_id=source.user_id,
        source_resume_id=source.id,
        job_profile_id=job_profile_id,
        match_score=result.match_score,
        summary=result.summary,
        matched_keywords=list(result.matched_keywords),
        missing_keywords=[gap.model_dump() for gap in result.missing_keywords],
        # Frozen here, replayed at finalize. A source re-uploaded or re-sliced in
        # between makes these stop matching, which is the only way to notice.
        base_hashes=slot_hashes(parsed),
    )
    session.add(review)
    await session.flush()

    for patch in build_patches(review.id, parsed, result.patches):
        session.add(patch)

    await scoring.record(
        session, resume=source, job_profile_id=job_profile_id, result=result, commit=False
    )

    await session.commit()
    await session.refresh(review)
    return review


async def patches_for(session: AsyncSession, review_id: uuid.UUID) -> list[ResumePatch]:
    """Every patch in a review, in a stable order the UI can rely on."""
    result = await session.exec(
        select(ResumePatch)
        .where(ResumePatch.review_id == review_id)
        .order_by(col(ResumePatch.created_at), col(ResumePatch.slot_id))
    )
    return list(result.all())


def pending_count(patches: list[ResumePatch]) -> int:
    return sum(1 for patch in patches if patch.status == "pending")


async def pending_counts(
    session: AsyncSession, review_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Outstanding patches per review, for a whole list in one query.

    The review list needs nothing from a patch except how many are undecided,
    and loading every patch row of every review to count them made opening a
    resume cost a query per review it had ever had. Reviews with none left are
    simply absent from the result — the caller defaults to zero.
    """
    if not review_ids:
        return {}
    rows = await session.exec(
        select(ResumePatch.review_id, func.count())
        .where(col(ResumePatch.review_id).in_(review_ids), ResumePatch.status == "pending")
        .group_by(col(ResumePatch.review_id))
    )
    return {review_id: count for review_id, count in rows.all()}


def as_tailoring(patches: list[ResumePatch]) -> ResumeTailoring:
    """The accepted patches, in the shape the splicer already understands.

    Rejected and pending patches are absent rather than reversed: the renderer
    leaves any slot it is not given exactly as the source has it.
    """
    return ResumeTailoring(
        groups=[
            TailoredGroup(group_id=patch.slot_id, items=list(patch.proposed_items or []))
            for patch in patches
            if patch.status == "accepted" and patch.is_group
        ],
        regions=[
            TailoredRegion(region_id=patch.slot_id, latex=patch.proposed_latex or "")
            for patch in patches
            if patch.status == "accepted" and not patch.is_group
        ],
    )


async def spliced_source(
    session: AsyncSession, review: ResumeReview, source: Resume
) -> tuple[str, list[ResumePatch]]:
    """The reviewed document with every accepted patch applied.

    Raises `ReviewIncomplete` while anything is pending — the rule that gates
    both preview and finalize, enforced in one place so the two cannot diverge.
    """
    from app.services.resume_text import slot_config_for

    patches = await patches_for(session, review.id)
    if outstanding := pending_count(patches):
        raise ReviewIncomplete(
            f"{outstanding} patch{'es' if outstanding != 1 else ''} still need a decision. "
            "Accept or reject every proposal before rendering the tailored resume."
        )

    tailored, _final, _notes = await apply_tailoring_with_repair(
        source.content,
        as_tailoring(patches),
        slot_config_for(source),
        review.base_hashes,
        resume_id=str(source.id),
        user_id=str(source.user_id),
    )
    return tailored, patches


def touch(review: ResumeReview) -> None:
    review.updated_at = _utcnow()
