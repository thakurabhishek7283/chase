r"""Split a master `.tex` into a frozen template half and an editable half.

Two extraction strategies, mirroring the dual-library philosophy of
`services/pdf_parser` — cover the common case automatically, and give the author
an escape hatch for everything else:

1. **Bullets, found automatically.** `\item` bodies inside `itemize`/`enumerate`,
   and `\resumeItem{...}` bodies inside `\resumeItemListStart`/`End` (the shape
   used by the widely-copied "Jake's resume" template).

2. **Marked regions, opted into explicitly.** Anything wrapped in
   `% jarvis:begin <label>` … `% jarvis:end`.

Everything else is frozen. That boundary is a deliberate content decision, not
just a parsing convenience: bullets and skill lines are what *should* change
between a Python role and a Rust one. Employers, job titles, dates, and degrees
are facts, and a tailoring pass must never be in a position to rewrite them.
"""

import re

from app.services.latex.model import (
    Bullet,
    ItemGroup,
    LatexResume,
    MarkedRegion,
    Section,
    Span,
)


class LatexParseError(ValueError):
    """Raised when a `.tex` file cannot be understood well enough to tailor."""


#: List environments whose `\item`s are editable.
_ITEM_ENVIRONMENTS = {"itemize", "enumerate", "itemize*", "enumerate*"}

#: Macro-delimited list "environments" used by popular resume templates.
_MACRO_LIST_PAIRS = {
    r"\resumeItemListStart": r"\resumeItemListEnd",
    r"\cvItemListStart": r"\cvItemListEnd",
}

#: Item macros whose sole braced argument is the bullet text.
_BRACE_ITEM_MACROS = ("resumeItem", "cvItem")

_ENV_TOKEN = re.compile(r"\\(begin|end)\s*\{([A-Za-z@*]+)\}")
_ITEM_TOKEN = re.compile(r"\\item\b(\s*\[[^\]]*\])?")
# No \A anchor: `.match(s, pos)` already anchors at `pos`, whereas \A would
# re-anchor to the start of the whole document and never match.
_OPTIONAL_ARG = re.compile(r"[ \t]*\[[^\]]*\]")
_MARKER_BEGIN = re.compile(r"^[ \t]*%+[ \t]*jarvis:begin[ \t]+(\S.*?)[ \t]*$", re.MULTILINE)
_MARKER_END = re.compile(r"^[ \t]*%+[ \t]*jarvis:end[ \t]*$", re.MULTILINE)
_COMMAND = re.compile(r"\\[A-Za-z@]+\*?")


def mask_comments(source: str) -> str:
    """Blank out comments while preserving every byte offset.

    Structural scanning runs against this masked copy so a `%`-commented
    `\\begin{itemize}` cannot desynchronise the environment stack, while spans
    computed from it still index correctly into the untouched original.
    """
    out = list(source)
    index, length = 0, len(source)
    while index < length:
        char = source[index]
        if char == "\\":
            index += 2  # An escaped character, `\%` included, is never a comment.
            continue
        if char == "%":
            line_end = source.find("\n", index)
            line_end = length if line_end == -1 else line_end
            for position in range(index, line_end):
                out[position] = " "
            index = line_end + 1
            continue
        index += 1
    return "".join(out)


