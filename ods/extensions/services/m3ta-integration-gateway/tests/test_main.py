from uuid import uuid4

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_is_safe_by_default():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["platforms"] == 9
    assert body["writes_enabled"] is False


def test_readiness_lists_all_adapters_with_writes_disabled():
    response = client.get("/v1/readiness")
    assert response.status_code == 200
    adapters = response.json()["adapters"]
    assert "plane" in adapters
    assert "raycast" in adapters
    assert all(item["write_enabled"] is False for item in adapters.values())


def test_valid_event_is_validated_but_not_delivered():
    response = client.post(
        "/v1/events/validate",
        json={
            "event_id": str(uuid4()),
            "event_type": "work_item.updated",
            "schema_version": "1.0",
            "occurred_at": "2026-09-06T00:00:00Z",
            "origin": "plane",
            "actor": {"type": "agent", "id": "qb"},
            "object": {
                "meta_object_id": str(uuid4()),
                "native_id": "M3TA-1",
                "native_url": "https://plane.example/m3ta-1",
                "type": "work_item"
            },
            "correlation_id": str(uuid4()),
            "payload": {"state": "started"},
            "classification": "internal"
        },
    )
    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert response.json()["accepted_for_delivery"] is False


def test_unknown_origin_is_rejected():
    response = client.post(
        "/v1/events/validate",
        json={
            "event_id": str(uuid4()),
            "event_type": "work_item.updated",
            "occurred_at": "2026-09-06T00:00:00Z",
            "origin": "unknown",
            "actor": {"type": "system", "id": "test"},
            "object": {
                "meta_object_id": str(uuid4()),
                "native_id": "1",
                "type": "work_item"
            },
            "correlation_id": str(uuid4()),
            "payload": {}
        },
    )
    assert response.status_code == 422


def test_plane_health_reports_missing_configuration(monkeypatch):
    monkeypatch.delenv("PLANE_WORKSPACE_SLUG", raising=False)
    monkeypatch.delenv("PLANE_API_KEY", raising=False)
    response = client.get("/v1/adapters/plane/health")
    assert response.status_code == 200
    assert response.json()["status"] == "unconfigured"
    assert "PLANE_WORKSPACE_SLUG" in response.json()["missing"]
    assert response.json()["write_enabled"] is False
