r"""Hashes that make splicing safe: one per editable slot, one for the template.

Two separate guarantees, both cheap:

- **`slot_hash` fingerprints one editable slot's current text.** Slot ids are
  positional — the second bullet list in the document is `g2`, whatever it now
  contains. A tailoring result therefore cannot be trusted against a master that
  has since been edited: `g2` may be a different list entirely. Carrying the
  hashes the tailoring was computed against turns that silent mis-splice into a
  refusal.

- **`template_hash` fingerprints everything *outside* the editable slots.** The
  back-to-front splice in `renderer` already makes template preservation
  structural, but structural guarantees decay quietly — one future span that is
  computed slightly too wide and the promise is gone with no test failing.
  Hashing the frozen bytes before and after a render makes "the template cannot
  change" an assertion that fails loudly on the day it stops being true.

Slot hashes normalise whitespace first, so re-wrapping a long `\item` across two
lines — an editing habit, not a content change — does not invalidate a pending
tailoring. The template hash deliberately does not: there, a changed byte is
exactly what we are looking for.
"""

import hashlib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cycle would be runtime-only
    from app.services.latex.model import LatexResume

_WHITESPACE = re.compile(r"\s+")

#: Half of SHA-256 is far past collision-resistant for a document with tens of
#: slots, and short enough to read in a JSON payload or a failing test.
_DIGEST_LENGTH = 32


def _digest(*parts: str) -> str:
    """Hash parts with an unambiguous separator between them.

    The NUL terminator is what stops `["ab", "c"]` and `["a", "bc"]` from
    hashing alike — which for the template hash would mean a slot boundary
    could move without the hash noticing.
    """
    sha = hashlib.sha256()
    for part in parts:
        sha.update(part.encode("utf-8"))
        sha.update(b"\x00")
    return sha.hexdigest()[:_DIGEST_LENGTH]


def normalise(text: str) -> str:
    """Collapse runs of whitespace so reflowing a line is not a content change."""
    return _WHITESPACE.sub(" ", text).strip()


def slot_hash(*parts: str) -> str:
    """Fingerprint an editable slot from its text, or from its children's hashes."""
    return _digest(*(normalise(part) for part in parts))


def slot_hashes(resume: "LatexResume") -> dict[str, str]:
    """Every editable slot's current fingerprint, keyed by the id clients use.

    Bullets are included alongside their group even though tailoring currently
    replaces whole groups: a client that lets the user accept one bullet at a
    time needs the finer-grained hash, and computing it here costs nothing.
    """
    hashes = {group.id: group.content_hash for group in resume.groups}
    hashes.update(
        {bullet.id: bullet.content_hash for group in resume.groups for bullet in group.bullets}
    )
    hashes.update({region.id: region.content_hash for region in resume.regions})
    return hashes


def document_fingerprint(*parts: str) -> str:
    """Fingerprint a stored document from the inputs that decide what it says.

    Coarser than either hash above and answering a different question: not "may
    this splice land" but "is a cached derivation of this document still about
    this document". A score is the derivation in question — it reads the resume
    through its slot vocabulary, so a changed vocabulary can move the number
    without a byte of `content` changing, and both belong in the hash.

    Whitespace is normalised, matching `slot_hash`: reflowing a long line is an
    editing habit, and invalidating every cached score over one helps nobody.
    """
    return _digest(*(normalise(part) for part in parts))


def frozen_chunks(resume: "LatexResume") -> list[str]:
    """The source split into the runs of bytes no edit is allowed to touch.

    Bullets are not subtracted separately — they live inside their group's span,
    which is already excluded.
    """
    spans = sorted(
        [group.span for group in resume.groups] + [region.span for region in resume.regions],
        key=lambda span: span.start,
    )
    chunks: list[str] = []
    cursor = 0
    for span in spans:
        chunks.append(resume.source[cursor : span.start])
        cursor = span.end
    chunks.append(resume.source[cursor:])
    return chunks


def template_hash(resume: "LatexResume") -> str:
    """Fingerprint the frozen half of the document.

    Two documents share this hash only if they have the same slots in the same
    places with byte-identical scaffolding between them. Content inside the
    slots is invisible to it — which is the entire point.
    """
    return _digest(*frozen_chunks(resume))
