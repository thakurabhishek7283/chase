import json

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.ai.ats import SCORING_SYSTEM_PROMPT, build_scoring_prompt, score_resume
from app.ai.autofix import run_autofix
from app.ai.schemas import ATSReport, PhrasingSuggestion

RESUME = "## Experience\n- Built REST APIs in Python"
JOB_DESCRIPTION = "We need a backend engineer with Python, FastAPI and Kubernetes experience."
POSITION = "Backend Engineer"


def _report_payload(score: int, suggestions: list[dict] | None = None) -> dict:
    return {
        "match_score": score,
        "summary": f"Scored {score}.",
        "matched_keywords": ["Python"],
        "missing_keywords": [
            {"keyword": "Kubernetes", "severity": "critical", "rationale": "Listed as required."}
        ],
        "suggestions": suggestions
        if suggestions is not None
        else [
            {
                "original_text": "- Built REST APIs in Python",
                "suggested_text": "- Built REST APIs in Python (FastAPI), deployed on Kubernetes",
                "reason": "Surfaces the two required keywords.",
                "severity": "critical",
            }
        ],
    }


def _scoring_model(scores: list[int]) -> FunctionModel:
    """A scoring model that returns each score in turn, then repeats the last."""
    calls = {"n": 0}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        index = min(calls["n"], len(scores) - 1)
        score = scores[index]
        calls["n"] += 1
        # No suggestions on the final score stops the loop cleanly.
        suggestions: list[dict] | None = [] if index == len(scores) - 1 and score < 100 else None
        tool_name = info.output_tools[0].name
        return ModelResponse(
            parts=[ToolCallPart(tool_name, _report_payload(score, suggestions))]
        )

    return FunctionModel(respond)


def _rewrite_model(text: str = "## Experience\n- Built REST APIs in Python (FastAPI) on Kubernetes"):
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(text)])

    return FunctionModel(respond)


def test_build_scoring_prompt_includes_all_inputs() -> None:
    prompt = build_scoring_prompt(RESUME, JOB_DESCRIPTION, POSITION)
    assert POSITION in prompt
    assert JOB_DESCRIPTION in prompt
    assert RESUME in prompt


def test_system_prompt_forbids_fabrication() -> None:
    # The anti-fabrication rule is a safety property of this feature, not a
    # stylistic preference — assert it survives future prompt edits.
    assert "Never fabricate" in SCORING_SYSTEM_PROMPT


async def test_score_resume_returns_validated_report() -> None:
    agent = Agent(_scoring_model([72]), output_type=ATSReport, system_prompt=SCORING_SYSTEM_PROMPT)
    report = await score_resume(RESUME, JOB_DESCRIPTION, POSITION, agent=agent)

    assert isinstance(report, ATSReport)
    assert report.match_score == 72
    assert report.missing_keywords[0].keyword == "Kubernetes"
    assert report.critical_gap_count == 1


async def test_autofix_loops_until_target_reached() -> None:
    scoring = Agent(_scoring_model([60, 90]), output_type=ATSReport)
    rewrite = Agent(_rewrite_model(), output_type=str)

    result = await run_autofix(
        RESUME,
        JOB_DESCRIPTION,
        POSITION,
        target_score=85,
        max_iterations=5,
        scoring_agent=scoring,
        rewrite_agent=rewrite,
    )

    assert result.original_score == 60
    assert result.final_score == 90
    assert result.iterations == 1
    assert result.stopped_because == "target_reached"
    assert "Kubernetes" in result.revised_resume_markdown
    assert result.applied_suggestions


async def test_autofix_respects_iteration_budget() -> None:
    # Score never reaches the target, so only the budget can stop the loop.
    scoring = Agent(_scoring_model([40, 41, 42, 43, 44, 45]), output_type=ATSReport)
    rewrite = Agent(_rewrite_model(), output_type=str)

    result = await run_autofix(
        RESUME,
        JOB_DESCRIPTION,
        POSITION,
        target_score=99,
        max_iterations=2,
        scoring_agent=scoring,
        rewrite_agent=rewrite,
    )

    assert result.iterations == 2
    assert result.stopped_because == "max_iterations"


async def test_autofix_stops_when_no_suggestions_remain() -> None:
    scoring = Agent(_scoring_model([70, 70]), output_type=ATSReport)
    rewrite = Agent(_rewrite_model(), output_type=str)

    result = await run_autofix(
        RESUME,
        JOB_DESCRIPTION,
        POSITION,
        target_score=99,
        max_iterations=5,
        scoring_agent=scoring,
        rewrite_agent=rewrite,
    )

    assert result.stopped_because == "no_further_gains"
    assert result.iterations < 5


async def test_autofix_returns_unchanged_resume_when_already_at_target() -> None:
    scoring = Agent(_scoring_model([95]), output_type=ATSReport)
    rewrite = Agent(_rewrite_model(), output_type=str)

    result = await run_autofix(
        RESUME,
        JOB_DESCRIPTION,
        POSITION,
        target_score=85,
        scoring_agent=scoring,
        rewrite_agent=rewrite,
    )

    assert result.iterations == 0
    assert result.revised_resume_markdown == RESUME
    assert result.stopped_because == "target_reached"
