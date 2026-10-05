from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from app.deps import SessionDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process is up and serving requests. Touches nothing else."""
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(session: SessionDep) -> dict[str, str]:
    """Readiness: the database answers too.

    Kept separate from `/health` so an orchestrator restarting on a failed
    liveness probe does not kill a healthy process during a database blip.
    The LLM key and the LaTeX worker are deliberately not checked: each has its
    own 503 at the route that needs it, and neither stops the rest of the API.
    """
    try:
        await session.exec(text("SELECT 1"))  # type: ignore[call-overload]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable."
        ) from exc
    return {"status": "ok", "database": "ok"}
