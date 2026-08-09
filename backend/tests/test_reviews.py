r"""The one business flow, end to end: upload → review → resolve → child.

Every model call is a `FunctionModel` with a fixed payload, so what is under
test is the *flow* — which calls cost a round trip, which are free, and above
all the rule that nothing renders until every patch has a decision on it.

The engine is real. Upload compiles, and so does preview, because "this document
works" is the one claim the app is not allowed to make on a model's say-so.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlmodel import select

from app.ai.intake import LatexIntake
from app.ai.patch_revision import RevisedPatch
from app.ai.review import ResumeReviewResult
from app.models.resume import Resume

# Aliased on import: pytest tries to collect any module-level name starting
# with `test_`, and an async_sessionmaker is not a test.
from tests.conftest import test_session_maker as session_maker

MASTER = r"""\documentclass{article}
\usepackage{enumitem}
\begin{document}
\section{Experience}
\textbf{Engineer}, Acme \hfill 2021 -- Present
\begin{itemize}
    \item Built a data pipeline in Python.
    \item Ran the on-call rotation.
\end{itemize}
\section{Skills}
% jarvis:begin skills
\textbf{Languages}: Python, Go
% jarvis:end
\end{document}
"""

JOB_DESCRIPTION = (
    "We need a backend engineer fluent in Rust and Python, comfortable owning "
    "distributed data pipelines and an on-call rotation."
)

_REVIEW_PAYLOAD = {
    "match_score": 62,
    "summary": "Strong pipeline experience; Rust is not surfaced.",
    "matched_keywords": ["Python", "pipeline"],
    "missing_keywords": [
        {"keyword": "Rust", "severity": "critical", "rationale": "Named as a requirement."}
    ],
    "patches": [
        {
            "slot_id": "g1",
            "items": [
                r"Built a \textbf{Python} data pipeline handling 40k events/sec.",
                "Ran the on-call rotation for a distributed platform.",
            ],
            "latex": "",
            "reason": "Surfaces throughput and the distributed framing the role asks for.",
            "severity": "important",
        },
        {
            "slot_id": "r1",
            "items": [],
            "latex": r"\textbf{Languages}: Python, Go",
            "reason": "Leads with the languages this role names.",
            "severity": "nice_to_have",
        },
    ],
}


def _fixed(payload: dict) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload)])

    return FunctionModel(respond)


@pytest.fixture(autouse=True)
def stub_the_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every agent a fixed answer, and pretend a key is configured.

    The suite runs with no credentials on purpose (see `conftest`), so the
    credential gate has to be lifted explicitly rather than by leaking a real
    key into the environment.
    """
    monkeypatch.setattr("app.ai.provider.has_llm_credentials", lambda: True)
    monkeypatch.setattr(
        "app.ai.intake.get_intake_agent",
        lambda: Agent(
            _fixed({"corrections": [], "slot_schema": {}, "verdict": "Reads cleanly."}),
            output_type=LatexIntake,
        ),
    )
    monkeypatch.setattr(
        "app.ai.review.get_review_agent",
        lambda: Agent(_fixed(_REVIEW_PAYLOAD), output_type=ResumeReviewResult),
    )
    monkeypatch.setattr(
        "app.ai.patch_revision.get_revision_agent",
        lambda: Agent(
            _fixed(
                {
                    "items": ["Built a Python data pipeline.", "Ran on-call."],
                    "latex": r"\textbf{Languages}: Python",
                    "note": "Shortened as asked.",
                }
            ),
            output_type=RevisedPatch,
        ),
    )


async def _upload(client: AsyncClient, title: str = "Master") -> str:
    response = await client.post(
        "/api/v1/resumes/upload",
        data={"title": title},
        files={"file": ("resume.tex", MASTER.encode(), "application/x-tex")},
    )
    assert response.status_code == 201, response.text
    return response.json()["resume_id"]


