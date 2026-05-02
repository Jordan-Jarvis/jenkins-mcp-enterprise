from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from jenkins_mcp_enterprise.base import Build
from jenkins_mcp_enterprise.streaming.log_processor import LogChunk
from jenkins_mcp_enterprise.vector_manager import QdrantVectorManager


def test_search_hierarchical_uses_query_points_and_preserves_payload():
    manager = QdrantVectorManager.__new__(QdrantVectorManager)
    manager.vector_search_disabled = False
    manager.collection_name = "test-collection"
    manager.model = Mock()
    manager.model.encode.return_value = [[0.1, 0.2, 0.3]]

    point = SimpleNamespace(
        id=123,
        score=0.91,
        payload={
            "build_id": "job:1",
            "root_build_id": "job:1",
            "log_level": "ERROR",
            "diagnostic_score": 0.8,
            "pipeline_stage": "test",
            "depth": 0,
            "start_line": 10,
            "end_line": 12,
            "content": "ERROR: synthetic failure marker",
            "job_name": "job",
            "build_number": 1,
        },
    )
    manager.client = Mock()
    manager.client.query_points.return_value = SimpleNamespace(points=[point])

    results = manager.search_hierarchical(
        query_text="synthetic failure",
        root_build=Build(job_name="job", build_number=1),
        top_k=3,
    )

    manager.client.query_points.assert_called_once()
    assert len(results) == 1
    assert results[0]["score"] == 0.91
    assert results[0]["content"] == "ERROR: synthetic failure marker"
    assert results[0]["payload"]["job_name"] == "job"


def test_index_build_log_processes_stream_and_upserts(monkeypatch, tmp_path):
    manager = QdrantVectorManager.__new__(QdrantVectorManager)
    manager.vector_search_disabled = False
    manager.client = object()
    manager.upsert_hierarchical_chunks = Mock()

    build = Build(job_name="job", build_number=1)
    chunk = LogChunk(
        build=build,
        chunk_id="job:1:chunk:0",
        content="ERROR: synthetic failure marker",
        start_line=1,
        end_line=1,
        log_level="ERROR",
        diagnostic_score=1.0,
    )

    class FakeProcessor:
        def process_streaming(self, log_stream, streamed_build):
            assert streamed_build == build
            assert "synthetic failure marker" in log_stream.read()
            return iter([chunk])

    monkeypatch.setattr(
        "jenkins_mcp_enterprise.vector_manager.StreamingLogProcessor",
        FakeProcessor,
    )

    log_path = tmp_path / "console.log"
    log_path.write_text("ERROR: synthetic failure marker\n", encoding="utf-8")

    manager.index_build_log(build, Path(log_path))

    manager.upsert_hierarchical_chunks.assert_called_once_with([chunk], build, depth=0)
