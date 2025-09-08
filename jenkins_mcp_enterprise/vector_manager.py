"""Qdrant-based vector management for Jenkins logs"""

import os
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)
from sentence_transformers import SentenceTransformer

from .base import Build, VectorChunk
from .config import VectorConfig
from .exceptions import VectorStoreError
from .logging_config import get_component_logger
from .streaming.log_processor import LogChunk

logger = get_component_logger("vector_manager")


class QdrantVectorManager:
    """Vector management using Qdrant vector database"""

    def __init__(self, config: VectorConfig, cache_manager, jenkins_client):
        self.config = config
        self.cache_manager = cache_manager
        self.jenkins_client = jenkins_client

        # Check if vector search is disabled via environment variable (default: disabled)
        self.vector_search_disabled = os.getenv(
            "DISABLE_VECTOR_SEARCH", "true"
        ).lower() in ("true", "1", "yes")

        if self.vector_search_disabled:
            logger.info(
                "Vector search functionality is DISABLED (default). Set DISABLE_VECTOR_SEARCH=false to enable."
            )
            logger.info(
                "Initialized in mock mode. No Qdrant or SentenceTransformer will be loaded"
            )
            self.client = None
            self.model = None
            self.embedding_dim = 384  # Default dimension
            self.collection_name = config.collection_name
            return

        # Initialize Qdrant client
        try:
            self.client = QdrantClient(
                host=self._extract_host(config.host),
                port=self._extract_port(config.host),
                timeout=30,
            )
            logger.info(f"Connected to Qdrant at {config.host}")
        except Exception as e:
            logger.error(f"Failed to connect to Qdrant: {e}")
            raise VectorStoreError(f"Failed to connect to Qdrant: {e}")

        # Load embedding model
        try:
            self.model = SentenceTransformer(config.embedding_model)
            self.embedding_dim = self.model.get_sentence_embedding_dimension()
            logger.info(
                f"Loaded embedding model {config.embedding_model} with dimension {self.embedding_dim}"
            )
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise VectorStoreError(f"Failed to load embedding model: {e}")

        # Collection naming
        self.collection_name = config.collection_name

        # Initialize collection with proper retry
        self._ensure_collection_exists()

    def _extract_host(self, host_url: str) -> str:
        """Extract hostname from URL"""
        if "://" in host_url:
            return host_url.split("://")[1].split(":")[0]
        return host_url.split(":")[0]

    def _extract_port(self, host_url: str) -> int:
        """Extract port from URL"""
        if ":" in host_url:
            port_str = host_url.split(":")[-1]
            try:
                return int(port_str)
            except ValueError:
                pass
        return 6333  # Default Qdrant port

    def _ensure_collection_exists(self) -> None:
        """Ensure the main collection exists with proper configuration"""
        if self.vector_search_disabled or not self.client:
            return

        try:
            # Wait briefly for Qdrant to be fully ready (Docker timing issue)
            import time
            time.sleep(2)
            
            # Check if collection exists
            collections = self.client.get_collections()
            collection_names = [col.name for col in collections.collections]

            if self.collection_name not in collection_names:
                logger.info(f"Creating Qdrant collection: {self.collection_name}")

                # Create collection with vector configuration
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.embedding_dim, distance=Distance.COSINE
                    ),
                )

                # Create indexes for efficient filtering
                self._create_indexes()

            logger.info(f"Qdrant collection '{self.collection_name}' is ready")

        except Exception as e:
            # Retry connection with exponential backoff
            import time
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s, 8s, 16s
                    logger.info(f"Retrying Qdrant connection (attempt {attempt + 1}/{max_retries})")
                    collections = self.client.get_collections()
                    collection_names = [col.name for col in collections.collections]
                    
                    if self.collection_name not in collection_names:
                        self.client.create_collection(
                            collection_name=self.collection_name,
                            vectors_config=VectorParams(
                                size=self.embedding_dim, distance=Distance.COSINE
                            ),
                        )
                        self._create_indexes()
                    
                    logger.info(f"Qdrant collection '{self.collection_name}' initialized successfully")
                    return
                    
                except Exception as retry_e:
                    logger.warning(f"Retry {attempt + 1} failed: {retry_e}")
                    if attempt == max_retries - 1:
                        raise VectorStoreError(f"Failed to initialize Qdrant after {max_retries} attempts: {e}")

    def _create_indexes(self) -> None:
        """Create indexes for efficient metadata filtering"""
        if self.vector_search_disabled or not self.client:
            return

        try:
            # Index commonly filtered fields
            index_fields = [
                "build_id",
                "root_build_id",
                "log_level",
                "pipeline_stage",
                "depth",
                "diagnostic_score",
            ]

            for field in index_fields:
                try:
                    self.client.create_payload_index(
                        collection_name=self.collection_name, field_name=field
                    )
                except Exception as e:
                    logger.debug(f"Index for {field} may already exist: {e}")

        except Exception as e:
            logger.warning(f"Failed to create some indexes: {e}")

    def embed_chunks(self, chunks: List[LogChunk]) -> List[VectorChunk]:
        """Generate embeddings for log chunks"""
        if self.vector_search_disabled or not chunks:
            return []

        try:
            # Extract text content
            texts = [chunk.content for chunk in chunks]

            # Generate embeddings in batch
            embeddings = self.model.encode(
                texts, batch_size=32, show_progress_bar=len(texts) > 100
            )

            # Create VectorChunk objects
            vector_chunks = []
            for chunk, embedding in zip(chunks, embeddings):
                vector_chunk = VectorChunk(
                    build=chunk.build,
                    chunk_index=int(chunk.chunk_id.split(":")[-1]),
                    text=chunk.content,
                    vector=embedding.tolist(),
                )
                vector_chunks.append(vector_chunk)

            return vector_chunks

        except Exception as e:
            logger.error(f"Failed to generate embeddings: {e}")
            raise VectorStoreError(f"Embedding generation failed: {e}")

    def upsert_hierarchical_chunks(
        self, chunks: List[LogChunk], root_build: Build, depth: int = 0
    ) -> None:
        """Upsert chunks with hierarchical metadata to Qdrant"""
        if self.vector_search_disabled or not chunks or not self.client:
            return

        try:
            # Generate embeddings
            vector_chunks = self.embed_chunks(chunks)

            # Prepare points for Qdrant
            points = []
            for log_chunk, vector_chunk in zip(chunks, vector_chunks):
                payload = {
                    "build_id": f"{log_chunk.build.job_name}:{log_chunk.build.build_number}",
                    "root_build_id": f"{root_build.job_name}:{root_build.build_number}",
                    "chunk_id": log_chunk.chunk_id,
                    "log_level": log_chunk.log_level,
                    "diagnostic_score": log_chunk.diagnostic_score,
                    "pipeline_stage": log_chunk.pipeline_stage or "",
                    "depth": depth,
                    "start_line": log_chunk.start_line,
                    "end_line": log_chunk.end_line,
                    "job_name": log_chunk.build.job_name,
                    "build_number": log_chunk.build.build_number,
                    "root_job_name": root_build.job_name,
                    "root_build_number": root_build.build_number,
                    "content": log_chunk.content[
                        :1000
                    ],  # Store truncated content for retrieval
                    "timestamp": getattr(log_chunk, "timestamp", ""),
                }

                # Convert chunk_id to valid Qdrant point ID (unsigned integer)
                # Use secure hash of the original chunk_id to create a unique integer
                import hashlib

                chunk_id_hash = int(
                    hashlib.sha256(log_chunk.chunk_id.encode()).hexdigest()[:8], 16
                )

                # Store original chunk_id in payload for retrieval
                payload["original_chunk_id"] = log_chunk.chunk_id

                point = PointStruct(
                    id=chunk_id_hash, vector=vector_chunk.vector, payload=payload
                )
                points.append(point)

            # Upsert to Qdrant
            self.client.upsert(collection_name=self.collection_name, points=points)

            logger.info(
                f"Upserted {len(points)} chunks for {root_build.job_name}#{root_build.build_number}"
            )

        except Exception as e:
            logger.error(f"Failed to upsert chunks: {e}")
            raise VectorStoreError(f"Chunk upsert failed: {e}")

    def search_hierarchical(
        self,
        query_text: str,
        root_build: Optional[Build] = None,
        log_level: Optional[str] = None,
        min_diagnostic_score: float = 0.0,
        max_depth: Optional[int] = None,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search with hierarchical filtering"""
        if self.vector_search_disabled or not self.client:
            return []

        try:
            # Generate query embedding
            query_embedding = self.model.encode([query_text])[0].tolist()

            # Build filter conditions
            filter_conditions = []

            if root_build:
                filter_conditions.append(
                    FieldCondition(
                        key="root_build_id",
                        match=MatchValue(
                            value=f"{root_build.job_name}:{root_build.build_number}"
                        ),
                    )
                )

            if log_level:
                filter_conditions.append(
                    FieldCondition(key="log_level", match=MatchValue(value=log_level))
                )

            if min_diagnostic_score > 0:
                filter_conditions.append(
                    FieldCondition(
                        key="diagnostic_score", range={"gte": min_diagnostic_score}
                    )
                )

            if max_depth is not None:
                filter_conditions.append(
                    FieldCondition(key="depth", range={"lte": max_depth})
                )

            # Create filter
            search_filter = (
                Filter(must=filter_conditions) if filter_conditions else None
            )

            # Perform search
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                query_filter=search_filter,
                limit=top_k,
                with_payload=True,
                with_vectors=False,
            )

            # Format results
            formatted_results = []
            for result in results:
                formatted_result = {
                    "id": result.id,
                    "score": result.score,
                    "build_id": result.payload["build_id"],
                    "root_build_id": result.payload["root_build_id"],
                    "log_level": result.payload["log_level"],
                    "diagnostic_score": result.payload["diagnostic_score"],
                    "pipeline_stage": result.payload["pipeline_stage"],
                    "depth": result.payload["depth"],
                    "start_line": result.payload["start_line"],
                    "end_line": result.payload["end_line"],
                    "content": result.payload["content"],
                }
                formatted_results.append(formatted_result)

            logger.info(
                f"Found {len(formatted_results)} results for query: '{query_text[:50]}...'"
            )
            return formatted_results

        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            raise VectorStoreError(f"Search failed: {e}")

    def delete_build_data(self, build: Build) -> None:
        """Delete all vectors for a specific build"""
        if self.vector_search_disabled or not self.client:
            return

        try:
            build_id = f"{build.job_name}:{build.build_number}"

            # Delete by filter
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=Filter(
                    must=[
                        FieldCondition(key="build_id", match=MatchValue(value=build_id))
                    ]
                ),
            )

            logger.info(f"Deleted vector data for {build_id}")

        except Exception as e:
            logger.error(f"Failed to delete build data: {e}")
            raise VectorStoreError(f"Build data deletion failed: {e}")

    def delete_root_pipeline_data(self, root_build: Build) -> None:
        """Delete all vectors for an entire pipeline hierarchy"""
        if self.vector_search_disabled or not self.client:
            return

        try:
            root_build_id = f"{root_build.job_name}:{root_build.build_number}"

            # Delete all data for this root pipeline
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="root_build_id", match=MatchValue(value=root_build_id)
                        )
                    ]
                ),
            )

            logger.info(f"Deleted all pipeline data for root {root_build_id}")

        except Exception as e:
            logger.error(f"Failed to delete pipeline data: {e}")
            raise VectorStoreError(f"Pipeline data deletion failed: {e}")

    def get_collection_stats(self) -> Dict[str, Any]:
        """Get statistics about the vector collection"""
        if self.vector_search_disabled or not self.client:
            return {"disabled": True}

        try:
            info = self.client.get_collection(self.collection_name)

            return {
                "collection_name": self.collection_name,
                "vectors_count": info.vectors_count,
                "indexed_vectors_count": info.indexed_vectors_count,
                "points_count": info.points_count,
                "segments_count": info.segments_count,
                "config": {
                    "distance": info.config.params.vectors.distance.value,
                    "size": info.config.params.vectors.size,
                },
            }

        except Exception as e:
            logger.error(f"Failed to get collection stats: {e}")
            return {"error": str(e)}

    def health_check(self) -> bool:
        """Check if Qdrant is healthy and accessible"""
        if self.vector_search_disabled or not self.client:
            return True  # Mock mode is always "healthy"

        try:
            # Simple health check
            self.client.get_collections()
            return True
        except Exception as e:
            logger.error(f"Qdrant health check failed: {e}")
            return False

    # Legacy methods for backward compatibility
    def chunk_and_upsert(
        self, build: Build, text: Optional[str] = None, chunk_size: Optional[int] = None
    ):
        """Legacy method for backward compatibility"""
        if self.vector_search_disabled:
            return

        # Use configured chunk size if not provided
        effective_chunk_size = chunk_size or self.config.chunk_size

        log_text_to_process: Optional[str] = text

        if log_text_to_process is None:
            if not self.cache_manager or not self.jenkins_client:
                return
            try:
                log_path = self.cache_manager.fetch(self.jenkins_client, build)
                log_text_to_process = log_path.read_text(errors="ignore")
            except Exception as e:
                logger.error(
                    f"Failed to fetch and read log for {build.job_name} #{build.build_number}: {e}"
                )
                return

        if not log_text_to_process:
            return

        # Simple word-based chunking for legacy compatibility
        words = log_text_to_process.split()
        chunks = [
            " ".join(words[i : i + effective_chunk_size])
            for i in range(0, len(words), effective_chunk_size)
        ]

        points = []
        for i, chunk_text in enumerate(chunks):
            vector = self.model.encode(chunk_text).tolist()

            payload = {
                "build_id": f"{build.job_name}:{build.build_number}",
                "chunk_index": i,
                "text": chunk_text,
                "job_name": build.job_name,
                "build_number": build.build_number,
            }

            point = PointStruct(
                id=f"{build.job_name}:{build.build_number}::{i}",
                vector=vector,
                payload=payload,
            )
            points.append(point)

        self.client.upsert(collection_name=self.collection_name, points=points)

    def query(self, build: Build, query_text: str, top_k: int = 5) -> List[VectorChunk]:
        """Legacy query method for backward compatibility"""
        if self.vector_search_disabled or not self.client:
            return []

        query_embedding = self.model.encode([query_text])[0].tolist()
        build_id = f"{build.job_name}:{build.build_number}"

        # Search with build filter
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_embedding,
            query_filter=Filter(
                must=[FieldCondition(key="build_id", match=MatchValue(value=build_id))]
            ),
            limit=top_k,
            with_payload=True,
            with_vectors=True,
        )

        vector_chunks = []
        for result in results:
            chunk_index = result.payload.get("chunk_index", -1)
            chunk_text = result.payload.get("text", "")
            vector_values = result.vector if hasattr(result, "vector") else []

            vector_chunks.append(
                VectorChunk(
                    build=build,
                    chunk_index=chunk_index,
                    text=chunk_text,
                    vector=vector_values,
                )
            )

        return vector_chunks


# Alias for backward compatibility
VectorManager = QdrantVectorManager
