r"""Turn an uploaded `.tex` into a stored master, or refuse it with a reason.

`ai/intake.py` produces a *claim*: these corrections will make it compile, and
these macros mean these things. This module is what stands between that claim
and the database, and nothing in it takes the model's word for anything.

The gauntlet, in order, because each stage is cheap relative to the next:

1. **Corrections must apply exactly.** Every `find` has to occur exactly once.
   Absent means the model quoted text that is not there; ambiguous means the edit
   would land somewhere unintended. Both are rejected by name rather than
   guessed at.
2. **The config must resolve.** `to_slot_config` validates the vocabulary and
   `parse` proves the macros find real spans — see `services/slot_discovery.py`,
   which already owns both checks and the invariants behind them.
3. **The document must compile.** The last word belongs to the engine. A
   correction that satisfies the parser and still will not build is a failed
   upload, not a stored resume somebody discovers is broken a week later.

Rejecting a document at upload, while its author is looking at it, is the whole
point. The alternative — storing it and failing at render — is what this flow
was rebuilt to stop.
"""

from dataclasses import dataclass

from app.ai.intake import Correction, LatexIntake, read_upload
from app.ai.slot_schema import preamble_end
from app.core.config import get_settings
from app.services.latex import (
    LatexCompileError,
    LatexEngineNotFoundError,
    LatexErrorCode,
    LatexParseError,
    LatexResume,
    SlotConfig,
    compile_pdf,
    detect_engine,
    incompatibility,
    parse,
)
from app.services.slot_discovery import (
    SlotDiscoveryError,
    check_invariants,
    to_slot_config,
)


class IntakeError(ValueError):
    """Raised when an uploaded document cannot be turned into a usable master.

    Carries a `code` distinguishing *why* rather than just *that*: the engine's
    own verdict (`INVALID_LATEX`) versus the parser or vocabulary describing the
    document being unable to find structure in it (`UNSUPPORTED_LATEX`, the
    default — most of the gauntlet's checks are of this kind). A caller can act
    differently on the two: the first means "fix the .tex", the second means
    "fix the vocabulary" or "widen what the parser understands".
    """

    def __init__(self, message: str, *, code: LatexErrorCode = LatexErrorCode.UNSUPPORTED_LATEX) -> None:
        super().__init__(message)
        self.code = code


class IntakeEngineMissing(RuntimeError):
    """Raised when the engine needed to verify the upload is not installed.

    Distinct from `IntakeError` because it is the operator's problem, not the
    author's: their document may well be fine and there is nothing for them to
    fix. The router turns this into a 503 rather than a 422.
    """


@dataclass(frozen=True)
class IntakeResult:
    """A document that has earned its way into the database."""

    source: str
    config: SlotConfig
    resume: LatexResume
    corrections: tuple[Correction, ...]
    verdict: str
    #: The engine the document was actually proven to compile under — the
    #: author's explicit choice, or detection's verdict on the server default.
    #: The caller persists this (not the raw, possibly-None request value) so
    #: a document detection moved off the default stays moved.
    engine: str


def apply_corrections(source: str, corrections: list[Correction]) -> str:
    r"""Apply exact-match edits, refusing anything ambiguous.

    Each `find` is located in the *original* text and all replacements are
    spliced in one pass, so a correction cannot land inside text another
    correction just introduced. Overlapping corrections are rejected for the same
    reason: two edits to one span have no defined order, and picking one would be
    a coin toss the author never sees.
    """
    edits: list[tuple[int, int, Correction]] = []
    for correction in corrections:
        if not correction.find:
            raise IntakeError("A correction arrived with an empty `find`, which matches nothing.")
        occurrences = source.count(correction.find)
        if occurrences == 0:
            raise IntakeError(
                f"A correction quoted text that is not in the document: "
                f"{_excerpt(correction.find)!r} ({correction.reason})"
            )
        if occurrences > 1:
            raise IntakeError(
                f"A correction quoted text that appears {occurrences} times, so there is no "
                f"single place to apply it: {_excerpt(correction.find)!r} ({correction.reason})"
            )
        start = source.index(correction.find)
        edits.append((start, start + len(correction.find), correction))

    edits.sort(key=lambda edit: edit[0])
    for (_, previous_end, earlier), (next_start, _, later) in zip(edits, edits[1:]):
        if next_start < previous_end:
            raise IntakeError(
                f"Two corrections overlap the same text, so neither can be applied safely: "
                f"{earlier.reason!r} and {later.reason!r}"
            )

    pieces: list[str] = []
    cursor = 0
    for start, end, correction in edits:
        pieces.append(source[cursor:start])
        pieces.append(correction.replace)
        cursor = end
    pieces.append(source[cursor:])
    return "".join(pieces)


