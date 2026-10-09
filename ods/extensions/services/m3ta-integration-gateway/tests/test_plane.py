import hashlib
import hmac

import httpx
import pytest

from adapters.plane import PlaneAPIError, PlaneClient, PlaneConfigurationError, PlaneSettings, verify_webhook_signature


def test_configuration_requires_workspace_and_key():
    settings = PlaneSettings(base_url="https://api.plane.so", workspace_slug="", api_key="")
    with pytest.raises(PlaneConfigurationError):
        PlaneClient(settings)


def test_probe_is_read_only_and_normalized():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("X-API-Key")))
        if request.url.path == "/api/v1/users/me/":
            return httpx.Response(200, json={"id": "user-1", "display_name": "M3ta"})
        if request.url.path == "/api/v1/workspaces/m3ta/projects/":
            return httpx.Response(200, json={"results": [], "count": 0, "total_results": 12})
        return httpx.Response(404)

    client = PlaneClient(
        PlaneSettings("https://api.plane.so", "m3ta", "test-key"),
        transport=httpx.MockTransport(handler),
    )
    try:
        result = client.probe()
    finally:
        client.close()

    assert result["status"] == "healthy"
    assert result["project_count"] == 12
    assert result["write_enabled"] is False
    assert all(method == "GET" for method, _, _ in seen)
    assert all(key == "test-key" for _, _, key in seen)


def test_api_errors_do_not_leak_response_body_or_token():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "secret backend message"})

    client = PlaneClient(
        PlaneSettings("https://api.plane.so", "m3ta", "sensitive-key"),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(PlaneAPIError) as exc:
            client.current_user()
    finally:
        client.close()
    assert "sensitive-key" not in str(exc.value)
    assert "secret backend message" not in str(exc.value)


def test_webhook_signature_verification():
    payload = b'{"event":"issue","action":"created"}'
    signature = hmac.new(b"secret", payload, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(payload, signature, "secret") is True
    assert verify_webhook_signature(payload, "bad", "secret") is False
    assert verify_webhook_signature(payload, signature, "") is False
