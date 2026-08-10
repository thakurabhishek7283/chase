r"""Read an uploaded `.tex` once: fix what will not compile, and say what the
macros mean.

Both halves need the same expensive thing — an understanding of this specific
template — so they are one request. The model that has just worked out that
`\resumeItem` is a bullet is the same model that can see `\resumeItemListStart`
opening a list with no `\item` before it.

**Corrections are scoped, never a rewrite.** The model returns
`{find, replace, reason}` triples, and `services/intake.py` applies them by exact
string match. It never returns the document. This is the difference between
"fix line 22" and "here is your resume again, slightly different everywhere" —
the second is untestable, drifts the author's wording, and is precisely how a
stored resume once came back wrapped in a Markdown code fence.

**Correctness is decided downstream, not here.** The model proposes; the engine
disposes. A correction that does not apply cleanly is rejected, and a corrected
document that still will not compile fails the upload. Nothing the model says is
taken on trust.

The slot half is `ai/slot_schema.py`'s `SlotSchema` verbatim — same type, same
rules, same validation path through `services/slot_discovery.py`.
"""

from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model

from app.ai.limits import run_agent
from app.ai.provider import resolve_model
from app.ai.slot_schema import SLOT_VOCABULARY_RULES, SlotSchema, build_template_prompt

INTAKE_SYSTEM_PROMPT = (
    """\
You process an uploaded LaTeX resume in one pass. You do two jobs at once.

## Job 1 — make it compile under the named engine

You are told which engine will compile this document. Report every construct \
that engine cannot run, as a `find`/`replace` correction.

The engine matters. XeTeX-based engines (xelatex) do not have pdfTeX's \
`\\pdf...` primitives: `\\pdfgentounicode`, `\\pdfglyphtounicode`, and \
`\\input{glyphtounicode}` all stop the run with "Undefined control sequence". \
The fix is to make them conditional, never to delete the author's line:
`\\ifdefined\\pdfgentounicode \\pdfgentounicode=1 \\fi`

Also report genuine LaTeX errors, whatever the engine:
- A list environment opened directly inside another with no `\\item` between \
them ("Something's wrong--perhaps a missing \\item").
- Unbalanced braces or `\\begin` without a matching `\\end`.
- A macro used but never defined.

Rules for corrections — these are absolute:
- `find` MUST be copied character for character from the document, including \
whitespace and newlines. If it is not present verbatim the correction is thrown \
away and the upload fails.
- `find` MUST appear EXACTLY ONCE in the document. If the text you want to fix \
is not unique, widen it with surrounding lines until it is.
- `find` MUST be the smallest span that fixes the problem. Never quote a whole \
section to change one line.
- NEVER change wording, bullets, dates, employers, or anything the candidate \
wrote. You are fixing syntax, not editing a resume. If a line compiles, leave it \
alone even if you would have phrased it differently.
- Return an EMPTY corrections list if the document is already valid. That is the \
expected answer for a well-formed resume and is not a failure.

## Job 2 — describe the template's vocabulary

"""
    + SLOT_VOCABULARY_RULES
    + """
Describe the vocabulary of the document **as it will be after your corrections \
are applied**. If a correction introduces or renames a macro, report the \
corrected form.
"""
)


class Correction(BaseModel):
    """One scoped, exact-match edit to the uploaded source."""

    find: str = Field(
        description=(
            "Text copied verbatim from the document, occurring exactly once. "
            "Widen it with surrounding lines if the fragment is not unique."
        )
    )
    replace: str = Field(description="What to put there instead.")
    reason: str = Field(description="One sentence: what would have gone wrong, and why this fixes it.")


class LatexIntake(BaseModel):
    """Everything the upload needs from the model, in one answer."""

    corrections: list[Correction] = Field(
        default_factory=list,
        description="Empty when the document already compiles under the named engine.",
    )
    slot_schema: SlotSchema = Field(
        default_factory=SlotSchema,
        description="What this template's macros mean, after the corrections are applied.",
    )
    verdict: str = Field(
        default="",
        description=(
            "Two or three sentences for the author: whether the document was valid, "
            "what had to change, and how the template is structured."
        ),
    )


def _model() -> Model | str:
    return resolve_model()


@lru_cache
def get_intake_agent() -> Agent[None, LatexIntake]:
    return Agent(_model(), output_type=LatexIntake, system_prompt=INTAKE_SYSTEM_PROMPT)


def build_intake_prompt(source: str, engine: str, cutoff: int, limit: int) -> str:
    """Name the engine, then show the template.

    `build_template_prompt` solves the payload: the preamble's macro
    *definitions* rather than its font and geometry bulk, the preamble whole for
    the settings a definition filter cannot see, and the body as-is because
    usage is what disambiguates an argument list.
    """
    return (
        f"# Target engine\n{engine}\n\n"
        f"{build_template_prompt(source, cutoff, limit)}\n\n"
        "Report the corrections this document needs to compile under the target "
        "engine, and the vocabulary of its macros."
    )


async def read_upload(
    source: str,
    engine: str,
    cutoff: int,
    limit: int,
    *,
    agent: Agent[None, LatexIntake] | None = None,
) -> LatexIntake:
    """One call: what to fix, and what the macros mean.

    `agent` is injectable so tests can drive this with a FunctionModel instead of
    a live API, matching `ai/review.py`.
    """
    active = agent or get_intake_agent()
    result = await run_agent(active, build_intake_prompt(source, engine, cutoff, limit))
    return result.output
