import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

GrowthTrajectory = Literal["declining", "stable", "growing", "hypergrowth"]
ModerationStatus = Literal["pending", "approved", "rejected"]

_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def _check_company_name(value: str) -> str:
    """Cheap structural checks, run before anything reaches the database.

    This is not spam detection — deciding whether a company is real is the
    admin's job, and no regex is going to do it. The point is to reject input
    that is *obviously* not a name, so the review queue holds plausible
    submissions rather than keyboard mashing.
    """
    name = " ".join(value.split())
    if len(name) < 2:
        raise ValueError("A company name needs at least two characters.")
    if not _HAS_LETTER.search(name):
        raise ValueError("A company name must contain at least one letter.")
    # A wall of one repeated character ("aaaaaaaa", "!!!!!!!!").
    if len(set(name.lower().replace(" ", ""))) == 1:
        raise ValueError("That does not look like a company name.")
    return name


def _check_website(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    url = value.strip()
    if not url.startswith(("http://", "https://")):
        # Users type "acme.com"; store something a browser can actually follow.
        url = f"https://{url}"
    if "." not in url.split("//", 1)[-1]:
        raise ValueError("That does not look like a website address.")
    return url


CompanyName = Annotated[str, AfterValidator(_check_company_name)]
Website = Annotated[str | None, AfterValidator(_check_website)]


class CompanyCreate(BaseModel):
    """What a contributor may propose.

    `status`, `created_by`, and the review fields are server-assigned — a client
    that could set `status='approved'` would make moderation decorative.
    """

    name: CompanyName = Field(max_length=255)
    industry: str | None = Field(default=None, max_length=255)
    growth_trajectory: GrowthTrajectory | None = None
    website: Website = None


class CompanyUpdate(BaseModel):
    name: CompanyName | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=255)
    growth_trajectory: GrowthTrajectory | None = None
    website: Website = None


class CompanyReject(BaseModel):
    reason: str = Field(min_length=1)


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    industry: str | None
    growth_trajectory: str | None
    website: str | None
    status: str
    created_by: uuid.UUID | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime


class DuplicateCompany(BaseModel):
    """409 body for a slug collision.

    Handing back the existing row turns a dead-end error into a usable branch:
    the client can offer "use the company that already exists" instead of making
    the user guess what they should have searched for.
    """

    detail: str
    existing: CompanyRead
