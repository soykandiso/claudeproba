"""Pings to healthchecks.io: how an alert leaves the box (docs/risks.md R1).

The app never sends the alert itself. It reports to a check on healthchecks.io
(hosted by Hetzner in Germany, operated from Latvia), and that service emails
when a check is told it failed, or when a ping it expects does not arrive. So a
dead box, a dead cron and a dead source all reach you by the same route, and none
of them depends on the thing that broke.

A ping body is operator text: source slugs, dates and error messages. It never
carries customer data.

    <url>        success
    <url>/fail   failure; the body is shown in the notification

A ping that cannot be delivered is reported, never raised: the command that
pings has already done its work, and a missed ping is itself what the check
alarms on.
"""

from collections.abc import Callable

import httpx

MAX_BODY = 10_000  # characters; healthchecks.io keeps the first 100 kB
TIMEOUT_S = 10
ATTEMPTS = 3


def ping(
    url: str | None,
    *,
    ok: bool,
    body: str,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] | None = None,
) -> str:
    """Send one ping. Returns a line for the command's own log."""
    if not url:
        return "heartbeat not configured"
    target = url.rstrip("/") + ("" if ok else "/fail")
    if len(body) > MAX_BODY:
        body = body[: MAX_BODY - 20] + "\n[... truncated]"
    error = None
    with httpx.Client(timeout=TIMEOUT_S, transport=transport) as client:
        for attempt in range(ATTEMPTS):
            try:
                response = client.post(target, content=body.encode("utf-8"))
                if response.status_code < 300:
                    return f"heartbeat sent ({'ok' if ok else 'fail'})"
                error = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                error = f"{type(exc).__name__}: {exc}"
            if sleep is not None and attempt < ATTEMPTS - 1:
                sleep(2**attempt)
    return f"heartbeat FAILED after {ATTEMPTS} attempts: {error}"
