from httpx import AsyncClient


async def test_company_crud(admin_client: AsyncClient) -> None:
    create_response = await admin_client.post(
        "/api/v1/companies",
        json={"name": "Globex", "industry": "Software", "growth_trajectory": "growing"},
    )
    assert create_response.status_code == 201
    company = create_response.json()
    company_id = company["id"]
    # An admin's own submission needs no review, so it is live immediately.
    assert company["status"] == "approved"
    assert company["slug"] == "globex"

    get_response = await admin_client.get(f"/api/v1/companies/{company_id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Globex"

    update_response = await admin_client.patch(
        f"/api/v1/companies/{company_id}", json={"industry": "Fintech"}
    )
    assert update_response.status_code == 200
    assert update_response.json()["industry"] == "Fintech"

    delete_response = await admin_client.delete(f"/api/v1/companies/{company_id}")
    assert delete_response.status_code == 204

    missing_response = await admin_client.get(f"/api/v1/companies/{company_id}")
    assert missing_response.status_code == 404
