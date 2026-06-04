import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.ai.schemas import ResumeTailoring
from app.ai.tailor import TAILOR_SYSTEM_PROMPT, build_outline, tailor_content
from app.services.latex import (
    GroupEdit,
    LatexParseError,
    LatexRenderError,
    RegionEdit,
    UnsafeLatexError,
    parse,
    render,
    to_markdown,
)
from app.services.latex.safety import braces_balanced, coerce_fragment, escape_text, validate_fragment
from app.services.tailoring import tailor_latex_resume

SECTION_MACROS = ["section", "subsection"]

MASTER = r"""\documentclass[letterpaper,11pt]{article}
\usepackage[margin=0.6in]{geometry}
\usepackage{enumitem}

% A commented-out list must not confuse the environment scanner:
% \begin{itemize} \item ignore me \end{itemize}

\begin{document}

\begin{center}\textbf{\Huge Ada Lovelace}\end{center}

\section{Skills}
% jarvis:begin skills
\textbf{Languages}: Python, Go, SQL
% jarvis:end

\section{Experience}
\textbf{Senior Engineer}, Acme Corp \hfill 2021 -- Present
\begin{itemize}[leftmargin=0.2in]
    \item Designed a \textbf{multi-tenant} pipeline handling 40k events/sec.
    \item Cut p99 latency by 38\% using a work queue.
    \item Mentored four engineers.
\end{itemize}

\section{Education}
\textbf{B.Tech}, State University \hfill 2018

\end{document}
"""

JAKES_STYLE = r"""\documentclass{article}
\newcommand{\resumeItem}[1]{\item\small{#1}}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}}
\begin{document}
\section{Experience}
\resumeItemListStart
    \resumeItem{Built a distributed scheduler in Go.}
    \resumeItem{Reduced build times by 60\%.}
\resumeItemListEnd
\end{document}
"""


def _parsed():
    return parse(MASTER, SECTION_MACROS)


# --- parsing -----------------------------------------------------------------


def test_parse_finds_bullets_and_marked_regions() -> None:
    resume = _parsed()

    assert [s.heading for s in resume.sections] == [
        "Header", "Skills", "Experience", "Education",
    ]
    assert len(resume.groups) == 1
    assert resume.bullet_count == 3
    assert len(resume.regions) == 1
    assert resume.regions[0].label == "skills"
    assert "Python, Go, SQL" in resume.regions[0].latex


def test_education_and_header_are_frozen() -> None:
    # Degrees and dates are facts. Tailoring must have no handle on them.
    resume = _parsed()
    frozen = [s.heading for s in resume.sections if not s.is_editable]
    assert frozen == ["Header", "Education"]


def test_commented_out_environment_is_ignored() -> None:
    # The preamble comment contains a full itemize; masking must hide it.
    resume = _parsed()
    assert all("ignore me" not in b.latex for g in resume.groups for b in g.bullets)


def test_parse_supports_macro_delimited_lists() -> None:
    resume = parse(JAKES_STYLE, SECTION_MACROS)
    assert len(resume.groups) == 1
    group = resume.groups[0]
    assert group.prefix == r"\resumeItem{"
    assert group.suffix == "}"
    assert [b.latex for b in group.bullets] == [
        "Built a distributed scheduler in Go.",
        r"Reduced build times by 60\%.",
    ]


def test_parse_rejects_a_fragment() -> None:
    with pytest.raises(LatexParseError, match=r"begin\{document\}"):
        parse(r"\section{Experience} \begin{itemize}\item hi\end{itemize}", SECTION_MACROS)


def test_parse_rejects_a_document_with_nothing_editable() -> None:
    with pytest.raises(LatexParseError, match="No editable content"):
        parse(
            r"\documentclass{article}\begin{document}\section{X}Just prose.\end{document}",
            SECTION_MACROS,
        )


def test_parse_rejects_an_unclosed_marker() -> None:
    source = MASTER.replace("% jarvis:end", "", 1)
    with pytest.raises(LatexParseError, match="no matching"):
        parse(source, SECTION_MACROS)


# --- rendering ---------------------------------------------------------------


