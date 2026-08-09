from app.models.audit import AuditLog
from app.models.company import Company
from app.models.embedding import EntityEmbedding
from app.models.job_profile import JobProfile
from app.models.resume import Resume
from app.models.review import ResumePatch, ResumeReview
from app.models.score import ResumeScore
from app.models.session import RefreshToken
from app.models.user import User

#: Tables that require the pgvector extension. Test fixtures and any
#: environment without pgvector exclude these from schema creation.
PGVECTOR_TABLES = {"entity_embeddings"}

__all__ = [
    "PGVECTOR_TABLES",
    "AuditLog",
    "Company",
    "EntityEmbedding",
    "JobProfile",
    "RefreshToken",
    "Resume",
    "ResumePatch",
    "ResumeReview",
    "ResumeScore",
    "User",
]
