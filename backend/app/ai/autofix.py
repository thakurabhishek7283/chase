from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, StateGraph
from pydantic_ai import Agent

from app.ai.ats import build_rewrite_prompt, get_rewrite_agent, get_scoring_agent, score_resume
from app.ai.limits import run_agent
from app.ai.schemas import ATSReport, AutofixResult, PhrasingSuggestion
from app.core.config import get_settings


def _keep_last(_current: object, incoming: object) -> object:
    return incoming


class AutofixState(TypedDict, total=False):
    """State threaded through the analyze -> fix -> re-score loop."""

    job_description: str
    position_title: str
    target_score: int
    max_iterations: int

    resume_markdown: str
    original_score: int
    current_report: ATSReport
    iterations: int
    applied_suggestions: Annotated[list[PhrasingSuggestion], _keep_last]
    stopped_because: Literal["target_reached", "no_further_gains", "max_iterations"]


def build_autofix_graph(
    scoring_agent: Agent | None = None,
    rewrite_agent: Agent | None = None,
):
    """Build the LangGraph state machine for iterative resume improvement.

    Flow:
        score -> [decide] -> rewrite -> score -> ... -> END

    The `decide` edge is what makes this a graph rather than a chain: it loops
    back to `rewrite` while the score is still climbing and the iteration budget
    holds, and exits otherwise. Agents are injectable for testing.
    """

    async def score_node(state: AutofixState) -> AutofixState:
        report = await score_resume(
            state["resume_markdown"],
            state["job_description"],
            state["position_title"],
            agent=scoring_agent or get_scoring_agent(),
        )
        update: AutofixState = {"current_report": report}
        if "original_score" not in state:
            update["original_score"] = report.match_score

        # The termination decision is made here, not in the conditional edge:
        # LangGraph passes edge functions a copy of state, so anything written
        # there is discarded. Nodes are the only place state updates persist.
        iterations = state.get("iterations", 0)
        if report.match_score >= state["target_score"]:
            update["stopped_because"] = "target_reached"
        elif iterations >= state["max_iterations"]:
            update["stopped_because"] = "max_iterations"
        elif not report.suggestions:
            # Nothing actionable left to apply — another rewrite would just churn.
            update["stopped_because"] = "no_further_gains"
        return update

    async def rewrite_node(state: AutofixState) -> AutofixState:
        report = state["current_report"]
        # Spend the rewrite on the gaps that actually move the score.
        actionable = [s for s in report.suggestions if s.severity in ("critical", "important")]
        if not actionable:
            actionable = report.suggestions

        suggestions_text = "\n".join(
            f"- [{s.severity}] Replace {s.original_text!r} with {s.suggested_text!r} ({s.reason})"
            if s.original_text
            else f"- [{s.severity}] Add: {s.suggested_text!r} ({s.reason})"
            for s in actionable
        )

        agent = rewrite_agent or get_rewrite_agent()
        result = await run_agent(
            agent,
            build_rewrite_prompt(
                state["resume_markdown"], state["job_description"], suggestions_text
            ),
        )
        return {
            "resume_markdown": result.output,
            "iterations": state.get("iterations", 0) + 1,
            "applied_suggestions": state.get("applied_suggestions", []) + actionable,
        }

    def decide(state: AutofixState) -> Literal["rewrite", "__end__"]:
        """Route only — `score_node` already recorded why we would stop."""
        return END if state.get("stopped_because") else "rewrite"

    graph = StateGraph(AutofixState)
    graph.add_node("score", score_node)
    graph.add_node("rewrite", rewrite_node)
    graph.set_entry_point("score")
    graph.add_conditional_edges("score", decide, {"rewrite": "rewrite", END: END})
    graph.add_edge("rewrite", "score")
    return graph.compile()


async def run_autofix(
    resume_markdown: str,
    job_description: str,
    position_title: str,
    *,
    target_score: int = 85,
    max_iterations: int | None = None,
    scoring_agent: Agent | None = None,
    rewrite_agent: Agent | None = None,
) -> AutofixResult:
    """Run the autofix loop and return the improved resume plus its final report."""
    settings = get_settings()
    budget = max_iterations if max_iterations is not None else settings.ats_max_autofix_iterations

    app = build_autofix_graph(scoring_agent, rewrite_agent)
    final: AutofixState = await app.ainvoke(
        {
            "resume_markdown": resume_markdown,
            "job_description": job_description,
            "position_title": position_title,
            "target_score": target_score,
            "max_iterations": budget,
            "iterations": 0,
            "applied_suggestions": [],
        }
    )

    report = final["current_report"]
    return AutofixResult(
        original_score=final.get("original_score", report.match_score),
        final_score=report.match_score,
        iterations=final.get("iterations", 0),
        revised_resume_markdown=final["resume_markdown"],
        applied_suggestions=final.get("applied_suggestions", []),
        final_report=report,
        stopped_because=final.get("stopped_because", "max_iterations"),
    )
