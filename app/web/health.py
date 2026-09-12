"""Liveness endpoint.

Deliberately dependency-free: it answers whether this process is up, nothing more.
Readiness checks against Postgres and Redis arrive with those services in session 2,
as a separate endpoint -- conflating the two makes a database blip look like a dead
web process and triggers the wrong alarm.
"""

from flask import Blueprint, current_app, jsonify

bp = Blueprint("health", __name__)


@bp.get("/healthz")
def healthz():
    settings = current_app.extensions["settings"]
    return jsonify(status="ok", env=settings.env, version=settings.version)
