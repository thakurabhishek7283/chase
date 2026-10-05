r"""Score a resume against one job and propose every change, in a single call.

Scoring and tailoring used to be two endpoints and two round trips, which was
always slightly dishonest: the suggestions a scorer produces and the edits a
tailorer makes are the same judgement, and asking twice invites the two answers
to disagree. One call, one verdict, one set of patches.

The model sees two views of the same resume and they do different jobs:

- **The flattened text** (`plain_text.to_markdown`) is what it scores. It
  approximates what an ATS extracts from the compiled PDF, including the frozen
  parts — employers and dates count toward a match even though nothing may
  rewrite them.
- **The slot outline** (`tailor.build_outline`) is what it may propose against.
  Every patch names a slot id from this list. Anything not in it does not exist
  as far as the model is concerned, which is what makes the template safe.

A patch is a *proposal*, never an application. The author resolves each one
before anything is spliced, so the model is explicitly told to propose
everything it believes in and let the human decline.
"""

from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model

from app.ai.limits import run_agent
from app.ai.provider import resolve_model
from app.ai.schemas import ResumeScoreResult, Severity
from app.ai.score import SCORING_RULES
from app.services.latex import allowed_commands_prompt
from app.services.latex.model import LatexResume

REVIEW_SYSTEM_PROMPT = f"""\
You are an ATS analyst who also proposes the concrete edits that would close the \
gaps you find. You do both in one pass, for one resume against one job.

You are given two views of the same resume: its full readable text, and the \
subset of it that is EDITABLE, as numbered slots. Score the full text. Propose \
changes only against the slots.

## Scoring

{SCORING_RULES}
- The score describes the resume AS IT IS, before any of your patches.

## Patches

Each patch targets one slot id from the outline and carries that slot's COMPLETE \
final content — not a diff, not a fragment.

- For a bullet group: the full final list of bullets, in final order. You may \
reorder, reword, and drop; keep at least two bullets in any group that started \
with two or more.
- For a marked region such as a skills line: the full replacement LaTeX.
- Propose a patch for every slot you would genuinely change, and omit slots you \
would leave alone. A resume needing three changes should return three patches, \
not one and not ten.
- Give each patch a `reason` the candidate can judge: which requirement it \
addresses and what it changes. They will accept or reject it one by one.

## Hard rules

- NEVER invent skills, employers, dates, metrics, or credentials. Every claim in \
a patch must already be supported somewhere in the resume you were given. If the \
resume says "built services in Python" and the job wants Rust, you may NOT say \
Rust; if the resume mentions Rust elsewhere, you may surface it.
- NEVER propose a patch against a slot id that is not in the outline.
- Item text is LaTeX. You may use only these commands: {allowed_commands_prompt()}. \
Escape literal & % $ # _ as \\& \\% \\$ \\# \\_. Keep braces balanced.
- Do NOT emit \\item, \\begin, \\end, or any sectioning command — the slot supplies \
its own list scaffolding.
- Preserve each bullet's existing formatting macros where they still make sense.
"""


class ProposedPatch(BaseModel):
    """One slot's complete proposed content, with the case for it."""

    slot_id: str = Field(
        description="A group or region id copied exactly from the outline, e.g. 'g2' or 'r1'."
    )
    items: list[str] = Field(
        default_factory=list,
        description=(
            "For a bullet group: the FULL final bullet list, in final order. "
            "Leave empty for a region patch."
        ),
    )
    latex: str = Field(
        default="",
        description=(
            "For a marked region: the full replacement LaTeX. Leave empty for a group patch."
        ),
    )
    reason: str = Field(
        description="Which job requirement this addresses and what it changes, in one or two sentences."
    )
    severity: Severity = Field(
        default="important", description="How much accepting this is worth to the match."
    )


class ResumeReviewResult(ResumeScoreResult):
    """The whole verdict: how this resume scores, and everything to do about it.

    A `ResumeScoreResult` with the work attached. Sharing the base is what lets
    `services/scoring` cache a review's verdict without a second model call —
    the score half of a review is a score, in the literal sense.
    """

    patches: list[ProposedPatch] = Field(
        default_factory=list, description="One per slot worth changing. Empty is a valid answer."
    )


def _model() -> Model | str:
    return resolve_model()


@lru_cache
def get_review_agent() -> Agent[None, ResumeReviewResult]:
    return Agent(_model(), output_type=ResumeReviewResult, system_prompt=REVIEW_SYSTEM_PROMPT)


def build_outline(resume: LatexResume) -> str:
    """Serialise the editable slots for the prompt.

    Section headings travel with the ids because the model needs to know *where*
    a bullet lives to judge relevance — one under "Projects" is weighted
    differently from one under "Experience". Frozen sections are omitted
    entirely: a slot the model cannot see is a slot it cannot propose against.
    """
    lines: list[str] = []
    for section in resume.sections:
        if not section.is_editable:
            continue
        lines.append(f"\n## Section {section.id}: {section.heading}")
        for region in section.regions:
            lines.append(f"\n[region {region.id}] label={region.label}")
            lines.append(region.latex)
        for group in section.groups:
            lines.append(f"\n[group {group.id}] {len(group.bullets)} bullets")
            for index, bullet in enumerate(group.bullets, start=1):
                lines.append(f"  {index}. {bullet.latex}")
    return "\n".join(lines).strip()


def build_review_prompt(
    resume: LatexResume, readable_text: str, job_description: str, position_title: str
) -> str:
    return (
        f"# Target role\n{position_title}\n\n"
        f"# Job description\n{job_description}\n\n"
        f"# The resume, as an ATS would read it\n{readable_text}\n\n"
        f"# Editable slots — the only things you may propose changes to\n"
        f"{build_outline(resume)}\n\n"
        "Score this resume against this role, and propose a patch for every slot "
        "worth changing."
    )


async def review_resume(
    resume: LatexResume,
    readable_text: str,
    job_description: str,
    position_title: str,
    *,
    agent: Agent[None, ResumeReviewResult] | None = None,
) -> ResumeReviewResult:
    """Score and propose in one call, then discard patches naming unknown slots.

    A hallucinated slot id would become a render error at finalize rather than a
    bad bullet the author could reject, and failing the whole review over one is
    worse than returning the patches that did resolve.
    """
    active = agent or get_review_agent()
    result = await run_agent(
        active, build_review_prompt(resume, readable_text, job_description, position_title)
    )
    return _drop_unknown_slots(resume, result.output)


def _drop_unknown_slots(resume: LatexResume, review: ResumeReviewResult) -> ResumeReviewResult:
    known = {group.id for group in resume.groups} | {region.id for region in resume.regions}
    # A duplicate slot id would violate the review's unique index at insert
    # time; keeping the first is the same "salvage what resolved" instinct.
    seen: set[str] = set()
    kept: list[ProposedPatch] = []
    for patch in review.patches:
        if patch.slot_id not in known or patch.slot_id in seen:
            continue
        seen.add(patch.slot_id)
        kept.append(patch)
    return review.model_copy(update={"patches": kept})
