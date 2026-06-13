import pytest
from httpx import AsyncClient

from app.services.latex import ENGINE_NAMES, engine_available

MASTER = r"""\documentclass{article}
\usepackage{enumitem}
\begin{document}
\section{Skills}
% jarvis:begin skills
\textbf{Languages}: Python, Go
% jarvis:end
\section{Experience}
\textbf{Engineer}, Acme \hfill 2021 -- Present
\begin{itemize}
    \item Built a data pipeline in Python.
    \item Ran the on-call rotation.
\end{itemize}
\section{Education}
\textbf{B.Tech}, State University \hfill 2018
\end{document}
"""


async def _create_user(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/users", json={"full_name": "Ada Lovelace", "email": "ada@example.com"}
    )
    assert response.status_code == 201
    return response.json()["id"]


FONTSPEC_MASTER = MASTER.replace(
    r"\usepackage{enumitem}", "\\usepackage{enumitem}\n\\usepackage{fontspec}"
)


async def _upload_master(
    client: AsyncClient, source: str = MASTER, engine: str | None = None
) -> dict:
    user_id = await _create_user(client)
    data = {"user_id": user_id, "title": "Ada Master"}
    if engine is not None:
        data["latex_engine"] = engine
    response = await client.post(
        "/api/v1/latex/resumes/upload",
        data=data,
        files={"file": ("master.tex", source.encode("utf-8"), "application/x-tex")},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_status_reports_engine_availability(client: AsyncClient) -> None:
    response = await client.get("/api/v1/latex/status")
    assert response.status_code == 200
    body = response.json()

    assert body["available"] is engine_available()
    # When the engine is missing the response must say how to install it,
    # not just report False.
    assert body["available"] or "install" in body["detail"].lower()


async def test_upload_returns_the_editable_outline(client: AsyncClient) -> None:
    body = await _upload_master(client)
    outline = body["outline"]

    assert outline["group_count"] == 1
    assert outline["bullet_count"] == 2
    assert outline["region_count"] == 1
    assert "Education" in outline["frozen_sections"]

    experience = next(s for s in outline["sections"] if s["heading"] == "Experience")
    assert [b["latex"] for b in experience["groups"][0]["bullets"]] == [
        "Built a data pipeline in Python.",
        "Ran the on-call rotation.",
    ]


async def test_upload_rejects_an_untailorable_document(client: AsyncClient) -> None:
    user_id = await _create_user(client)
    source = r"\documentclass{article}\begin{document}Just prose.\end{document}"
    response = await client.post(
        "/api/v1/latex/resumes/upload",
        data={"user_id": user_id, "title": "Bad"},
        files={"file": ("bad.tex", source.encode("utf-8"), "application/x-tex")},
    )
    # Rejected at upload time, while the author can still fix it.
    assert response.status_code == 422
    assert "editable content" in response.json()["detail"]


async def test_upload_rejects_non_utf8(client: AsyncClient) -> None:
    user_id = await _create_user(client)
    response = await client.post(
        "/api/v1/latex/resumes/upload",
        data={"user_id": user_id, "title": "Latin-1"},
        files={"file": ("bad.tex", b"\\begin{document}\xff\\end{document}", "application/x-tex")},
    )
    assert response.status_code == 422
    assert "UTF-8" in response.json()["detail"]


async def test_outline_rejects_a_markdown_resume(client: AsyncClient) -> None:
    user_id = await _create_user(client)
    created = await client.post(
        "/api/v1/resumes",
        json={"user_id": user_id, "title": "Markdown", "content": "# Resume"},
    )
    resume_id = created.json()["id"]

    response = await client.get(f"/api/v1/latex/resumes/{resume_id}/outline")
    assert response.status_code == 409
    assert "not LaTeX" in response.json()["detail"]


async def test_outline_404s_for_a_missing_resume(client: AsyncClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/api/v1/latex/resumes/{missing}/outline")
    assert response.status_code == 404


async def test_render_returns_the_stored_tex(client: AsyncClient) -> None:
    resume_id = (await _upload_master(client))["resume_id"]

    response = await client.get(f"/api/v1/latex/resumes/{resume_id}/render?output=tex")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-tex")
    # Round-trips byte-identically — the stored master is the source of truth.
    assert response.text == MASTER


async def test_preview_applies_a_tailoring_without_calling_the_model(
    client: AsyncClient,
) -> None:
    resume_id = (await _upload_master(client))["resume_id"]

    response = await client.post(
        f"/api/v1/latex/resumes/{resume_id}/preview?output=tex",
        json={
            "tailoring": {
                "groups": [{"group_id": "g1", "items": [r"Built a data pipeline in \textbf{Rust}."]}],
                "regions": [{"region_id": "r1", "latex": r"\textbf{Languages}: Rust, Python"}],
                "emphasis": ["Rust"],
                "deemphasis": [],
                "notes": "Systems-first.",
            }
        },
    )

    assert response.status_code == 200
    tailored = response.text
    assert r"\textbf{Rust}" in tailored
    assert r"\textbf{Languages}: Rust, Python" in tailored
    assert "Ran the on-call rotation" not in tailored
    # Frozen facts and preamble are untouched.
    assert r"\usepackage{enumitem}" in tailored
    assert r"\textbf{B.Tech}, State University \hfill 2018" in tailored


async def test_preview_rejects_an_unknown_slot_id(client: AsyncClient) -> None:
    resume_id = (await _upload_master(client))["resume_id"]

    response = await client.post(
        f"/api/v1/latex/resumes/{resume_id}/preview?output=tex",
        json={
            "tailoring": {
                "groups": [{"group_id": "g99", "items": ["nope"]}],
                "regions": [],
                "emphasis": [],
                "deemphasis": [],
                "notes": "",
            }
        },
    )
    assert response.status_code == 422
    assert "Unknown bullet group" in response.json()["detail"]


async def test_tailor_requires_an_api_key(client: AsyncClient, monkeypatch) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.delenv(settings.llm_env_var, raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    monkeypatch.setattr(settings, "google_api_key", None)

    resume_id = (await _upload_master(client))["resume_id"]
    response = await client.post(
        "/api/v1/latex/tailor",
        json={
            "resume_id": resume_id,
            "job_profile_id": "00000000-0000-0000-0000-000000000000",
        },
    )

    assert response.status_code == 503
    # The message names the *active* provider's variable, so switching
    # LLM_PROVIDER doesn't send users hunting for the wrong key.
    assert settings.llm_env_var in response.json()["detail"]
    assert settings.llm_provider in response.json()["detail"]


async def test_status_lists_every_allowlisted_engine(client: AsyncClient) -> None:
    body = (await client.get("/api/v1/latex/status")).json()

    assert set(body["engines"]) == set(ENGINE_NAMES)
    assert all(isinstance(v, bool) for v in body["engines"].values())


async def test_upload_records_an_explicit_engine(client: AsyncClient) -> None:
    body = await _upload_master(client, engine="lualatex")
    assert body["outline"]["latex_engine"] == "lualatex"


async def test_upload_rejects_an_engine_off_the_allowlist(client: AsyncClient) -> None:
    user_id = await _create_user(client)
    response = await client.post(
        "/api/v1/latex/resumes/upload",
        data={"user_id": user_id, "title": "Evil", "latex_engine": "tectonic; whoami"},
        files={"file": ("master.tex", MASTER.encode("utf-8"), "application/x-tex")},
    )
    assert response.status_code == 422
    assert "not a supported LaTeX engine" in response.json()["detail"]


async def test_upload_autodetects_a_unicode_engine_for_fontspec(client: AsyncClient) -> None:
    from app.core.config import get_settings

    outline = (await _upload_master(client, FONTSPEC_MASTER))["outline"]
    stored = outline["latex_engine"]

    # Detection only upgrades: with a Unicode-capable default nothing changes,
    # but a pdflatex default must be lifted to xelatex.
    if get_settings().latex_engine_path == "pdflatex":
        assert stored == "xelatex"
    assert outline["engine_warning"] is None


async def test_outline_warns_when_the_engine_cannot_build_the_document(
    client: AsyncClient,
) -> None:
    resume_id = (await _upload_master(client, FONTSPEC_MASTER, engine="pdflatex"))["resume_id"]

    outline = (await client.get(f"/api/v1/latex/resumes/{resume_id}/outline")).json()
    assert outline["latex_engine"] == "pdflatex"
    assert "fontspec" in outline["engine_warning"]


async def test_render_refuses_a_known_incompatible_pairing(client: AsyncClient) -> None:
    # Better a clear 422 than a hundred lines of TeX log.
    resume_id = (await _upload_master(client, FONTSPEC_MASTER, engine="pdflatex"))["resume_id"]

    response = await client.get(f"/api/v1/latex/resumes/{resume_id}/render?output=pdf")
    assert response.status_code == 422
    assert "fontspec" in response.json()["detail"]


async def test_engine_can_be_changed_and_reset(client: AsyncClient) -> None:
    resume_id = (await _upload_master(client, engine="pdflatex"))["resume_id"]

    changed = await client.patch(
        f"/api/v1/latex/resumes/{resume_id}/engine", json={"latex_engine": "xelatex"}
    )
    assert changed.status_code == 200
    assert changed.json()["latex_engine"] == "xelatex"

    reset = await client.patch(
        f"/api/v1/latex/resumes/{resume_id}/engine", json={"latex_engine": None}
    )
    assert reset.status_code == 200
    # Back to tracking the server default.
    assert reset.json()["latex_engine"] is None


async def test_engine_change_rejects_a_name_off_the_allowlist(client: AsyncClient) -> None:
    resume_id = (await _upload_master(client))["resume_id"]

    response = await client.patch(
        f"/api/v1/latex/resumes/{resume_id}/engine", json={"latex_engine": "/usr/bin/evil"}
    )
    # Rejected by the Pydantic Literal before it reaches the service layer.
    assert response.status_code == 422


@pytest.mark.skipif(not engine_available(), reason="No LaTeX engine installed")
async def test_render_produces_a_pdf(client: AsyncClient) -> None:
    resume_id = (await _upload_master(client))["resume_id"]

    response = await client.get(f"/api/v1/latex/resumes/{resume_id}/render?output=pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
