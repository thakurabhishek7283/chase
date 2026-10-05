import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.core.config import get_settings
from app.core.db import engine
from app.routers import (
    admin,
    auth,
    companies,
    health,
    job_profiles,
    matching,
    resumes,
    reviews,
    scores,
    users,
)

settings = get_settings()

# uvicorn configures its own loggers but leaves the root logger alone, so
# without this every `logging.getLogger(__name__)` under `app.` would only
# surface at WARNING and above, through Python's last-resort handler.
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    # Close pooled connections on shutdown, so a rolling restart does not leave
    # Postgres holding sockets until they time out.
    await engine.dispose()


app = FastAPI(
    title="Interview Tracker & Resume Optimizer API",
    summary="Semantic job matching and template-preserving, ATS-scored LaTeX resume tailoring.",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # Off by default. Authentication is a bearer token read from localStorage,
    # so no cross-origin cookie ever needs to ride along; the header would only
    # widen what a mistaken entry in CORS_ORIGINS is able to grant.
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (
    health,
    auth,
    users,
    companies,
    job_profiles,
    resumes,
    reviews,
    scores,
    matching,
    admin,
):
    app.include_router(module.router, prefix="/api/v1")
