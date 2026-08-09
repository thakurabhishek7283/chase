r"""Compile `.tex` to PDF by running a LaTeX engine inside Docker.

Every allowlisted engine lives in one image (`docker/latex/Dockerfile`): a
curated TeX Live (pdflatex, xelatex, lualatex, latexmk) plus Tectonic, which
TeX Live does not ship. Nothing is installed on the host but Docker itself —
no multi-gigabyte TeX distribution on a dev machine, and a resume that turns
`\write18` into command execution lands in a container instead of the host
shell.

Compilation always runs `--untrusted` where the engine supports it, on top of
the container boundary — belt and suspenders, since `--untrusted` is a flag an
engine could have bugs in. Network stays enabled: Tectonic fetches packages it
doesn't already have from its bundle server, the same as it did on the host,
so a persistent named volume (`tectonic-cache`) backs its package cache across
compiles — otherwise every one would re-download.

**A single long-lived worker container, not one `docker run` per compile.**
Creating a container has real overhead (several hundred ms, more on Docker
Desktop), which is wasteful for something invoked once per resume upload or
tailor. `_ensure_worker()` keeps one named container (`_WORKER_NAME`) running
`sleep infinity` and every compile shells out to `docker exec` against it
instead. The worker holds no state of its own — the image is immutable and
the Tectonic cache lives in the separate `tectonic-cache` volume — so it is
freely disposable: `_ensure_worker()` re-probes it before every compile
(container present, running, built from the currently configured image,
actually answers an `exec`) and transparently kills and recreates it on any
mismatch. A wedged, OOM-killed, or manually-removed worker self-heals on the
very next request rather than wedging the app.
"""

import asyncio
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from app.core.config import get_settings
from app.services.latex.engines import validate_engine

INSTALL_HINT = (
    "No LaTeX engine found. Install Docker Desktop, then build the engine "
    "image once with `docker build -t jarvis-latex:latest backend/docker/latex` "
    "(or your configured LATEX_DOCKER_IMAGE tag)."
)

#: LaTeX reports real errors on lines starting with '!'. Everything else in a
#: log is font and package chatter that helps nobody debug their resume.
_ERROR_LINE = re.compile(r"^(!.*|l\.\d+.*|.*\.tex:\d+:.*)$", re.MULTILINE)


class LatexEngineNotFoundError(RuntimeError):
    """Raised when the configured LaTeX engine is not on the system."""


class LatexCompileError(RuntimeError):
    """Raised when the engine runs but rejects the document."""


#: Where Tectonic caches downloaded packages inside the container. Named so a
#: Docker volume of the same name persists it across worker recreations.
_TECTONIC_CACHE_VOLUME = "tectonic-cache"
_TECTONIC_CACHE_MOUNT = "/root/.cache/Tectonic"

#: The one long-lived container every compile execs into. Fixed name so
#: `_ensure_worker` can find it again across requests (and across app
#: restarts — it isn't tied to this process's lifetime).
_WORKER_NAME = "jarvis-latex-worker"
#: Host directory bind-mounted into the worker at `/scratch`. Each compile
#: gets its own subdirectory under it; a plain host temp dir wouldn't work
#: here because a bind mount's *source* is fixed when the worker is created,
#: unlike the per-`docker run` mount the old ephemeral-container version used.
_SCRATCH_MOUNT = "/scratch"
#: Only one thread may create/recreate the worker at a time — otherwise two
#: requests that both see it missing race to `docker run --name`, and the
#: loser fails on "name already in use".
_WORKER_LOCK = threading.Lock()


def _docker_path() -> str | None:
    return shutil.which("docker")