def _excerpt(text: str, limit: int = 80) -> str:
    """A one-line, length-capped view of a fragment, for an error message."""
    flattened = " ".join(text.split())
    return flattened if len(flattened) <= limit else f"{flattened[:limit]}…"


def build_config(intake: LatexIntake) -> SlotConfig:
    """Turn the proposed vocabulary into a validated config, or refuse it."""
    try:
        return to_slot_config(intake.slot_schema, get_settings().latex_section_macro_list)
    except SlotDiscoveryError as exc:
        raise IntakeError(str(exc)) from exc


async def verify_compiles(source: str, engine: str) -> None:
    """The engine's verdict on the corrected document.

    A known-bad document/engine pairing is caught first: `incompatibility` can
    say "these primitives need pdfTeX" in one sentence, where the engine would
    take a hundred lines of log to say the same thing less clearly. `engine`
    is always concrete here — resolving *which* engine is the caller's job,
    because that resolution has to happen before the model is prompted too.
    """
    if reason := incompatibility(source, engine):
        raise IntakeError(
            f"The document still cannot compile under '{engine}' after corrections. {reason}",
            code=LatexErrorCode.INVALID_LATEX,
        )
    try:
        await compile_pdf(source, engine)
    except LatexEngineNotFoundError as exc:
        raise IntakeEngineMissing(str(exc)) from exc
    except LatexCompileError as exc:
        raise IntakeError(
            f"The corrected document still does not compile:\n{exc}",
            code=LatexErrorCode.INVALID_LATEX,
        ) from exc


async def ingest(source: str, engine: str | None, *, agent=None) -> IntakeResult:
    """Read, correct, validate and prove an uploaded `.tex`.

    `engine` is the name the author chose, or None to run detection against the
    server default (see `services/latex/engines.py::detect_engine`) — a
    document using pdfTeX-only primitives like `\\input{glyphtounicode}` moves
    off a XeTeX-based default before the model ever sees it, the same way it
    would move off an explicit XeTeX choice. Either way the model is always
    told a concrete engine, because "whatever the server is configured with"
    is not something it can reason about. The resolved engine comes back on
    `IntakeResult.engine` so the caller can persist *that*, not the original
    possibly-None request value — otherwise the document reverts to the
    server's raw default (which it may not compile under) the next time
    something falls back to "no engine chosen".
    """
    settings = get_settings()
    resolved = engine or detect_engine(source, settings.latex_default_engine)

    intake = await read_upload(
        source,
        resolved,
        preamble_end(source),
        settings.latex_discovery_max_chars,
        agent=agent,
    )

    corrected = apply_corrections(source, intake.corrections)
    config = build_config(intake)

    try:
        resume = parse(corrected, config)
    except LatexParseError as exc:
        raise IntakeError(
            f"The proposed macros do not resolve to any content in this document: {exc}"
        ) from exc

    try:
        check_invariants(resume, config)
    except SlotDiscoveryError as exc:
        raise IntakeError(str(exc)) from exc

    await verify_compiles(corrected, resolved)

    return IntakeResult(
        source=corrected,
        config=config,
        resume=resume,
        corrections=tuple(intake.corrections),
        verdict=intake.verdict,
        engine=resolved,
    )
