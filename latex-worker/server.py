r"""A minimal HTTP wrapper around the LaTeX engines baked into this image.

Deliberately stdlib-only: this image already carries a multi-GB TeX Live
install, so pulling in a web framework isn't worth an extra layer for three
routes. The backend (`app/services/latex/compiler.py`) talks to this over
HTTP instead of managing this container's lifecycle itself — see that
module's docstring for why that split exists.

Routes:
  GET  /health   -> 200, liveness only
  GET  /engines  -> {name: {available, version}} for every allowlisted engine
  POST /compile?engine=<name>&timeout=<seconds>, body = raw .tex source
       -> 200 + PDF bytes on success
       -> 400 unknown engine name, 503 engine not installed,
          422 the engine ran but rejected the document (JSON {"detail": ...})
"""

import json
import re
import shutil
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ENGINE_NAMES = frozenset({"latexmk", "pdflatex", "xelatex", "lualatex"})
DEFAULT_TIMEOUT_SECONDS = 120
PORT = 8100

#: LaTeX reports real errors on lines starting with '!'. Everything else in a
#: log is font and package chatter that helps nobody debug their resume.
_ERROR_LINE = re.compile(r"^(!.*|l\.\d+.*|.*\.tex:\d+:.*)$", re.MULTILINE)


def _build_command(engine: str) -> list[str]:
    # -no-shell-escape: this document is untrusted (uploaded, then rewritten
    # by an LLM), and \write18 is exactly the kind of feature that turns
    # "compile a resume" into arbitrary command execution. The container
    # boundary around this whole process is belt-and-suspenders on top of
    # this, not a substitute for it — an engine bug in the sandboxing is
    # still contained here.
    if engine == "latexmk":
        return [
            engine, "-pdf", "-interaction=nonstopmode", "-halt-on-error",
            "-latexoption=-no-shell-escape", "-outdir=out", "resume.tex",
        ]
    return [
        engine, "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
        "-output-directory=out", "resume.tex",
    ]


def _summarise(log: str) -> str:
    errors = _ERROR_LINE.findall(log)
    if errors:
        return "\n".join(errors[:12])
    return "\n".join(log.strip().splitlines()[-12:])


def _engine_version(engine: str) -> str | None:
    if shutil.which(engine) is None:
        return None
    try:
        completed = subprocess.run(
            [engine, "--version"], capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.SubprocessError):
        return None
    banner = (completed.stdout or completed.stderr or "").strip().splitlines()
    return banner[0] if banner else None


def _json(status: int, payload: dict) -> tuple[int, bytes, str]:
    return status, json.dumps(payload).encode(), "application/json"


def _compile(engine: str, tex_source: str, timeout_seconds: int) -> tuple[int, bytes, str]:
    directory = Path(tempfile.mkdtemp())
    try:
        (directory / "resume.tex").write_text(tex_source, encoding="utf-8")
        (directory / "out").mkdir()

        try:
            completed = subprocess.run(
                _build_command(engine),
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return _json(422, {"detail": f"Compilation timed out after {timeout_seconds}s."})

        pdf_path = directory / "out" / "resume.pdf"
        if completed.returncode != 0 and not pdf_path.exists():
            detail = _summarise((completed.stdout or "") + (completed.stderr or ""))
            return _json(422, {"detail": detail})
        if not pdf_path.exists():
            return _json(422, {"detail": "The engine reported success but produced no PDF."})
        return 200, pdf_path.read_bytes(), "application/pdf"
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        # The backend already logs the outcome of every compile it requests;
        # this would just be a second, less useful copy of the same event.
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send(200, b"ok", "text/plain")
            return
        if parsed.path == "/engines":
            payload = {
                name: {"available": shutil.which(name) is not None, "version": _engine_version(name)}
                for name in sorted(ENGINE_NAMES)
            }
            self._send(*_json(200, payload))
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/compile":
            self._send(404, b"not found", "text/plain")
            return

        params = parse_qs(parsed.query)
        engine = (params.get("engine") or [""])[0]
        if engine not in ENGINE_NAMES:
            self._send(*_json(400, {"detail": f"Unknown engine {engine!r}."}))
            return
        if shutil.which(engine) is None:
            self._send(*_json(503, {"detail": f"Engine {engine!r} is not installed in this image."}))
            return

        try:
            timeout_seconds = int((params.get("timeout") or [str(DEFAULT_TIMEOUT_SECONDS)])[0])
        except ValueError:
            timeout_seconds = DEFAULT_TIMEOUT_SECONDS

        length = int(self.headers.get("Content-Length", 0))
        tex_source = self.rfile.read(length).decode("utf-8")

        self._send(*_compile(engine, tex_source, timeout_seconds))


if __name__ == "__main__":
    print(f"LaTeX worker listening on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
