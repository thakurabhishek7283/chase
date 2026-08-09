import uuid
from datetime import datetime, timezone

from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col, func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.company import Company
from app.models.user import User
from app.schemas.company import CompanyCreate, CompanyUpdate
from app.services.slug import slugify_company


async def create_company(
    session: AsyncSession, data: CompanyCreate, *, author: User
) -> Company:
    """Insert a proposed company, attributed to its contributor.

    An admin's own submission is approved on the spot — routing it into a queue
    they alone can clear would be a review of themselves by themselves.
    """
    approved = author.is_admin
    now = datetime.now(timezone.utc)
    company = Company(
        **data.model_dump(),
        slug=slugify_company(data.name),
        created_by=author.id,
        status="approved" if approved else "pending",
        reviewed_by=author.id if approved else None,
        reviewed_at=now if approved else None,
    )
    session.add(company)
    await session.commit()
    await session.refresh(company)
    return company


async def find_by_slug(session: AsyncSession, slug: str) -> Company | None:
    """The live company holding this slug, if any.

    Rejected rows are skipped so they match `uq_companies_slug_active`. A
    rejected submission must not block the real company from being added later
    — and it would be worse than a plain block, because the contributor cannot
    see the row the 409 is pointing at.
    """
    result = await session.exec(
        select(Company).where(Company.slug == slug, Company.status != "rejected")
    )
    return result.first()


async def count_pending_for(session: AsyncSession, user_id: uuid.UUID) -> int:
    result = await session.exec(
        select(func.count())
        .select_from(Company)
        .where(Company.created_by == user_id, Company.status == "pending")
    )
    return int(result.one())


async def list_companies(
    session: AsyncSession,
    scope: ColumnElement[bool],
    *,
    search: str | None = None,
    status: str | None = None,
) -> list[Company]:
    query = select(Company).where(scope)
    if status is not None:
        query = query.where(Company.status == status)
    if search:
        # Matched against the slug as well as the name so a user typing
        # "acme inc" finds the row stored as "Acme" — the search box is the
        # first line of duplicate prevention, and it only helps if it
        # normalises the same way the unique index does.
        pattern = f"%{search.strip().lower()}%"
        query = query.where(
            or_(col(Company.name).ilike(pattern), col(Company.slug).ilike(pattern))
        )
    result = await session.exec(query.order_by(col(Company.name)))
    return list(result.all())


async def get_company(session: AsyncSession, company_id: uuid.UUID) -> Company | None:
    return await session.get(Company, company_id)


async def update_company(
    session: AsyncSession, company: Company, data: CompanyUpdate
) -> Company:
    fields = data.model_dump(exclude_unset=True)
    for field, value in fields.items():
        setattr(company, field, value)
    # The slug is derived, never client-supplied, so renaming has to recompute
    # it or the dedup key would drift away from the name it describes.
    if "name" in fields and fields["name"] is not None:
        company.slug = slugify_company(fields["name"])
    company.updated_at = datetime.now(timezone.utc)
    session.add(company)
    await session.commit()
    await session.refresh(company)
    return company


async def set_moderation_status(
    session: AsyncSession,
    company: Company,
    *,
    status: str,
    reviewer: User,
    reason: str | None = None,
) -> Company:
    company.status = status
    company.reviewed_by = reviewer.id
    company.reviewed_at = datetime.now(timezone.utc)
    company.rejection_reason = reason
    company.updated_at = company.reviewed_at
    session.add(company)
    await session.commit()
    await session.refresh(company)
    return company


async def delete_company(session: AsyncSession, company: Company) -> None:
    await session.delete(company)
    await session.commit()


async def purge_rejected(session: AsyncSession, older_than: datetime) -> int:
    """Delete rejected companies reviewed before `older_than`.

    Rejected rows are kept for a while so the contributor can read why. Past
    that they are just junk taking up space, and nothing references them: a
    company that never got approved never had a posting attached to it.
    """
    rows = (
        await session.exec(
            select(Company).where(
                Company.status == "rejected", col(Company.reviewed_at) < older_than
            )
        )
    ).all()
    for row in rows:
        await session.delete(row)
    await session.commit()
    return len(rows)
