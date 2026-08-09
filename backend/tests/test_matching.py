"""Tests for the Phase 2 matching endpoints.

The test database has no pgvector extension (its migration is deferred), so
these assert the *degradation* contract: every vector-dependent endpoint must
answer 503 with an actionable message, never a 500.
"""

from httpx import AsyncClient

from app.models.job_profile import JobProfile
from app.services.matching import build_job_profile_text


async def _set_goals(client: AsyncClient) -> str:
    response = await client.patch(
        "/api/v1/auth/me",
        json={"career_goals": "Lead distributed systems teams working in Python."},
    )
    assert response.status_code == 200, response.text
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


async def test_reindex_degrades_to_503_without_pgvector(admin_client: AsyncClient) -> None:
    await _set_goals(admin_client)
    company = await admin_client.post("/api/v1/companies", json={"name": "Vector Co"})
    await admin_client.post(
        "/api/v1/job-profiles",
        json={
            "company_id": company.json()["id"],
            "position_title": "Backend Engineer",
            "description": "Python, distributed systems, and platform reliability work.",
        },
    )

    response = await admin_client.post("/api/v1/matching/reindex")
    assert response.status_code == 503, f"expected a clean 503, got {response.status_code}"
    assert "pgvector" in response.json()["detail"]


async def test_reindex_is_admin_only(user_client: AsyncClient) -> None:
    """Walking the whole corpus costs money, so it is not a per-user lever."""
    response = await user_client.post("/api/v1/matching/reindex")
    assert response.status_code == 403


async def test_job_matches_degrades_to_503_without_pgvector(user_client: AsyncClient) -> None:
    user_id = await _set_goals(user_client)
    response = await user_client.get(f"/api/v1/users/{user_id}/job-matches")
    assert response.status_code == 503
    detail = response.json()["detail"]
    # Either the embedding provider or the vector table is the missing piece;
    # both must produce an actionable message rather than a stack trace.
    assert "pgvector" in detail or "fastembed" in detail


async def test_job_matches_requires_career_goals(user_client: AsyncClient) -> None:
    me = await user_client.get("/api/v1/auth/me")
    matches = await user_client.get(f"/api/v1/users/{me.json()['id']}/job-matches")
    assert matches.status_code == 400
    assert "career goals" in matches.json()["detail"]


async def test_job_matches_are_self_only(
    user_client: AsyncClient, other_client: AsyncClient
) -> None:
    """Career goals are personal; nobody else's matches are readable."""
    victim_id = await _set_goals(other_client)
    response = await user_client.get(f"/api/v1/users/{victim_id}/job-matches")
    assert response.status_code == 404


async def test_job_matches_404s_for_unknown_user(user_client: AsyncClient) -> None:
    response = await user_client.get(
        "/api/v1/users/00000000-0000-0000-0000-0000000000ff/job-matches"
    )
    assert response.status_code == 404
