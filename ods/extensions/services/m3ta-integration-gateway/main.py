"""M3ta Integration Gateway: governed MetaHuman OS platform boundary."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from adapters.plane import PlaneAPIError, PlaneClient, PlaneConfigurationError, PlaneSettings

CONFIG_DIR = Path(os.getenv("M3TA_GATEWAY_CONFIG_DIR", Path(__file__).parent / "config"))


def load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.is_file():
        raise RuntimeError(f"required configuration missing: {path}")
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise RuntimeError(f"configuration must be a mapping: {path}")
    return value


class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["human", "agent", "system"]
    id: str = Field(min_length=1, max_length=200)


class ObjectReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meta_object_id: UUID
    native_id: str = Field(min_length=1, max_length=500)
    native_url: str | None = None
    type: str = Field(min_length=1, max_length=100)


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    event_type: str = Field(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    schema_version: Literal["1.0"] = "1.0"
    occurred_at: datetime
    origin: str = Field(min_length=1, max_length=100)
    actor: Actor
    object: ObjectReference
    correlation_id: UUID
    causation_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    classification: Literal["public", "internal", "confidential", "restricted"] = "internal"


app = FastAPI(
    title="M3ta Integration Gateway",
    version="0.1.0",
    description="Governed integration boundary for QB, Hermes, and MetaHuman OS platforms.",
)


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        platforms = load_yaml("platforms.yaml")
        ownership = load_yaml("ownership.yaml")
        policy = load_yaml("policies.yaml")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "status": "healthy",
        "service": "m3ta-integration-gateway",
        "version": app.version,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "platforms": len(platforms.get("platforms", {})),
        "ownership_rules": len(ownership.get("object_types", {})),
        "writes_enabled": bool(policy.get("defaults", {}).get("writes_enabled", False)),
    }


@app.get("/v1/platforms")
def list_platforms() -> dict[str, Any]:
    return load_yaml("platforms.yaml")


@app.get("/v1/ownership")
def ownership() -> dict[str, Any]:
    return load_yaml("ownership.yaml")


@app.get("/v1/readiness")
def readiness() -> dict[str, Any]:
    platforms = load_yaml("platforms.yaml").get("platforms", {})
    return {
        "ready": all(item.get("mode") != "unclassified" for item in platforms.values()),
        "adapters": {
            key: {
                "mode": item.get("mode"),
                "write_enabled": item.get("write_enabled", False),
                "configuration_required": item.get("configuration_required", []),
            }
            for key, item in platforms.items()
        },
    }


@app.get("/v1/adapters/plane/health")
def plane_health() -> dict[str, Any]:
    settings = PlaneSettings.from_environment()
    missing = settings.missing()
    if missing:
        return {
            "status": "unconfigured",
            "authenticated": False,
            "missing": missing,
            "write_enabled": False,
        }
    try:
        client = PlaneClient(settings)
        try:
            return client.probe()
        finally:
            client.close()
    except (PlaneConfigurationError, PlaneAPIError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/v1/events/validate")
def validate_event(event: EventEnvelope) -> dict[str, Any]:
    platforms = load_yaml("platforms.yaml").get("platforms", {})
    if event.origin not in platforms:
        raise HTTPException(status_code=422, detail=f"unknown event origin: {event.origin}")
    return {
        "valid": True,
        "event_id": str(event.event_id),
        "correlation_id": str(event.correlation_id),
        "accepted_for_delivery": False,
        "reason": "validation-only foundation; adapter delivery is disabled",
    }
