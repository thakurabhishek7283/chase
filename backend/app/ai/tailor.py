r"""Reshape a LaTeX resume's editable content for one specific job.

This is the counterpart to `ai/autofix.py`, and the difference between them is
the point of the LaTeX pipeline. Autofix rewrites a Markdown resume as free
text — the model returns a whole new document, so the layout is whatever it
decides to emit. Tailoring returns *only* the contents of numbered slots, which
are spliced back into the master's own bytes. The model never sees the preamble
and cannot restructure the document, so a tailored resume is guaranteed to be
the same resume with different words in it.

The model is shown bullets as LaTeX rather than plain text so it can preserve
the `\textbf{}` the author already had. Everything it returns goes through
`services.latex.safety` before it reaches the compiler.
"""

from functools import lru_cache

from pydantic_ai import Agent
from pydantic_ai.models import Model

from app.ai.limits import run_agent
from app.ai.provider import resolve_model
from app.ai.schemas import ResumeTailoring
from app.services.latex.model import LatexResume

TAILOR_SYSTEM_PROMPT = """\
You tailor an existing resume to one specific job description.

You are given the resume's *editable slots only* — bullet groups and marked \
regions, each with a stable id. The rest of the document (layout, section \
headings, employers, job titles, dates, degrees) is frozen and you will never \
see or change it.

What tailoring means here:
- Re-order bullets so the ones this job cares about come first.
- Reword bullets to use the job description's vocabulary for work the candidate \
genuinely did. If the resume says "built services in Python" and the job wants \
Rust, you may NOT say Rust. If the resume mentions Rust elsewhere, you may \
surface it.
- Drop bullets that are irrelevant to this role, as long as each group keeps at \
least two bullets where it started with two or more.
- In a skills region, re-order and prune the list so the technologies this role \
asks for appear first. Do not add technologies the resume never claimed.

Hard rules:
- NEVER invent skills, employers, dates, metrics, or credentials. Every claim in \
your output must already be supported somewhere in the resume you were given.
- Return each group's COMPLETE final item list, in final order — not a diff.
- Only include groups and regions you actually changed. Omit the rest.
- Item text is LaTeX. You may use \\textbf, \\textit, \\emph, \\texttt, \\underline \
and \\href only. Escape literal & % $ # _ as \\& \\% \\$ \\# \\_. Keep braces balanced.
- Do not emit \\item, \\begin, \\end, or any sectioning command — the slot supplies \
its own list scaffolding.
- Preserve each bullet's existing formatting macros where they still make sense.
"""


def _model() -> Model | str:
    """Resolve the configured provider's model — see `ai/provider.py`."""
    return resolve_model()


@lru_cache
def get_tailor_agent() -> Agent[None, ResumeTailoring]:
    return Agent(_model(), output_type=ResumeTailoring, system_prompt=TAILOR_SYSTEM_PROMPT)


def build_outline(resume: LatexResume) -> str:
    """Serialise the editable slots for the prompt.

    Section headings and the ids are included because the model needs to know
    *where* a bullet lives to judge relevance — a bullet under "Projects" is
    weighted differently from one under "Experience".
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


def build_tailor_prompt(resume: LatexResume, job_description: str, position_title: str) -> str:
    return (
        f"# Target role\n{position_title}\n\n"
        f"# Job description\n{job_description}\n\n"
        f"# Editable slots in the candidate's resume\n{build_outline(resume)}\n\n"
        "Tailor these slots for this role. Return only the slots you changed."
    )


async def tailor_content(
    resume: LatexResume,
    job_description: str,
    position_title: str,
    *,
    agent: Agent[None, ResumeTailoring] | None = None,
) -> ResumeTailoring:
    """Ask the model how this resume's slots should change for this job.

    `agent` is injectable so tests can supply a Pydantic AI TestModel-backed
    agent instead of calling the real API, matching `ai/ats.py`.
    """
    active = agent or get_tailor_agent()
    result = await run_agent(
        active, build_tailor_prompt(resume, job_description, position_title)
    )
    return _drop_unknown_slots(resume, result.output)


def _drop_unknown_slots(resume: LatexResume, tailoring: ResumeTailoring) -> ResumeTailoring:
    """Discard edits pointing at ids that do not exist.

    A hallucinated id is a render error rather than a bad bullet, and failing the
    whole run over one is worse than tailoring the slots that did resolve.
    """
    known_groups = {group.id for group in resume.groups}
    known_regions = {region.id for region in resume.regions}
    return tailoring.model_copy(
        update={
            "groups": [g for g in tailoring.groups if g.group_id in known_groups],
            "regions": [r for r in tailoring.regions if r.region_id in known_regions],
        }
    )
