import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


GATEWAY_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GATEWAY_DIR))


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    key_file = tmp_path / "plane-api-key"
    key_file.write_text("test-plane-key", encoding="utf-8")
    monkeypatch.setenv("ODS_PLANE_BASE_URL", "https://plane.example.test")
    monkeypatch.setenv("ODS_PLANE_WORKSPACE_SLUG", "workspace")
    monkeypatch.setenv("ODS_PLANE_API_KEY_FILE", str(key_file))
    monkeypatch.delenv("ODS_PLANE_ALLOW_INSECURE_HTTP", raising=False)
    if "main" in sys.modules:
        del sys.modules["main"]
    module = importlib.import_module("main")
    with TestClient(module.app) as client:
        yield module, client, key_file
