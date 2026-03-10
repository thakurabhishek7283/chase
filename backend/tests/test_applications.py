from httpx import AsyncClient


async def _create_company(client: AsyncClient) -> str:
    response = await client.post("/api/v1/companies", json={"name": "Acme Corp"})
    assert response.status_code == 201
    return response.json()["id"]


async def _create_job_profile(client: AsyncClient, company_id: str) -> str:
    response = await client.post(
        "/api/v1/job-profiles",
        json={
            "company_id": company_id,
            "position_title": "Backend Engineer",
            "description": "Build APIs",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_user(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/users", json={"full_name": "Test User", "email": "test@example.com"}
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_resume(client: AsyncClient, user_id: str) -> str:
    response = await client.post(
        "/api/v1/resumes",
        json={"user_id": user_id, "title": "Master Resume", "content": "# Resume"},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_company_crud(client: AsyncClient) -> None:
    create_response = await client.post(
        "/api/v1/companies",
        json={"name": "Globex", "industry": "Software", "growth_trajectory": "growing"},
    )
    assert create_response.status_code == 201
    company = create_response.json()
    company_id = company["id"]

    get_response = await client.get(f"/api/v1/companies/{company_id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Globex"
    assert get_response.json()["technologies"] == []

    update_response = await client.patch(
        f"/api/v1/companies/{company_id}", json={"industry": "Fintech"}
    )
    assert update_response.status_code == 200
    assert update_response.json()["industry"] == "Fintech"

    delete_response = await client.delete(f"/api/v1/companies/{company_id}")
    assert delete_response.status_code == 204

    missing_response = await client.get(f"/api/v1/companies/{company_id}")
    assert missing_response.status_code == 404


async def test_application_lifecycle_and_stage_move(client: AsyncClient) -> None:
    company_id = await _create_company(client)
    job_profile_id = await _create_job_profile(client, company_id)
    user_id = await _create_user(client)
    resume_id = await _create_resume(client, user_id)

    create_response = await client.post(
        "/api/v1/applications",
        json={
            "user_id": user_id,
            "company_id": company_id,
            "job_profile_id": job_profile_id,
            "resume_id": resume_id,
        },
    )
    assert create_response.status_code == 201
    application = create_response.json()
    assert application["stage"] == "applied"
    application_id = application["id"]

    list_response = await client.get("/api/v1/applications")
    assert list_response.status_code == 200
    listed = list_response.json()
    assert len(listed) == 1
    assert listed[0]["company"]["name"] == "Acme Corp"
    assert listed[0]["job_profile"]["position_title"] == "Backend Engineer"
    assert listed[0]["resume"]["title"] == "Master Resume"

    stage_response = await client.patch(
        f"/api/v1/applications/{application_id}/stage",
        json={"stage": "interviewing", "board_position": 1},
    )
    assert stage_response.status_code == 200
    moved = stage_response.json()
    assert moved["stage"] == "interviewing"
    assert moved["board_position"] == 1
    assert moved["stage_updated_at"] != application["stage_updated_at"]

    filtered_response = await client.get("/api/v1/applications", params={"stage": "interviewing"})
    assert filtered_response.status_code == 200
    assert len(filtered_response.json()) == 1

    empty_stage_response = await client.get("/api/v1/applications", params={"stage": "applied"})
    assert empty_stage_response.status_code == 200
    assert empty_stage_response.json() == []
