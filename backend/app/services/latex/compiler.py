r"""Compile `.tex` to PDF by shelling out to a LaTeX engine.

Tectonic is the default: one binary, no TeX distribution, and it fetches the
packages a document actually needs on first compile. The trade-off is that the
*first* run on a new machine is slow and needs network access — after that it
works from its local cache.

Compilation always runs `--untrusted` where the engine supports it. The document
being compiled is user-supplied, and `\\write18` turning a resume upload into
command execution is exactly the kind of thing that flag exists to stop.
"""

import asyncio
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.core.config import get_settings
from app.services.latex.engines import validate_engine

INSTALL_HINT = (
    "No LaTeX engine found. Install Tectonic with "
    "`winget install TectonicProject.Tectonic` (or `cargo install tectonic`), "
    "then restart the API. Override the binary with LATEX_ENGINE_PATH."
)

#: LaTeX reports real errors on lines starting with '!'. Everything else in a
#: log is font and package chatter that helps nobody debug their resume.
_ERROR_LINE = re.compile(r"^(!.*|l\.\d+.*|.*\.tex:\d+:.*)$", re.MULTILINE)


class LatexEngineNotFoundError(RuntimeError):
    """Raised when the configured LaTeX engine is not on the system."""


class LatexCompileError(RuntimeError):
    """Raised when the engine runs but rejects the document."""


def engine_path(engine: str | None = None) -> str | None:
    """Resolve an engine to a runnable path, or None if it is not installed.

    With no argument this resolves the operator's configured default, which may
    be an absolute path. With an argument it resolves a *name* — validated
    against the allowlist first, because the result is executed.
    """
    if engine is None:
        configured = get_settings().latex_engine_path
        if Path(configured).is_file():
            return configured
        return shutil.which(configured)
    return shutil.which(validate_engine(engine))


def engine_available(engine: str | None = None) -> bool:
    return engine_path(engine) is not None


def engine_version(engine: str | None = None) -> str | None:
    """Return the engine's version banner, for the health endpoint."""
    resolved = engine_path(engine)
    if resolved is None:
        return None
    try:
        completed = subprocess.run(
            [resolved, "--version"], capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.SubprocessError):
        return None
    banner = (completed.stdout or completed.stderr or "").strip().splitlines()
    return banner[0] if banner else None


def _build_command(engine: str, tex_path: Path, out_dir: Path, *, v2: bool) -> list[str]:
    name = Path(engine).stem.lower()
    if "tectonic" in name:
        flags = ["--untrusted", "--outdir", str(out_dir), str(tex_path)]
        return [engine, "-X", "compile", *flags] if v2 else [engine, *flags]
    if "latexmk" in name:
        return [
            engine, "-pdf", "-interaction=nonstopmode", "-halt-on-error",
            f"-outdir={out_dir}", str(tex_path),
        ]
    return [
        engine, "-interaction=nonstopmode", "-halt-on-error",
        f"-output-directory={out_dir}", str(tex_path),
    ]


def _summarise(log: str) -> str:
    errors = _ERROR_LINE.findall(log)
    if errors:
        return "\n".join(errors[:12])
    return "\n".join(log.strip().splitlines()[-12:])


def _compile_sync(tex_source: str, requested: str | None = None) -> bytes:
    engine = engine_path(requested)
    if engine is None:
        raise LatexEngineNotFoundError(
            f"LaTeX engine '{requested}' is not installed on this machine."
            if requested
            else INSTALL_HINT
        )

    settings = get_settings()
    with tempfile.TemporaryDirectory(prefix="jarvis-latex-") as workdir:
        directory = Path(workdir)
        tex_path = directory / "resume.tex"
        tex_path.write_text(tex_source, encoding="utf-8")
        out_dir = directory / "out"
        out_dir.mkdir()

        attempts = [True, False] if "tectonic" in Path(engine).stem.lower() else [True]
        completed: subprocess.CompletedProcess[str] | None = None
        for v2 in attempts:
            try:
                completed = subprocess.run(
                    _build_command(engine, tex_path, out_dir, v2=v2),
                    capture_output=True,
                    text=True,
                    timeout=settings.latex_compile_timeout_seconds,
                    cwd=directory,
                )
            except subprocess.TimeoutExpired as exc:
                raise LatexCompileError(
                    f"Compilation timed out after {settings.latex_compile_timeout_seconds}s. "
                    "Tectonic downloads packages on its first run; retry once it is warm."
                ) from exc
            except OSError as exc:
                raise LatexEngineNotFoundError(INSTALL_HINT) from exc

            log = (completed.stdout or "") + (completed.stderr or "")
            # Older Tectonic builds predate the `-X` subcommand CLI; a usage
            # error on the first attempt means "retry the legacy invocation",
            # not "the document is broken".
            if completed.returncode != 0 and v2 and re.search(r"unrecognized|USAGE|Usage:", log):
                continue
            break

        pdf_path = out_dir / "resume.pdf"
        if completed is not None and completed.returncode != 0 and not pdf_path.exists():
            raise LatexCompileError(_summarise((completed.stdout or "") + (completed.stderr or "")))
        if not pdf_path.exists():
            raise LatexCompileError("The engine reported success but produced no PDF.")
        return pdf_path.read_bytes()


async def compile_pdf(tex_source: str, engine: str | None = None) -> bytes:
    """Compile LaTeX source to PDF bytes without blocking the event loop.

    `engine` is an allowlisted name (see `services.latex.engines`); None uses the
    operator's configured default.
    """
    return await asyncio.to_thread(_compile_sync, tex_source, engine)
