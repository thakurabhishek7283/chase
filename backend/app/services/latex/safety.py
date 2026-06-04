r"""Validate the LaTeX fragments the tailoring model produces.

Bullets are handed to the model *as LaTeX* rather than as plain text, so a
rewrite can keep the `\textbf{}` and `\href{}` the author already had. The cost
of that choice is that model output is now injected into a document we compile,
so it has to be checked before it goes anywhere near the engine.

Two rules, in order of importance:

- **Allowlist, never blocklist.** Only the inline formatting commands a resume
  bullet legitimately needs are permitted. Anything unrecognised is rejected,
  so a command nobody thought of is refused by default rather than by omission.
- **Balanced braces.** An unbalanced fragment does not fail locally — it
  swallows the rest of the document and corrupts the layout the whole feature
  exists to preserve.

`escape_text` is the fallback: when a fragment fails validation the caller can
still use the model's words, just stripped of its markup.
"""

import re

#: Inline commands a resume bullet has a real reason to use.
ALLOWED_COMMANDS = frozenset(
    {
        "textbf", "textit", "textsc", "texttt", "textrm", "textsf", "emph",
        "underline", "uline", "textsuperscript", "textsubscript",
        "href", "url", "texorpdfstring",
        "LaTeX", "TeX", "ldots", "dots", "textbar", "textbackslash",
        "times", "textendash", "textemdash", "textquotesingle", "degree",
        "small", "footnotesize", "normalsize", "bfseries", "itshape",
    }
)

#: Constructs that read files, shell out, or redefine the document. None of
#: these belong in a bullet; all of them are how a LaTeX injection would work.
_FORBIDDEN = re.compile(
    r"\\(write18|immediate|input|include|openin|openout|read|catcode|def|let|"
    r"newcommand|renewcommand|expandafter|csname|documentclass|usepackage|"
    r"begin|end|section|subsection|item|newpage|clearpage|special|directlua|"
    r"write|loop|repeat)\b",
    re.IGNORECASE,
)

_COMMAND = re.compile(r"\\([A-Za-z@]+)")
_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


class UnsafeLatexError(ValueError):
    """Raised when a generated fragment is unsafe or malformed."""


def escape_text(text: str) -> str:
    """Escape plain text so it survives LaTeX as literal characters."""
    return "".join(_ESCAPES.get(char, char) for char in text)


def braces_balanced(fragment: str) -> bool:
    depth, index, length = 0, 0, len(fragment)
    while index < length:
        char = fragment[index]
        if char == "\\":
            index += 2  # `\{` and `\}` are literal glyphs, not grouping.
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
        index += 1
    return depth == 0


def validate_fragment(fragment: str) -> str:
    """Return `fragment` unchanged if it is safe to splice, else raise."""
    if not fragment.strip():
        raise UnsafeLatexError("Fragment is empty.")
    if "%" in re.sub(r"\\%", "", fragment):
        raise UnsafeLatexError(
            "Unescaped '%' would comment out the rest of the line; write '\\%'."
        )
    if _FORBIDDEN.search(fragment):
        raise UnsafeLatexError("Fragment uses a structural or file-access command.")
    if not braces_balanced(fragment):
        raise UnsafeLatexError("Fragment has unbalanced braces.")
    unknown = {name for name in _COMMAND.findall(fragment) if name not in ALLOWED_COMMANDS}
    if unknown:
        raise UnsafeLatexError(
            "Fragment uses commands that are not allowed in bullet text: "
            + ", ".join("\\" + name for name in sorted(unknown))
        )
    return fragment.strip()


def coerce_fragment(fragment: str) -> str:
    """Validate if possible; otherwise fall back to the words without markup.

    Losing a `\\textbf` is a cosmetic regression inside one bullet. Refusing to
    render at all, or splicing something unbalanced, is not — so degrade rather
    than fail the whole tailoring run over a single bad fragment.
    """
    try:
        return validate_fragment(fragment)
    except UnsafeLatexError:
        stripped = _COMMAND.sub(" ", fragment).replace("{", " ").replace("}", " ")
        collapsed = re.sub(r"\s+", " ", stripped).strip()
        if not collapsed:
            raise
        return escape_text(collapsed)
