"""One CSRF check, shared by every blueprint that has a form.

A token minted once per session, put in a hidden field, and compared in constant
time when the form comes back. The session cookie is signed and `SameSite=Lax`
(app/__init__.py), so this is the second of two locks rather than the only one.

It lives here rather than in a blueprint because the intake form (P2 s23) is the
first form that will be registered in production, and a second copy of a security
check is a second place to get it wrong.
"""

import secrets

from flask import abort, request, session

FIELD = "csrf"
UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def token() -> str:
    if FIELD not in session:
        session[FIELD] = secrets.token_urlsafe(32)
    return session[FIELD]


def protect(bp) -> None:
    """Refuse any unsafe request to `bp` that does not carry the session's token."""

    @bp.before_request
    def _check_csrf():
        if request.method in UNSAFE:
            sent = request.form.get(FIELD, "")
            if not sent or not secrets.compare_digest(sent, session.get(FIELD, "")):
                abort(400, "CSRF token missing or wrong; reload the page and try again")

    @bp.context_processor
    def _token():
        return {"csrf_token": token}
