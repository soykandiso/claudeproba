def test_healthz_reports_ok(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json == {"status": "ok", "env": "testing", "version": "test"}


def test_healthz_needs_no_database(app):
    """The liveness endpoint must not depend on Postgres or Redis.

    If it ever does, a database blip reads as a dead web process and the wrong
    alarm fires. Readiness is a separate endpoint, added in session 2.
    """
    settings = app.extensions["settings"]
    settings.database_url = "postgresql+psycopg://nobody@127.0.0.1:1/nothing"
    settings.redis_url = "redis://127.0.0.1:1/0"

    assert app.test_client().get("/healthz").status_code == 200


def test_readyz_reports_each_dependency_separately(app):
    """A failing dependency must name itself, not just fail the whole check."""
    settings = app.extensions["settings"]
    settings.database_url = "postgresql://nobody@127.0.0.1:1/nothing"
    settings.redis_url = "redis://127.0.0.1:1/0"

    response = app.test_client().get("/readyz")

    assert response.status_code == 503
    assert response.json["status"] == "not ready"
    assert response.json["checks"]["postgres"]["ok"] is False
    assert response.json["checks"]["redis"]["ok"] is False
    assert "error" in response.json["checks"]["postgres"]


def test_readyz_does_not_leak_credentials(app):
    """Probe errors reach operators and monitoring; they must not carry the password.

    An unrecognised URL scheme is the case that matters: psycopg echoes the whole
    connection string back in the exception, so without redaction the password
    would appear in the /readyz body.
    """
    settings = app.extensions["settings"]
    settings.database_url = "postgres-bad://grants:hunter2@127.0.0.1:1/nothing"
    settings.redis_url = "redis://:hunter2@127.0.0.1:1/0"

    body = app.test_client().get("/readyz").get_data(as_text=True)

    assert "hunter2" not in body
    assert "***" in body, "the DSN was echoed but redaction did not fire"
