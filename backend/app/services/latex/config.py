r"""What the parser should treat as editable in *this* document.

The parser started with three hardcoded shapes — `\item` bodies, `\resumeItem{…}`,
and `% jarvis:begin` markers — which covers stock LaTeX and the widely-copied
"Jake's resume" template and nothing else. Real resumes are written on top of
moderncv, AltaCV, or a preamble the author wrote themselves, where the bullets
live inside `\achievement{…}` or `\cvline{}{}` and the automatic parser finds
nothing at all.

A `SlotConfig` lifts those constants into per-document configuration, so the same
deterministic machinery can read a template it has never seen. Three ways to
declare content:

| Declaration | Shape | Becomes |
|---|---|---|
| `environments` / `list_pairs` | `\begin{itemize}…`, `\workItems…\workItemsEnd` | a reorderable bullet group |
| `bullet_macros` | `\achievement{prose}` | a bullet, whether inside a list or standing on its own |
| `field_macros` | `\cvline{Languages}{prose}` | one editable argument; every other argument stays frozen |

`field_macros` is the important one for truthfulness. A macro like
`\cventry{employer}{title}{dates}{prose}` has exactly one argument a tailoring
pass should touch, and naming that index means the employer and the dates are
not merely *asked* to stay put — they are outside every editable span, so
nothing in the pipeline can reach them.

Where the config comes from is deliberately not this module's business: the
built-in default, an LLM proposal (`services/slot_discovery.py`), and an author
editing it by hand all produce the same frozen dataclass, and all three go
through the same `validate` on the way in.
"""

import re
from dataclasses import asdict, dataclass, replace
from typing import Any

#: Commands that define the document rather than fill it. Naming one as a slot
#: macro would hand tailoring the layout, which is the one thing it must never
#: have — so this is refused wherever a config comes from.
_STRUCTURAL_MACROS = frozenset(
    {
        "documentclass",
        "usepackage",
        "begin",
        "end",
        "item",
        "newcommand",
        "renewcommand",
        "providecommand",
        "def",
        "let",
        "input",
        "include",
        "section",
        "subsection",
        "subsubsection",
        "chapter",
        "part",
        "paragraph",
        "write18",
        "immediate",
        "csname",
        "expandafter",
        "catcode",
        "newpage",
        "clearpage",
        "special",
        "directlua",
        "write",
        "openout",
        "openin",
        "read",
    }
)

#: Inline formatting. Legal inside a slot, never legal *as* one: declaring
#: `\textbf` a bullet macro would make every bold run in the document editable
#: and nest slots inside each other.
_FORMATTING_MACROS = frozenset(
    {
        "textbf",
        "textit",
        "textsc",
        "texttt",
        "textrm",
        "textsf",
        "emph",
        "underline",
        "uline",
        "href",
        "url",
        "small",
        "footnotesize",
        "normalsize",
        "large",
        "Large",
        "LARGE",
        "huge",
        "Huge",
        "mbox",
        "text",
        "hfill",
        "vspace",
        "hspace",
        "textsuperscript",
        "textsubscript",
        "color",
        "textcolor",
    }
)

_MACRO_NAME = re.compile(r"^[A-Za-z@]+\*?$")

#: Ceilings on a proposed config. A template with thirty different bullet macros
#: is not a template that was understood, so refuse it rather than parse it.
MAX_BULLET_MACROS = 12
MAX_FIELD_MACROS = 24
MAX_LIST_PAIRS = 8
MAX_ARITY = 9


class SlotConfigError(ValueError):
    """Raised when a slot configuration is malformed or unsafe to parse with."""


def _clean_macro_name(raw: str, *, role: str) -> str:
    """Normalise a macro name and refuse the ones no config may claim."""
    name = raw.strip().lstrip("\\").strip()
    if not _MACRO_NAME.match(name):
        raise SlotConfigError(f"{role} '{raw}' is not a valid LaTeX macro name.")
    if name in _STRUCTURAL_MACROS:
        raise SlotConfigError(
            f"{role} '\\{name}' is a structural command. Tailoring may fill a document, "
            "never define one."
        )
    if name in _FORMATTING_MACROS:
        raise SlotConfigError(
            f"{role} '\\{name}' is inline formatting, not a content slot. Naming it would "
            "make every use of it in the document editable."
        )
    return name


