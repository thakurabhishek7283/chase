import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Resume(SQLModel, table=True):
    __tablename__ = "resumes"
    __table_args__ = (
        CheckConstraint(
            "content_format IN ('markdown', 'json', 'latex')",
            name="ck_resumes_content_format",
        ),
        # NULL means "use the operator's configured default". The constraint
        # mirrors ENGINE_NAMES in services/latex/engines.py — the value is
        # executed as a subprocess, so the database refuses anything else even
        # if a caller finds a way past the schema layer.
        CheckConstraint(
            "latex_engine IS NULL OR latex_engine IN "
            "('tectonic', 'latexmk', 'pdflatex', 'xelatex', 'lualatex')",
            name="ck_resumes_latex_engine",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    master_resume_id: uuid.UUID | None = Field(default=None, foreign_key="resumes.id", index=True)
    title: str = Field(max_length=255)
    content_format: str = Field(default="markdown", max_length=10)
    content: str
    version_label: str | None = Field(default=None, max_length=100)
    #: LaTeX engine this document compiles under. NULL falls back to settings.
    latex_engine: str | None = Field(default=None, max_length=20)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
