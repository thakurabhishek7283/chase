r"""Split a master `.tex` into a frozen template half and an editable half.

Four extraction strategies, on one principle — cover the common case
automatically, and give the author an escape hatch for everything else:

1. **Bullets in lists, found automatically.** `\item` bodies inside
   `itemize`/`enumerate`, and `\resumeItem{...}` bodies inside
   `\resumeItemListStart`/`End` (the shape used by the widely-copied "Jake's
   resume" template).

2. **Standalone bullet macros.** A run of consecutive `\achievement{...}` calls
   with nothing but whitespace between them is a bullet list whether or not the
   template wrapped it in an environment.

3. **Field arguments.** One named argument of a multi-argument macro —
   `\cventry{employer}{title}{dates}{prose}` yields a slot over the prose alone.

4. **Marked regions, opted into explicitly.** Anything wrapped in
   `% jarvis:begin <label>` … `% jarvis:end`.

Which macros count for (2) and (3) comes from the `SlotConfig` the caller
supplies — that is what lets an unseen template be parsed without code changes.
The *mechanism* stays entirely deterministic either way: spans are computed by
brace matching, never guessed.

Everything else is frozen. That boundary is a deliberate content decision, not
just a parsing convenience: bullets and skill lines are what *should* change
between a Python role and a Rust one. Employers, job titles, dates, and degrees
are facts, and a tailoring pass must never be in a position to rewrite them.
"""

import re

from app.services.latex.config import SlotConfig
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


def _scan_macro_lists(masked: str, config: SlotConfig) -> list[tuple[str, int, int, int, int]]:
    """Match the macro-delimited list pairs, same shape as `_scan_environments`."""
    found: list[tuple[str, int, int, int, int]] = []
    for pair in config.list_pairs:
        start_macro, end_macro = "\\" + pair.start, "\\" + pair.end
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


def _bullets_in(
    source: str, masked: str, body: Span, group_id: str, config: SlotConfig
) -> tuple[list[Bullet], str, str]:
    """Extract item bodies from a list body, returning them with their idiom."""
    for macro in config.bullet_macro_names:
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
    """Pair `% jarvis:begin <label>` with the next `% jarvis:end`.

    Ids are placeholders: regions are renumbered in document order once the
    config-derived field slots have been merged in.
    """
    ends = [m for m in _MARKER_END.finditer(source)]
    regions: list[MarkedRegion] = []
    for begin in _MARKER_BEGIN.finditer(source):
        end = next((e for e in ends if e.start() >= begin.end()), None)
        if end is None:
            raise LatexParseError(
                f"'% jarvis:begin {begin.group(1)}' has no matching '% jarvis:end'."
            )
        span = _strip_span(source, begin.end(), end.start())
        regions.append(
            MarkedRegion(
                id="", label=begin.group(1).strip(), span=span, latex=span.text(source)
            )
        )
    return regions


def _braced_args(masked: str, index: int, count: int) -> list[tuple[int, int]] | None:
    """Locate `count` consecutive braced arguments starting at `index`.

    Returns `(open, close)` index pairs, or None when the macro is not followed
    by that many arguments — a call that does not match its declared arity is
    skipped rather than fatal, because one odd usage should not cost the author
    the rest of the document.
    """
    spans: list[tuple[int, int]] = []
    cursor, length = index, len(masked)
    for _ in range(count):
        while cursor < length and masked[cursor] in " \t\r\n":
            cursor += 1
        optional = _OPTIONAL_ARG.match(masked, cursor)
        if optional:
            cursor = optional.end()
            while cursor < length and masked[cursor] in " \t\r\n":
                cursor += 1
        if cursor >= length or masked[cursor] != "{":
            return None
        try:
            close = match_brace(masked, cursor)
        except LatexParseError:
            return None
        spans.append((cursor, close))
        cursor = close + 1
    return spans


def _overlaps_any(span: Span, taken: list[Span]) -> bool:
    return any(span.overlaps(other) for other in taken)


def _standalone_runs(
    source: str, masked: str, body: Span, config: SlotConfig, taken: list[Span], first_id: int
) -> list[ItemGroup]:
    r"""Find runs of consecutive bullet-macro calls that no list environment claimed.

    `\achievement{a}\achievement{b}` with only whitespace between them is a
    bullet list even though nothing wrapped it in one. Requiring whitespace-only
    separation is what makes replacing the whole run safe: anything else between
    two calls is template, and template is not ours to overwrite.
    """
    groups: list[ItemGroup] = []
    number = first_id
    for name in config.bullet_macro_names:
        pattern = re.compile(r"\\" + name + r"(?![A-Za-z@])")
        #: (whole call including the macro name, the argument's inner text)
        calls: list[tuple[Span, Span]] = []
        for match in pattern.finditer(masked, body.start, body.end):
            args = _braced_args(masked, match.end(), 1)
            if args is None:
                continue
            open_index, close_index = args[0]
            if close_index >= body.end:
                continue
            call = Span(match.start(), close_index + 1)
            if _overlaps_any(call, taken):
                continue
            calls.append((call, _strip_span(source, open_index + 1, close_index)))

        for run in _contiguous_runs(source, calls):
            number += 1
            groups.append(_run_group(source, name, run, f"g{number}"))
    return groups


