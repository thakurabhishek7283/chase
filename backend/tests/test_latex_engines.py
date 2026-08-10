import pytest

from app.services.latex.engines import (
    ENGINE_NAMES,
    UnknownEngineError,
    detect_engine,
    incompatibility,
    pdftex_only_markers,
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

#: The opening of the widely-copied "Jake's Résumé" template, which is where
#: this pairing shows up in practice.
GLYPHTOUNICODE = r"""\documentclass{article}
\input{glyphtounicode}
\pdfgentounicode=1
\begin{document}\begin{itemize}\item hi\end{itemize}\end{document}
"""

#: The same document after the fix the error message recommends.
GUARDED = r"""\documentclass{article}
\ifdefined\pdfglyphtounicode \input{glyphtounicode} \fi
\ifdefined\pdfgentounicode \pdfgentounicode=1 \fi
\begin{document}\begin{itemize}\item hi\end{itemize}\end{document}
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
    assert detect_engine(PLAIN, "xelatex") == "xelatex"


def test_detection_upgrades_pdflatex_for_fontspec() -> None:
    assert detect_engine(FONTSPEC, "pdflatex") == "xelatex"


def test_detection_leaves_a_unicode_default_alone() -> None:
    # xelatex already handles fontspec natively — no need to switch.
    assert detect_engine(FONTSPEC, "xelatex") == "xelatex"


@pytest.mark.parametrize("source", [LUA, DIRECTLUA])
def test_detection_pins_lua_documents_to_lualatex(source: str) -> None:
    assert detect_engine(source, "xelatex") == "lualatex"
    assert detect_engine(source, "pdflatex") == "lualatex"


def test_incompatibility_flags_fontspec_under_pdflatex() -> None:
    reason = incompatibility(FONTSPEC, "pdflatex")
    assert reason is not None
    assert "fontspec" in reason


def test_incompatibility_flags_lua_under_xelatex() -> None:
    reason = incompatibility(LUA, "xelatex")
    assert reason is not None
    assert "LuaLaTeX" in reason


@pytest.mark.parametrize("engine", sorted(ENGINE_NAMES))
def test_a_plain_document_is_compatible_with_every_engine(engine: str) -> None:
    assert incompatibility(PLAIN, engine) is None


def test_pdftex_primitives_are_found_and_named() -> None:
    assert pdftex_only_markers(GLYPHTOUNICODE) == {
        r"\input{glyphtounicode}",
        r"\pdfgentounicode",
    }


def test_a_guarded_primitive_is_not_a_requirement() -> None:
    # `\ifdefined` is the fix the error message recommends; flagging the fixed
    # document would make the advice impossible to follow.
    assert pdftex_only_markers(GUARDED) == set()
    assert incompatibility(GUARDED, "xelatex") is None
    assert detect_engine(GUARDED, "xelatex") == "xelatex"


def test_a_commented_out_primitive_does_not_count() -> None:
    assert pdftex_only_markers("% \\pdfgentounicode=1\n\\documentclass{article}") == set()


@pytest.mark.parametrize("engine", ["xelatex"])
def test_incompatibility_flags_pdftex_primitives_under_xetex(engine: str) -> None:
    reason = incompatibility(GLYPHTOUNICODE, engine)
    assert reason is not None
    assert "glyphtounicode" in reason
    # The message has to carry the fix; the engine's own answer is a hundred
    # lines of log that never mentions `\ifdefined`.
    assert r"\ifdefined" in reason


@pytest.mark.parametrize("engine", ["pdflatex", "latexmk", "lualatex"])
def test_pdftex_primitives_are_fine_off_xetex(engine: str) -> None:
    assert incompatibility(GLYPHTOUNICODE, engine) is None


def test_detection_moves_a_pdftex_document_off_xelatex() -> None:
    assert detect_engine(GLYPHTOUNICODE, "xelatex") == "pdflatex"
    assert detect_engine(GLYPHTOUNICODE, "pdflatex") == "pdflatex"


def test_unicode_fonts_outrank_a_glyph_map() -> None:
    # Unsatisfiable: fontspec needs XeTeX, \pdfgentounicode needs pdfTeX. Losing
    # the glyph map beats losing the typeface, and the mismatch is still
    # reported rather than swallowed.
    both = FONTSPEC.replace(r"\begin{document}", "\\pdfgentounicode=1\n\\begin{document}")
    assert detect_engine(both, "pdflatex") == "xelatex"
    assert "pdfgentounicode" in (incompatibility(both, "xelatex") or "")


def test_validate_accepts_every_allowlisted_name() -> None:
    for name in ENGINE_NAMES:
        assert validate_engine(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "rm -rf /",
        "/usr/bin/evil",
        "pdflatex; whoami",
        "PDFLATEX",
        "pdftex",
        "",
    ],
)
def test_validate_rejects_anything_off_the_allowlist(name: str) -> None:
    # This value becomes argv[0] of a subprocess — the allowlist is the boundary.
    with pytest.raises(UnknownEngineError):
        validate_engine(name)
