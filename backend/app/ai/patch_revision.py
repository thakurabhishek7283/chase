r"""Rewrite one patch after the author says what is wrong with it.

The narrowest LLM call in the app, deliberately. It sees one slot: what the
master says now, what was proposed, and the author's note. It cannot touch any
other slot, cannot re-score, and cannot change which slot it is answering about —
the caller supplies the id and the result is written back to that row.

This is the difference between "revise this bullet" and "try again": the author
has already accepted the other patches, and a call that re-derived the whole
review would undo work they have done.
"""

from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model

from app.ai.limits import run_agent
from app.ai.provider import resolve_model
from app.services.latex import allowed_commands_prompt

REVISION_SYSTEM_PROMPT = f"""\
You revise ONE proposed change to ONE part of a resume, after the candidate has \
told you what is wrong with it.

You are given the text the resume currently has, the change that was proposed, \
and the candidate's feedback. Return a new version of that change.

- The feedback is the brief. Follow it. If they say a bullet is too long, \
shorten it; if they say a claim overstates what they did, walk it back.
- Return the COMPLETE final content for this slot, in final order — not a diff \
and not only the part you changed.
- If the feedback asks for something you cannot do truthfully — a skill or a \
metric that appears nowhere in what you were shown — do not invent it. Return \
the closest honest version and say so in `note`.
- Keep at least two bullets in a group that started with two or more.
- Item text is LaTeX. You may use only these commands: {allowed_commands_prompt()}. \
Escape literal & % $ # _ as \\& \\% \\$ \\# \\_. Keep braces balanced.
- Do NOT emit \\item, \\begin, \\end, or any sectioning command.
"""


class RevisedPatch(BaseModel):
    """One slot's content, rewritten to the author's brief."""

    items: list[str] = Field(
        default_factory=list,
        description="For a bullet group: the FULL revised bullet list. Empty for a region.",
    )
    latex: str = Field(
        default="", description="For a marked region: the full revised LaTeX. Empty for a group."
    )
    note: str = Field(
        default="",
        description="One sentence on what changed, or why the feedback could not be followed exactly.",
    )


def _model() -> Model | str:
    return resolve_model()


@lru_cache
def get_revision_agent() -> Agent[None, RevisedPatch]:
    return Agent(_model(), output_type=RevisedPatch, system_prompt=REVISION_SYSTEM_PROMPT)


def build_revision_prompt(
    *,
    section_heading: str,
    original: str,
    proposed: str,
    feedback: str,
    job_description: str,
    position_title: str,
) -> str:
    return (
        f"# Target role\n{position_title}\n\n"
        f"# Job description\n{job_description}\n\n"
        f"# Where this lives in the resume\n{section_heading}\n\n"
        f"# What the resume says now\n{original}\n\n"
        f"# What was proposed\n{proposed}\n\n"
        f"# The candidate's feedback\n{feedback}\n\n"
        "Revise the proposal to address the feedback."
    )


async def revise_patch(
    *,
    section_heading: str,
    original: str,
    proposed: str,
    feedback: str,
    job_description: str,
    position_title: str,
    agent: Agent[None, RevisedPatch] | None = None,
) -> RevisedPatch:
    """Ask for one slot again, with the author's note as the brief."""
    active = agent or get_revision_agent()
    result = await run_agent(
        active,
        build_revision_prompt(
            section_heading=section_heading,
            original=original,
            proposed=proposed,
            feedback=feedback,
            job_description=job_description,
            position_title=position_title,
        ),
    )
    return result.output
