"""Browser auto-refresh for development.

Registered only when GRANTS_LIVE_RELOAD is on, which the settings refuse in
production. Every HTML page gets a small script that polls /__dev/reload once a
second and reloads the page when the token changes.

The token combines two things:
- a per-process id, so a Python edit (which restarts the Flask dev server)
  changes it;
- the newest modification time under templates/ and static/, so a template or
  stylesheet edit changes it without any restart.

Polling rather than a websocket or SSE: it survives the server restarting under
it, needs no extra dependency, and goes through Caddy unchanged.
"""

import logging
import uuid
from pathlib import Path

from flask import Blueprint, Flask, Response, current_app, jsonify

bp = Blueprint("devreload", __name__)

POLL_PATH = "/__dev/reload"

_PROCESS_ID = uuid.uuid4().hex

_SCRIPT = """
<script>
(() => {
  let token = "%s";
  async function poll() {
    if (!document.hidden) {
      try {
        const response = await fetch("%s", { cache: "no-store" });
        if (response.ok) {
          const current = (await response.json()).token;
          if (current !== token) { location.reload(); return; }
        }
      } catch (_) { /* server restarting; try again shortly */ }
    }
    setTimeout(poll, 1000);
  }
  setTimeout(poll, 1000);
})();
</script>
"""


def init_app(app: Flask) -> None:
    app.register_blueprint(bp)
    app.after_request(_inject_script)
    # The poll would otherwise put a line in the dev server log every second.
    logging.getLogger("werkzeug").addFilter(_HidePollRequests())


@bp.get(POLL_PATH)
def token():
    return jsonify(token=_current_token())


def _current_token() -> str:
    newest = 0
    for folder in (current_app.template_folder, current_app.static_folder):
        root = Path(current_app.root_path, folder) if folder else None
        if root and root.is_dir():
            for path in root.rglob("*"):
                newest = max(newest, path.stat().st_mtime_ns)
    return f"{_PROCESS_ID}-{newest}"


def _inject_script(response: Response) -> Response:
    if response.mimetype != "text/html" or response.direct_passthrough:
        return response
    body = response.get_data()
    marker = body.rfind(b"</body>")
    if marker == -1:
        return response
    script = (_SCRIPT % (_current_token(), POLL_PATH)).encode()
    response.set_data(body[:marker] + script + body[marker:])
    return response


class _HidePollRequests(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return POLL_PATH not in record.getMessage()
