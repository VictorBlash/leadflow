"""
Tests for API-key authentication.

Why these matter: the public deployment exposed GET /leads, which returns
names and email addresses, to anyone. Every route except /health and the API
docs must now require the X-API-Key header, and the check must fail closed:
an unset or empty LEADFLOW_API_KEY rejects requests rather than letting them
through. A wrong key and a missing key get the same response, so a caller
cannot tell which one they got wrong.

Run with: pytest
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import database
from database import Base
from main import app, get_db

API_KEY = "test-key-7f3a9c"  # gitleaks:allow

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setenv("LEADFLOW_API_KEY", API_KEY)
    return API_KEY


def test_the_app_never_uses_the_local_database_file():
    # Importing main runs create_all; conftest.py must have redirected it.
    assert str(database.engine.url) == "sqlite://"


def test_listing_leads_without_a_key_is_rejected(client, api_key):
    response = client.get("/leads")
    assert response.status_code == 401


def test_listing_leads_with_a_wrong_key_is_rejected_the_same_way_as_no_key(client, api_key):
    missing = client.get("/leads")
    wrong = client.get("/leads", headers={"X-API-Key": "not-the-key"})

    assert wrong.status_code == 401
    # Identical responses: the caller learns nothing about which check failed.
    assert wrong.json() == missing.json()
    assert wrong.headers.get("www-authenticate") == missing.headers.get("www-authenticate")


def test_listing_leads_with_the_correct_key_succeeds(client, api_key):
    response = client.get("/leads", headers={"X-API-Key": api_key})
    assert response.status_code == 200
    assert response.json() == []


def test_health_needs_no_key(client, api_key):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_an_unset_server_key_rejects_every_request(client):
    # Fail closed: a deploy that forgot LEADFLOW_API_KEY must not be open.
    assert client.get("/leads").status_code == 401
    assert client.get("/leads", headers={"X-API-Key": "anything"}).status_code == 401
    assert client.get("/leads", headers={"X-API-Key": ""}).status_code == 401


def test_an_empty_server_key_does_not_match_an_empty_header(client, monkeypatch):
    # Copying .env.example leaves LEADFLOW_API_KEY= blank. An empty header
    # compared to an empty key would otherwise pass.
    monkeypatch.setenv("LEADFLOW_API_KEY", "")
    assert client.get("/leads", headers={"X-API-Key": ""}).status_code == 401


def test_a_non_ascii_key_is_rejected_not_a_server_error(client, api_key):
    # compare_digest raises TypeError on non-ASCII str; headers arrive latin-1 decoded.
    response = client.get("/leads", headers={"X-API-Key": "clé".encode("latin-1")})
    assert response.status_code == 401


def test_every_route_except_health_requires_a_key(client, api_key):
    # Guards future routes: one added without the key check fails here.
    # Read from the OpenAPI schema, not app.routes, whose structure differs across FastAPI versions.
    paths = app.openapi()["paths"]
    operations = [
        (method.upper(), path)
        for path, item in paths.items() if path != "/health"
        for method in item if method in HTTP_METHODS
    ]
    assert operations, "expected protected routes to exist"
    for method, path in operations:
        response = client.request(method, path)
        assert response.status_code == 401, f"{method} {path} returned {response.status_code}"


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_stay_public(client, api_key, path):
    assert client.get(path).status_code == 200
