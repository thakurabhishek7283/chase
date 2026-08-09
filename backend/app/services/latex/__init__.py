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
from app.services.latex.errors import LatexErrorCode
from app.services.latex.config import (
    BulletMacro,
    FieldMacro,
    ListPair,
    SlotConfig,
    SlotConfigError,
)
from app.services.latex.fingerprint import (
    document_fingerprint,
    slot_hash,
    slot_hashes,
    template_hash,
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
from app.services.latex.renderer import (
    GroupEdit,
    LatexRenderError,
    RegionEdit,
    StaleEditError,
    TemplateDriftError,
    render,
)
from app.services.latex.safety import (
    UnsafeLatexError,
    allowed_commands_prompt,
    escape_text,
    validate_fragment,
)

__all__ = [
    "ENGINE_NAMES",
    "Bullet",
    "BulletMacro",
    "EngineName",
    "FieldMacro",
    "GroupEdit",
    "ItemGroup",
    "ListPair",
    "LatexCompileError",
    "LatexEngineNotFoundError",
    "LatexErrorCode",
    "LatexParseError",
    "LatexRenderError",
    "LatexResume",
    "MarkedRegion",
    "RegionEdit",
    "Section",
    "SlotConfig",
    "SlotConfigError",
    "Span",
    "StaleEditError",
    "TemplateDriftError",
    "UnknownEngineError",
    "UnsafeLatexError",
    "allowed_commands_prompt",
    "compile_pdf",
    "detect_engine",
    "document_fingerprint",
    "engine_available",
    "engine_version",
    "escape_text",
    "incompatibility",
    "parse",
    "render",
    "slot_hash",
    "slot_hashes",
    "template_hash",
    "to_markdown",
    "validate_fragment",
]
