r"""Compile `.tex` to PDF by calling the LaTeX worker service over HTTP.

Every allowlisted engine lives in one image (`latex-worker/`): a curated TeX
Live install providing pdflatex, xelatex, lualatex, and latexmk. That image
runs as its own long-lived service — a docker-compose service in the
containerized setup, or a container you start once for native development
(see README.md) — wrapped in a small stdlib-only HTTP server
(`latex-worker/server.py`). This module only ever speaks HTTP to it, at
`LATEX_WORKER_URL`.

That split is deliberate, not incidental. This module used to manage the
worker container's entire lifecycle itself: `docker run` to create it,
`docker exec` into it per compile, health-probing it, tearing it down and
recreating it on drift. Doing that from inside a container of its own (the
containerized backend) meant sharing the host's Docker socket in — giving this
process the same control over Docker an operator's own user account has, just
to compile a handful of PDFs. Compiling untrusted `.tex` still happens in its
own disposable container, exactly as before; this module just no longer needs
the power to *create* containers to make that happen, which is a much smaller
thing to hand it.

Compilation always runs `--untrusted` where the engine supports it, on top of
the container boundary — belt and suspenders, since `--untrusted` is a flag an
engine could have bugs in.
"""

import httpx

from app.core.config import get_settings
from app.services.latex.engines import validate_engine

INSTALL_HINT = (
    "No LaTeX worker reachable. Start it once — "
    "`docker run -d -p 8100:8100 --name jarvis-latex-worker jarvis-latex:latest` "
    "for native development, or `docker compose up -d latex-worker` — and check "
    "LATEX_WORKER_URL points at it."
)


class LatexEngineNotFoundError(RuntimeError):
    """Raised when the configured LaTeX engine is not reachable or not installed."""


class LatexCompileError(RuntimeError):
    """Raised when the engine runs but rejects the document."""


def _resolve(engine: str | None) -> str:
    return (
        validate_engine(engine)
        if engine is not None
        else validate_engine(get_settings().latex_default_engine)
    )


def _engines_sync() -> dict[str, dict] | None:
    """`GET /engines` from the worker, or None if it isn't reachable at all.

    Synchronous and short-timeout — used only from the status/outline paths,
    which were already making a short blocking call in this spot before this
    module talked to a worker over HTTP instead of shelling out to `docker`.
    """
    try:
        response = httpx.get(f"{get_settings().latex_worker_url}/engines", timeout=5)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    return response.json()


def engine_available(engine: str | None = None) -> bool:
    name = _resolve(engine)
    engines = _engines_sync()
    return bool(engines and engines.get(name, {}).get("available"))


def engine_version(engine: str | None = None) -> str | None:
    """Return the engine's version banner, for the health endpoint."""
    engines = _engines_sync()
    if not engines:
        return None
    return engines.get(_resolve(engine), {}).get("version")


def _error_detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    return detail or response.text or f"HTTP {response.status_code}"


async def compile_pdf(tex_source: str, engine: str | None = None) -> bytes:
    """Compile LaTeX source to PDF bytes via the LaTeX worker service.

    `engine` is an allowlisted name (see `services.latex.engines`); None uses
    the operator's configured default.
    """
    name = _resolve(engine)
    settings = get_settings()
    params = {"engine": name, "timeout": settings.latex_compile_timeout_seconds}
    # A little slack over the worker's own compile timeout, so its clean
    # "timed out after Ns" response wins the race against this client just
    # giving up first.
    timeout = httpx.Timeout(settings.latex_compile_timeout_seconds + 15)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{settings.latex_worker_url}/compile",
                params=params,
                content=tex_source.encode("utf-8"),
            )
    except httpx.HTTPError as exc:
        raise LatexEngineNotFoundError(INSTALL_HINT) from exc

    if response.status_code == 200:
        return response.content
    if response.status_code in (404, 503):
        raise LatexEngineNotFoundError(
            f"LaTeX engine {name!r} is not available: {_error_detail(response)}"
        )
    raise LatexCompileError(_error_detail(response))
