"""One module per source. Each defines a Fetcher subclass decorated with @register.

Modules are discovered by importing everything in this package, so adding a
source never means editing a list somewhere else.
"""

import importlib
import pkgutil

from app.ingestion.fetcher import Fetcher

_REGISTRY: dict[str, type[Fetcher]] = {}


def register[F: type[Fetcher]](cls: F) -> F:
    if cls.slug in _REGISTRY:
        raise ValueError(f"two fetchers claim the source {cls.slug!r}")
    _REGISTRY[cls.slug] = cls
    return cls


def fetchers() -> dict[str, type[Fetcher]]:
    for module in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{module.name}")
    return dict(_REGISTRY)
