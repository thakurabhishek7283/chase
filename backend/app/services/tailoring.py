"""Tie the LaTeX pipeline together: parse -> tailor -> splice -> (optionally) score."""

from pydantic_ai import Agent

from app.ai.ats import score_resume
from app.ai.schemas import ATSReport, ResumeTailoring, TailorResult
from app.ai.tailor import tailor_content
from app.services.latex import parse, render
from app.services.latex.plain_text import to_markdown
from app.services.latex.renderer import GroupEdit, RegionEdit


def apply_tailoring(source: str, tailoring: ResumeTailoring, section_macros: list[str]) -> str:
    """Splice a tailoring result into a master `.tex` and return the new source."""
    resume = parse(source, section_macros)
    return render(
        resume,
        group_edits=[GroupEdit(g.group_id, g.items) for g in tailoring.groups],
        region_edits=[RegionEdit(r.region_id, r.latex) for r in tailoring.regions],
    )


async def tailor_latex_resume(
    source: str,
    job_description: str,
    position_title: str,
    section_macros: list[str],
    *,
    score: bool = False,
    tailor_agent: Agent[None, ResumeTailoring] | None = None,
    scoring_agent: Agent[None, ATSReport] | None = None,
) -> TailorResult:
    """Tailor a LaTeX master resume for one role.

    When `score` is set, the master and the tailored version are both flattened
    to Markdown and run through the existing ATS scorer, so the caller can show
    the lift the tailoring bought.

    Those two calls are independent and used to run concurrently. They are now
    sequential: firing both at once doubles the instantaneous request rate, and
    against Gemini's 5-requests-per-minute free tier that reliably triggers a
    429 that then has to be waited out anyway. Serialising costs one round trip
    on an operation that already takes tens of seconds, and buys a much better
    chance of never being throttled at all.
    """
    resume = parse(source, section_macros)
    tailoring = await tailor_content(
        resume, job_description, position_title, agent=tailor_agent
    )
    tailored_latex = render(
        resume,
        group_edits=[GroupEdit(g.group_id, g.items) for g in tailoring.groups],
        region_edits=[RegionEdit(r.region_id, r.latex) for r in tailoring.regions],
    )

    result = TailorResult(
        tailored_latex=tailored_latex,
        tailoring=tailoring,
        groups_changed=len(tailoring.groups),
        regions_changed=len(tailoring.regions),
    )
    if not score:
        return result

    before = await score_resume(
        to_markdown(resume), job_description, position_title, agent=scoring_agent
    )
    after = await score_resume(
        to_markdown(parse(tailored_latex, section_macros)),
        job_description,
        position_title,
        agent=scoring_agent,
    )
    result.original_score = before.match_score
    result.tailored_score = after.match_score
    result.tailored_report = after
    return result
