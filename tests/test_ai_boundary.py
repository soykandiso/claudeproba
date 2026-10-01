"""The boundary rules from docs/repo-skeleton.md, checked in code rather than by review."""

import re
from pathlib import Path

from app.ai.gateway import Routing

APP = Path(__file__).resolve().parents[1] / "app"
GATEWAY = APP / "ai" / "gateway.py"

# Provider SDKs and raw HTTP to provider hosts. Extend when a provider is added.
PROVIDER_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(anthropic|openai|mistralai|google\.generativeai|cohere)\b", re.M
)
PROVIDER_HOST = re.compile(r"api\.anthropic\.com|api\.openai\.com|api\.mistral\.ai")


def test_only_the_gateway_contacts_a_model_provider():
    offenders = [
        str(path.relative_to(APP.parent))
        for path in APP.rglob("*.py")
        if path != GATEWAY
        and (
            PROVIDER_IMPORT.search(text := path.read_text(encoding="utf-8"))
            or PROVIDER_HOST.search(text)
        )
    ]

    assert offenders == [], "only app/ai/gateway.py may contact a model provider"


def test_the_routing_config_loads():
    routing = Routing.load()

    for route in routing.tasks.values():
        assert route.model in routing.pricing, f"{route.model} has no price in config/models.yaml"
