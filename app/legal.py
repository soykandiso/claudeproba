"""The terms, the privacy policy and who processes data (roadmap P3 s45).

The texts are versioned templates (`legal/terms/<version>.html`, `legal/privacy/<version>.html`),
as prompts are versioned files: what an account accepted (`consent_record.policy_version`)
can always be read again. The facts they state live in `config/legal.yaml`.

`missing()` lists what is still unknown; `flask legal check` fails on any of it, and the
deploy runbook runs that check, so no placeholder reaches a public page.
"""

from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "legal.yaml"
TERMS = "terms"  # consent_record.purpose for accepting the terms and the privacy notice


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Entity(_Strict):
    name: str | None
    embs: str | None
    address: str | None
    email: str | None


class Processor(_Strict):
    role: str
    provider: str | None
    location: str | None
    data: str
    in_use: bool
    chosen: bool


class Legal(_Strict):
    version: str
    entity: Entity
    processors: tuple[Processor, ...]

    def missing(self) -> list[str]:
        """What a public page would show as a placeholder."""
        gaps = [f"entity.{k}" for k, v in self.entity.model_dump().items() if not v]
        gaps += [f"processor: {p.role}" for p in self.processors if not p.chosen or not p.provider]
        return gaps


@cache
def legal(path: Path = DEFAULT_PATH) -> Legal:
    return Legal.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
