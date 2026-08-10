r"""Which LaTeX engine a given document needs, and which ones we will run.

A resume that loads `fontspec` cannot compile under pdfLaTeX, and one that calls
`\directlua` cannot compile under anything but LuaLaTeX. With a single global
engine those two masters cannot coexist, so the engine belongs to the document
rather than to the server.

**The allowlist is a security boundary, not a convenience.** The stored value
becomes `argv[0]` inside the Docker container `compiler.py` runs (see
`docker/latex/Dockerfile`), so this module only ever accepts a name from a
fixed set — never an arbitrary caller-supplied string, which one bad allowlist
check away would be argument injection into `docker run`.
"""

import re
from typing import Literal

from app.services.latex.parser import mask_comments

EngineName = Literal["latexmk", "pdflatex", "xelatex", "lualatex"]

#: The only names accepted from a request. Widening this means widening the
#: `ck_resumes_latex_engine` CHECK constraint in a migration too.
ENGINE_NAMES: frozenset[str] = frozenset(
    {"latexmk", "pdflatex", "xelatex", "lualatex"}
)

#: Engines built on a Unicode TeX — handle `fontspec` and friends natively.
UNICODE_ENGINES: frozenset[str] = frozenset({"xelatex", "lualatex"})

#: Engines built on XeTeX, which is the family that lacks pdfTeX's `\pdf...`
#: primitives. LuaTeX is Unicode *and* keeps them, so it is deliberately absent.
XETEX_ENGINES: frozenset[str] = frozenset({"xelatex"})

#: Packages that simply do not work under pdfLaTeX.
_UNICODE_ONLY_PACKAGES = {
    "fontspec", "unicode-math", "polyglossia", "xecjk", "xltxtra", "xunicode",
    "mathspec", "luatextra",
}
#: Markers that pin the document to LuaLaTeX specifically.
_LUA_ONLY_PACKAGES = {"luacode", "luatexbase", "lualatex-math", "luaotfload"}
_LUA_ONLY_COMMANDS = re.compile(r"\\directlua\b|\\luaexec\b")

#: Primitives pdfTeX provides and XeTeX does not. Under XeTeX these are not
#: degraded output, they are `Undefined control sequence` — the engine stops.
_PDFTEX_ONLY_PRIMITIVES = {
    "pdfgentounicode", "pdfglyphtounicode", "pdfximage", "pdfrefximage",
    "pdfpageattr", "pdfpagesattr", "pdfinfo", "pdfcompresslevel",
}
#: Files whose *contents* are pdfTeX-only, mapped to the primitive that proves
#: the engine can read them. `glyphtounicode.tex` ships with every distribution
#: and is found under XeTeX too — it just explodes on line 7. Widely copied
#: resume templates `\input` it for PDF text extraction, so it earns a name here.
_PDFTEX_ONLY_INPUTS = {"glyphtounicode": "pdfglyphtounicode"}

_USEPACKAGE = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
_PDF_PRIMITIVE = re.compile(r"\\(pdf[A-Za-z@]+)")
_INPUT = re.compile(r"\\input\s*(?:\{\s*([^}\s]+?)\s*\}|([A-Za-z0-9@_.-]+))")
#: The three idiomatic ways to ask "does this engine have that primitive?".
#: A marker inside such a test is not a requirement — it is the author already
#: handling both engines, and flagging it would punish the correct fix.
_GUARDED = re.compile(
    r"\\ifdefined\s*\\([A-Za-z@]+)"
    r"|\\ifx\s*\\([A-Za-z@]+)\s*\\undefined"
    r"|\\@ifundefined\s*\{\s*([A-Za-z@]+)\s*\}"
)


class UnknownEngineError(ValueError):
    """Raised when an engine name is not on the allowlist."""


def validate_engine(name: str) -> str:
    """Return `name` if it is an allowed engine, else raise."""
    if name not in ENGINE_NAMES:
        raise UnknownEngineError(
            f"'{name}' is not a supported LaTeX engine. Choose one of: "
            + ", ".join(sorted(ENGINE_NAMES))
        )
    return name


