from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
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

app = FastAPI(title="Interview Tracker & Resume Optimizer API")

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

app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(companies.router, prefix="/api/v1")
app.include_router(job_profiles.router, prefix="/api/v1")
app.include_router(resumes.router, prefix="/api/v1")
app.include_router(reviews.router, prefix="/api/v1")
app.include_router(scores.router, prefix="/api/v1")
app.include_router(matching.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
