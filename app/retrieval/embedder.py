"""Text → vectors, computed on this machine.

The model (config/models.yaml `embedding`) runs on CPU through fastembed and
ONNX Runtime. Nothing is sent anywhere, so this is not a model provider in the
sense of CLAUDE.md invariant 4 and does not go through app/ai/gateway.py.

The model files are fetched once, explicitly, with `flask ingest fetch-model`,
into GRANTS_MODEL_DIR (a Docker volume on the VPS). Every other use loads them
with local_files_only: a missing model is an error, never a 2 GB download in the
middle of a cron run.

`Embedder.name` is stored on every chunk. It includes the fastembed version,
because fastembed has changed how a model's vectors are pooled between releases
(after 0.5.1, for this very model); vectors under different names are never
compared.
"""

import os
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from importlib import metadata
from pathlib import Path
from typing import Protocol

import yaml

from app.models import Chunk

# Set before huggingface_hub is imported by fastembed.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "models.yaml"

# Small batches: memory grows with batch size times sequence length, and this
# shares a small VPS with PostgreSQL.
BATCH_SIZE = 8


class ModelNotDownloaded(RuntimeError):
    """The embedding model is not in GRANTS_MODEL_DIR. Run `flask ingest fetch-model`."""


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str
    dimensions: int
    query_prefix: str = ""
    passage_prefix: str = ""

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG) -> "EmbeddingConfig":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        config = cls(**raw["embedding"])
        column = Chunk.__table__.c.embedding.type.dim
        if config.dimensions != column:
            raise ValueError(
                f"config/models.yaml embedding has {config.dimensions} dimensions, "
                f"chunk.embedding has {column}; a different model needs a migration"
            )
        return config


class Embedder(Protocol):
    name: str

    def passages(self, texts: Sequence[str]) -> list[list[float]]: ...

    def query(self, text: str) -> list[float]: ...


class LocalEmbedder:
    def __init__(self, model_dir: str | Path, config: EmbeddingConfig | None = None):
        self._model_dir = Path(model_dir)
        self._config = config or EmbeddingConfig.load()

    @cached_property
    def name(self) -> str:
        # From package metadata: importing fastembed loads ONNX Runtime, which a run
        # with nothing to embed should not pay for.
        return f"{self._config.model}@fastembed-{metadata.version('fastembed')}"

    def passages(self, texts: Sequence[str]) -> list[list[float]]:
        prefixed = [self._config.passage_prefix + text for text in texts]
        return self._embed(prefixed)

    def query(self, text: str) -> list[float]:
        return self._embed([self._config.query_prefix + text])[0]

    def download(self) -> None:
        """Fetch the model files into model_dir. The only method that uses the network."""
        from fastembed import TextEmbedding

        self._model_dir.mkdir(parents=True, exist_ok=True)
        TextEmbedding(self._config.model, cache_dir=str(self._model_dir))

    def _embed(self, texts: list[str]) -> list[list[float]]:
        vectors = [v.tolist() for v in self._model.embed(texts, batch_size=BATCH_SIZE)]
        for vector in vectors:
            if len(vector) != self._config.dimensions:
                raise ValueError(
                    f"{self.name} returned {len(vector)} dimensions, "
                    f"expected {self._config.dimensions}"
                )
        return vectors

    @cached_property
    def _model(self):
        # Imported here: ONNX Runtime is heavy, and the web process never embeds.
        from fastembed import TextEmbedding

        try:
            with warnings.catch_warnings():
                # "now uses mean pooling instead of CLS": true after fastembed 0.5.1, and
                # the reason `name` carries the fastembed version. Not news on every run.
                warnings.filterwarnings("ignore", message=".*mean pooling.*")
                return TextEmbedding(
                    self._config.model, cache_dir=str(self._model_dir), local_files_only=True
                )
        except Exception as exc:
            # fastembed reports a missing model as a generic error; say what to do.
            raise ModelNotDownloaded(
                f"{self._config.model} could not be loaded from {self._model_dir} "
                f"({type(exc).__name__}: {exc}); run `flask ingest fetch-model`"
            ) from exc
