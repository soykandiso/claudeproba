#!/usr/bin/env python3
"""See the platform in a browser, with changes showing up as you save.

    ./run.py            start the dev stack, open the browser, follow the logs
                        (Ctrl+C stops the stack)
    ./run.py --detach   start it and leave it running in the background
    ./run.py stop       stop a stack left running
    ./run.py --no-open  do not open a browser
    ./run.py --build    rebuild the image first (after changing dependencies)

This is a thin wrapper around

    docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

so nothing here is magic; see "Developing with live reload" in README.md.
Standard library only, so it runs with any python3 before `uv sync`.
"""

import argparse
import contextlib
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml"]
READY_TIMEOUT_SECONDS = 180


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", nargs="?", choices=["up", "stop"], default="up")
    parser.add_argument("--detach", action="store_true", help="leave the stack running")
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    parser.add_argument("--build", action="store_true", help="rebuild the image first")
    args = parser.parse_args()
    os.chdir(ROOT)

    if shutil.which("docker") is None:
        return fail("docker is not installed or not on PATH.")

    if args.command == "stop":
        return compose("stop")

    ensure_env_file()
    allow_bridge_traffic_in_codespaces()

    # app/ is bind-mounted, so code changes never need a rebuild; only dependency
    # or Dockerfile changes do. Compose still builds the image if it is missing.
    say("Starting the development stack (the first run builds the image, which takes a while)...")
    if compose("up", "-d", *(["--build"] if args.build else [])) != 0:
        return fail("docker compose could not start the stack; see the output above.")

    port = env_value("HTTP_PORT", "80")
    if not wait_until_healthy(f"http://127.0.0.1:{port}/healthz"):
        compose("logs", "--tail", "40", "web")
        return fail(f"The site did not answer on port {port} within {READY_TIMEOUT_SECONDS}s.")

    url = public_url(port)
    say(f"\n  Platform is up:  {url}\n")
    say("  Save a template, stylesheet or Python file and the open page refreshes itself.")
    if not args.no_open:
        webbrowser.open(url)

    if args.detach:
        say("  Left running. Stop it with:  ./run.py stop\n")
        return 0

    say("  Following web logs. Ctrl+C stops the stack.\n")
    with contextlib.suppress(KeyboardInterrupt):
        compose("logs", "-f", "--tail", "0", "web")
    say("\nStopping...")
    return compose("stop")


def compose(*args: str) -> int:
    return subprocess.call([*COMPOSE, *args])


def ensure_env_file() -> None:
    env = ROOT / ".env"
    if not env.exists():
        shutil.copy(ROOT / ".env.example", env)
        say("Created .env from .env.example (development defaults).")


def env_value(key: str, default: str) -> str:
    """Read a value the way compose does: the environment first, then .env."""
    if key in os.environ:
        return os.environ[key]
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == key:
            return value.strip()
    return default


def allow_bridge_traffic_in_codespaces() -> None:
    """The nested-Docker iptables quirk described in README.md. Best effort."""
    if not os.environ.get("CODESPACES") or shutil.which("iptables-legacy") is None:
        return
    rules = [
        # containers talking to each other
        ["-i", "grants-br", "-o", "grants-br", "-j", "ACCEPT"],
        # containers reaching the internet (the crawler), and the replies coming back
        ["-i", "grants-br", "!", "-o", "grants-br", "-j", "ACCEPT"],
        ["-o", "grants-br", "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
    ]
    for rule in rules:
        exists = subprocess.call(
            ["sudo", "-n", "iptables-legacy", "-C", "FORWARD", *rule],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if exists != 0:
            subprocess.call(["sudo", "-n", "iptables-legacy", "-I", "FORWARD", "1", *rule])


def wait_until_healthy(url: str) -> bool:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(1)
    return False


def public_url(port: str) -> str:
    """The URL to open. In Codespaces, localhost is the codespace, not your laptop."""
    codespace = os.environ.get("CODESPACE_NAME")
    domain = os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN")
    if codespace and domain:
        return f"https://{codespace}-{port}.{domain}"
    return f"http://localhost:{port}"


def say(message: str) -> None:
    print(message, flush=True)


def fail(message: str) -> int:
    print(f"run.py: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