def test_no_op_render_is_byte_identical() -> None:
    # The core guarantee: untouched content cannot drift.
    assert render(_parsed()) == MASTER


def test_render_preserves_everything_outside_the_edited_spans() -> None:
    resume = _parsed()
    tailored = render(resume, group_edits=[GroupEdit("g1", ["Rewrote it in Rust."])])

    assert tailored[: resume.body.start] == MASTER[: resume.body.start]
    assert r"\usepackage[margin=0.6in]{geometry}" in tailored
    assert r"\textbf{Senior Engineer}, Acme Corp \hfill 2021 -- Present" in tailored
    assert r"\textbf{B.Tech}, State University \hfill 2018" in tailored


def test_render_preserves_the_list_optional_argument() -> None:
    # Regression: `\begin{itemize}[leftmargin=0.2in]` must keep its option, or
    # every tailored resume silently changes indentation.
    tailored = render(_parsed(), group_edits=[GroupEdit("g1", ["One bullet."])])
    assert r"\begin{itemize}[leftmargin=0.2in]" in tailored


def test_render_can_reorder_drop_and_add_bullets() -> None:
    tailored = render(
        _parsed(),
        group_edits=[GroupEdit("g1", ["Mentored four engineers.", "A brand new bullet."])],
    )
    # Search from \begin{document}: the preamble holds a commented-out itemize.
    doc = tailored.index(r"\begin{document}")
    body = tailored[tailored.index(r"\begin{itemize}", doc) : tailored.index(r"\end{itemize}", doc)]

    assert body.count(r"\item ") == 2
    assert body.index("Mentored") < body.index("brand new")
    assert "40k events" not in body


def test_render_uses_the_documents_own_item_idiom() -> None:
    resume = parse(JAKES_STYLE, SECTION_MACROS)
    tailored = render(resume, group_edits=[GroupEdit("g1", ["Wrote Rust.", "Wrote more Rust."])])
    assert tailored.count(r"\resumeItem{Wrote") == 2
    assert r"\item " not in tailored


def test_render_replaces_a_marked_region() -> None:
    tailored = render(
        _parsed(), region_edits=[RegionEdit("r1", r"\textbf{Languages}: Rust, Python")]
    )
    assert r"\textbf{Languages}: Rust, Python" in tailored
    assert "Go, SQL" not in tailored
    # The markers themselves survive so the document stays re-tailorable.
    assert "% jarvis:begin skills" in tailored
    assert "% jarvis:end" in tailored


def test_render_keeps_the_original_list_when_every_bullet_is_dropped() -> None:
    # An empty itemize is a LaTeX error; a bulletless section is never intended.
    tailored = render(_parsed(), group_edits=[GroupEdit("g1", [])])
    assert tailored == MASTER


def test_render_rejects_an_unknown_slot_id() -> None:
    with pytest.raises(LatexRenderError, match="Unknown bullet group"):
        render(_parsed(), group_edits=[GroupEdit("g99", ["nope"])])


def test_render_output_reparses() -> None:
    # A tailored resume must itself be a valid master, or the version tree
    # breaks after one generation.
    tailored = render(_parsed(), group_edits=[GroupEdit("g1", ["Shipped Rust services."])])
    assert parse(tailored, SECTION_MACROS).bullet_count == 1


# --- safety ------------------------------------------------------------------


def test_validate_accepts_ordinary_bullet_markup() -> None:
    fragment = r"Built \textbf{Rust} services, cutting cost by 30\%."
    assert validate_fragment(fragment) == fragment


@pytest.mark.parametrize(
    "fragment",
    [
        r"\input{/etc/passwd}",
        r"\write18{rm -rf /}",
        r"\renewcommand{\section}[1]{}",
        r"Unbalanced {braces",
        r"50% off",
        r"\begin{itemize}\item nested\end{itemize}",
    ],
)
def test_validate_rejects_unsafe_or_malformed_fragments(fragment: str) -> None:
    with pytest.raises(UnsafeLatexError):
        validate_fragment(fragment)


def test_escape_text_neutralises_every_special_character() -> None:
    assert escape_text("A & B 50% $9 #1 a_b {x}") == r"A \& B 50\% \$9 \#1 a\_b \{x\}"


