"""Liveness and readiness endpoints.

These are deliberately two endpoints, not one. /healthz answers whether this
process is up; /readyz answers whether it can serve real traffic. Conflating them
makes a database blip look like a dead web process and fires the wrong alarm --
the thing a solo operator can least afford at 2am.
"""

import re

import psycopg
import redis
from flask import Blueprint, current_app, jsonify

bp = Blueprint("health", __name__)

# Short, because a hung dependency must fail the check rather than hang it.
PROBE_TIMEOUT_SECONDS = 2


@bp.get("/healthz")
def healthz():
    """Liveness. Touches no dependency, by design."""
    settings = current_app.extensions["settings"]
    return jsonify(status="ok", env=settings.env, version=settings.version)


@bp.get("/readyz")
def readyz():
    """Readiness. Reports each dependency separately so the cause is obvious."""
    settings = current_app.extensions["settings"]
    checks = {
        "postgres": _check_postgres(settings.database_url),
        "redis": _check_redis(settings.redis_url),
    }
    ready = all(check["ok"] for check in checks.values())
    status_code = 200 if ready else 503
    return jsonify(status="ready" if ready else "not ready", checks=checks), status_code


def _check_postgres(url: str) -> dict:
    try:
        with psycopg.connect(url, connect_timeout=PROBE_TIMEOUT_SECONDS) as conn:
            conn.execute("SELECT 1")
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": _summarise(exc)}


def _check_redis(url: str) -> dict:
    try:
        client = redis.from_url(
            url,
            socket_connect_timeout=PROBE_TIMEOUT_SECONDS,
            socket_timeout=PROBE_TIMEOUT_SECONDS,
        )
        client.ping()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": _summarise(exc)}


# Some driver errors echo the whole connection string back. psycopg does exactly
# this when the URL scheme is unrecognised -- a realistic misconfiguration -- which
# would put the database password into the /readyz body, and from there into
# whatever scrapes and stores it.
_CREDENTIALS_IN_URL = re.compile(r"//[^/\s]*:[^/\s@]*@")


def _summarise(exc: Exception) -> str:
    """A one-line cause, with any credentials redacted."""
    message = str(exc).strip().splitlines()[0]
    return f"{type(exc).__name__}: {_CREDENTIALS_IN_URL.sub('//***:***@', message)[:160]}"