def _contiguous_runs(
    source: str, calls: list[tuple[Span, Span]]
) -> list[list[tuple[Span, Span]]]:
    """Split calls into runs separated by nothing but whitespace."""
    runs: list[list[tuple[Span, Span]]] = []
    current: list[tuple[Span, Span]] = []
    for call, inner in calls:
        if current and source[current[-1][0].end : call.start].strip():
            runs.append(current)
            current = []
        current.append((call, inner))
    if current:
        runs.append(current)
    return runs


def _run_group(
    source: str, name: str, run: list[tuple[Span, Span]], group_id: str
) -> ItemGroup:
    """Build a standalone group whose span covers the macro calls themselves."""
    bullets = [
        Bullet(id=f"{group_id}-b{number}", span=inner, latex=inner.text(source))
        for number, (_call, inner) in enumerate(run, start=1)
    ]
    return ItemGroup(
        id=group_id,
        kind=name,
        span=Span(run[0][0].start, run[-1][0].end),
        indent=_indent_before(source, run[0][0].start) or "    ",
        prefix=f"\\{name}{{",
        suffix="}",
        bullets=bullets,
        standalone=True,
    )


def _field_regions(
    source: str, masked: str, body: Span, config: SlotConfig, taken: list[Span]
) -> list[MarkedRegion]:
    r"""Carve one editable argument out of each multi-argument macro call.

    `\cventry{Google}{Engineer}{2021--Now}{prose}` yields a slot over the prose
    and nothing else, so the employer and the dates are not merely asked to stay
    put — they are outside every editable span in the document.
    """
    regions: list[MarkedRegion] = []
    for macro in config.field_macros:
        pattern = re.compile(r"\\" + macro.name + r"(?![A-Za-z@])")
        for match in pattern.finditer(masked, body.start, body.end):
            args = _braced_args(masked, match.end(), macro.arity)
            if args is None:
                continue
            open_index, close_index = args[macro.content_arg - 1]
            if close_index >= body.end:
                continue
            span = _strip_span(source, open_index + 1, close_index)
            if span.end <= span.start or _overlaps_any(span, taken):
                continue
            regions.append(
                MarkedRegion(
                    id="", label=macro.label, span=span, latex=span.text(source), origin="field"
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


def parse(source: str, config: SlotConfig | None = None) -> LatexResume:
    """Parse a master `.tex` into its frozen template and editable content.

    `config` decides which macros carry content in *this* document; omitting it
    uses the built-in shapes, which is what an ordinary `\\item` resume needs.
    """
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

    active = (config or SlotConfig.default()).validate()
    sections = _find_sections(source, masked, body, list(active.section_macros))
    regions = _find_marked_regions(source)

    list_names = {pair.start for pair in active.list_pairs}
    candidates = [
        (name, begin_start, body_start, body_end, end_stop)
        for (name, begin_start, body_start, body_end, end_stop) in (
            _scan_environments(masked, body.start) + _scan_macro_lists(masked, active)
        )
        if name in active.environments or name in list_names
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
        bullets, prefix, suffix = _bullets_in(source, masked, group_body, group_id, active)
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

    # Configured macros fill in where the list scan found nothing. Both passes
    # are handed every span already claimed, so a bullet cannot be discovered
    # twice and a field cannot be carved out of a group's text.
    taken = [g.span for g in groups] + [r.span for r in regions]
    groups += _standalone_runs(source, masked, body, active, taken, len(groups))
    taken = [g.span for g in groups] + [r.span for r in regions]
    regions += _field_regions(source, masked, body, active, taken)

    # Renumber in document order. Ids are what the model and the client address
    # slots by, so "g2 is the second list in the resume" has to stay true no
    # matter which pass discovered it.
    groups.sort(key=lambda group: group.span.start)
    regions.sort(key=lambda region: region.span.start)
    for number, group in enumerate(groups, start=1):
        group.id = f"g{number}"
        for index, bullet in enumerate(group.bullets, start=1):
            bullet.id = f"{group.id}-b{index}"
    for number, region in enumerate(regions, start=1):
        region.id = f"r{number}"

    for section in sections:
        section.groups = [g for g in groups if section.span.start <= g.span.start < section.span.end]
        section.regions = [
            r for r in regions if section.span.start <= r.span.start < section.span.end
        ]

    resume = LatexResume(
        source=source,
        preamble=Span(0, begin_doc.start()),
        body=body,
        sections=sections,
        config=active,
    )
    if not resume.groups and not resume.regions:
        raise LatexParseError(
            "No editable content found. Tailoring needs bullet lists "
            "(\\begin{itemize} … \\item) or regions marked with "
            "'% jarvis:begin <label>' … '% jarvis:end'."
        )
    return resume
