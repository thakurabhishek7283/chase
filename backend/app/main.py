from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers import (
    applications,
    ats,
    companies,
    health,
    job_profiles,
    latex,
    matching,
    resumes,
    technologies,
    users,
)

settings = get_settings()

app = FastAPI(title="Interview Tracker & Resume Optimizer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(companies.router, prefix="/api/v1")
app.include_router(technologies.router, prefix="/api/v1")
app.include_router(job_profiles.router, prefix="/api/v1")
app.include_router(resumes.router, prefix="/api/v1")
app.include_router(applications.router, prefix="/api/v1")
app.include_router(matching.router, prefix="/api/v1")
app.include_router(ats.router, prefix="/api/v1")
app.include_router(latex.router, prefix="/api/v1")
