"""Model output types shared across the AI seams.

Everything here is either something a model is asked to produce or something
produced from one.

`ResumeScoreResult` lives here rather than in `ai/score.py` because two agents
answer it: the scorer returns it alone, and the reviewer returns it with patches
attached (`ai/review.ResumeReviewResult` subclasses it). That inheritance is the
point — a verdict shown as "your ATS score" has to mean the same thing whichever
call produced it, and two hand-kept copies of four fields would eventually not.
"""

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "important", "nice_to_have"]


class MissingKeyword(BaseModel):
    """A term the job description expects that the resume does not cover."""

    keyword: str = Field(description="The exact term or phrase the job description uses.")
    severity: Severity = Field(description="How much this gap costs the candidate.")
    rationale: str = Field(description="One sentence on why this matters for this specific role.")


class ResumeScoreResult(BaseModel):
    """How one resume screens against one job, with nothing proposed about it.

    The scorer's whole output and the first four fields of the reviewer's. It
    describes the document **as it is** — for a tailored child that means after
    its patches landed, which is exactly the number the author wants to see.
    """

    match_score: int = Field(ge=0, le=100, description="ATS match for the resume as it is now.")
    summary: str = Field(description="Two or three sentences on the resume's fit for this role.")
    matched_keywords: list[str] = Field(
        default_factory=list, description="Job-description terms the resume already covers well."
    )
    missing_keywords: list[MissingKeyword] = Field(default_factory=list)


class TailoredGroup(BaseModel):
    """The complete final bullet list for one editable group."""

    group_id: str = Field(description="The group id exactly as given in the outline, e.g. 'g2'.")
    items: list[str] = Field(
        description=(
            "The FULL final list of bullets for this group, in the order they should "
            "appear. Reorder, reword, or drop the originals; add at most one new bullet "
            "and only if it restates experience already present elsewhere in the resume."
        )
    )


class TailoredRegion(BaseModel):
    """Replacement LaTeX for one author-marked region."""

    region_id: str = Field(description="The region id exactly as given in the outline, e.g. 'r1'.")
    latex: str = Field(description="The full replacement LaTeX for this region.")


class ResumeTailoring(BaseModel):
    """A set of slot edits ready to be spliced into a master.

    Not a model output type any more — the review flow builds one of these from
    the patches an author accepted. It stays because it is the vocabulary the
    renderer and the repair loop already speak.
    """

    groups: list[TailoredGroup] = Field(default_factory=list)
    regions: list[TailoredRegion] = Field(default_factory=list)
