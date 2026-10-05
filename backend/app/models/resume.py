import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Resume(SQLModel, table=True):
    """A LaTeX resume — either an uploaded master or a finalized child of one.

    There is no `content_format`. `.tex` is the only accepted input, so every
    row's `content` is LaTeX by construction: the sole way content enters is
    `POST /resumes/upload`, which will not store a document it could not parse
    and compile, and children are produced by splicing into one of those.
    """

    __tablename__ = "resumes"
    __table_args__ = (
        # NULL means "use the operator's configured default". The constraint
        # mirrors ENGINE_NAMES in services/latex/engines.py — the value is
        # executed as a subprocess, so the database refuses anything else even
        # if a caller finds a way past the schema layer.
        CheckConstraint(
            "latex_engine IS NULL OR latex_engine IN "
            "('latexmk', 'pdflatex', 'xelatex', 'lualatex')",
            name="ck_resumes_latex_engine",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    master_resume_id: uuid.UUID | None = Field(default=None, foreign_key="resumes.id", index=True)
    title: str = Field(max_length=255)
    content: str
    version_label: str | None = Field(default=None, max_length=100)
    #: LaTeX engine this document compiles under. NULL falls back to settings.
    #: Chosen at upload and fixed for life: the intake pass validates and
    #: corrects the source *for this engine specifically*, so a later switch
    #: would leave corrections that were made for a different one.
    latex_engine: str | None = Field(default=None, max_length=20)
    #: How to find the editable content in this document — see
    #: `services/latex/config.py`. NULL means the built-in shapes were enough,
    #: which is the case for any resume built on `\item` or `\resumeItem`. A
    #: value here is a template the parser could not read unaided, so the
    #: vocabulary is stored rather than rediscovered on every request.
    #: `none_as_null` so a cleared config is SQL NULL rather than the JSON value
    #: `null` — the two read back identically in Python and differently in SQL.
    latex_slot_config: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB(none_as_null=True), nullable=True)
    )
    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
