"""Tests for the Phase 2 matching endpoints.

The test database has no pgvector extension (its migration is deferred), so
these assert the *degradation* contract: every vector-dependent endpoint must
answer 503 with an actionable message, never a 500.
"""

from httpx import AsyncClient

from app.services.matching import build_job_profile_text
from app.models.job_profile import JobProfile


async def _create_user_with_goals(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/users",
        json={
            "full_name": "Goal Haver",
            "email": "goals@example.com",
            "career_goals": "Lead distributed systems teams working in Python.",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_build_job_profile_text_skips_missing_fields() -> None:
    job = JobProfile(
        company_id="00000000-0000-0000-0000-000000000001",
        position_title="Backend Engineer",
        description="Build APIs.",
    )
    text = build_job_profile_text(job)
    assert "Backend Engineer" in text
    assert "Build APIs." in text
    # No stray blank lines from the absent tier/location.
    assert "\n\n" not in text


async def test_reindex_degrades_to_503_without_pgvector(client: AsyncClient) -> None:
    await _create_user_with_goals(client)
    company = await client.post("/api/v1/companies", json={"name": "Vector Co"})
    await client.post(
        "/api/v1/job-profiles",
        json={
            "company_id": company.json()["id"],
            "position_title": "Backend Engineer",
            "description": "Python and distributed systems.",
        },
    )

    response = await client.post("/api/v1/matching/reindex")
    assert response.status_code == 503, f"expected a clean 503, got {response.status_code}"
    assert "pgvector" in response.json()["detail"]


async def test_job_matches_degrades_to_503_without_pgvector(client: AsyncClient) -> None:
    user_id = await _create_user_with_goals(client)
    response = await client.get(f"/api/v1/users/{user_id}/job-matches")
    assert response.status_code == 503
    detail = response.json()["detail"]
    # Either the embedding provider or the vector table is the missing piece;
    # both must produce an actionable message rather than a stack trace.
    assert "pgvector" in detail or "fastembed" in detail


async def test_job_matches_requires_career_goals(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/users", json={"full_name": "No Goals", "email": "nogoals@example.com"}
    )
    user_id = response.json()["id"]

    matches = await client.get(f"/api/v1/users/{user_id}/job-matches")
    assert matches.status_code == 400
    assert "career goals" in matches.json()["detail"]


async def test_job_matches_404s_for_unknown_user(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/users/00000000-0000-0000-0000-0000000000ff/job-matches"
    )
    assert response.status_code == 404


async def test_parse_pdf_rejects_non_pdf(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/resumes/parse-pdf",
        files={"file": ("not-a.pdf", b"plain text, not a pdf", "application/pdf")},
    )
    assert response.status_code == 422


async def test_ats_score_requires_api_key(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/ats/score",
        json={
            "resume_id": "00000000-0000-0000-0000-000000000001",
            "job_profile_id": "00000000-0000-0000-0000-000000000002",
        },
    )
    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]