def required_packages(source: str) -> set[str]:
    """Every package the document loads, lowercased."""
    masked = mask_comments(source)
    packages: set[str] = set()
    for match in _USEPACKAGE.finditer(masked):
        packages.update(name.strip().lower() for name in match.group(1).split(",") if name.strip())
    return packages


def pdftex_only_markers(source: str) -> set[str]:
    r"""Every pdfTeX-only construct this document uses *unguarded*.

    Returned as the text the author would search for — `\pdfgentounicode`,
    `\input{glyphtounicode}` — because the only useful thing to say about one is
    where it is.

    A construct wrapped in `\ifdefined\pdfgentounicode ... \fi` does not count:
    the document already degrades gracefully, and that guard is exactly the fix
    this function's error message recommends.
    """
    masked = mask_comments(source)
    guarded = {name for group in _GUARDED.findall(masked) for name in group if name}

    markers = {
        f"\\{name}"
        for name in _PDF_PRIMITIVE.findall(masked)
        if name in _PDFTEX_ONLY_PRIMITIVES and name not in guarded
    }
    for braced, bare in _INPUT.findall(masked):
        stem = (braced or bare).removesuffix(".tex")
        proof = _PDFTEX_ONLY_INPUTS.get(stem)
        if proof is not None and proof not in guarded:
            markers.add(f"\\input{{{stem}}}")
    return markers


def detect_engine(source: str, default: str) -> str:
    """Pick the engine this document needs, falling back to `default`.

    Detection only fires on a *hard* requirement — a package or primitive that
    makes the default engine stop rather than merely produce different output.
    A document with no special requirements compiles fine under whatever the
    operator configured, and second-guessing that would override a deliberate
    choice for no reason.

    The three rules are checked in order of how load-bearing they are. Needing
    Unicode fonts outranks needing `\\pdfgentounicode`: a document with both is
    unsatisfiable, and losing the glyph map is a smaller loss than losing the
    typeface. `incompatibility` still reports what the chosen engine cannot do.
    """
    masked = mask_comments(source)
    packages = required_packages(source)

    if packages & _LUA_ONLY_PACKAGES or _LUA_ONLY_COMMANDS.search(masked):
        return "lualatex"
    if packages & _UNICODE_ONLY_PACKAGES:
        return default if default in UNICODE_ENGINES else "xelatex"
    if default in XETEX_ENGINES and pdftex_only_markers(source):
        return "pdflatex"
    return default


def incompatibility(source: str, engine: str) -> str | None:
    """Explain why `engine` cannot compile this document, or None if it can.

    Surfaced at upload time so a mismatch is a clear message rather than a wall
    of TeX log output on the first render.
    """
    packages = required_packages(source)
    lua_only = packages & _LUA_ONLY_PACKAGES
    if (lua_only or _LUA_ONLY_COMMANDS.search(mask_comments(source))) and engine != "lualatex":
        reason = ", ".join(sorted(lua_only)) or "\\directlua"
        return f"This document needs LuaLaTeX ({reason}), but '{engine}' is selected."

    unicode_only = packages & _UNICODE_ONLY_PACKAGES
    if unicode_only and engine not in UNICODE_ENGINES:
        return (
            f"This document loads {', '.join(sorted(unicode_only))}, which needs a "
            f"Unicode engine (xelatex or lualatex). '{engine}' is selected."
        )

    pdftex_only = pdftex_only_markers(source)
    if pdftex_only and engine in XETEX_ENGINES:
        first = sorted(pdftex_only)[0]
        return (
            f"This document uses {', '.join(sorted(pdftex_only))}, which only pdfTeX "
            f"provides. '{engine}' is XeTeX-based and stops at the first one with "
            f"'Undefined control sequence'. Either switch this resume to pdflatex, or — "
            f"since these only add a PDF glyph map — make them conditional: "
            f"\\ifdefined\\pdfgentounicode {first} \\fi"
        )
    return None
