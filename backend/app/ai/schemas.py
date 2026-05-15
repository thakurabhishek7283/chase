from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "important", "nice_to_have"]


class MissingKeyword(BaseModel):
    """A term the job description expects that the resume does not cover."""

    keyword: str = Field(description="The exact term or phrase the job description uses.")
    severity: Severity = Field(description="How much this gap costs the candidate.")
    rationale: str = Field(description="One sentence on why this matters for this specific role.")


class PhrasingSuggestion(BaseModel):
    """A concrete, applyable rewrite of one line of the resume."""

    original_text: str = Field(
        description=(
            "The exact text from the resume to replace. Must appear verbatim in the "
            "resume so the client can locate and apply it. Empty when this is an addition."
        )
    )
    suggested_text: str = Field(description="The replacement text.")
    reason: str = Field(description="Why this rewrite improves the ATS match.")
    severity: Severity


class ATSReport(BaseModel):
    """Structured ATS analysis of one resume against one job description."""

    match_score: int = Field(ge=0, le=100, description="Overall ATS match score, 0-100.")
    summary: str = Field(description="Two or three sentences on the resume's fit for this role.")
    matched_keywords: list[str] = Field(
        default_factory=list, description="Job-description terms the resume already covers well."
    )
    missing_keywords: list[MissingKeyword] = Field(default_factory=list)
    suggestions: list[PhrasingSuggestion] = Field(default_factory=list)

    @property
    def critical_gap_count(self) -> int:
        return sum(1 for keyword in self.missing_keywords if keyword.severity == "critical")


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
    """How one resume's editable content should change for one specific role."""

    groups: list[TailoredGroup] = Field(default_factory=list)
    regions: list[TailoredRegion] = Field(default_factory=list)
    emphasis: list[str] = Field(
        default_factory=list,
        description="The skills and themes this pass moved to the front for this role.",
    )
    deemphasis: list[str] = Field(
        default_factory=list,
        description="Themes that were pushed down or cut because this role does not ask for them.",
    )
    notes: str = Field(default="", description="Two or three sentences on the tailoring strategy.")


class TailorResult(BaseModel):
    """Outcome of tailoring a LaTeX master resume for one job."""

    tailored_latex: str
    tailoring: ResumeTailoring
    groups_changed: int
    regions_changed: int
    #: Present only when scoring was requested; lets the caller show the lift.
    original_score: int | None = None
    tailored_score: int | None = None
    tailored_report: ATSReport | None = None


class AutofixResult(BaseModel):
    """Outcome of the LangGraph analyze -> fix -> re-score loop."""

    original_score: int
    final_score: int
    iterations: int
    revised_resume_markdown: str
    applied_suggestions: list[PhrasingSuggestion] = Field(default_factory=list)
    final_report: ATSReport
    stopped_because: Literal["target_reached", "no_further_gains", "max_iterations"] = Field(
        description="Why the loop terminated."
    )
