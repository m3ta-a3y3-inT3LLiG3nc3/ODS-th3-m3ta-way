"""Read-only Plane REST adapter and webhook verification helpers."""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Any

import httpx


class PlaneConfigurationError(RuntimeError):
    """Raised when the Plane adapter is missing required runtime settings."""


class PlaneAPIError(RuntimeError):
    """Raised when Plane returns an unsuccessful response."""


@dataclass(frozen=True)
class PlaneSettings:
    base_url: str
    workspace_slug: str
    api_key: str
    webhook_secret: str = ""

    @classmethod
    def from_environment(cls) -> "PlaneSettings":
        return cls(
            base_url=os.getenv("PLANE_BASE_URL", "https://api.plane.so"),
            workspace_slug=os.getenv("PLANE_WORKSPACE_SLUG", ""),
            api_key=os.getenv("PLANE_API_KEY", ""),
            webhook_secret=os.getenv("PLANE_WEBHOOK_SECRET", ""),
        )

    def missing(self) -> list[str]:
        missing = []
        if not self.base_url.strip():
            missing.append("PLANE_BASE_URL")
        if not self.workspace_slug.strip():
            missing.append("PLANE_WORKSPACE_SLUG")
        if not self.api_key.strip():
            missing.append("PLANE_API_KEY")
        return missing


class PlaneClient:
    def __init__(self, settings: PlaneSettings, *, transport: httpx.BaseTransport | None = None, timeout: float = 10.0) -> None:
        missing = settings.missing()
        if missing:
            raise PlaneConfigurationError(f"missing Plane configuration: {', '.join(missing)}")
        self.settings = settings
        self.client = httpx.Client(
            base_url=settings.base_url.rstrip("/"),
            headers={"X-API-Key": settings.api_key, "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self.client.close()

    def _get(self, path: str, **params: Any) -> Any:
        response = self.client.get(path, params=params or None)
        if response.is_error:
            raise PlaneAPIError(f"Plane GET {path} failed with HTTP {response.status_code}")
        return response.json()

    def current_user(self) -> dict[str, Any]:
        value = self._get("/api/v1/users/me/")
        if not isinstance(value, dict):
            raise PlaneAPIError("Plane current-user response is not an object")
        return value

    def list_projects(self, *, per_page: int = 100) -> dict[str, Any]:
        value = self._get(
            f"/api/v1/workspaces/{self.settings.workspace_slug}/projects/",
            per_page=max(1, min(per_page, 100)),
        )
        if isinstance(value, list):
            return {"results": value, "count": len(value), "next_cursor": None}
        if not isinstance(value, dict):
            raise PlaneAPIError("Plane projects response is not a collection")
        return value

    def probe(self) -> dict[str, Any]:
        user = self.current_user()
        projects = self.list_projects(per_page=1)
        return {
            "status": "healthy",
            "authenticated": True,
            "workspace_slug": self.settings.workspace_slug,
            "user_id": user.get("id"),
            "display_name": user.get("display_name"),
            "project_count": projects.get("total_results", projects.get("count", 0)),
            "write_enabled": False,
        }


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    if not payload or not signature or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
