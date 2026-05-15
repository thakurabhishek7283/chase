from functools import lru_cache

from pydantic_ai import Agent
from pydantic_ai.models import Model

from app.ai.limits import run_agent
from app.ai.provider import resolve_model
from app.ai.schemas import ATSReport

SCORING_SYSTEM_PROMPT = """\
You are an ATS (Applicant Tracking System) analyst. You compare a candidate's \
resume against a specific job description and report, in structured form, how \
well the resume would score in an automated screen.

Rules:
- Judge only against the supplied job description. Do not invent requirements.
- `original_text` in every suggestion MUST be copied verbatim from the resume, \
character for character, so the client can locate and apply it. If you are \
proposing new content rather than a rewrite, leave `original_text` empty.
- Never fabricate experience the candidate does not have. Rewrites may surface, \
reword, or re-emphasise what is already there; they may not claim new skills, \
employers, or dates.
- Mark a missing keyword `critical` only when the job description states it as a \
requirement, not a preference.
- Keep the score honest. A resume that genuinely does not fit should score low.
"""

REWRITE_SYSTEM_PROMPT = """\
You revise resumes to close ATS gaps. You will be given a resume in Markdown, a \
job description, and a list of specific suggestions to apply.

Rules:
- Return the COMPLETE revised resume in Markdown. Do not return a diff or a fragment.
- Apply the supplied suggestions faithfully; do not invent unrelated changes.
- Never fabricate experience, employers, dates, credentials, or skills the \
candidate does not already claim. If a suggestion cannot be applied truthfully, \
leave that part of the resume unchanged.
- Preserve the resume's existing structure and voice.
"""


def _model() -> Model | str:
    """Resolve the configured provider's model — see `ai/provider.py`."""
    return resolve_model()


@lru_cache
def get_scoring_agent() -> Agent[None, ATSReport]:
    """Agent that produces a validated ATSReport.

    `output_type=ATSReport` makes Pydantic AI enforce the schema, so callers get
    a typed object rather than free text they have to parse.
    """
    return Agent(
        _model(),
        output_type=ATSReport,
        system_prompt=SCORING_SYSTEM_PROMPT,
    )


@lru_cache
def get_rewrite_agent() -> Agent[None, str]:
    """Agent that returns a full revised resume in Markdown."""
    return Agent(
        _model(),
        output_type=str,
        system_prompt=REWRITE_SYSTEM_PROMPT,
    )


def build_scoring_prompt(resume_markdown: str, job_description: str, position_title: str) -> str:
    return (
        f"# Target role\n{position_title}\n\n"
        f"# Job description\n{job_description}\n\n"
        f"# Candidate resume (Markdown)\n{resume_markdown}\n\n"
        "Analyse this resume against the job description and produce the ATS report."
    )


def build_rewrite_prompt(
    resume_markdown: str, job_description: str, suggestions_text: str
) -> str:
    return (
        f"# Job description\n{job_description}\n\n"
        f"# Current resume (Markdown)\n{resume_markdown}\n\n"
        f"# Suggestions to apply\n{suggestions_text}\n\n"
        "Return the complete revised resume in Markdown."
    )


async def score_resume(
    resume_markdown: str,
    job_description: str,
    position_title: str,
    *,
    agent: Agent[None, ATSReport] | None = None,
) -> ATSReport:
    """Score a resume against a job description.

    `agent` is injectable so tests can pass a Pydantic AI TestModel-backed agent
    instead of calling the real API.
    """
    active = agent or get_scoring_agent()
    result = await run_agent(
        active, build_scoring_prompt(resume_markdown, job_description, position_title)
    )
    return result.output
