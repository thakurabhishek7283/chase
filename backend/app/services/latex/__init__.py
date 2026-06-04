"""LaTeX resume pipeline: parse a master .tex, splice tailored content, compile."""

from app.services.latex.compiler import (
    LatexCompileError,
    LatexEngineNotFoundError,
    compile_pdf,
    engine_available,
    engine_version,
)
from app.services.latex.engines import (
    ENGINE_NAMES,
    EngineName,
    UnknownEngineError,
    detect_engine,
    incompatibility,
    validate_engine,
)
from app.services.latex.model import (
    Bullet,
    ItemGroup,
    LatexResume,
    MarkedRegion,
    Section,
    Span,
)
from app.services.latex.parser import LatexParseError, parse
from app.services.latex.plain_text import to_markdown
from app.services.latex.renderer import GroupEdit, LatexRenderError, RegionEdit, render
from app.services.latex.safety import UnsafeLatexError, escape_text, validate_fragment

__all__ = [
    "ENGINE_NAMES",
    "Bullet",
    "EngineName",
    "GroupEdit",
    "ItemGroup",
    "LatexCompileError",
    "LatexEngineNotFoundError",
    "LatexParseError",
    "LatexRenderError",
    "LatexResume",
    "MarkedRegion",
    "RegionEdit",
    "Section",
    "Span",
    "UnknownEngineError",
    "UnsafeLatexError",
    "compile_pdf",
    "detect_engine",
    "engine_available",
    "engine_version",
    "escape_text",
    "incompatibility",
    "parse",
    "render",
    "to_markdown",
    "validate_fragment",
]
