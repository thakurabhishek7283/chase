"""Wire types for resumes: the document, its outline, and what upload reports.

This absorbed the old `schemas/latex.py`. There is no longer a LaTeX feature
sitting beside a resume feature — a resume *is* a LaTeX document — and keeping
two schema modules meant an import cycle the moment the upload response wanted
to carry an outline.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Mirrors ENGINE_NAMES in services/latex/engines.py. A Literal rather than a
#: free string because the value is executed as a subprocess.
LatexEngine = Literal["tectonic", "latexmk", "pdflatex", "xelatex", "lualatex"]


# --- the document ----------------------------------------------------------


class ResumeRead(BaseModel):
    """A stored resume, source included. There is no `ResumeCreate`.

    Content enters through `POST /resumes/upload` and nowhere else: an upload is
    validated, corrected and compiled before it is stored, and a JSON body
    accepting arbitrary `content` would be a way around all three.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    master_resume_id: uuid.UUID | None
    title: str
    content: str
    version_label: str | None
    latex_engine: str | None
    created_at: datetime
    updated_at: datetime


class ResumeSummary(BaseModel):
    """A resume without its source — what the list screen needs.

    Every resume's `.tex` runs to tens of kilobytes and the list renders none of
    it, so the list endpoint does not send it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    master_resume_id: uuid.UUID | None
    title: str
    version_label: str | None
    latex_engine: str | None
    created_at: datetime
    updated_at: datetime


# --- the slot vocabulary ---------------------------------------------------


class BulletMacroOut(BaseModel):
    r"""A macro whose sole argument is a bullet, e.g. `\resumeItem{…}`."""

    name: str


class FieldMacroOut(BaseModel):
    r"""One editable argument of a multi-argument macro."""

    name: str
    arity: int
    content_arg: int
    label: str = "field"


class ListPairOut(BaseModel):
    start: str
    end: str


class SlotConfigOut(BaseModel):
    """The vocabulary the parser used to read this document.

    Round-trips: what comes out of the outline can be edited and sent straight
    back to `PUT /resumes/{id}/slots`, which is how an author corrects a boundary
    the intake pass got wrong without touching their `.tex`.
    """

    section_macros: list[str] = Field(default_factory=list)
    environments: list[str] = Field(default_factory=list)
    bullet_macros: list[BulletMacroOut] = Field(default_factory=list)
    list_pairs: list[ListPairOut] = Field(default_factory=list)
    field_macros: list[FieldMacroOut] = Field(default_factory=list)
    #: "builtin", "discovered", or "author".
    source: str = "builtin"
    #: False for a proposal from intake the author has not agreed to yet.
    confirmed: bool = True


class SlotConfigUpdate(BaseModel):
    """Replace a resume's slot config, or reset it to the built-in shapes.

    `config: null` clears the stored vocabulary — the right move when intake
    misread a document that the default shapes can handle after all.
    """

    config: SlotConfigOut | None = None


# --- the outline -----------------------------------------------------------


class BulletOut(BaseModel):
    """One editable bullet, as the client sees it."""

    id: str
    latex: str
    #: Fingerprint of this slot's current content. Ids are positional, so this
    #: is what a client echoes back to prove its edit still targets the text it
    #: was written against. See `services.latex.fingerprint`.
    content_hash: str = ""


class ItemGroupOut(BaseModel):
    id: str
    kind: str
    bullets: list[BulletOut]
    content_hash: str = ""


class MarkedRegionOut(BaseModel):
    id: str
    label: str
    latex: str
    content_hash: str = ""
    #: "marker" when the author wrote `% jarvis:begin`, "field" when this is one
    #: argument of a configured macro. The client shows inferred slots
    #: differently — they are the ones worth a second look.
    origin: str = "marker"


class SectionOut(BaseModel):
    id: str
    heading: str
    editable: bool
    groups: list[ItemGroupOut] = Field(default_factory=list)
    regions: list[MarkedRegionOut] = Field(default_factory=list)


class ResumeOutline(BaseModel):
    """What a review may change in a master, and what it will leave alone.

    Deliberately exposes the frozen/editable split rather than hiding it: the
    author needs to see that a section has no editable slots so they know to add
    a `% jarvis:begin` marker or correct the slot config.
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
    #: Set when the selected engine cannot compile this document.
    engine_warning: str | None = None
    #: Fingerprint of everything *outside* the editable slots. Identical in a
    #: master and every resume finalized from it — that is the promise, and a
    #: client can check it rather than take our word for it.
    template_hash: str = ""
    #: The vocabulary this document was read with, and where it came from.
    slot_config: SlotConfigOut = Field(default_factory=SlotConfigOut)


# --- upload ----------------------------------------------------------------


class AppliedCorrection(BaseModel):
    """One fix the intake pass made to an uploaded document.

    Surfaced because the stored master is not byte-identical to the file the
    author picked, and they are entitled to see exactly where it differs.
    """

    find: str
    replace: str
    reason: str


class ResumeUploadResponse(BaseModel):
    resume_id: uuid.UUID
    title: str
    #: Empty when the document compiled as submitted, which is the good case.
    corrections: list[AppliedCorrection] = Field(default_factory=list)
    #: The model's account of the document: whether it was valid, what had to
    #: change, and how the template is put together.
    verdict: str = ""
    outline: ResumeOutline


class LatexEngineStatus(BaseModel):
    """Which engines this deployment can actually run."""

    available: bool
    engine: str
    version: str | None = None
    detail: str | None = None
    #: Every allowlisted engine and whether it is installed, so the upload form
    #: can offer only the ones that will work.
    engines: dict[str, bool] = Field(default_factory=dict)