async def _job(client: AsyncClient, title: str = "Backend Engineer") -> str:
    company = await client.post("/api/v1/companies", json={"name": f"Acme {title}"})
    assert company.status_code == 201, company.text
    response = await client.post(
        "/api/v1/job-profiles",
        json={
            "company_id": company.json()["id"],
            "position_title": title,
            "description": JOB_DESCRIPTION,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _review(client: AsyncClient) -> dict:
    resume_id = await _upload(client)
    job_id = await _job(client)
    response = await client.post(
        f"/api/v1/resumes/{resume_id}/reviews", json={"job_profile_id": job_id}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _resolve_all(client: AsyncClient, review: dict, action: str = "accept") -> None:
    for patch in review["patches"]:
        response = await client.patch(
            f"/api/v1/reviews/{review['id']}/patches/{patch['id']}", json={"action": action}
        )
        assert response.status_code == 200, response.text


async def _finalize(client: AsyncClient, review: dict) -> str:
    """Accept everything and keep the result. Returns the new version's id."""
    await _resolve_all(client, review)
    response = await client.post(f"/api/v1/reviews/{review['id']}/finalize", json={})
    assert response.status_code == 201, response.text
    return response.json()["child_resume_id"]


@pytest_asyncio.fixture
async def review(user_client: AsyncClient) -> dict:
    return await _review(user_client)


# --- upload ------------------------------------------------------------------


async def test_upload_is_the_only_way_content_enters(user_client: AsyncClient) -> None:
    # There is no JSON create and no content update. Every previous way in was a
    # way to store a document nobody had proved was renderable.
    assert (await user_client.post("/api/v1/resumes", json={"title": "x", "content": "y"})).status_code == 405
    resume_id = await _upload(user_client)
    assert (await user_client.patch(f"/api/v1/resumes/{resume_id}", json={"title": "z"})).status_code == 405


async def test_upload_refuses_anything_that_is_not_a_tex_file(user_client: AsyncClient) -> None:
    response = await user_client.post(
        "/api/v1/resumes/upload",
        data={"title": "From a PDF"},
        files={"file": ("resume.pdf", b"%PDF-1.4 not really", "application/pdf")},
    )
    assert response.status_code == 422
    assert ".tex" in response.json()["detail"]


async def test_upload_failure_reports_a_machine_readable_category(
    user_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 422 from the intake gauntlet says *why*, not just that it failed.

    `detail` is `{code, message}` here rather than a bare string, so a client
    could offer "widen your slot markers" for `unsupported_latex` and "fix your
    LaTeX" for `invalid_latex` instead of one generic error screen.
    """
    monkeypatch.setattr(
        "app.ai.intake.get_intake_agent",
        lambda: Agent(
            _fixed(
                {
                    "corrections": [
                        {"find": "nowhere in this file", "replace": "x", "reason": "imagined"}
                    ],
                    "slot_schema": {},
                    "verdict": "Reads cleanly.",
                }
            ),
            output_type=LatexIntake,
        ),
    )
    response = await user_client.post(
        "/api/v1/resumes/upload",
        data={"title": "Master"},
        files={"file": ("resume.tex", MASTER.encode(), "application/x-tex")},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "unsupported_latex"
    assert "not in the document" in detail["message"]


async def test_upload_reports_what_it_had_to_change(user_client: AsyncClient) -> None:
    response = await user_client.post(
        "/api/v1/resumes/upload",
        data={"title": "Master"},
        files={"file": ("resume.tex", MASTER.encode(), "application/x-tex")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # This document needed nothing, and saying so is as much a result as a fix.
    assert body["corrections"] == []
    assert body["verdict"]
    assert body["outline"]["group_count"] == 1
    assert body["outline"]["region_count"] == 1


# --- the review call ---------------------------------------------------------


async def test_one_call_returns_the_score_and_every_patch(review: dict) -> None:
    assert review["match_score"] == 62
    assert [gap["keyword"] for gap in review["missing_keywords"]] == ["Rust"]
    assert {p["slot_id"] for p in review["patches"]} == {"g1", "r1"}
    # Everything starts undecided; that is what gates the output.
    assert all(p["status"] == "pending" for p in review["patches"])
    assert review["pending_count"] == 2


async def test_a_patch_carries_the_text_it_would_replace(review: dict) -> None:
    group = next(p for p in review["patches"] if p["slot_id"] == "g1")
    assert group["original_items"] == [
        "Built a data pipeline in Python.",
        "Ran the on-call rotation.",
    ]
    assert group["section_heading"] == "Experience"
    assert group["reason"]


async def test_a_review_leaves_its_verdict_in_the_score_cache(
    user_client: AsyncClient, review: dict
) -> None:
    """A review already scored the document, so the screen gets it for free.

    Without this the obvious flow — review a master, then look at what it scores
    — would spend two model calls to answer one question, and the two answers
    could disagree.
    """
    scores = await user_client.get(f"/api/v1/resumes/{review['source_resume_id']}/scores")

    assert scores.status_code == 200, scores.text
    assert [row["match_score"] for row in scores.json()] == [62]
    assert scores.json()[0]["job_profile_id"] == review["job_profile_id"]
    assert scores.json()[0]["stale"] is False


async def test_a_tailored_version_can_be_reviewed_again(
    user_client: AsyncClient, review: dict
) -> None:
    """Improving a tailored resume is the same call, aimed at the version.

    The point of the whole feature: a version has an ATS score of its own, and
    the way to raise it is to review the version rather than its master.
    """
    child_id = await _finalize(user_client, review)

    second = await user_client.post(
        f"/api/v1/resumes/{child_id}/reviews", json={"job_profile_id": review["job_profile_id"]}
    )
    assert second.status_code == 201, second.text
    # The round is against the version, not the document it came from.
    assert second.json()["source_resume_id"] == child_id
    assert second.json()["match_score"] == 62

    # And it shows up on the version's own history, not the master's.
    on_child = await user_client.get(f"/api/v1/resumes/{child_id}/reviews")
    on_master = await user_client.get(
        f"/api/v1/resumes/{review['source_resume_id']}/reviews"
    )
    assert [row["id"] for row in on_child.json()] == [second.json()["id"]]
    assert [row["id"] for row in on_master.json()] == [review["id"]]


async def test_improving_a_version_produces_a_sibling_not_a_grandchild(
    user_client: AsyncClient, review: dict
) -> None:
    """The tree stays one level deep however many rounds it takes.

    A grandchild would break `crud.delete_resume`, which only reaches one
    generation down, and would leave a version whose template provenance runs
    through a document nobody is looking at.
    """
    master_id = review["source_resume_id"]
    first_id = await _finalize(user_client, review)

    second = (
        await user_client.post(
            f"/api/v1/resumes/{first_id}/reviews",
            json={"job_profile_id": review["job_profile_id"]},
        )
    ).json()
    second_id = await _finalize(user_client, second)

    grandchild = (await user_client.get(f"/api/v1/resumes/{second_id}")).json()
    assert grandchild["master_resume_id"] == master_id

    versions = await user_client.get(f"/api/v1/resumes/{master_id}/versions")
    assert {v["id"] for v in versions.json()} == {first_id, second_id}
    # Both were tailored for the same role, so the default labels have to differ
    # or the version list is two identical lines.
    labels = {v["version_label"] for v in versions.json()}
    assert labels == {"Tailored for Backend Engineer", "Tailored for Backend Engineer v2"}


    # Siblings rather than grandchildren is also what keeps `crud.delete_resume`
    # correct: it reaches exactly one generation down.
    assert (await user_client.delete(f"/api/v1/resumes/{master_id}")).status_code == 204
    assert (await user_client.get(f"/api/v1/resumes/{second_id}")).status_code == 404


# --- resolving ---------------------------------------------------------------


async def test_accepting_and_rejecting_costs_nothing(
    user_client: AsyncClient, review: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If a decision reached a model this would raise; it must not.
    def explode() -> None:
        raise AssertionError("resolving a patch must not call the model")

    monkeypatch.setattr("app.ai.review.get_review_agent", explode)
    monkeypatch.setattr("app.ai.patch_revision.get_revision_agent", explode)

    first, second = review["patches"]
    accepted = await user_client.patch(
        f"/api/v1/reviews/{review['id']}/patches/{first['id']}", json={"action": "accept"}
    )
    rejected = await user_client.patch(
        f"/api/v1/reviews/{review['id']}/patches/{second['id']}", json={"action": "reject"}
    )

    assert accepted.json()["status"] == "accepted"
    assert rejected.json()["status"] == "rejected"


async def test_a_decision_can_be_changed(user_client: AsyncClient, review: dict) -> None:
    patch_id = review["patches"][0]["id"]
    url = f"/api/v1/reviews/{review['id']}/patches/{patch_id}"

    await user_client.patch(url, json={"action": "accept"})
    flipped = await user_client.patch(url, json={"action": "reject"})
    assert flipped.json()["status"] == "rejected"


async def test_feedback_revises_only_that_patch(user_client: AsyncClient, review: dict) -> None:
    target, other = review["patches"]
    response = await user_client.post(
        f"/api/v1/reviews/{review['id']}/patches/{target['id']}/feedback",
        json={"feedback": "Too long. Say it in half the words."},
    )

    assert response.status_code == 200, response.text
    revised = response.json()
    assert revised["proposed_items"] != target["proposed_items"]
    assert revised["revision_count"] == 1
    # A revision is a new proposal, so it comes back undecided.
    assert revised["status"] == "pending"
    assert revised["feedback"] == "Too long. Say it in half the words."

    untouched = await user_client.get(f"/api/v1/reviews/{review['id']}")
    sibling = next(p for p in untouched.json()["patches"] if p["id"] == other["id"])
    assert sibling["proposed_items"] == other["proposed_items"]
    assert sibling["revision_count"] == 0


async def test_revert_restores_the_first_proposal(
    user_client: AsyncClient, review: dict
) -> None:
    patch = review["patches"][0]
    await user_client.post(
        f"/api/v1/reviews/{review['id']}/patches/{patch['id']}/feedback",
        json={"feedback": "Shorter please."},
    )
    reverted = await user_client.post(
        f"/api/v1/reviews/{review['id']}/patches/{patch['id']}/revert"
    )

    assert reverted.status_code == 200, reverted.text
    assert reverted.json()["proposed_items"] == patch["proposed_items"]
    assert reverted.json()["feedback"] is None


# --- the gate ----------------------------------------------------------------


@pytest.mark.parametrize("resolved", [0, 1])
async def test_nothing_renders_while_a_patch_is_pending(
    user_client: AsyncClient, review: dict, resolved: int
) -> None:
    for patch in review["patches"][:resolved]:
        await user_client.patch(
            f"/api/v1/reviews/{review['id']}/patches/{patch['id']}", json={"action": "accept"}
        )

    preview = await user_client.get(f"/api/v1/reviews/{review['id']}/preview?output=tex")
    finalize = await user_client.post(f"/api/v1/reviews/{review['id']}/finalize", json={})

    assert preview.status_code == 409
    assert finalize.status_code == 409
    assert "decision" in finalize.json()["detail"]


async def test_preview_renders_once_everything_is_resolved(
    user_client: AsyncClient, review: dict
) -> None:
    await _resolve_all(user_client, review)

    tex = await user_client.get(f"/api/v1/reviews/{review['id']}/preview?output=tex")
    assert tex.status_code == 200, tex.text
    assert r"40k events/sec" in tex.text

    pdf = await user_client.get(f"/api/v1/reviews/{review['id']}/preview?output=pdf")
    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b"%PDF")

    # Preview keeps nothing: the master is still the only resume there is.
    listed = await user_client.get("/api/v1/resumes")
    assert len(listed.json()) == 1


# --- finalizing --------------------------------------------------------------


async def test_finalize_applies_accepted_patches_and_leaves_the_rest(
    user_client: AsyncClient, review: dict
) -> None:
    group = next(p for p in review["patches"] if p["slot_id"] == "g1")
    region = next(p for p in review["patches"] if p["slot_id"] == "r1")
    await user_client.patch(
        f"/api/v1/reviews/{review['id']}/patches/{group['id']}", json={"action": "accept"}
    )
    await user_client.patch(
        f"/api/v1/reviews/{review['id']}/patches/{region['id']}", json={"action": "reject"}
    )

    response = await user_client.post(f"/api/v1/reviews/{review['id']}/finalize", json={})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["accepted_count"] == 1
    assert body["rejected_count"] == 1

    child = await user_client.get(f"/api/v1/resumes/{body['child_resume_id']}")
    content = child.json()["content"]
    assert "40k events/sec" in content  # the accepted patch landed
    assert r"\textbf{Languages}: Python, Go" in content  # the rejected slot is untouched
    # And the template around them is the master's own bytes.
    assert content.split(r"\begin{document}")[0] == MASTER.split(r"\begin{document}")[0]


async def test_the_child_hangs_off_the_master_and_inherits_its_engine(
    user_client: AsyncClient, review: dict
) -> None:
    await _resolve_all(user_client, review)
    finalized = await user_client.post(
        f"/api/v1/reviews/{review['id']}/finalize", json={"version_label": "For Acme"}
    )
    child = (await user_client.get(f"/api/v1/resumes/{finalized.json()['child_resume_id']}")).json()

    assert child["master_resume_id"] == review["source_resume_id"]
    assert child["version_label"] == "For Acme"

    versions = await user_client.get(f"/api/v1/resumes/{review['source_resume_id']}/versions")
    assert [v["id"] for v in versions.json()] == [child["id"]]


async def test_a_finalized_review_is_a_record_not_a_workspace(
    user_client: AsyncClient, review: dict
) -> None:
    await _resolve_all(user_client, review)
    await user_client.post(f"/api/v1/reviews/{review['id']}/finalize", json={})

    again = await user_client.post(f"/api/v1/reviews/{review['id']}/finalize", json={})
    decision = await user_client.patch(
        f"/api/v1/reviews/{review['id']}/patches/{review['patches'][0]['id']}",
        json={"action": "reject"},
    )

    assert again.status_code == 409
    assert decision.status_code == 409


async def test_a_master_that_changed_under_the_review_refuses_to_finalize(
    user_client: AsyncClient, review: dict
) -> None:
    """The whole reason `base_hashes` is stored.

    Splicing happens at finalize, potentially long after the patches were
    written. If the master's slots have moved on, the ids still resolve — to
    different text — and the splice would silently land in the wrong place.
    """
    await _resolve_all(user_client, review)

    async with session_maker() as session:
        master = (
            await session.exec(
                select(Resume).where(Resume.id == review["source_resume_id"])
            )
        ).one()
        master.content = MASTER.replace(
            "Ran the on-call rotation.", "Ran the on-call rotation for six teams."
        )
        session.add(master)
        await session.commit()

    response = await user_client.post(f"/api/v1/reviews/{review['id']}/finalize", json={})
    assert response.status_code == 409
    assert "new review" in response.json()["detail"]


# --- scope -------------------------------------------------------------------


async def test_another_users_review_does_not_exist(
    user_client: AsyncClient, other_client: AsyncClient, review: dict
) -> None:
    patch_id = review["patches"][0]["id"]
    review_id = review["id"]

    assert (await other_client.get(f"/api/v1/reviews/{review_id}")).status_code == 404
    assert (
        await other_client.patch(
            f"/api/v1/reviews/{review_id}/patches/{patch_id}", json={"action": "accept"}
        )
    ).status_code == 404
    assert (
        await other_client.post(f"/api/v1/reviews/{review_id}/finalize", json={})
    ).status_code == 404
    assert (
        await other_client.get(f"/api/v1/reviews/{review_id}/preview")
    ).status_code == 404


async def test_deleting_a_master_takes_its_reviews_and_children(
    user_client: AsyncClient, review: dict
) -> None:
    await _resolve_all(user_client, review)
    finalized = await user_client.post(f"/api/v1/reviews/{review['id']}/finalize", json={})
    child_id = finalized.json()["child_resume_id"]

    deleted = await user_client.delete(f"/api/v1/resumes/{review['source_resume_id']}")
    assert deleted.status_code == 204

    assert (await user_client.get(f"/api/v1/resumes/{child_id}")).status_code == 404
    assert (await user_client.get(f"/api/v1/reviews/{review['id']}")).status_code == 404