def match_brace(masked: str, open_index: int) -> int:
    """Return the index of the `}` closing the `{` at `open_index`."""
    if open_index >= len(masked) or masked[open_index] != "{":
        raise LatexParseError(f"Expected '{{' at offset {open_index}.")
    depth, index, length = 0, open_index, len(masked)
    while index < length:
        char = masked[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise LatexParseError(f"Unbalanced '{{' starting at offset {open_index}.")


def _strip_span(source: str, start: int, end: int) -> Span:
    """Trim surrounding whitespace so a splice does not swallow line breaks."""
    while start < end and source[start] in " \t\r\n":
        start += 1
    while end > start and source[end - 1] in " \t\r\n":
        end -= 1
    return Span(start, end)


def _indent_before(source: str, index: int) -> str:
    line_start = source.rfind("\n", 0, index) + 1
    prefix = source[line_start:index]
    return prefix if prefix.strip() == "" else ""


def heading_text(raw: str) -> str:
    """Reduce a heading's LaTeX to the words a human (and the LLM) reads."""
    text = _COMMAND.sub(" ", raw).replace("{", " ").replace("}", " ")
    return re.sub(r"\s+", " ", text).strip()


def _scan_environments(masked: str, offset: int = 0) -> list[tuple[str, int, int, int, int]]:
    """Stack-match `\\begin{X}`/`\\end{X}` pairs.

    Returns `(name, begin_start, body_start, body_end, end_stop)` tuples. An
    unmatched `\\end` is skipped rather than fatal — resume templates sometimes
    hide one inside a macro definition we are not expanding.
    """
    stack: list[tuple[str, int, int]] = []
    found: list[tuple[str, int, int, int, int]] = []
    for match in _ENV_TOKEN.finditer(masked, offset):
        kind, name = match.group(1), match.group(2)
        if kind == "begin":
            body_start = match.end()
            optional = _OPTIONAL_ARG.match(masked, body_start)
            if optional:
                body_start = optional.end()
            stack.append((name, match.start(), body_start))
            continue
        for depth in range(len(stack) - 1, -1, -1):
            if stack[depth][0] == name:
                open_name, begin_start, body_start = stack[depth]
                del stack[depth:]
                found.append((open_name, begin_start, body_start, match.start(), match.end()))
                break
    return found


def _scan_macro_lists(masked: str) -> list[tuple[str, int, int, int, int]]:
    """Match the macro-delimited list pairs, same shape as `_scan_environments`."""
    found: list[tuple[str, int, int, int, int]] = []
    for start_macro, end_macro in _MACRO_LIST_PAIRS.items():
        opens = [m.end() for m in re.finditer(re.escape(start_macro) + r"(?![A-Za-z])", masked)]
        closes = [m.start() for m in re.finditer(re.escape(end_macro) + r"(?![A-Za-z])", masked)]
        # Pair them innermost-first so nesting cannot cross-link two lists.
        for close in closes:
            candidates = [o for o in opens if o < close]
            if not candidates:
                continue
            open_end = max(candidates)
            opens.remove(open_end)
            name = start_macro.lstrip("\\")
            found.append((name, open_end - len(start_macro), open_end, close, close + len(end_macro)))
    return found


def _bullets_in(source: str, masked: str, body: Span, group_id: str) -> tuple[list[Bullet], str, str]:
    """Extract item bodies from a list body, returning them with their idiom."""
    for macro in _BRACE_ITEM_MACROS:
        pattern = re.compile(r"\\" + macro + r"\s*(?=\{)")
        starts = [m.end() for m in pattern.finditer(masked, body.start, body.end)]
        if starts:
            bullets: list[Bullet] = []
            for number, brace_open in enumerate(starts, start=1):
                brace_close = match_brace(masked, brace_open)
                span = _strip_span(source, brace_open + 1, brace_close)
                bullets.append(
                    Bullet(id=f"{group_id}-b{number}", span=span, latex=span.text(source))
                )
            return bullets, f"\\{macro}{{", "}"

    matches = list(_ITEM_TOKEN.finditer(masked, body.start, body.end))
    bullets = []
    for number, match in enumerate(matches, start=1):
        stop = matches[number].start() if number < len(matches) else body.end
        span = _strip_span(source, match.end(), stop)
        bullets.append(Bullet(id=f"{group_id}-b{number}", span=span, latex=span.text(source)))
    return bullets, "\\item ", ""


def _find_marked_regions(source: str) -> list[MarkedRegion]:
    """Pair `% jarvis:begin <label>` with the next `% jarvis:end`."""
    ends = [m for m in _MARKER_END.finditer(source)]
    regions: list[MarkedRegion] = []
    for number, begin in enumerate(_MARKER_BEGIN.finditer(source), start=1):
        end = next((e for e in ends if e.start() >= begin.end()), None)
        if end is None:
            raise LatexParseError(
                f"'% jarvis:begin {begin.group(1)}' has no matching '% jarvis:end'."
            )
        span = _strip_span(source, begin.end(), end.start())
        regions.append(
            MarkedRegion(
                id=f"r{number}",
                label=begin.group(1).strip(),
                span=span,
                latex=span.text(source),
            )
        )
    return regions


def _find_sections(source: str, masked: str, body: Span, macros: list[str]) -> list[Section]:
    """Slice the body at section macros; content before the first is the header."""
    pattern = re.compile(r"\\(?:" + "|".join(re.escape(m) for m in macros) + r")\*?\s*(?=\{)")
    starts: list[tuple[int, str]] = []
    for match in pattern.finditer(masked, body.start, body.end):
        brace_close = match_brace(masked, match.end())
        starts.append((match.start(), heading_text(source[match.end() + 1 : brace_close])))

    sections: list[Section] = []
    if not starts or starts[0][0] > body.start:
        first_end = starts[0][0] if starts else body.end
        sections.append(
            Section(id="s0", heading="Header", span=Span(body.start, first_end))
        )
    for number, (start, heading) in enumerate(starts, start=1):
        stop = starts[number][0] if number < len(starts) else body.end
        sections.append(
            Section(id=f"s{number}", heading=heading or f"Section {number}", span=Span(start, stop))
        )
    return sections


def parse(source: str, section_macros: list[str] | None = None) -> LatexResume:
    """Parse a master `.tex` into its frozen template and editable content."""
    if not source.strip():
        raise LatexParseError("The uploaded .tex file is empty.")

    masked = mask_comments(source)
    begin_doc = re.search(r"\\begin\s*\{document\}", masked)
    if begin_doc is None:
        raise LatexParseError(
            "No \\begin{document} found. Upload a complete LaTeX document, not a fragment."
        )
    end_doc = re.search(r"\\end\s*\{document\}", masked)
    body = Span(begin_doc.end(), end_doc.start() if end_doc else len(source))
    if body.end <= body.start:
        raise LatexParseError("The document body is empty.")

    macros = section_macros or ["section", "subsection"]
    sections = _find_sections(source, masked, body, macros)
    regions = _find_marked_regions(source)

    candidates = [
        (name, begin_start, body_start, body_end, end_stop)
        for (name, begin_start, body_start, body_end, end_stop) in (
            _scan_environments(masked, body.start) + _scan_macro_lists(masked)
        )
        if name in _ITEM_ENVIRONMENTS or name in {m.lstrip("\\") for m in _MACRO_LIST_PAIRS}
        if body.start <= begin_start and end_stop <= body.end
    ]
    candidates.sort(key=lambda item: item[1])

    groups: list[ItemGroup] = []
    number = 0
    for name, _begin_start, body_start, body_end, _end_stop in candidates:
        # A list wrapping another list is scaffolding, not a bullet list; only
        # the innermost one holds editable text.
        if any(body_start <= other[2] and other[3] <= body_end for other in candidates
               if (other[2], other[3]) != (body_start, body_end)):
            continue
        group_body = Span(body_start, body_end)
        number += 1
        group_id = f"g{number}"
        bullets, prefix, suffix = _bullets_in(source, masked, group_body, group_id)
        if not bullets:
            number -= 1
            continue
        groups.append(
            ItemGroup(
                id=group_id,
                kind=name,
                span=group_body,
                indent=_indent_before(source, bullets[0].span.start) or "    ",
                prefix=prefix,
                suffix=suffix,
                bullets=bullets,
            )
        )

    # An explicit marker wins over an inferred bullet list: the author reached
    # for the escape hatch precisely to take control of that span.
    groups = [g for g in groups if not any(g.span.overlaps(r.span) for r in regions)]

    for section in sections:
        section.groups = [g for g in groups if section.span.start <= g.span.start < section.span.end]
        section.regions = [
            r for r in regions if section.span.start <= r.span.start < section.span.end
        ]

    resume = LatexResume(
        source=source, preamble=Span(0, begin_doc.start()), body=body, sections=sections
    )
    if not resume.groups and not resume.regions:
        raise LatexParseError(
            "No editable content found. Tailoring needs bullet lists "
            "(\\begin{itemize} … \\item) or regions marked with "
            "'% jarvis:begin <label>' … '% jarvis:end'."
        )
    return resume
