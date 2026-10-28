from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db import get_session
from app.main import app


class DownSession:
    """Stands in for a session whose database does not answer."""

    # Only `execute` is needed: it is what /health calls. It fails at once, which is much
    # faster than a real connection to a closed port (130 s on Windows).
    def execute(self, *args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


# Uses the `client` fixture, so it needs the PostgreSQL of the tests (skipped without it).
def test_health_returns_ok(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "document-service"}


# Does not use `client`, so it runs without a database: the failure is simulated.
def test_health_returns_503_when_the_database_is_down():
    app.dependency_overrides[get_session] = lambda: DownSession()
    try:
        response = TestClient(app).get("/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "service": "document-service",
        "detail": "database",
    }
