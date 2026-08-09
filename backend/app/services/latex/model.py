"""The in-memory shape of a parsed LaTeX resume.

The central idea of the whole LaTeX feature lives here: a master `.tex` is never
*regenerated*, only *spliced*. We keep the original source verbatim and record
byte spans of the regions that tailoring is allowed to touch. Everything outside
those spans — documentclass, packages, `\\newcommand` macros, geometry, fonts,
section scaffolding, employers, titles, dates — is reproduced byte for byte in
every tailored child.

That is what makes "same template, different content" a structural guarantee
rather than a best effort: the untouched bytes cannot drift, because nothing
ever rewrites them.
"""

from dataclasses import dataclass, field

from app.services.latex.config import SlotConfig
from app.services.latex.fingerprint import slot_hash


@dataclass(frozen=True)
class Span:
    """A half-open `[start, end)` range of the original source."""

    start: int
    end: int

    def text(self, source: str) -> str:
        return source[self.start : self.end]

    def overlaps(self, other: "Span") -> bool:
        return self.start < other.end and other.start < self.end


@dataclass
class Bullet:
    """One `\\item` (or `\\resumeItem{...}`) body — the atom of tailoring."""

    id: str
    span: Span
    latex: str

    @property
    def content_hash(self) -> str:
        return slot_hash(self.latex)


@dataclass
class ItemGroup:
    """A list environment whose items may be rewritten, reordered, or dropped.

    `prefix`/`suffix` are captured from the *original* items so re-rendered
    items are written back in the document's own idiom: a `\\item` list gets
    `\\item `, a Jake's-template list gets `\\resumeItem{` … `}`.
    """

    id: str
    kind: str
    span: Span
    indent: str
    prefix: str
    suffix: str
    bullets: list[Bullet] = field(default_factory=list)
    #: True when the group is a bare run of macro calls rather than the body of
    #: a list environment. The span then covers the calls themselves, so the
    #: renderer must emit them rather than just their contents.
    standalone: bool = False

    @property
    def content_hash(self) -> str:
        """Fingerprint of the whole list — its bullets, in their current order.

        Built from the bullet hashes rather than the raw span so that reordering
        the list changes it, which is what a group-level edit actually competes
        with.
        """
        return slot_hash(*(bullet.content_hash for bullet in self.bullets))


@dataclass
class MarkedRegion:
    """An arbitrary span the author opted into with `% jarvis:begin <label>`.

    The bullet parser handles the common case automatically. Markers exist for
    everything it deliberately does not guess at — a skills line built out of
    custom macros, a professional summary, a tagline — letting the author widen
    the editable surface without the parser having to understand their macros.
    """

    id: str
    label: str
    span: Span
    latex: str
    #: "marker" for `% jarvis:begin`, "field" for one argument of a configured
    #: macro. The distinction matters to the discovery invariants: an author who
    #: wrote a marker meant it, while an inferred field slot has to earn trust.
    origin: str = "marker"

    @property
    def content_hash(self) -> str:
        return slot_hash(self.latex)


@dataclass
class Section:
    """A `\\section`-delimited slice of the body and the editable units in it."""

    id: str
    heading: str
    span: Span
    groups: list[ItemGroup] = field(default_factory=list)
    regions: list[MarkedRegion] = field(default_factory=list)

    @property
    def is_editable(self) -> bool:
        return bool(self.groups or self.regions)


@dataclass
class LatexResume:
    """A master `.tex` plus the map of what tailoring may change."""

    source: str
    preamble: Span
    body: Span
    sections: list[Section] = field(default_factory=list)
    #: The config this document was parsed with. Recorded so a render can
    #: re-parse its own output the same way to verify the template survived —
    #: re-parsing with different rules would compare two different documents.
    config: SlotConfig = field(default_factory=SlotConfig.default)

    @property
    def groups(self) -> list[ItemGroup]:
        return [group for section in self.sections for group in section.groups]

    @property
    def regions(self) -> list[MarkedRegion]:
        return [region for section in self.sections for region in section.regions]

    @property
    def bullet_count(self) -> int:
        return sum(len(group.bullets) for group in self.groups)

    def group_by_id(self, group_id: str) -> ItemGroup | None:
        return next((g for g in self.groups if g.id == group_id), None)

    def region_by_id(self, region_id: str) -> MarkedRegion | None:
        return next((r for r in self.regions if r.id == region_id), None)
