r"""Splice tailored content back into the master `.tex`.

Rendering walks the recorded spans from the end of the document backwards and
replaces each one in place. Working back to front means earlier offsets stay
valid as later ones are rewritten, so no bookkeeping is needed to keep the span
map in sync mid-render.

Everything outside the spans is copied through untouched. That is the whole
guarantee: a tailored resume differs from its master only inside bullets and
marked regions, so it cannot look different.
"""

from dataclasses import dataclass

from app.services.latex.model import ItemGroup, LatexResume, Span
from app.services.latex.safety import coerce_fragment


class LatexRenderError(ValueError):
    """Raised when an edit cannot be applied to the document it targets."""


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
    """
    closing_indent = _indent_before(source, group.span.end)
    lines = [f"\n{group.indent}{group.prefix}{item}{group.suffix}" for item in items]
    return "".join(lines) + f"\n{closing_indent}"


def render(
    resume: LatexResume,
    group_edits: list[GroupEdit] | None = None,
    region_edits: list[RegionEdit] | None = None,
) -> str:
    """Return the tailored `.tex` source."""
    replacements: list[tuple[Span, str]] = []

    for edit in group_edits or []:
        group = resume.group_by_id(edit.group_id)
        if group is None:
            raise LatexRenderError(f"Unknown bullet group '{edit.group_id}'.")
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
    return source
