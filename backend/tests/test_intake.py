r"""The upload gauntlet: correct, resolve, compile — or refuse with a reason.

Every test here drives the model with a `FunctionModel` payload, so the intake
*policy* is under test rather than any model's judgement. The point of the
module being tested is that nothing the model says is taken on trust, which is
exactly the kind of thing a fixed payload can prove.
"""

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.ai.intake import Correction, LatexIntake
from app.services.intake import IntakeError, apply_corrections, ingest
from app.services.latex import LatexErrorCode

#: A template the built-in shapes cannot read: bullets live in `\achievement`
#: and the facts in `\cventry`, so intake has to describe the vocabulary before
#: anything can be parsed out of it. It also has to genuinely compile — several
#: of these tests reach the engine, and a fixture that fails there would pass
#: for the wrong reason.
CUSTOM = r"""\documentclass{article}
\newcommand{\achievement}[1]{\item #1}
\newcommand{\cventry}[4]{\textbf{#1} \hfill #3 \\ \textit{#2} \\ #4}
\begin{document}
\section{Experience}
\cventry{Acme}{Engineer}{2021 -- Present}{Led the platform team.}
\begin{itemize}
    \achievement{Built a data pipeline in Python.}
    \achievement{Ran the on-call rotation.}
\end{itemize}
\section{Education}
\textbf{B.Tech}, State University \hfill 2018
\end{document}
"""

_SCHEMA = {
    "bullet_macros": [{"name": "achievement", "evidence": "one argument, rendered as an item"}],
    "field_macros": [
        {
            "name": "cventry",
            "arity": 4,
            "content_arg": 4,
            "label": "experience",
            "evidence": "args 1-3 are employer, title and dates",
        }
    ],
    "list_pairs": [],
    "environments": [],
    "section_macros": ["section"],
    "frozen_macros": ["cventry"],
    "reasoning": r"Bullets are \achievement; \cventry carries the facts in args 1-3.",
}


def _intake_model(payload: dict) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload)])

    return FunctionModel(respond)


def _agent(corrections: list[dict] | None = None, schema: dict | None = None) -> Agent:
    payload = {
        "corrections": corrections or [],
        "slot_schema": schema if schema is not None else _SCHEMA,
        "verdict": "Reads cleanly.",
    }
    return Agent(_intake_model(payload), output_type=LatexIntake)


# --- applying corrections ----------------------------------------------------


def test_corrections_apply_in_document_order() -> None:
    source = "alpha\nbeta\ngamma\n"
    result = apply_corrections(
        source,
        [
            Correction(find="gamma", replace="GAMMA", reason="third"),
            Correction(find="alpha", replace="ALPHA", reason="first"),
        ],
    )
    assert result == "ALPHA\nbeta\nGAMMA\n"


def test_a_correction_reads_the_original_not_an_earlier_replacement() -> None:
    # Splicing in one pass over the original offsets. If replacements were
    # applied sequentially with `str.replace`, the second correction here would
    # find the text the first one just introduced and fire twice.
    source = "one two\n"
    result = apply_corrections(
        source,
        [
            Correction(find="one", replace="two", reason="rename"),
            Correction(find="two", replace="three", reason="rename"),
        ],
    )
    assert result == "two three\n"


def test_a_correction_quoting_absent_text_is_refused_by_name() -> None:
    with pytest.raises(IntakeError, match="not in the document") as excinfo:
        apply_corrections(
            "hello\n", [Correction(find="goodbye", replace="hi", reason="the reason")]
        )
    # The document itself may be fine; it is the model's correction that is
    # unusable, so this is the parser/vocabulary side, not a compile failure.
    assert excinfo.value.code == LatexErrorCode.UNSUPPORTED_LATEX


def test_an_ambiguous_correction_is_refused_rather_than_guessed() -> None:
    # Two candidate sites and no way to know which was meant. Picking one would
    # edit the wrong line and nobody would ever see that it happened.
    with pytest.raises(IntakeError, match="appears 2 times"):
        apply_corrections(
            "\\item a\n\\item b\n",
            [Correction(find="\\item", replace="\\item[-]", reason="bullet style")],
        )


def test_overlapping_corrections_are_refused() -> None:
    with pytest.raises(IntakeError, match="overlap"):
        apply_corrections(
            "abcdef\n",
            [
                Correction(find="abcd", replace="x", reason="first fix"),
                Correction(find="cdef", replace="y", reason="second fix"),
            ],
        )


def test_an_empty_find_matches_nothing_and_is_refused() -> None:
    with pytest.raises(IntakeError, match="empty"):
        apply_corrections("hello\n", [Correction(find="", replace="x", reason="oops")])


# --- the whole gauntlet ------------------------------------------------------


