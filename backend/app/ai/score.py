r"""Score one resume against one job, and propose nothing.

The deliberately cheap half of `ai/review`. A review reads the document, judges
it, *and* drafts a rewrite for every slot worth changing — which is the right
call when you are about to change something, and pure waste when the question is
just "what does this version score?".

That question is the common one for a tailored child. The document already went
through review; the author wants the number that came out the other side. So this
agent is given the same scoring rules and the same readable text, and no outline
at all. Nothing is proposed, so nothing has to be drafted: the response is four
short fields instead of a paragraph of LaTeX per slot, which is most of why it
comes back in a fraction of the time.

`SCORING_RULES` is shared with the review prompt rather than restated. A resume
that scores 71 from the scorer and 58 from the reviewer is worse than no score at
all, and identical rules over identical input is the only cheap defence there is.
"""

from functools import lru_cache

from pydantic_ai import Agent
from pydantic_ai.models import Model

from app.ai.limits import run_agent
from app.ai.provider import resolve_model
from app.ai.schemas import ResumeScoreResult

#: Interpolated into both this prompt and `ai/review.REVIEW_SYSTEM_PROMPT`.
SCORING_RULES = """\
- Judge only against the supplied job description. Do not invent requirements.
- Mark a missing keyword `critical` only when the job description states it as a \
requirement, not a preference.
- Keep the score honest. A resume that genuinely does not fit should score low.\
"""

SCORE_SYSTEM_PROMPT = f"""\
You are an ATS analyst. You are given one resume as an applicant tracking system \
would read it, and one job description. Report how it screens.

{SCORING_RULES}
- Do NOT suggest edits, rewrites or improvements. Reporting the gap is the whole \
job; something else decides what to do about it.
- Judge the document you were given. It may be a version already tailored for \
this role — score what is in front of you, not what you imagine it started as.\
"""


def _model() -> Model | str:
    return resolve_model()


@lru_cache
def get_score_agent() -> Agent[None, ResumeScoreResult]:
    return Agent(_model(), output_type=ResumeScoreResult, system_prompt=SCORE_SYSTEM_PROMPT)


def build_score_prompt(readable_text: str, job_description: str, position_title: str) -> str:
    return (
        f"# Target role\n{position_title}\n\n"
        f"# Job description\n{job_description}\n\n"
        f"# The resume, as an ATS would read it\n{readable_text}\n\n"
        "Score this resume against this role."
    )


async def score_resume(
    readable_text: str,
    job_description: str,
    position_title: str,
    *,
    agent: Agent[None, ResumeScoreResult] | None = None,
) -> ResumeScoreResult:
    active = agent or get_score_agent()
    result = await run_agent(
        active, build_score_prompt(readable_text, job_description, position_title)
    )
    return result.output