@dataclass(frozen=True)
class BulletMacro:
    r"""A macro whose sole braced argument holds one bullet, e.g. `\resumeItem{…}`.

    Recognised both inside a list environment and as a bare run of consecutive
    calls, because plenty of templates emit bullets without wrapping them in
    anything.

    Single-argument by definition. A bullet is *reorderable* — the renderer
    rebuilds the whole run from `\name{` + text + `}` — and it cannot do that for
    a macro whose other arguments carry per-bullet content it would have to
    invent. Multi-argument macros belong in `field_macros`, where each occurrence
    keeps its own frozen arguments.
    """

    name: str

    def validated(self) -> "BulletMacro":
        return replace(self, name=_clean_macro_name(self.name, role="Bullet macro"))


@dataclass(frozen=True)
class FieldMacro:
    r"""A multi-argument macro with exactly one editable argument.

    `\cventry{Google}{Engineer}{2021--Now}{prose}` is a `FieldMacro` with
    `arity=4, content_arg=4`: the prose is a slot, and the employer, title and
    dates are frozen by construction rather than by instruction.
    """

    name: str
    arity: int
    content_arg: int
    label: str = "field"

    def validated(self) -> "FieldMacro":
        name = _clean_macro_name(self.name, role="Field macro")
        _check_args(name, self.arity, self.content_arg)
        label = self.label.strip()[:60] or "field"
        return replace(self, name=name, label=label)


@dataclass(frozen=True)
class ListPair:
    r"""A macro-delimited list, e.g. `\resumeItemListStart` … `\resumeItemListEnd`."""

    start: str
    end: str

    def validated(self) -> "ListPair":
        start = _clean_macro_name(self.start, role="List start macro")
        end = _clean_macro_name(self.end, role="List end macro")
        if start == end:
            raise SlotConfigError(f"List pair '\\{start}' opens and closes with the same macro.")
        return replace(self, start=start, end=end)


def _check_args(name: str, arity: int, content_arg: int) -> None:
    if not 1 <= arity <= MAX_ARITY:
        raise SlotConfigError(f"'\\{name}' declares {arity} arguments; expected 1 to {MAX_ARITY}.")
    if not 1 <= content_arg <= arity:
        raise SlotConfigError(
            f"'\\{name}' marks argument {content_arg} as content, but it only takes {arity}."
        )


#: The shapes the parser understood before configuration existed. Kept as the
#: default so an ordinary `\item` resume never pays for the flexibility.
DEFAULT_ENVIRONMENTS = ("itemize", "enumerate", "itemize*", "enumerate*")
DEFAULT_BULLET_MACROS = (BulletMacro("resumeItem"), BulletMacro("cvItem"))
DEFAULT_LIST_PAIRS = (
    ListPair("resumeItemListStart", "resumeItemListEnd"),
    ListPair("cvItemListStart", "cvItemListEnd"),
)
DEFAULT_SECTION_MACROS = ("section", "subsection")


