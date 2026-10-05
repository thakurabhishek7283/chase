"""Splice reviewed content back into a master's own bytes.

The model never returns a document — only the contents of numbered slots — and
this is where those land. The master's preamble, section machinery, employers
and dates are copied through untouched, which is what makes a tailored resume
provably the same resume with different words in it.
"""

import logging

from app.ai.schemas import ResumeTailoring
from app.services.latex import SlotConfig, parse, render
from app.services.latex.failure_dump import dump_failure
from app.services.latex.parser import LatexParseError
from app.services.latex.patch_repair import repair_tailoring
from app.services.latex.renderer import (
    GroupEdit,
    LatexRenderError,
    RegionEdit,
    StaleEditError,
    TemplateDriftError,
)

logger = logging.getLogger(__name__)


def apply_tailoring(
    source: str,
    tailoring: ResumeTailoring,
    config: SlotConfig | None = None,
    base_hashes: dict[str, str] | None = None,
    *,
    resume_id: str | None = None,
    user_id: str | None = None,
) -> str:
    """Splice a tailoring result into a master `.tex` and return the new source.

    `base_hashes` is what makes applying a *stored* tailoring safe. The master is
    re-parsed here, so ids are recomputed against whatever it contains now; the
    hashes are the only thing that can tell whether `g2` is still the list the
    tailoring was written for.

    On `LatexParseError` or `LatexRenderError` the failed patch and source are
    written to a timestamped directory under ``JARVIS_FAILURE_DUMP_DIR`` so the
    error can be investigated offline. `StaleEditError` and `TemplateDriftError`
    are re-raised immediately — they are concurrency/integrity issues, not content
    issues, and the AI repair loop cannot help with them.
    """
    resume = parse(source, config)
    try:
        return render(
            resume,
            group_edits=[GroupEdit(g.group_id, g.items) for g in tailoring.groups],
            region_edits=[RegionEdit(r.region_id, r.latex) for r in tailoring.regions],
            base_hashes=base_hashes,
        )
    except (StaleEditError, TemplateDriftError):
        # These are not content/fragment errors; re-raise immediately so the
        # caller can map them to 409 / 500 respectively.
        raise
    except (LatexParseError, LatexRenderError) as exc:
        dump_failure(
            error=exc,
            tailoring=tailoring,
            source_tex=source,
            resume_id=resume_id,
            user_id=user_id,
            context="apply_tailoring",
        )
        raise


async def apply_tailoring_with_repair(
    source: str,
    tailoring: ResumeTailoring,
    config: SlotConfig | None = None,
    base_hashes: dict[str, str] | None = None,
    *,
    resume_id: str | None = None,
    user_id: str | None = None,
    max_repair_iterations: int = 2,
) -> tuple[str, ResumeTailoring, list[str]]:
    """Like `apply_tailoring` but uses the LLM to fix broken patches at runtime.

    On `LatexParseError` or `LatexRenderError` the failure is dumped to disk
    *and* the repair agent is invoked to rewrite the offending fragments. If the
    repair succeeds the result is returned transparently; if all iterations are
    exhausted the last error is re-raised.

    Returns ``(tailored_latex, final_tailoring, repair_notes)`` where
    ``repair_notes`` is empty when no repair was needed.
    """
    resume = parse(source, config)

    def _render(t: ResumeTailoring) -> str:
        return render(
            resume,
            group_edits=[GroupEdit(g.group_id, g.items) for g in t.groups],
            region_edits=[RegionEdit(r.region_id, r.latex) for r in t.regions],
            base_hashes=base_hashes,
        )

    try:
        return _render(tailoring), tailoring, []
    except (StaleEditError, TemplateDriftError):
        raise
    except (LatexParseError, LatexRenderError) as exc:
        dump_failure(
            error=exc,
            tailoring=tailoring,
            source_tex=source,
            resume_id=resume_id,
            user_id=user_id,
            context="apply_tailoring_pre_repair",
        )
        logger.warning(
            "[apply_tailoring] Initial apply failed (%s: %s) — attempting AI repair.",
            type(exc).__name__,
            exc,
        )
        # Python unbinds the `as` name when the clause ends, so the repair loop
        # below needs its own reference. Without this the whole repair path
        # dies with UnboundLocalError instead of surfacing the real error.
        first_exc = exc

    # Repair loop -----------------------------------------------------------
    repaired, notes = await repair_tailoring(
        tailoring,
        first_exc,
        max_iterations=max_repair_iterations,
    )

    try:
        result = _render(repaired)
        logger.info("[apply_tailoring] Patch applied successfully after AI repair.")
        return result, repaired, notes
    except (LatexParseError, LatexRenderError) as post_exc:
        dump_failure(
            error=post_exc,
            tailoring=repaired,
            source_tex=source,
            resume_id=resume_id,
            user_id=user_id,
            context="apply_tailoring_post_repair",
        )
        logger.error("[apply_tailoring] AI repair did not fix the issue: %s", post_exc)
        raise post_exc
