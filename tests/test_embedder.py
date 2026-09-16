"""The local embedder's configuration and its refusal to download in passing."""

import pytest

from app.models import Chunk
from app.retrieval.embedder import EmbeddingConfig, LocalEmbedder, ModelNotDownloaded


def test_the_configured_model_fits_the_chunk_column():
    config = EmbeddingConfig.load()

    assert config.dimensions == Chunk.__table__.c.embedding.type.dim
    assert config.query_prefix and config.passage_prefix  # E5 needs both


def test_a_missing_model_is_an_error_not_a_download(tmp_path):
    embedder = LocalEmbedder(tmp_path)

    with pytest.raises(ModelNotDownloaded, match="flask ingest fetch-model"):
        embedder.query("проверка")

    assert not any(tmp_path.rglob("*.onnx")), "nothing was fetched"


def test_a_dimension_mismatch_with_the_schema_is_refused(tmp_path):
    path = tmp_path / "models.yaml"
    path.write_text("embedding:\n  model: some/other-model\n  dimensions: 384\n")

    with pytest.raises(ValueError, match="needs a migration"):
        EmbeddingConfig.load(path)
