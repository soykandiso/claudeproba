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
