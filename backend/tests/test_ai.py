r"""The model seams, driven by fixed payloads rather than a live provider.

Two things are worth pinning here and neither is about model quality:

- **What reaches the model.** The review prompt shows the resume twice, for two
  different jobs, and shows the preamble neither time.
- **What the app refuses to believe.** A patch naming a slot that does not
  exist, or the same slot twice, is discarded before it can become a render
  error somebody has to debug at finalize.
"""

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.ai.patch_revision import RevisedPatch, build_revision_prompt, revise_patch
from app.ai.review import (
    REVIEW_SYSTEM_PROMPT,
    ResumeReviewResult,
    build_review_prompt,
    review_resume,
)
from app.ai.text import strip_code_fence
from app.services.latex import SlotConfig, parse

MASTER = r"""\documentclass{article}
\usepackage{enumitem}
\begin{document}
\section{Experience}
\textbf{Engineer}, Acme \hfill 2021 -- Present
\begin{itemize}
    \item Built REST APIs in Python.
    \item Ran the on-call rotation.
\end{itemize}
\section{Education}
\textbf{B.Tech}, State University \hfill 2018
\end{document}
"""

JOB_DESCRIPTION = "We need a backend engineer with Python, FastAPI and Kubernetes experience."
POSITION = "Backend Engineer"
READABLE = "## Experience\nEngineer, Acme 2021 - Present\n- Built REST APIs in Python"


def _parsed():
    return parse(MASTER, SlotConfig.default(["section"]))


def _fixed(payload: dict) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload)])

    return FunctionModel(respond)


_REVIEW = {
    "match_score": 71,
    "summary": "Solid Python, no Kubernetes.",
    "matched_keywords": ["Python"],
    "missing_keywords": [
        {"keyword": "Kubernetes", "severity": "critical", "rationale": "Listed as required."}
    ],
    "patches": [
        {
            "slot_id": "g1",
            "items": ["Built REST APIs in Python (FastAPI).", "Ran the on-call rotation."],
            "latex": "",
            "reason": "Names the framework the role asks for.",
            "severity": "critical",
        }
    ],
}


# --- what the model is shown -------------------------------------------------


def test_review_prompt_carries_both_views_and_never_the_preamble() -> None:
    prompt = build_review_prompt(_parsed(), READABLE, JOB_DESCRIPTION, POSITION)

    assert POSITION in prompt
    assert JOB_DESCRIPTION in prompt
    assert READABLE in prompt  # what it scores
    assert "[group g1]" in prompt  # what it may propose against
    assert "documentclass" not in prompt
    assert "Education" not in prompt  # frozen sections are not offered up


def test_review_system_prompt_forbids_fabrication() -> None:
    # A safety property of the feature, not a stylistic preference — assert it
    # survives future prompt edits.
    assert "NEVER invent skills" in REVIEW_SYSTEM_PROMPT
    assert "NEVER propose a patch against a slot id that is not in the outline" in (
        REVIEW_SYSTEM_PROMPT
    )


def test_revision_prompt_shows_the_brief_and_what_it_is_revising() -> None:
    prompt = build_revision_prompt(
        section_heading="Experience",
        original="- Built REST APIs in Python.",
        proposed="- Built REST APIs in Python (FastAPI).",
        feedback="Too long.",
        job_description=JOB_DESCRIPTION,
        position_title=POSITION,
    )

    assert "Experience" in prompt
    assert "Too long." in prompt
    assert "(FastAPI)" in prompt


# --- what the app refuses to believe -----------------------------------------


async def test_review_returns_a_validated_result() -> None:
    agent = Agent(_fixed(_REVIEW), output_type=ResumeReviewResult)

    result = await review_resume(_parsed(), READABLE, JOB_DESCRIPTION, POSITION, agent=agent)

    assert result.match_score == 71
    assert result.missing_keywords[0].keyword == "Kubernetes"
    assert [p.slot_id for p in result.patches] == ["g1"]


async def test_a_patch_naming_an_unknown_slot_is_discarded() -> None:
    # A hallucinated id would be a render error at finalize rather than a bad
    # bullet the author could reject. Dropping it salvages the rest.
    payload = {
        **_REVIEW,
        "patches": [*_REVIEW["patches"], {**_REVIEW["patches"][0], "slot_id": "g42"}],
    }
    agent = Agent(_fixed(payload), output_type=ResumeReviewResult)

    result = await review_resume(_parsed(), READABLE, JOB_DESCRIPTION, POSITION, agent=agent)

    assert [p.slot_id for p in result.patches] == ["g1"]


async def test_a_slot_proposed_twice_keeps_only_the_first() -> None:
    # Two patches for one slot would violate the review's unique index, and
    # splicing both is not a thing that can happen — one would silently win.
    payload = {**_REVIEW, "patches": [_REVIEW["patches"][0], _REVIEW["patches"][0]]}
    agent = Agent(_fixed(payload), output_type=ResumeReviewResult)

    result = await review_resume(_parsed(), READABLE, JOB_DESCRIPTION, POSITION, agent=agent)

    assert len(result.patches) == 1


async def test_revise_patch_returns_the_revision() -> None:
    agent = Agent(
        _fixed({"items": ["Built REST APIs."], "latex": "", "note": "Shortened."}),
        output_type=RevisedPatch,
    )

    revised = await revise_patch(
        section_heading="Experience",
        original="- Built REST APIs in Python.",
        proposed="- Built REST APIs in Python (FastAPI).",
        feedback="Too long.",
        job_description=JOB_DESCRIPTION,
        position_title=POSITION,
        agent=agent,
    )

    assert revised.items == ["Built REST APIs."]
    assert revised.note == "Shortened."


# --- fenced replies ----------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("```latex\n\\textbf{Rust}, Go\n```", "\\textbf{Rust}, Go"),
        ("```\nbare fence\n```", "bare fence"),
        ("  ```md\ntrimmed\n```  \n", "trimmed"),
        # Not a wrapper: prose around a fenced block is commentary, and
        # unwrapping the middle would throw the rest away.
        ("Here you go:\n```\nx\n```", "Here you go:\n```\nx\n```"),
        ("```\na\n```\n```\nb\n```", "```\na\n```\n```\nb\n```"),
        ("no fence at all", "no fence at all"),
    ],
)
def test_strip_code_fence(reply: str, expected: str) -> None:
    assert strip_code_fence(reply) == expected


def test_a_text_part_reply_is_still_a_valid_agent_output() -> None:
    # Guards the assumption behind `strip_code_fence` living where it does: an
    # agent can hand back free text, and free text is where fences come from.
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("```latex\n\\textbf{Go}\n```")])

    assert strip_code_fence(respond([], None).parts[0].content) == "\\textbf{Go}"
