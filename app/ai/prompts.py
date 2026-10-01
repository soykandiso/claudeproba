"""Versioned prompt files (prompts/README.md)."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from string import Template

USER_MARKER = "<!-- user -->"


class PromptError(RuntimeError):
    pass


@dataclass(frozen=True)
class Prompt:
    task: str
    version: str
    path: Path
    content_sha256: str
    system: Template
    user: Template

    @property
    def id(self) -> str:
        return f"{self.task}/{self.version}"

    def render(self, variables: dict[str, str]) -> tuple[str, str]:
        """(system, user). A missing variable raises rather than rendering empty."""
        try:
            return self.system.substitute(variables), self.user.substitute(variables)
        except KeyError as exc:
            raise PromptError(f"{self.id}: variable {exc} was not supplied") from exc


def load_prompt(prompts_dir: Path, task: str, version: str) -> Prompt:
    path = prompts_dir / task / f"{version}.md"
    if not path.is_file():
        raise PromptError(f"prompt file not found: {path}")
    content = path.read_text(encoding="utf-8")
    system, marker, user = content.partition(USER_MARKER)
    if not marker:
        raise PromptError(f"{path}: missing the {USER_MARKER} line")
    return Prompt(
        task=task,
        version=version,
        path=path,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        system=Template(system.strip()),
        user=Template(user.strip()),
    )
