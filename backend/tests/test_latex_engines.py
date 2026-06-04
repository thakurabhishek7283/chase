import pytest

from app.services.latex.engines import (
    ENGINE_NAMES,
    UnknownEngineError,
    detect_engine,
    incompatibility,
    required_packages,
    validate_engine,
)

PLAIN = r"""\documentclass{article}
\usepackage[T1]{fontenc}
\usepackage{enumitem}
\begin{document}\begin{itemize}\item hi\end{itemize}\end{document}
"""

FONTSPEC = r"""\documentclass{article}
\usepackage{fontspec}
\setmainfont{EB Garamond}
\begin{document}\begin{itemize}\item hi\end{itemize}\end{document}
"""

LUA = r"""\documentclass{article}
\usepackage{luacode}
\begin{document}\begin{itemize}\item hi\end{itemize}\end{document}
"""

DIRECTLUA = r"""\documentclass{article}
\begin{document}\directlua{tex.print("hi")}\begin{itemize}\item hi\end{itemize}\end{document}
"""


def test_required_packages_handles_options_and_multiples() -> None:
    packages = required_packages(
        r"\usepackage[margin=1in]{geometry}" "\n" r"\usepackage{amsmath, amssymb}"
    )
    assert packages == {"geometry", "amsmath", "amssymb"}


def test_required_packages_ignores_commented_lines() -> None:
    # A package the author commented out must not drive engine selection.
    assert required_packages("% \\usepackage{fontspec}\n\\usepackage{geometry}") == {"geometry"}


def test_detection_leaves_an_ordinary_document_on_the_default() -> None:
    assert detect_engine(PLAIN, "pdflatex") == "pdflatex"
    assert detect_engine(PLAIN, "tectonic") == "tectonic"


def test_detection_upgrades_pdflatex_for_fontspec() -> None:
    assert detect_engine(FONTSPEC, "pdflatex") == "xelatex"


def test_detection_leaves_a_unicode_default_alone() -> None:
    # Tectonic is XeTeX-based and handles fontspec natively — no need to switch.
    assert detect_engine(FONTSPEC, "tectonic") == "tectonic"


@pytest.mark.parametrize("source", [LUA, DIRECTLUA])
def test_detection_pins_lua_documents_to_lualatex(source: str) -> None:
    assert detect_engine(source, "tectonic") == "lualatex"
    assert detect_engine(source, "pdflatex") == "lualatex"


def test_incompatibility_flags_fontspec_under_pdflatex() -> None:
    reason = incompatibility(FONTSPEC, "pdflatex")
    assert reason is not None
    assert "fontspec" in reason


def test_incompatibility_flags_lua_under_tectonic() -> None:
    reason = incompatibility(LUA, "tectonic")
    assert reason is not None
    assert "LuaLaTeX" in reason


@pytest.mark.parametrize("engine", sorted(ENGINE_NAMES))
def test_a_plain_document_is_compatible_with_every_engine(engine: str) -> None:
    assert incompatibility(PLAIN, engine) is None


def test_validate_accepts_every_allowlisted_name() -> None:
    for name in ENGINE_NAMES:
        assert validate_engine(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "rm -rf /",
        "/usr/bin/evil",
        "tectonic; whoami",
        "TECTONIC",
        "pdftex",
        "",
    ],
)
def test_validate_rejects_anything_off_the_allowlist(name: str) -> None:
    # This value becomes argv[0] of a subprocess — the allowlist is the boundary.
    with pytest.raises(UnknownEngineError):
        validate_engine(name)
