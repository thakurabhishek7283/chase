import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas import ResumeTailoring, TailorResult
from app.schemas.resume import LatexEngine


class BulletOut(BaseModel):
    """One editable bullet, as the client sees it."""

    id: str
    latex: str


class ItemGroupOut(BaseModel):
    id: str
    kind: str
    bullets: list[BulletOut]


class MarkedRegionOut(BaseModel):
    id: str
    label: str
    latex: str


class SectionOut(BaseModel):
    id: str
    heading: str
    editable: bool
    groups: list[ItemGroupOut] = Field(default_factory=list)
    regions: list[MarkedRegionOut] = Field(default_factory=list)


class ResumeOutline(BaseModel):
    """What tailoring may change in a master, and what it will leave alone.

    Deliberately exposes the frozen/editable split rather than hiding it: the
    author needs to see that a section has no editable slots so they know to add
    a `% jarvis:begin` marker.
    """

    resume_id: uuid.UUID | None = None
    sections: list[SectionOut]
    group_count: int
    bullet_count: int
    region_count: int
    #: Sections with nothing editable — usually Education, sometimes a skills
    #: block built from macros the parser will not guess at.
    frozen_sections: list[str] = Field(default_factory=list)
    #: The engine this document compiles under, and whether it can actually run.
    latex_engine: str | None = None
    engine_available: bool = True
    #: Set when the selected engine cannot compile this document — e.g. the
    #: resume loads fontspec but pdflatex is selected.
    engine_warning: str | None = None


class LatexUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resume_id: uuid.UUID
    title: str
    outline: ResumeOutline


class TailorRequest(BaseModel):
    """Tailor a stored LaTeX master against a stored job profile."""

    resume_id: uuid.UUID
    job_profile_id: uuid.UUID
    #: Also run the ATS scorer over the before/after text to show the lift.
    score: bool = False
    #: Persist the result as a tailored child of the master.
    save_as_tailored_version: bool = True


class TailorResponse(BaseModel):
    resume_id: uuid.UUID
    job_profile_id: uuid.UUID
    saved_resume_id: uuid.UUID | None = None
    result: TailorResult


class PreviewTailoringRequest(BaseModel):
    """Apply an already-reviewed tailoring without calling the model again.

    This is what makes the flow human-in-the-loop: the client can take the
    `tailoring` from a tailor response, let the user edit bullets by hand, and
    re-render deterministically.
    """

    tailoring: ResumeTailoring


class LatexEngineStatus(BaseModel):
    """Which engines this deployment can actually run."""

    available: bool
    engine: str
    version: str | None = None
    detail: str | None = None
    #: Every allowlisted engine and whether it is installed, so a client can
    #: offer only the ones that will work.
    engines: dict[str, bool] = Field(default_factory=dict)


class EngineUpdateRequest(BaseModel):
    """Change the engine a stored resume compiles under."""

    latex_engine: LatexEngine | None = Field(
        default=None, description="None resets the resume to the server default."
    )
