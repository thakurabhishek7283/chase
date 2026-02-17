from app.models.application import Application
from app.models.company import Company
from app.models.embedding import EntityEmbedding
from app.models.job_profile import JobProfile
from app.models.resume import Resume
from app.models.technology import CompanyTechnology, JobProfileTechnology, Technology
from app.models.user import User

#: Tables that require the pgvector extension. Test fixtures and any
#: environment without pgvector exclude these from schema creation.
PGVECTOR_TABLES = {"entity_embeddings"}

__all__ = [
    "PGVECTOR_TABLES",
    "Application",
    "Company",
    "CompanyTechnology",
    "EntityEmbedding",
    "JobProfile",
    "JobProfileTechnology",
    "Resume",
    "Technology",
    "User",
]