def _image_present(image: str) -> bool:
    """Whether `docker image inspect` finds `image` — i.e. it has been built."""
    docker = _docker_path()
    if docker is None:
        return False
    try:
        completed = subprocess.run(
            [docker, "image", "inspect", image], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _scratch_root() -> Path:
    """Host directory bind-mounted into the worker at `_SCRATCH_MOUNT`.

    Created once, outside any single compile's lifetime, because it has to
    exist *before* the worker container is created (a `-v` source is fixed
    for the container's life) and has to keep existing across compiles.
    """
    root = Path(tempfile.gettempdir()) / "jarvis-latex-scratch"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _worker_image(docker: str) -> str | None:
    """The image the running worker was created from, or None if it isn't running."""
    try:
        completed = subprocess.run(
            [docker, "inspect", "--format", "{{.State.Running}}|{{.Config.Image}}", _WORKER_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    running, _, image = completed.stdout.strip().partition("|")
    return image if running == "true" else None


def _worker_responds(docker: str) -> bool:
    """A container can report `running` while wedged; only a real `exec` proves it works."""
    try:
        completed = subprocess.run(
            [docker, "exec", _WORKER_NAME, "true"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _recreate_worker(docker: str, image: str) -> None:
    """Kill whatever is at `_WORKER_NAME` (if anything) and start fresh.

    Always safe: the worker holds no state of its own, so there is nothing to
    preserve. `docker rm -f` on a name that doesn't exist just fails quietly.
    """
    subprocess.run([docker, "rm", "-f", _WORKER_NAME], capture_output=True, text=True, timeout=15)
    completed = subprocess.run(
        [
            docker, "run", "-d", "--name", _WORKER_NAME,
            "-v", f"{_scratch_root()}:{_SCRATCH_MOUNT}",
            "-v", f"{_TECTONIC_CACHE_VOLUME}:{_TECTONIC_CACHE_MOUNT}",
            image, "sleep", "infinity",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise LatexEngineNotFoundError(
            f"Could not start the LaTeX worker container: {completed.stderr.strip() or completed.stdout.strip()}"
        )


def _ensure_worker(docker: str, image: str) -> None:
    """Guarantee `_WORKER_NAME` is running `image` and responsive, or raise trying.

    Cheap when the worker is already healthy (an inspect and an exec, tens of
    milliseconds) — worth paying on every compile so a worker that died,
    drifted onto a stale image after a config change, or was removed by hand
    is never more than one request away from healing itself.
    """
    with _WORKER_LOCK:
        if _worker_image(docker) == image and _worker_responds(docker):
            return
        _recreate_worker(docker, image)


def engine_path(engine: str | None = None) -> str | None:
    """Resolve an engine to a runnable name, or None if it cannot run.

    There is no host binary anymore: every engine lives inside
    `docker/latex/Dockerfile`'s image, so "runnable" means Docker is on PATH
    *and* that image has been built. With no argument this resolves the
    operator's configured default; with an argument it validates the name
    against the allowlist first, because it ends up as `argv` inside the
    container.
    """
    name = validate_engine(engine) if engine is not None else validate_engine(
        get_settings().latex_default_engine
    )
    return name if _image_present(get_settings().latex_docker_image) else None


def engine_available(engine: str | None = None) -> bool:
    return engine_path(engine) is not None


def engine_version(engine: str | None = None) -> str | None:
    """Return the engine's version banner, for the health endpoint."""
    resolved = engine_path(engine)
    docker = _docker_path()
    if resolved is None or docker is None:
        return None
    try:
        completed = subprocess.run(
            [docker, "run", "--rm", get_settings().latex_docker_image, resolved, "--version"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    banner = (completed.stdout or completed.stderr or "").strip().splitlines()
    return banner[0] if banner else None


def _build_command(engine: str, *, v2: bool) -> list[str]:
    """The argv to run *inside* the container. Paths are relative to the exec's
    working directory (the per-compile scratch subdirectory, set via `docker
    exec -w`), so `resume.tex` and `out/` are all the engine ever needs to see."""
    if engine == "tectonic":
        flags = ["--untrusted", "--outdir", "out", "resume.tex"]
        return [engine, "-X", "compile", *flags] if v2 else [engine, *flags]
    if engine == "latexmk":
        return [
            engine, "-pdf", "-interaction=nonstopmode", "-halt-on-error",
            "-outdir=out", "resume.tex",
        ]
    return [
        engine, "-interaction=nonstopmode", "-halt-on-error",
        "-output-directory=out", "resume.tex",
    ]


def _summarise(log: str) -> str:
    errors = _ERROR_LINE.findall(log)
    if errors:
        return "\n".join(errors[:12])
    return "\n".join(log.strip().splitlines()[-12:])


def _compile_sync(tex_source: str, requested: str | None = None) -> bytes:
    engine = engine_path(requested)
    docker = _docker_path()
    if engine is None or docker is None:
        raise LatexEngineNotFoundError(
            f"LaTeX engine '{requested}' is not available in the "
            f"{get_settings().latex_docker_image} image."
            if requested
            else INSTALL_HINT
        )

    settings = get_settings()
    _ensure_worker(docker, settings.latex_docker_image)

    # A subdirectory of the worker's bind-mounted scratch root, not a fresh
    # `docker run` mount — the worker is already running, so its mounts are
    # fixed. `dir=` keeps this on the same filesystem/bind mount as the root.
    directory = Path(tempfile.mkdtemp(dir=_scratch_root()))
    container_dir = f"{_SCRATCH_MOUNT}/{directory.name}"
    try:
        (directory / "resume.tex").write_text(tex_source, encoding="utf-8")
        (directory / "out").mkdir()

        attempts = [True, False] if engine == "tectonic" else [True]
        completed: subprocess.CompletedProcess[str] | None = None
        for v2 in attempts:
            try:
                completed = subprocess.run(
                    [docker, "exec", "-w", container_dir, _WORKER_NAME,
                     *_build_command(engine, v2=v2)],
                    capture_output=True,
                    text=True,
                    timeout=settings.latex_compile_timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                raise LatexCompileError(
                    f"Compilation timed out after {settings.latex_compile_timeout_seconds}s. "
                    "Tectonic downloads packages on its first run; retry once the "
                    f"'{_TECTONIC_CACHE_VOLUME}' volume is warm."
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

        pdf_path = directory / "out" / "resume.pdf"
        if completed is not None and completed.returncode != 0 and not pdf_path.exists():
            raise LatexCompileError(_summarise((completed.stdout or "") + (completed.stderr or "")))
        if not pdf_path.exists():
            raise LatexCompileError("The engine reported success but produced no PDF.")
        return pdf_path.read_bytes()
    finally:
        shutil.rmtree(directory, ignore_errors=True)


async def compile_pdf(tex_source: str, engine: str | None = None) -> bytes:
    """Compile LaTeX source to PDF bytes without blocking the event loop.

    `engine` is an allowlisted name (see `services.latex.engines`); None uses the
    operator's configured default.
    """
    return await asyncio.to_thread(_compile_sync, tex_source, engine)
