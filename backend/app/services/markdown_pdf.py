"""Compile a markdown resume to PDF via Pandoc, using Tectonic as the PDF engine.

Pandoc handles markdown parsing and LaTeX escaping — hand-rolling that escaping
(`%`, `&`, `#`, `_`, `~`, `^`, `{`, `}`, `\\`) is exactly the kind of thing that
looks simple and then corrupts someone's resume the first time a bullet mentions
"50% growth" or a `snake_case_project`. `--pdf-engine=tectonic` reuses the LaTeX
engine already required for the Phase 5 pipeline instead of installing a second
one.
"""

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.core.config import get_settings
from app.services.latex.compiler import engine_path

INSTALL_HINT = (
    "Pandoc not found. Install it with `winget install JohnMacFarlane.Pandoc`, "
    "then restart the API. Override the binary with PANDOC_PATH."
)


class PandocNotFoundError(RuntimeError):
    """Raised when Pandoc, or its configured PDF engine, is not on the system."""


class MarkdownCompileError(RuntimeError):
    """Raised when Pandoc runs but rejects the document."""


def pandoc_path() -> str | None:
    configured = get_settings().pandoc_path
    if Path(configured).is_file():
        return configured
    return shutil.which(configured)


def pandoc_available() -> bool:
    return pandoc_path() is not None


def _compile_sync(markdown_source: str) -> bytes:
    pandoc = pandoc_path()
    if pandoc is None:
        raise PandocNotFoundError(INSTALL_HINT)
    # The markdown pipeline piggybacks on the LaTeX engine's install, so a
    # missing Tectonic surfaces here rather than as an opaque Pandoc failure.
    tectonic = engine_path()
    if tectonic is None:
        from app.services.latex.compiler import INSTALL_HINT as TECTONIC_INSTALL_HINT

        raise PandocNotFoundError(TECTONIC_INSTALL_HINT)

    settings = get_settings()
    with tempfile.TemporaryDirectory(prefix="jarvis-pandoc-") as workdir:
        directory = Path(workdir)
        md_path = directory / "resume.md"
        md_path.write_text(markdown_source, encoding="utf-8")
        pdf_path = directory / "resume.pdf"

        try:
            completed = subprocess.run(
                [pandoc, str(md_path), "-o", str(pdf_path), f"--pdf-engine={tectonic}"],
                capture_output=True,
                text=True,
                timeout=settings.pandoc_compile_timeout_seconds,
                cwd=directory,
            )
        except subprocess.TimeoutExpired as exc:
            raise MarkdownCompileError(
                f"Compilation timed out after {settings.pandoc_compile_timeout_seconds}s."
            ) from exc
        except OSError as exc:
            raise PandocNotFoundError(INSTALL_HINT) from exc

        if completed.returncode != 0 or not pdf_path.exists():
            log = (completed.stdout or "") + (completed.stderr or "")
            raise MarkdownCompileError(log.strip() or "Pandoc reported failure with no output.")
        return pdf_path.read_bytes()


async def compile_markdown_pdf(markdown_source: str) -> bytes:
    """Compile markdown resume text to PDF bytes without blocking the event loop."""
    return await asyncio.to_thread(_compile_sync, markdown_source)
