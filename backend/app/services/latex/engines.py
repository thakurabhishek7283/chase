r"""Which LaTeX engine a given document needs, and which ones we will run.

A resume that loads `fontspec` cannot compile under pdfLaTeX, and one that calls
`\directlua` cannot compile under anything but LuaLaTeX. With a single global
engine those two masters cannot coexist, so the engine belongs to the document
rather than to the server.

**The allowlist is a security boundary, not a convenience.** The stored value
becomes `argv[0]` of a subprocess, so this module only ever accepts a name from
a fixed set and resolves it through `PATH`. A caller-supplied *path* is never
executed — pointing at a binary somewhere unusual stays a server-side setting
(`LATEX_ENGINE_PATH`), which is operator configuration rather than user data.
"""

import re
from typing import Literal

from app.services.latex.parser import mask_comments

EngineName = Literal["tectonic", "latexmk", "pdflatex", "xelatex", "lualatex"]

#: The only names accepted from a request. Widening this means widening the
#: `ck_resumes_latex_engine` CHECK constraint in a migration too.
ENGINE_NAMES: frozenset[str] = frozenset(
    {"tectonic", "latexmk", "pdflatex", "xelatex", "lualatex"}
)

#: Engines built on a Unicode TeX. Tectonic qualifies: it is XeTeX-based, so it
#: handles `fontspec` and friends natively.
UNICODE_ENGINES: frozenset[str] = frozenset({"tectonic", "xelatex", "lualatex"})

#: Packages that simply do not work under pdfLaTeX.
_UNICODE_ONLY_PACKAGES = {
    "fontspec", "unicode-math", "polyglossia", "xecjk", "xltxtra", "xunicode",
    "mathspec", "luatextra",
}
#: Markers that pin the document to LuaLaTeX specifically.
_LUA_ONLY_PACKAGES = {"luacode", "luatexbase", "lualatex-math", "luaotfload"}
_LUA_ONLY_COMMANDS = re.compile(r"\\directlua\b|\\luaexec\b")

_USEPACKAGE = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")


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


def detect_engine(source: str, default: str) -> str:
    """Pick the engine this document needs, falling back to `default`.

    Detection only *upgrades* — it never downgrades a Unicode engine to
    pdfLaTeX. A document with no special requirements compiles fine under
    whatever the operator configured, and second-guessing that would override a
    deliberate choice for no reason.
    """
    masked = mask_comments(source)
    packages = required_packages(source)

    if packages & _LUA_ONLY_PACKAGES or _LUA_ONLY_COMMANDS.search(masked):
        return "lualatex"
    if packages & _UNICODE_ONLY_PACKAGES and default not in UNICODE_ENGINES:
        return "xelatex"
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
            f"Unicode engine (tectonic, xelatex, or lualatex). '{engine}' is selected."
        )
    return None
