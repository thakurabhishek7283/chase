r"""Seeing an ATS score, and what it costs to see it again.

The scoring endpoint has one job and one performance promise, and both are worth
a test each: it reports how a resume screens, and looking at the answer a second
time does not reach a model. Every test here counts model calls explicitly,
because "fast" in this feature means "did not ask", not "asked quickly".
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlmodel import select

from app.ai.schemas import ResumeScoreResult
from app.models.resume import Resume
from tests.conftest import test_session_maker as session_maker

SCORE_PAYLOAD = {
    "match_score": 74,
    "summary": "Covers the pipeline work; Rust is still absent.",
    "matched_keywords": ["Python", "pipeline"],
    "missing_keywords": [
        {"keyword": "Rust", "severity": "critical", "rationale": "Named as a requirement."}
    ],
}

JOB_DESCRIPTION = (
    "We need a backend engineer fluent in Rust and Python, comfortable owning "
    "distributed data pipelines and an on-call rotation."
)


class ScoreCounter:
    """A stubbed scorer that remembers how often it was actually asked."""

    def __init__(self) -> None:
        self.calls = 0

    def agent(self) -> Agent:
        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            self.calls += 1
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, SCORE_PAYLOAD)])

        return Agent(FunctionModel(respond), output_type=ResumeScoreResult)


@pytest.fixture
def scorer(monkeypatch: pytest.MonkeyPatch) -> ScoreCounter:
    counter = ScoreCounter()
    monkeypatch.setattr("app.ai.provider.has_llm_credentials", lambda: True)
    monkeypatch.setattr("app.ai.score.get_score_agent", counter.agent)
    return counter


@pytest_asyncio.fixture
async def job_id(user_client: AsyncClient) -> str:
    company = await user_client.post("/api/v1/companies", json={"name": "Acme"})
    assert company.status_code == 201, company.text
    response = await user_client.post(
        "/api/v1/job-profiles",
        json={
            "company_id": company.json()["id"],
            "position_title": "Backend Engineer",
            "description": JOB_DESCRIPTION,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_scoring_reports_how_the_resume_screens(
    user_client: AsyncClient, make_resume, job_id: str, scorer: ScoreCounter
) -> None:
    resume_id = await make_resume(user_client)
    response = await user_client.post(
        f"/api/v1/resumes/{resume_id}/scores", json={"job_profile_id": job_id}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["match_score"] == 74
    assert [gap["keyword"] for gap in body["missing_keywords"]] == ["Rust"]
    assert body["computed"] is True
    assert body["stale"] is False
    assert scorer.calls == 1


async def test_looking_again_costs_nothing(
    user_client: AsyncClient, make_resume, job_id: str, scorer: ScoreCounter
) -> None:
    """The performance promise, stated as a call count.

    A resume screen that re-scored on every open would make five tailored
    versions five model calls and several seconds of blocking, which is the
    failure `resume_scores` exists to prevent.
    """
    resume_id = await make_resume(user_client)
    await user_client.post(f"/api/v1/resumes/{resume_id}/scores", json={"job_profile_id": job_id})

    again = await user_client.post(
        f"/api/v1/resumes/{resume_id}/scores", json={"job_profile_id": job_id}
    )
    listed = await user_client.get(f"/api/v1/resumes/{resume_id}/scores")

    assert again.json()["match_score"] == 74
    assert again.json()["computed"] is False
    assert [row["match_score"] for row in listed.json()] == [74]
    assert scorer.calls == 1


async def test_an_unscored_resume_lists_empty_rather_than_404(
    user_client: AsyncClient, make_resume, scorer: ScoreCounter
) -> None:
    resume_id = await make_resume(user_client)
    response = await user_client.get(f"/api/v1/resumes/{resume_id}/scores")
    assert response.status_code == 200
    assert response.json() == []
    assert scorer.calls == 0


async def test_a_changed_resume_makes_its_score_stale(
    user_client: AsyncClient, make_resume, job_id: str, scorer: ScoreCounter
) -> None:
    """A stale score is shown and labelled, never silently refreshed on read.

    Refreshing on read would turn opening a resume into an unbounded row of
    model calls; hiding the number would throw away the last thing anyone knew.
    """
    resume_id = await make_resume(user_client)
    await user_client.post(f"/api/v1/resumes/{resume_id}/scores", json={"job_profile_id": job_id})

    async with session_maker() as session:
        resume = (await session.exec(select(Resume).where(Resume.id == resume_id))).one()
        resume.content = resume.content.replace(
            "Ran the on-call rotation.", "Ran the on-call rotation for six teams."
        )
        session.add(resume)
        await session.commit()

    listed = await user_client.get(f"/api/v1/resumes/{resume_id}/scores")
    assert listed.json()[0]["stale"] is True
    assert listed.json()[0]["match_score"] == 74
    assert scorer.calls == 1

    # Asking again does re-score, without needing `refresh`: the stored answer
    # is known not to describe this document any more.
    refreshed = await user_client.post(
        f"/api/v1/resumes/{resume_id}/scores", json={"job_profile_id": job_id}
    )
    assert refreshed.json()["stale"] is False
    assert scorer.calls == 2


async def test_refresh_rescores_a_score_that_was_not_stale(
    user_client: AsyncClient, make_resume, job_id: str, scorer: ScoreCounter
) -> None:
    """For the change the fingerprint cannot see: the job description itself."""
    resume_id = await make_resume(user_client)
    await user_client.post(f"/api/v1/resumes/{resume_id}/scores", json={"job_profile_id": job_id})

    forced = await user_client.post(
        f"/api/v1/resumes/{resume_id}/scores",
        json={"job_profile_id": job_id, "refresh": True},
    )
    assert forced.json()["computed"] is True
    assert scorer.calls == 2


async def test_another_users_resume_cannot_be_scored_or_read(
    user_client: AsyncClient,
    other_client: AsyncClient,
    make_resume,
    job_id: str,
    scorer: ScoreCounter,
) -> None:
    resume_id = await make_resume(user_client)
    assert (
        await other_client.post(
            f"/api/v1/resumes/{resume_id}/scores", json={"job_profile_id": job_id}
        )
    ).status_code == 404
    assert (await other_client.get(f"/api/v1/resumes/{resume_id}/scores")).status_code == 404
    assert scorer.calls == 0
