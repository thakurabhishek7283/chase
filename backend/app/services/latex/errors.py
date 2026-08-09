"""Shared vocabulary for classifying why a LaTeX document could not be used.

Every failure on the validate/parse/compile path reduces to one of two reasons
a caller can act on differently:

- `INVALID_LATEX` — the engine's own verdict: the document does not compile,
  or is pre-flighted as unable to (see `services/latex/engines.incompatibility`).
  Fixing it means fixing the `.tex` itself.
- `UNSUPPORTED_LATEX` — the document may well be valid LaTeX, but the parser or
  the slot vocabulary describing it cannot find structure in it: a correction
  did not apply, a proposed macro resolves to nothing, or a config fails its
  invariants. Fixing it means fixing the vocabulary, not the document.

There is no third code for the success case: a document that raises neither
needs no error to render.
"""

from enum import Enum


class LatexErrorCode(str, Enum):
    INVALID_LATEX = "invalid_latex"
    UNSUPPORTED_LATEX = "unsupported_latex"
