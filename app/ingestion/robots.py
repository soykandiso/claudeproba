"""robots.txt matching per RFC 9309.

Not urllib.robotparser: it treats `*` and `$` literally, so av.gov.mk's real rule
`Disallow: *.pdf` would silently match nothing and the crawler would fetch what
the site asked it not to. Found by tests/test_ingestion_http.py.

Rules: the group whose user-agent token matches ours is used, otherwise the `*`
group. Among the rules in that group, the longest matching path wins, and on a
tie Allow beats Disallow. `*` matches any run of characters, `$` anchors the end.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit


@dataclass
class Robots:
    groups: dict[str, list[tuple[bool, str]]] = field(default_factory=dict)
    allow_all: bool = False
    disallow_all: bool = False

    @classmethod
    def parse(cls, text: str) -> "Robots":
        groups: dict[str, list[tuple[bool, str]]] = {}
        agents: list[str] = []
        in_rules = False
        # av.gov.mk serves its file with a byte-order mark; without this every rule is lost.
        for raw in text.lstrip("\ufeff").splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if in_rules:  # a user-agent after rules starts a new group
                    agents, in_rules = [], False
                agents.append(value.lower())
                for agent in agents:
                    groups.setdefault(agent, [])
            elif key in ("allow", "disallow") and agents:
                in_rules = True
                if value:  # an empty Disallow means "allow everything", i.e. no rule
                    for agent in agents:
                        groups[agent].append((key == "allow", value))
        return cls(groups=groups)

    def can_fetch(self, agent: str, url: str) -> bool:
        if self.disallow_all:
            return False
        if self.allow_all:
            return True
        rules = self.groups.get(agent.lower(), self.groups.get("*", []))
        parts = urlsplit(url)
        path = unquote(parts.path or "/") + (f"?{parts.query}" if parts.query else "")

        best: tuple[int, bool] | None = None  # (length, allowed)
        for allowed, pattern in rules:
            if _matches(pattern, path):
                candidate = (len(pattern), allowed)
                if best is None or candidate > best:  # longer wins; on equal length True > False
                    best = candidate
        return True if best is None else best[1]


def _matches(pattern: str, path: str) -> bool:
    anchored = pattern.endswith("$")
    body = unquote(pattern[:-1] if anchored else pattern)
    regex = ".*".join(re.escape(piece) for piece in body.split("*"))
    # Patterns match from the start of the path; one without a leading slash
    # (like `*.pdf`) is treated as starting with a wildcard, which is how sites
    # that write it mean it.
    if not body.startswith(("/", "*")):
        regex = ".*" + regex
    return re.match(regex + ("$" if anchored else ""), path) is not None
