import os
import tempfile
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="archive-tests-"))
os.environ["DATA_DIR"] = str(ROOT)
os.environ["AUTH_USERNAME"] = "admin"
os.environ["AUTH_PASSWORD"] = "test-password-please"
os.environ["AUTH_SECRET"] = "test-secret"
os.environ["RETENTION_DAYS"] = "3"
os.environ["MAX_CONCURRENT"] = "2"
os.environ["MAX_FILESIZE_MB"] = "50"
os.environ["MAX_DURATION_SEC"] = "0"
os.environ["COOKIE_SECURE"] = "0"
os.environ["SESSION_DAYS"] = "14"

import pytest
from fastapi.testclient import TestClient

from app.auth import reset_attempts_for_tests
from app.db import init_db, reset_for_tests
from app.downloader import manager
from app.main import app


@pytest.fixture(autouse=True)
def _fresh_state():
    init_db()
    reset_for_tests()
    reset_attempts_for_tests()
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(manager, "submit", lambda job_id: None)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_client(client):
    response = client.post("/api/login", json={"username": "admin", "password": "test-password-please"})
    assert response.status_code == 200, response.text
    return client