async def test_ingest_reads_a_template_the_builtin_shapes_cannot() -> None:
    result = await ingest(CUSTOM, "xelatex", agent=_agent())

    assert result.resume.bullet_count == 2
    assert [r.latex for r in result.resume.regions] == ["Led the platform team."]
    # Never self-confirmed: passing the checks means a boundary is not obviously
    # wrong, which is not the same as being right.
    assert result.config.confirmed is False
    assert result.config.source == "discovered"
    assert result.source == CUSTOM  # nothing to correct, so nothing changed


async def test_ingest_applies_the_corrections_it_was_given() -> None:
    broken = CUSTOM.replace(
        r"\documentclass{article}",
        "\\documentclass{article}\n\\input{glyphtounicode}",
    )
    agent = _agent(
        corrections=[
            {
                "find": r"\input{glyphtounicode}",
                "replace": r"\ifdefined\pdfglyphtounicode \input{glyphtounicode} \fi",
                "reason": "pdfTeX-only under XeTeX",
            }
        ]
    )

    result = await ingest(broken, "xelatex", agent=agent)

    assert r"\ifdefined\pdfglyphtounicode" in result.source
    assert len(result.corrections) == 1
    assert result.corrections[0].reason == "pdfTeX-only under XeTeX"


async def test_a_bullet_dense_resume_is_not_mistaken_for_a_lost_boundary() -> None:
    r"""The regression that only a real document exposed.

    The editable-fraction ceiling was written for a *model-invented* vocabulary,
    where the null hypothesis is that the built-in shapes already failed. Running
    it on every upload changed its meaning: a resume that is mostly
    `\resumeItem{...}` bullets is legitimately two-thirds editable, and the
    deterministic parser reads it perfectly. The ceiling now applies to what the
    proposal claims *beyond* that baseline.
    """
    bullets = "\n".join(
        rf"    \item Delivered project {n} end to end, from design through to production support."
        for n in range(14)
    )
    dense = (
        "\\documentclass{article}\n\\usepackage{enumitem}\n\\begin{document}\n"
        "\\section{Experience}\n\\textbf{Engineer}, Acme \\hfill 2021\n"
        f"\\begin{{itemize}}\n{bullets}\n\\end{{itemize}}\n\\end{{document}}\n"
    )

    result = await ingest(dense, "xelatex", agent=_agent(schema={}))

    assert result.resume.bullet_count == 14


async def test_ingest_refuses_a_vocabulary_that_resolves_to_nothing() -> None:
    schema = {**_SCHEMA, "bullet_macros": [{"name": "nosuchmacro"}], "field_macros": []}

    # Valid LaTeX; the proposed macro just isn't in it — exactly the
    # "parser doesn't understand this document" case, not a compile failure.
    with pytest.raises(IntakeError, match="do not resolve") as excinfo:
        await ingest(CUSTOM, "xelatex", agent=_agent(schema=schema))
    assert excinfo.value.code == LatexErrorCode.UNSUPPORTED_LATEX


async def test_ingest_refuses_a_vocabulary_naming_a_formatting_macro() -> None:
    # `\textbf` is markup that appears *inside* a slot, never a slot itself.
    schema = {**_SCHEMA, "bullet_macros": [{"name": "textbf"}]}

    with pytest.raises(IntakeError, match="rejected") as excinfo:
        await ingest(CUSTOM, "xelatex", agent=_agent(schema=schema))
    assert excinfo.value.code == LatexErrorCode.UNSUPPORTED_LATEX


async def test_ingest_refuses_a_correction_that_does_not_apply() -> None:
    agent = _agent(
        corrections=[{"find": "not in here", "replace": "x", "reason": "imagined problem"}]
    )

    with pytest.raises(IntakeError, match="not in the document") as excinfo:
        await ingest(CUSTOM, "xelatex", agent=agent)
    assert excinfo.value.code == LatexErrorCode.UNSUPPORTED_LATEX


async def test_ingest_refuses_a_document_that_still_will_not_compile() -> None:
    # The engine has the last word. This one is caught before the engine even
    # runs, by the incompatibility pre-flight — a pdfTeX primitive left
    # unguarded under a XeTeX-family engine is a sentence, not a hundred lines
    # of log.
    broken = CUSTOM.replace(
        r"\documentclass{article}", "\\documentclass{article}\n\\pdfgentounicode=1"
    )

    # This is the other category: the document itself cannot compile, whatever
    # the vocabulary says about it.
    with pytest.raises(IntakeError, match="pdfgentounicode") as excinfo:
        await ingest(broken, "xelatex", agent=_agent())
    assert excinfo.value.code == LatexErrorCode.INVALID_LATEX
