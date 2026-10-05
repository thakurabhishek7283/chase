"""Write failure artefacts to disk for post-mortem analysis.

When a patch fails to apply or compile, calling `dump_failure` writes a
timestamped directory under ``JARVIS_FAILURE_DUMP_DIR`` (default: ``./failure_dumps``
relative to the working directory) containing:

- ``patch.json``    — the full ``ResumeTailoring`` that was being applied
- ``source.tex``    — the master LaTeX source at the time of failure
- ``error.txt``     — the exception type, message, and traceback
- ``meta.json``     — resume_id, user_id, timestamp, error type

These files are never sent to the client and contain PII (the resume text), so
the dump directory should be excluded from version control and restricted to
operators who already have database access.
"""

from __future__ import annotations

import json
import logging
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.ai.schemas import ResumeTailoring

logger = logging.getLogger(__name__)

_DUMP_ENV_VAR = "JARVIS_FAILURE_DUMP_DIR"


def _dump_dir() -> Path:
    """Resolve the dump root, creating it if necessary."""
    import os

    raw = os.environ.get(_DUMP_ENV_VAR, "failure_dumps")
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def dump_failure(
    *,
    error: Exception,
    tailoring: ResumeTailoring | None = None,
    source_tex: str | None = None,
    resume_id: str | uuid.UUID | None = None,
    user_id: str | uuid.UUID | None = None,
    context: str = "apply_tailoring",
) -> Path | None:
    """Persist failure artefacts to disk and return the dump directory path.

    Returns ``None`` if the write itself fails (so callers never crash on a
    diagnostic path) and logs a warning in that case.
    """
    try:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%f")
        slug = f"{context}_{stamp}"
        out = _dump_dir() / slug
        out.mkdir(parents=True, exist_ok=True)

        # meta.json --------------------------------------------------------
        meta = {
            "timestamp": datetime.now(UTC).isoformat(),
            "context": context,
            "resume_id": str(resume_id) if resume_id else None,
            "user_id": str(user_id) if user_id else None,
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
        (out / "meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # error.txt --------------------------------------------------------
        tb = traceback.format_exc()
        (out / "error.txt").write_text(f"{type(error).__name__}: {error}\n\n{tb}", encoding="utf-8")

        # patch.json -------------------------------------------------------
        if tailoring is not None:
            (out / "patch.json").write_text(tailoring.model_dump_json(indent=2), encoding="utf-8")

        # source.tex -------------------------------------------------------
        if source_tex is not None:
            (out / "source.tex").write_text(source_tex, encoding="utf-8")

        logger.info(
            "[failure_dump] Artefacts written to %s  (error=%s: %s)",
            out,
            type(error).__name__,
            str(error)[:200],
        )
        return out

    except Exception as dump_exc:
        logger.warning("[failure_dump] Could not write artefacts: %s", dump_exc, exc_info=True)
        return None
