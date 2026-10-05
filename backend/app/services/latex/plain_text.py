r"""Project a LaTeX resume down to readable plain text.

The scoring half of the review call reasons about prose, not markup. Rather
than teaching it LaTeX, a resume is flattened once here and shown to the model
alongside its slot outline — one view to judge, one view to edit.

The projection is deliberately lossy and one-way. It approximates what an ATS
extracts from the compiled PDF — text, headings, bullets — which is exactly the
right input for scoring. It is never parsed back into LaTeX.
"""

import re

from app.services.latex.model import LatexResume, MarkedRegion
from app.services.latex.parser import heading_text, mask_comments

#: `\\` is a line break, not a command; it has to be turned into one before the
#: command stripper eats it.
_LINEBREAK = re.compile(r"\\\\\*?(\s*\[[^\]]*\])?")
#: `\href{url}{label}` keeps the label; the URL is noise to a keyword scan.
_HREF = re.compile(r"\\href\s*\{[^}]*\}\s*\{")
_URL = re.compile(r"\\url\s*\{([^}]*)\}")
#: Commands whose braced argument is content to keep (`\textbf{Rust}` -> `Rust`).
_UNWRAP = re.compile(
    r"\\(?:textbf|textit|textsc|texttt|textrm|textsf|emph|underline|uline|small|"
    r"large|Large|LARGE|huge|Huge|footnotesize|normalsize|mbox|text|item)\s*\{"
)
#: Commands whose braced argument is structural and must go with them —
#: otherwise `\end{itemize}` leaves the word "itemize" in the output and
#: `\section{Skills}` duplicates a heading already emitted separately.
#: Arguments are consumed with `[ \t]*` rather than `\s*` so the match cannot
#: cross a newline: `\section{Experience}` followed by `\textbf{Senior Engineer}`
#: on the next line must not swallow the job title along with the heading.
#: Braced and bracketed arguments interleave because `\begin{itemize}[leftmargin]`
#: puts them in that order.
_DROP_WITH_ARG = re.compile(
    r"\\(?:begin|end|section|subsection|subsubsection|cvsection|resumeSection|"
    r"heading|documentclass|usepackage|newcommand|renewcommand|label|vspace|"
    r"hspace|setlength|includegraphics)\*?"
    r"(?:[ \t]*(?:\{[^{}]*\}|\[[^\]]*\]))*"
)
#: Layout commands that carry no text at all.
_LAYOUT = re.compile(
    r"\\(?:hfill|newline|linebreak|noindent|centering|smallskip|medskip|bigskip|par|"
    r"newpage|clearpage|hrule|rule|quad|qquad)\b\*?"
)
_REMAINING_COMMAND = re.compile(r"\\[A-Za-z@]+\*?(\s*\[[^\]]*\])?")
#: Bare `$` is a math-mode delimiter; escaped `\$` is a dollar sign and is
#: handled by the unescape table below, so the lookbehind matters.
_MATH_DELIMITER = re.compile(r"(?<!\\)\$")
_UNESCAPE = [
    (r"\textbackslash{}", "\\"),
    (r"\&", "&"),
    (r"\%", "%"),
    (r"\$", "$"),
    (r"\#", "#"),
    (r"\_", "_"),
    (r"\{", "{"),
    (r"\}", "}"),
    (r"\ldots", "..."),
    (r"\dots", "..."),
    ("---", "-"),
    ("--", "-"),
    ("~", " "),
]


def _flatten(fragment: str) -> str:
    """Strip LaTeX markup from a fragment, keeping the words."""
    text = mask_comments(fragment)
    text = _LINEBREAK.sub("\n", text)
    text = _HREF.sub("{", text)
    text = _URL.sub(r"\1", text)
    # Unwrapping is iterative because formatting commands nest.
    for _ in range(6):
        replaced = _UNWRAP.sub("{", text)
        if replaced == text:
            break
        text = replaced
    text = _DROP_WITH_ARG.sub(" ", text)
    text = _LAYOUT.sub(" ", text)
    text = _MATH_DELIMITER.sub("", text)
    text = _REMAINING_COMMAND.sub(" ", text)
    for source, target in _UNESCAPE:
        text = text.replace(source, target)
    # Adjacent arguments are separate facts, so they need a separator before the
    # braces vanish: `\cventry{Acme Corp}{Engineer}` must read "Acme Corp
    # Engineer", not "Acme CorpEngineer" — an ATS matches neither the run-on
    # word nor the two keywords hidden inside it.
    text = text.replace("}{", "} {")
    # Braces themselves collapse to nothing rather than a space: `\textbf{Languages}:`
    # must read "Languages:", not "Languages :".
    text = text.replace("{", "").replace("}", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" +([,.;:)])", r"\1", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip(" .,\n")


def flatten_latex(source: str) -> str:
    """Strip markup from raw `.tex` that could not be parsed into sections.

    A last resort for the scoring path: without section structure the output has
    no headings and no bullet markers, but it is words rather than a preamble
    full of `\\newcommand` bodies, which is the difference between a rough score
    and a meaningless one.
    """
    return re.sub(r"\n{3,}", "\n\n", _flatten(source)).strip()


def to_markdown(resume: LatexResume) -> str:
    """Render the parsed resume as the Markdown the rest of the app consumes."""
    lines: list[str] = []
    for section in resume.sections:

        def emit(fragment: str, bullet: bool = False) -> None:
            for part in _flatten(fragment).splitlines():
                if part.strip():
                    lines.append(f"- {part.strip()}" if bullet else part.strip())

        if section.heading and section.heading != "Header":
            lines.append(f"## {heading_text(section.heading)}")

        # Walk the section in document order so the projection reads the way the
        # compiled PDF does. Frozen prose — employers, titles, dates — matters to
        # an ATS as much as the bullets, so it is projected alongside them.
        units = [(group.span, group) for group in section.groups]
        units += [(region.span, region) for region in section.regions]
        cursor = section.span.start
        for span, unit in sorted(units, key=lambda item: item[0].start):
            emit(resume.source[cursor : span.start])
            if isinstance(unit, MarkedRegion):
                emit(unit.latex)
            else:
                for bullet in unit.bullets:
                    emit(bullet.latex, bullet=True)
            cursor = span.end
        emit(resume.source[cursor : section.span.end])
        lines.append("")

    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
