"""AI-driven repair loop for tailoring patches that fail to apply or compile.

When `apply_tailoring` raises a `LatexRenderError` or `LatexParseError` the
caller normally surfaces a 422 and gives up. This module gives the pipeline a
second chance: it asks the LLM to inspect the error message and the offending
content, rewrite whatever fragment is broken, and retry — up to `max_iterations`
times. A successful run returns the repaired tailoring; exhausting the retries
re-raises the last exception so the caller's existing error handling still works.

The repair agent is intentionally narrow in scope: it may only rewrite the LaTeX
text of individual bullets and region bodies. It cannot add or remove groups,
change group IDs, or touch the master source. This keeps the repair deterministic
and auditable.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from app.ai.limits import run_agent
from app.ai.provider import resolve_model
from app.ai.schemas import ResumeTailoring, TailoredGroup, TailoredRegion
from app.services.latex.parser import LatexParseError
from app.services.latex.renderer import LatexRenderError

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Repair agent schema
# ---------------------------------------------------------------------------

REPAIR_SYSTEM_PROMPT = """\
You are a LaTeX fragment repair assistant.

A tailoring patch was applied to a resume .tex file and caused an error. You are
given the error message and the current state of the patch. Your job is to fix
the specific fragment(s) that caused the problem and return a corrected patch.

Rules:
- Only fix fragments that are clearly broken (unbalanced braces, forbidden
  commands like \\begin/\\end/\\item, unescaped special characters).
- Do NOT invent new content or change the meaning of bullets.
- Do NOT add or remove groups or regions — return exactly the same group_ids and
  region_ids that were given to you.
- Item text is LaTeX. Allowed inline commands: \\textbf, \\textit, \\emph,
  \\texttt, \\underline, \\href, \\textsc, \\textbf. Escape & % $ # _ as \\& \\% \\$ \\# \\_.
- Keep braces balanced. Do NOT emit \\item, \\begin, \\end, or sectioning commands.
- If a fragment cannot be fixed while keeping its meaning, simplify it to plain
  escaped text (strip all markup).
"""


class RepairRequest(BaseModel):
    """What we hand the repair agent."""

    error_message: str = Field(description="The exact error that caused the failure.")
    patch: ResumeTailoring = Field(description="The current patch that failed.")


class RepairedPatch(BaseModel):
    """What the repair agent must return."""

    groups: list[TailoredGroup] = Field(
        default_factory=list,
        description="Corrected groups, same IDs as the input, repaired content.",
    )
    regions: list[TailoredRegion] = Field(
        default_factory=list,
        description="Corrected regions, same IDs as the input, repaired content.",
    )
    repair_notes: str = Field(
        default="",
        description="One sentence describing what was wrong and what was fixed.",
    )


# ---------------------------------------------------------------------------
# Agent factory (lazy, cached per process)
# ---------------------------------------------------------------------------

_repair_agent: Agent[None, RepairedPatch] | None = None


def _get_repair_agent() -> Agent[None, RepairedPatch]:
    global _repair_agent
    if _repair_agent is None:
        _repair_agent = Agent(
            resolve_model(),
            output_type=RepairedPatch,
            system_prompt=REPAIR_SYSTEM_PROMPT,
        )
    return _repair_agent


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _build_repair_prompt(error: str, tailoring: ResumeTailoring) -> str:
    lines: list[str] = [
        f"## Error\n{error}\n",
        "## Current patch",
    ]
    for g in tailoring.groups:
        lines.append(f"\n[group {g.group_id}]")
        for i, item in enumerate(g.items, 1):
            lines.append(f"  {i}. {item}")
    for r in tailoring.regions:
        lines.append(f"\n[region {r.region_id}]")
        lines.append(r.latex)
    lines.append("\nReturn the corrected patch. Keep all group_ids and region_ids unchanged.")
    return "\n".join(lines)


async def repair_tailoring(
    tailoring: ResumeTailoring,
    error: Exception,
    *,
    max_iterations: int = 2,
) -> tuple[ResumeTailoring, list[str]]:
    """Attempt to repair a broken tailoring patch using the LLM.

    Returns ``(repaired_tailoring, repair_notes)`` where ``repair_notes`` is a
    list of the model's explanations across all iterations. Raises the original
    ``error`` unchanged if all iterations are exhausted.
    """
    from app.ai.provider import has_llm_credentials

    if not has_llm_credentials():
        logger.warning("[patch_repair] No LLM credentials — skipping AI repair.")
        raise error

    agent = _get_repair_agent()
    current = tailoring
    notes: list[str] = []
    last_error: Exception = error

    for attempt in range(1, max_iterations + 1):
        error_msg = str(last_error)
        prompt = _build_repair_prompt(error_msg, current)
        logger.info(
            "[patch_repair] Repair attempt %d/%d — error: %s",
            attempt,
            max_iterations,
            error_msg[:200],
        )
        try:
            result = await run_agent(agent, prompt)
            repaired: RepairedPatch = result.output
        except Exception as agent_exc:
            logger.error("[patch_repair] Repair agent failed: %s", agent_exc)
            raise last_error from agent_exc

        # Merge repaired slots back into current tailoring (keep unreferenced
        # groups/regions from the original patch intact).
        repaired_group_map = {g.group_id: g for g in repaired.groups}
        repaired_region_map = {r.region_id: r for r in repaired.regions}

        new_groups = [repaired_group_map.get(g.group_id, g) for g in current.groups]
        new_regions = [repaired_region_map.get(r.region_id, r) for r in current.regions]
        current = current.model_copy(update={"groups": new_groups, "regions": new_regions})
        if repaired.repair_notes:
            notes.append(f"[attempt {attempt}] {repaired.repair_notes}")
            logger.info("[patch_repair] %s", repaired.repair_notes)

        # Validate: try to apply the repaired tailoring to catch issues early.
        # Import here to avoid circular imports (tailoring.py -> renderer.py).
        try:
            from app.services.latex.safety import validate_fragment

            for g in current.groups:
                for item in g.items:
                    if item.strip():
                        try:
                            validate_fragment(item)
                        except Exception as frag_exc:
                            raise LatexRenderError(
                                f"Group '{g.group_id}' item still invalid after repair: {frag_exc}"
                            ) from frag_exc
        except (LatexRenderError, LatexParseError) as validation_exc:
            logger.warning(
                "[patch_repair] Post-repair validation failed (attempt %d): %s",
                attempt,
                validation_exc,
            )
            last_error = validation_exc
            continue

        logger.info("[patch_repair] Repair succeeded on attempt %d.", attempt)
        return current, notes

    logger.error(
        "[patch_repair] All %d repair attempts exhausted. Last error: %s",
        max_iterations,
        last_error,
    )
    raise last_error
