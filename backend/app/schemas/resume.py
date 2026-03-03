import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ContentFormat = Literal["markdown", "json", "latex"]
#: Mirrors ENGINE_NAMES in services/latex/engines.py. A Literal rather than a
#: free string because the value is executed as a subprocess.
LatexEngine = Literal["tectonic", "latexmk", "pdflatex", "xelatex", "lualatex"]


class ResumeCreate(BaseModel):
    user_id: uuid.UUID
    master_resume_id: uuid.UUID | None = None
    title: str
    content_format: ContentFormat = "markdown"
    content: str
    version_label: str | None = None
    latex_engine: LatexEngine | None = None


class ResumeUpdate(BaseModel):
    title: str | None = None
    content_format: ContentFormat | None = None
    content: str | None = None
    version_label: str | None = None
    latex_engine: LatexEngine | None = None


class ResumeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    master_resume_id: uuid.UUID | None
    title: str
    content_format: str
    content: str
    version_label: str | None
    latex_engine: str | None
    created_at: datetime
    updated_at: datetime
