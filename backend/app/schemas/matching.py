import uuid

from pydantic import BaseModel, ConfigDict

from app.schemas.company import CompanyRead
from app.schemas.job_profile import JobProfileRead


class EmbeddingStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entity_type: str
    entity_id: uuid.UUID
    provider: str
    model: str


class ReindexSummary(BaseModel):
    """Result of (re)embedding a batch of entities."""

    job_profiles_indexed: int
    users_indexed: int


class JobMatch(BaseModel):
    """A job profile ranked by semantic similarity to a user's career goals."""

    similarity: float
    job_profile: JobProfileRead
    company: CompanyRead