def test_braces_balanced_ignores_escaped_braces() -> None:
    assert braces_balanced(r"\{ literal \}")
    assert not braces_balanced(r"{ unclosed")


def test_coerce_degrades_to_plain_words_instead_of_failing() -> None:
    # Losing markup in one bullet beats refusing to render the resume.
    assert coerce_fragment(r"\unknowncmd{Shipped Rust}") == "Shipped Rust"


# --- plain-text projection ---------------------------------------------------


def test_projection_keeps_bullets_frozen_prose_and_headings() -> None:
    markdown = to_markdown(_parsed())

    assert "## Skills" in markdown
    assert "Languages: Python, Go, SQL" in markdown
    assert "- Designed a multi-tenant pipeline handling 40k events/sec" in markdown
    assert "Senior Engineer, Acme Corp 2021 - Present" in markdown
    assert "B.Tech, State University 2018" in markdown
    assert "\\" not in markdown


# --- tailoring ---------------------------------------------------------------


def test_tailor_system_prompt_forbids_fabrication() -> None:
    # Safety property of the feature, not a style choice.
    assert "NEVER invent skills" in TAILOR_SYSTEM_PROMPT


def test_outline_exposes_slots_but_never_the_preamble() -> None:
    outline = build_outline(_parsed())

    assert "[group g1]" in outline
    assert "[region r1] label=skills" in outline
    assert "Mentored four engineers." in outline
    assert "documentclass" not in outline
    assert "Education" not in outline  # Frozen sections are not offered up.


def _tailoring_model(payload: dict) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload)])

    return FunctionModel(respond)


_PAYLOAD = {
    "groups": [
        {
            "group_id": "g1",
            "items": [
                r"Designed a \textbf{Rust} pipeline handling 40k events/sec.",
                r"Cut p99 latency by 38\% using a work queue.",
            ],
        }
    ],
    "regions": [{"region_id": "r1", "latex": r"\textbf{Languages}: Rust, Python, Go"}],
    "emphasis": ["Rust"],
    "deemphasis": ["mentoring"],
    "notes": "Led with systems work.",
}


async def test_tailor_content_drops_hallucinated_slot_ids() -> None:
    payload = {**_PAYLOAD, "groups": [*_PAYLOAD["groups"], {"group_id": "g42", "items": ["x"]}]}
    agent = Agent(_tailoring_model(payload), output_type=ResumeTailoring)

    tailoring = await tailor_content(_parsed(), "Rust role", "Rust Engineer", agent=agent)

    assert [g.group_id for g in tailoring.groups] == ["g1"]


async def test_tailor_latex_resume_splices_without_touching_the_template() -> None:
    agent = Agent(_tailoring_model(_PAYLOAD), output_type=ResumeTailoring)

    result = await tailor_latex_resume(
        MASTER, "We need Rust.", "Rust Engineer", SECTION_MACROS, tailor_agent=agent
    )

    assert result.groups_changed == 1
    assert result.regions_changed == 1
    assert r"\textbf{Rust} pipeline" in result.tailored_latex
    assert r"\textbf{Languages}: Rust, Python, Go" in result.tailored_latex
    # Dropped bullet is gone; frozen facts and preamble are untouched.
    assert "Mentored four engineers" not in result.tailored_latex
    assert result.tailored_latex.split(r"\begin{document}")[0] == MASTER.split(
        r"\begin{document}"
    )[0]
    assert r"\textbf{B.Tech}, State University \hfill 2018" in result.tailored_latex


async def test_tailoring_sanitises_unsafe_model_output() -> None:
    payload = {
        "groups": [{"group_id": "g1", "items": [r"Shipped \input{/etc/passwd} services"]}],
        "regions": [],
        "emphasis": [],
        "deemphasis": [],
        "notes": "",
    }
    agent = Agent(_tailoring_model(payload), output_type=ResumeTailoring)

    result = await tailor_latex_resume(
        MASTER, "Rust.", "Rust Engineer", SECTION_MACROS, tailor_agent=agent
    )

    assert r"\input" not in result.tailored_latex
    assert "Shipped" in result.tailored_latex
