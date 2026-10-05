"""Probes an orchestrator (Docker, Kubernetes, a load balancer) polls."""

from httpx import AsyncClient


async def test_liveness_needs_no_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_checks_the_database(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
