r"""Splice tailored content back into the master `.tex`.

Rendering walks the recorded spans from the end of the document backwards and
replaces each one in place. Working back to front means earlier offsets stay
valid as later ones are rewritten, so no bookkeeping is needed to keep the span
map in sync mid-render.

Everything outside the spans is copied through untouched. That is the whole
guarantee: a tailored resume differs from its master only inside bullets and
marked regions, so it cannot look different.

Two checks defend that guarantee from opposite directions, and both live here
because this is the only place an edit ever reaches the document:

- **Before splicing**, a caller-supplied `base_hashes` map is compared against
  the slots as they are *now*. Slot ids are positional, so an edit computed
  against an older master must be refused rather than applied to whatever `g2`
  has since become.
- **After splicing**, the frozen bytes are re-hashed. If they moved, the splice
  was wrong and the output is thrown away instead of shipped.
"""

from dataclasses import dataclass

from app.services.latex.fingerprint import template_hash
from app.services.latex.model import ItemGroup, LatexResume, Span
from app.services.latex.safety import coerce_fragment


class LatexRenderError(ValueError):
    """Raised when an edit cannot be applied to the document it targets."""


class StaleEditError(LatexRenderError):
    """Raised when an edit was computed against a slot that has since changed.

    Recoverable, and the caller's problem: re-read the outline and redo the
    edit. Distinct from its parent so the API can answer 409 rather than 422.
    """


class TemplateDriftError(LatexRenderError):
    """Raised when a render changed bytes outside the editable slots.

    Not recoverable and never the caller's fault — reaching this means the
    splice itself is broken, so the output is discarded rather than returned.
    """


@dataclass
class GroupEdit:
    """The final bullet list for one group, already ordered and filtered."""

    group_id: str
    items: list[str]


@dataclass
class RegionEdit:
    """Replacement LaTeX for one `% jarvis:begin` region."""

    region_id: str
    latex: str


def _indent_before(source: str, index: int) -> str:
    line_start = source.rfind("\n", 0, index) + 1
    prefix = source[line_start:index]
    return prefix if prefix.strip() == "" else ""


def render_group_body(source: str, group: ItemGroup, items: list[str]) -> str:
    """Rebuild a list body in the document's own idiom.

    The item prefix, suffix, and indentation were captured from the original
    items, so a `\\item` list stays a `\\item` list and a `\\resumeItem{...}`
    list stays one — including when the model adds a bullet that was not there.

    A standalone run has no enclosing `\\begin`/`\\end` to sit between: its span
    covers the macro calls themselves, so the replacement must start and end
    exactly on one, with no framing newline.
    """
    rendered = [f"{group.prefix}{item}{group.suffix}" for item in items]
    if group.standalone:
        return f"\n{group.indent}".join(rendered)
    closing_indent = _indent_before(source, group.span.end)
    return "".join(f"\n{group.indent}{line}" for line in rendered) + f"\n{closing_indent}"


def _check_not_stale(slot_id: str, current: str, base_hashes: dict[str, str] | None) -> None:
    """Refuse an edit whose slot no longer holds what the edit was written for.

    A caller that supplies no hash for a slot is trusting the id alone, which is
    the right default for an edit generated and applied in one request.
    """
    expected = (base_hashes or {}).get(slot_id)
    if expected is not None and expected != current:
        raise StaleEditError(
            f"Slot '{slot_id}' has changed since this edit was generated "
            f"(expected {expected}, found {current}). Re-read the outline and redo the edit."
        )


def render(
    resume: LatexResume,
    group_edits: list[GroupEdit] | None = None,
    region_edits: list[RegionEdit] | None = None,
    *,
    base_hashes: dict[str, str] | None = None,
) -> str:
    """Return the tailored `.tex` source.

    `base_hashes` maps slot id to the fingerprint the edit was computed against
    (see `services.latex.fingerprint`). Slots it does not mention are applied
    unconditionally.
    """
    replacements: list[tuple[Span, str]] = []

    for edit in group_edits or []:
        group = resume.group_by_id(edit.group_id)
        if group is None:
            raise LatexRenderError(f"Unknown bullet group '{edit.group_id}'.")
        _check_not_stale(group.id, group.content_hash, base_hashes)
        items = [coerce_fragment(item) for item in edit.items if item.strip()]
        if not items:
            # An empty itemize is a LaTeX error, and a section that lost every
            # bullet is never what the author wanted. Keep the original.
            continue
        replacements.append((group.span, render_group_body(resume.source, group, items)))

    for edit in region_edits or []:
        region = resume.region_by_id(edit.region_id)
        if region is None:
            raise LatexRenderError(f"Unknown marked region '{edit.region_id}'.")
        _check_not_stale(region.id, region.content_hash, base_hashes)
        if not edit.latex.strip():
            continue
        replacements.append((region.span, coerce_fragment(edit.latex)))

    replacements.sort(key=lambda item: item[0].start, reverse=True)
    for earlier, later in zip(replacements[1:], replacements):
        if earlier[0].overlaps(later[0]):
            raise LatexRenderError("Two edits target overlapping regions of the document.")

    source = resume.source
    for span, text in replacements:
        source = source[: span.start] + text + source[span.end :]
    if replacements:
        _assert_template_survived(resume, source)
    return source


def _assert_template_survived(resume: LatexResume, rendered: str) -> None:
    """Re-parse the output and confirm the frozen bytes are unchanged.

    Imported here rather than at module scope: `parser` is a heavier peer that
    does not need `renderer`, and keeping the dependency inside the one function
    that needs it keeps the import graph one-directional.
    """
    from app.services.latex.parser import LatexParseError, parse

    try:
        reparsed = parse(rendered, resume.config)
    except LatexParseError as exc:
        raise TemplateDriftError(
            f"The rendered document no longer parses as a resume: {exc}"
        ) from exc

    before, after = template_hash(resume), template_hash(reparsed)
    if before != after:
        raise TemplateDriftError(
            "Rendering changed the document outside its editable slots "
            f"(template hash {before} became {after}). The output was discarded."
        )
