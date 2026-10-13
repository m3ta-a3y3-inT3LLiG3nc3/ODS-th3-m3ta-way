#!/usr/bin/env python3
"""Governed, read-only adapters for MetaHuman OS platform integrations."""

import hashlib
import hmac
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from jsonschema import Draft202012Validator
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parent
PLATFORMS_PATH = ROOT / "config" / "platforms.json"
OWNERSHIP_PATH = ROOT / "config" / "ownership-policy.json"
CLASSIFICATION_PATH = ROOT / "config" / "classification-policy.json"
SCHEMAS_PATH = ROOT / "schemas"
PLANE_TIMEOUT = httpx.Timeout(connect=3.0, read=10.0, write=3.0, pool=3.0)
WORKSPACE_SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}$")

app = FastAPI(title="ODS Integration Gateway", version="1.0.0")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _valid_base_url(base_url: str, allow_insecure_http: bool = False) -> bool:
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
        return bool(
            (parsed.scheme == "https" or (allow_insecure_http and parsed.scheme == "http"))
            and parsed.hostname
            and (port is None or 1 <= port <= 65535)
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


def _has_plane_api_key(key_file: Path) -> bool:
    try:
        api_key = key_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return False
    return bool(api_key and "\n" not in api_key and "\r" not in api_key)


def _plane_configuration() -> tuple[str, str, Path] | None:
    base_url = os.getenv("ODS_PLANE_BASE_URL", "").strip().rstrip("/")
    workspace_slug = os.getenv("ODS_PLANE_WORKSPACE_SLUG", "").strip()
    key_file = Path(os.getenv("ODS_PLANE_API_KEY_FILE", "/run/secrets/plane_api_key"))
    allow_insecure_http = os.getenv("ODS_PLANE_ALLOW_INSECURE_HTTP", "").lower() == "true"
    if not (base_url and workspace_slug and _has_plane_api_key(key_file)):
        return None
    if (
        not _valid_base_url(base_url, allow_insecure_http)
        or not WORKSPACE_SLUG_RE.fullmatch(workspace_slug)
    ):
        return None
    return base_url, workspace_slug, key_file


class PlaneClient:
    """Minimal Plane client. The only outbound verb is GET."""

    def __init__(self, base_url: str, api_key_file: Path):
        self.base_url = base_url.rstrip("/")
        self.api_key_file = api_key_file

    async def get(self, path: str):
        try:
            api_key = self.api_key_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise PlaneUnavailable from exc
        if not api_key or "\n" in api_key or "\r" in api_key:
            raise PlaneUnavailable
        try:
            async with httpx.AsyncClient(
                timeout=PLANE_TIMEOUT,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/{path.lstrip('/')}",
                    headers={"X-API-Key": api_key, "Accept": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PlaneUnavailable from exc
        if not isinstance(payload, (dict, list)):
            raise PlaneUnavailable
        return payload

    async def current_user(self):
        return await self.get("users/me/")

    async def workspaces(self):
        return await self.get("workspaces/")

    async def projects(self, workspace_slug: str):
        return await self.get(f"workspaces/{workspace_slug}/projects/")

    async def health(self, workspace_slug: str):
        await self.current_user()
        workspaces = await self.workspaces()
        projects = await self.projects(workspace_slug)
        workspace_entries = (
            workspaces.get("results", [])
            if isinstance(workspaces, dict)
            else workspaces
        )
        workspace_found = any(
            isinstance(item, dict) and item.get("slug") == workspace_slug
            for item in workspace_entries
        )
        if not workspace_found:
            raise PlaneUnavailable
        project_entries = (
            projects.get("results", []) if isinstance(projects, dict) else projects
        )
        return {
            "status": "ok",
            "workspace": workspace_slug,
            "workspace_accessible": True,
            "project_count": len(project_entries) if isinstance(project_entries, list) else 0,
        }


class PlaneUnavailable(Exception):
    pass


def verify_plane_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify Plane's hexadecimal SHA-256 HMAC without accepting partial matches."""
    if signature.startswith("sha256="):
        signature = signature[7:]
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _schema_registry() -> Registry:
    resources = []
    for path in SCHEMAS_PATH.glob("*.schema.json"):
        schema = _read_json(path)
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def _plane_client_or_503() -> tuple[PlaneClient, str]:
    configuration = _plane_configuration()
    if configuration is None:
        raise HTTPException(status_code=503, detail="Plane adapter is not configured")
    base_url, workspace_slug, key_file = configuration
    return PlaneClient(base_url, key_file), workspace_slug


def _as_http_error(exc: PlaneUnavailable) -> HTTPException:
    return HTTPException(status_code=503, detail="Plane is unavailable")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/platforms")
async def platforms():
    entries = _read_json(PLATFORMS_PATH)
    plane_configured = _plane_configuration() is not None
    for entry in entries:
        entry["configured"] = plane_configured if entry["id"] == "plane" else False
    return {"platforms": entries, "external_writes_enabled": False}


@app.get("/api/ownership")
async def ownership():
    return {
        "field_authority": _read_json(OWNERSHIP_PATH),
        "classification": _read_json(CLASSIFICATION_PATH),
        "external_writes_enabled": False,
    }


@app.get("/api/readiness")
async def readiness():
    missing = []
    base_url = os.getenv("ODS_PLANE_BASE_URL", "").strip()
    workspace_slug = os.getenv("ODS_PLANE_WORKSPACE_SLUG", "").strip()
    key_file = Path(os.getenv("ODS_PLANE_API_KEY_FILE", "/run/secrets/plane_api_key"))
    if not base_url:
        missing.append("ODS_PLANE_BASE_URL")
    elif not _valid_base_url(
        base_url,
        os.getenv("ODS_PLANE_ALLOW_INSECURE_HTTP", "").lower() == "true",
    ):
        missing.append("HTTPS ODS_PLANE_BASE_URL (or explicit HTTP opt-in)")
    if not workspace_slug:
        missing.append("ODS_PLANE_WORKSPACE_SLUG")
    elif not WORKSPACE_SLUG_RE.fullmatch(workspace_slug):
        missing.append("valid ODS_PLANE_WORKSPACE_SLUG")
    if not _has_plane_api_key(key_file):
        missing.append("Plane API key secret file")
    configuration = _plane_configuration()
    if configuration is None:
        return {
            "status": "not_configured",
            "missing": missing,
            "external_writes_enabled": False,
        }
    client, workspace_slug = _plane_client_or_503()
    try:
        plane = await client.health(workspace_slug)
    except PlaneUnavailable as exc:
        return {
            "status": "not_ready",
            "platform": "plane",
            "reason": "health_probe_failed",
            "external_writes_enabled": False,
        }
    return {
        "status": "ready",
        "platform": "plane",
        "plane": plane,
        "external_writes_enabled": False,
    }


@app.post("/api/events/validate")
async def validate_event(request: Request):
    try:
        body = await request.json()
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    schema_name = body.get("schema") if isinstance(body, dict) else None
    payload = body.get("payload") if isinstance(body, dict) else None
    if not isinstance(schema_name, str) or schema_name not in {
        "event", "object-reference", "sync-result"
    }:
        raise HTTPException(status_code=400, detail="Unsupported schema")
    schema = _read_json(SCHEMAS_PATH / f"{schema_name}.schema.json")
    errors = sorted(
        Draft202012Validator(
            schema,
            registry=_schema_registry(),
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        ).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    return {
        "valid": not errors,
        "schema": schema_name,
        "errors": [
            {
                "path": "/" + "/".join(str(part) for part in error.absolute_path),
                "message": error.message,
            }
            for error in errors
        ],
        "delivered": False,
        "external_writes_enabled": False,
    }


@app.get("/api/plane/me")
async def plane_current_user():
    client, _ = _plane_client_or_503()
    try:
        return await client.current_user()
    except PlaneUnavailable as exc:
        raise _as_http_error(exc) from exc


@app.get("/api/plane/workspaces")
async def plane_workspaces():
    client, _ = _plane_client_or_503()
    try:
        return await client.workspaces()
    except PlaneUnavailable as exc:
        raise _as_http_error(exc) from exc


@app.get("/api/plane/projects")
async def plane_projects():
    client, workspace_slug = _plane_client_or_503()
    try:
        return await client.projects(workspace_slug)
    except PlaneUnavailable as exc:
        raise _as_http_error(exc) from exc


@app.get("/api/plane/health")
async def plane_health():
    client, workspace_slug = _plane_client_or_503()
    try:
        return await client.health(workspace_slug)
    except PlaneUnavailable as exc:
        raise _as_http_error(exc) from exc


@app.get("/api/capabilities")
async def capabilities():
    return {
        "platform_reads": ["plane"],
        "event_delivery_enabled": False,
        "webhook_ingestion_enabled": False,
        "external_writes_enabled": False,
    }