@dataclass(frozen=True)
class SlotConfig:
    """How to find the editable content in one document.

    Immutable and hashable, so it can be cached alongside a parsed resume and
    compared cheaply. `source` and `confirmed` ride along because a client needs
    to know whether a boundary was inferred by a model or agreed by the author —
    the parser ignores both.
    """

    section_macros: tuple[str, ...] = DEFAULT_SECTION_MACROS
    environments: tuple[str, ...] = DEFAULT_ENVIRONMENTS
    bullet_macros: tuple[BulletMacro, ...] = DEFAULT_BULLET_MACROS
    list_pairs: tuple[ListPair, ...] = DEFAULT_LIST_PAIRS
    field_macros: tuple[FieldMacro, ...] = ()
    #: "builtin" (the defaults), "discovered" (proposed by a model), or "author".
    source: str = "builtin"
    #: Whether a human has agreed to this frozen/editable boundary.
    confirmed: bool = True

    @classmethod
    def default(cls, section_macros: list[str] | tuple[str, ...] | None = None) -> "SlotConfig":
        """The built-in shapes, with the operator's section macros."""
        macros = tuple(section_macros) if section_macros else DEFAULT_SECTION_MACROS
        return cls(section_macros=macros)

    @property
    def bullet_macro_names(self) -> tuple[str, ...]:
        return tuple(macro.name for macro in self.bullet_macros)

    def validate(self) -> "SlotConfig":
        """Return a normalised copy, or raise `SlotConfigError`.

        Every path into a config runs through here — the default, a model's
        proposal, and an author's hand edit — so a rule written once holds
        everywhere.
        """
        if len(self.bullet_macros) > MAX_BULLET_MACROS:
            raise SlotConfigError(
                f"{len(self.bullet_macros)} bullet macros declared; at most "
                f"{MAX_BULLET_MACROS} is a template that was understood."
            )
        if len(self.field_macros) > MAX_FIELD_MACROS:
            raise SlotConfigError(f"At most {MAX_FIELD_MACROS} field macros may be declared.")
        if len(self.list_pairs) > MAX_LIST_PAIRS:
            raise SlotConfigError(f"At most {MAX_LIST_PAIRS} list pairs may be declared.")

        # Section macros only *locate* headings — nothing is ever spliced into
        # one — so `\section` itself is legal here even though the structural
        # ban rejects it as a content slot. Format is all that needs checking.
        sections = (
            tuple(
                dict.fromkeys(
                    name.strip().lstrip("\\")
                    for name in self.section_macros
                    if _MACRO_NAME.match(name.strip().lstrip("\\"))
                )
            )
            or DEFAULT_SECTION_MACROS
        )

        environments = tuple(
            dict.fromkeys(
                env.strip()
                for env in self.environments
                if env.strip() and _MACRO_NAME.match(env.strip())
            )
        )
        bullets = tuple(macro.validated() for macro in self.bullet_macros)
        fields = tuple(macro.validated() for macro in self.field_macros)
        pairs = tuple(pair.validated() for pair in self.list_pairs)

        overlap = {m.name for m in bullets} & {m.name for m in fields}
        if overlap:
            raise SlotConfigError(
                "A macro cannot be both a bullet and a field: "
                + ", ".join("\\" + name for name in sorted(overlap))
            )
        if not (environments or bullets or fields or pairs):
            raise SlotConfigError("A slot config must declare at least one way to find content.")

        return replace(
            self,
            section_macros=sections,
            environments=environments,
            bullet_macros=bullets,
            list_pairs=pairs,
            field_macros=fields,
        )

    def to_dict(self) -> dict[str, Any]:
        """A JSON-safe form for the `resumes.latex_slot_config` column."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SlotConfig | None":
        """Rebuild and re-validate a stored config. `None` means "use the default"."""
        if not data:
            return None
        try:
            config = cls(
                section_macros=tuple(data.get("section_macros") or DEFAULT_SECTION_MACROS),
                environments=tuple(data.get("environments") or ()),
                bullet_macros=tuple(
                    BulletMacro(**macro) for macro in data.get("bullet_macros") or ()
                ),
                list_pairs=tuple(ListPair(**pair) for pair in data.get("list_pairs") or ()),
                field_macros=tuple(FieldMacro(**macro) for macro in data.get("field_macros") or ()),
                source=str(data.get("source") or "builtin"),
                confirmed=bool(data.get("confirmed", True)),
            )
        except TypeError as exc:  # an unexpected or missing key in the stored JSON
            raise SlotConfigError(f"Stored slot config is malformed: {exc}") from exc
        return config.validate()
