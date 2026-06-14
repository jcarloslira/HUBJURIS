"""Testes do endpoint de health check."""

from fastapi.testclient import TestClient


def test_health_retorna_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["env"] == "development"
