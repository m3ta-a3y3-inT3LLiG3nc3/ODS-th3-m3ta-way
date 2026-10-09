import hashlib
import hmac

import httpx


def test_health_and_platform_inventory(gateway):
    _, client, _ = gateway

    assert client.get("/health").json() == {"status": "ok"}
    response = client.get("/api/platforms")

    assert response.status_code == 200
    body = response.json()
    assert {entry["id"] for entry in body["platforms"]} == {
        "qb", "hermes", "plane", "open-notebook", "nimbalyst",
        "colanode", "hynote", "raycast", "brainoutside",
    }
    assert next(item for item in body["platforms"] if item["id"] == "plane")["configured"]
    assert body["external_writes_enabled"] is False


def test_ownership_and_classification_policies(gateway):
    _, client, _ = gateway

    body = client.get("/api/ownership").json()

    assert body["field_authority"]["fields"]["task.status"]["authority"] == "plane"
    assert body["classification"]["default_classification"] == "internal"
    assert body["external_writes_enabled"] is False


def test_readiness_requires_operator_configuration(gateway, monkeypatch):
    _, client, _ = gateway
    monkeypatch.delenv("ODS_PLANE_BASE_URL")
    monkeypatch.delenv("ODS_PLANE_WORKSPACE_SLUG")
    monkeypatch.setenv("ODS_PLANE_API_KEY_FILE", "/not/a/secret/file")

    response = client.get("/api/readiness")

    assert response.status_code == 200
    assert response.json()["status"] == "not_configured"
    assert response.json()["external_writes_enabled"] is False


def test_readiness_rejects_malformed_plane_url(gateway, monkeypatch):
    _, client, _ = gateway
    monkeypatch.setenv("ODS_PLANE_BASE_URL", "https://[invalid")

    response = client.get("/api/readiness")

    assert response.status_code == 200
    assert response.json()["status"] == "not_configured"
    assert "valid ODS_PLANE_BASE_URL" in response.json()["missing"]


def test_validate_event_and_reject_invalid_schema(gateway):
    _, client, _ = gateway
    payload = {
        "id": "event-1",
        "type": "task.updated",
        "source": "plane",
        "occurred_at": "2026-10-09T02:00:00Z",
        "object": {
            "platform": "plane",
            "object_type": "issue",
            "external_id": "123",
        },
        "classification": "internal",
        "payload": {"title": "A task"},
    }

    accepted = client.post(
        "/api/events/validate", json={"schema": "event", "payload": payload}
    )
    rejected = client.post(
        "/api/events/validate",
        json={"schema": "object-reference", "payload": {"platform": "plane"}},
    )

    assert accepted.status_code == 200
    assert accepted.json()["valid"] is True
    assert accepted.json()["delivered"] is False
    assert rejected.json()["valid"] is False


def test_validate_sync_result_uses_shared_object_reference(gateway):
    _, client, _ = gateway
    reference = {
        "platform": "plane",
        "object_type": "issue",
        "external_id": "123",
    }
    response = client.post(
        "/api/events/validate",
        json={
            "schema": "sync-result",
            "payload": {
                "status": "pending",
                "source": reference,
                "target": reference,
                "external_writes_enabled": False,
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_unsupported_event_schema_is_rejected(gateway):
    _, client, _ = gateway

    response = client.post(
        "/api/events/validate", json={"schema": "unknown", "payload": {}}
    )

    assert response.status_code == 400


def test_plane_probes_use_get_and_api_key_header(gateway, monkeypatch):
    module, client, _ = gateway
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/users/me/"):
            return httpx.Response(200, json={"id": "user-1"})
        if request.url.path.endswith("/workspaces/"):
            return httpx.Response(200, json={"results": [{"slug": "workspace"}]})
        if request.url.path.endswith("/projects/"):
            return httpx.Response(200, json={"results": [{"id": "project-1"}]})
        return httpx.Response(404)

    original = httpx.AsyncClient

    def create_client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(**kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", create_client)

    response = client.get("/api/plane/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["project_count"] == 1
    assert [request.method for request in seen] == ["GET", "GET", "GET"]
    assert all(request.headers["X-API-Key"] == "test-plane-key" for request in seen)


def test_plane_errors_are_sanitized(gateway, monkeypatch):
    module, client, _ = gateway
    original = httpx.AsyncClient

    def create_client(**kwargs):
        return original(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(401, text="test-plane-key upstream secret")
            ),
            **kwargs,
        )

    monkeypatch.setattr(module.httpx, "AsyncClient", create_client)

    response = client.get("/api/plane/me")

    assert response.status_code == 503
    assert response.json() == {"detail": "Plane is unavailable"}
    assert "test-plane-key" not in response.text
    assert "upstream secret" not in response.text


def test_readiness_runs_live_plane_probe(gateway, monkeypatch):
    module, client, _ = gateway
    original = httpx.AsyncClient

    def handler(request):
        if request.url.path.endswith("/users/me/"):
            return httpx.Response(200, json={"id": "user-1"})
        if request.url.path.endswith("/workspaces/"):
            return httpx.Response(200, json=[{"slug": "workspace"}])
        if request.url.path.endswith("/projects/"):
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    def create_client(**kwargs):
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", create_client)

    response = client.get("/api/readiness")

    assert response.json()["status"] == "ready"
    assert response.json()["plane"]["workspace_accessible"] is True
    assert response.json()["external_writes_enabled"] is False


def test_plane_hmac_signature_verification(gateway):
    module, _, _ = gateway
    payload = b'{"event":"task.updated"}'
    signature = hmac.new(b"hook-secret", payload, hashlib.sha256).hexdigest()

    assert module.verify_plane_signature(payload, f"sha256={signature}", "hook-secret")
    assert not module.verify_plane_signature(payload, signature, "wrong-secret")


def test_capabilities_keep_delivery_ingestion_and_writes_disabled(gateway):
    _, client, _ = gateway

    response = client.get("/api/capabilities")

    assert response.json() == {
        "platform_reads": ["plane"],
        "event_delivery_enabled": False,
        "webhook_ingestion_enabled": False,
        "external_writes_enabled": False,
    }
