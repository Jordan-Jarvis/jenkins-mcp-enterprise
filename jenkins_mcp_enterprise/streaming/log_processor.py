"""Streaming log processor for massive Jenkins console logs"""

import io
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, List, Optional, Tuple

from ..base import Build
from ..exceptions import CacheError
from ..logging_config import get_component_logger

logger = get_component_logger("streaming.log_processor")


@dataclass
class LogChunk:
    """Semantic chunk of log content with metadata"""

    build: Build
    chunk_id: str
    content: str
    start_line: int
    end_line: int
    log_level: str  # ERROR, WARN, INFO, DEBUG
    pipeline_stage: Optional[str] = None
    timestamp: Optional[str] = None
    diagnostic_score: float = 0.0  # 0-1, higher = more diagnostic value


@dataclass
class LogMetrics:
    """Metrics about log processing"""

    total_bytes: int
    total_lines: int
    error_lines: int
    warning_lines: int
    chunks_created: int
    processing_time_ms: float


class StreamingLogProcessor:
    """Process massive logs in streaming fashion"""

    def __init__(self, chunk_size_bytes: int = 1024 * 1024):  # 1MB chunks
        self.chunk_size_bytes = chunk_size_bytes
        self.error_patterns = [
            r"\[ERROR\]",
            r"FAILED",
            r"Exception in thread",
            r"Caused by:",
            r"at\s+[\w.]+\(",  # Stack trace lines
            r"BUILD FAILED",
            r"FAILURE:",
            r"Error:",
            r".*Exception:",
            r"Process exited with code \d+",
            r"maven-surefire.*FAILURE",
            r"Test.*FAILED",
        ]
        self.warning_patterns = [
            r"\[WARNING\]",
            r"\[WARN\]",
            r"deprecated",
            r"warning:",
            r"UNSTABLE",
        ]
        self.noise_patterns = [
            r"Downloading from",
            r"Downloaded:",
            r"manifest",
            r"Progress \(\d+\)",
            r"\[INFO\]\s*$",
            r"^\s*$",  # Empty lines
            r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}$",  # Standalone timestamps
        ]
        
        # Timestamp removal regex (moved from cache manager for better performance)
        self.timestamp_regex = re.compile(
            r"^\d{2}:\d{2}:\d{2}(\.\d{3})?\s*|"
            r"^\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}(?:[.,]\d{3,6})?\s*|"
            r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\]\s*"
        )

    def process_streaming(
        self, log_stream: io.TextIOBase, build: Build
    ) -> Generator[LogChunk, None, None]:
        """Process log stream in chunks, yielding semantic chunks"""
        start_time = time.time()
        
        # Fast batch processing mode when vector search is disabled
        if getattr(self, '_vector_search_disabled', True):
            yield from self._process_batch_fast(log_stream, build, start_time)
            return
            
        # Original streaming mode for vector search compatibility
        current_chunk_lines = []
        current_chunk_bytes = 0
        line_number = 0
        chunk_id = 0

        try:
            for line in log_stream:
                line_number += 1
                line_bytes = len(line.encode("utf-8"))

                # Skip noise lines early
                if self._is_noise_line(line):
                    continue

                # Remove timestamps for better context analysis while preserving original line structure
                cleaned_line = self.timestamp_regex.sub("", line.rstrip())
                current_chunk_lines.append((line_number, cleaned_line))
                current_chunk_bytes += line_bytes

                # Yield chunk when size limit reached or semantic boundary detected
                if (
                    current_chunk_bytes >= self.chunk_size_bytes
                    or self._is_chunk_boundary(line)
                ):

                    if current_chunk_lines:
                        yield self._create_chunk(build, chunk_id, current_chunk_lines)
                        chunk_id += 1
                        current_chunk_lines = []
                        current_chunk_bytes = 0

            # Yield final chunk
            if current_chunk_lines:
                yield self._create_chunk(build, chunk_id, current_chunk_lines)

            processing_time = (time.time() - start_time) * 1000
            logger.info(
                f"Processed {line_number} lines in {processing_time:.1f}ms for {build.job_name}#{build.build_number}"
            )

        except Exception as e:
            logger.error(
                f"Error processing log stream for {build.job_name}#{build.build_number}: {e}"
            )
            raise CacheError(f"Stream processing failed: {e}")

    def _process_batch_fast(
        self, log_stream: io.TextIOBase, build: Build, start_time: float
    ) -> Generator[LogChunk, None, None]:
        """Fast batch processing mode - read entire file and process in bulk"""
        try:
            # Read entire file at once
            content = log_stream.read()
            if not content:
                return
                
            # Compile combined noise pattern for single-pass removal
            combined_noise_pattern = re.compile(
                '|'.join(f'({pattern})' for pattern in self.noise_patterns),
                re.IGNORECASE | re.MULTILINE
            )
            
            # Apply all transformations in bulk
            # 1. Remove noise lines (lines matching any noise pattern)
            lines = content.split('\n')
            filtered_lines = []
            for line in lines:
                if not combined_noise_pattern.search(line):
                    # Remove timestamps and clean the line
                    cleaned_line = self.timestamp_regex.sub("", line.rstrip())
                    if cleaned_line:  # Skip empty lines after cleaning
                        filtered_lines.append(cleaned_line)
            
            # 2. Rejoin content and split into semantic chunks
            cleaned_content = '\n'.join(filtered_lines)
            total_lines = len(filtered_lines)
            
            # Create chunks based on content size, not line-by-line processing
            chunk_id = 0
            chunk_size_chars = self.chunk_size_bytes  # Approximate bytes as chars
            
            for i in range(0, len(cleaned_content), chunk_size_chars):
                chunk_content = cleaned_content[i:i + chunk_size_chars]
                if chunk_content.strip():
                    # Create a simplified chunk
                    chunk_lines = [(0, chunk_content)]  # Single entry per chunk for simplicity
                    yield self._create_chunk(build, chunk_id, chunk_lines)
                    chunk_id += 1
            
            processing_time = (time.time() - start_time) * 1000
            logger.info(
                f"FAST MODE: Processed {total_lines} lines → {chunk_id} chunks in {processing_time:.1f}ms for {build.job_name}#{build.build_number}"
            )
            
        except Exception as e:
            logger.error(
                f"Error in fast batch processing for {build.job_name}#{build.build_number}: {e}"
            )
            raise CacheError(f"Fast batch processing failed: {e}")

    def _create_chunk(
        self, build: Build, chunk_id: int, lines: List[Tuple[int, str]]
    ) -> LogChunk:
        """Create a semantic log chunk from lines"""
        if not lines:
            raise ValueError("Cannot create chunk from empty lines")

        start_line = lines[0][0]
        end_line = lines[-1][0]
        content = "\n".join([line[1] for line in lines])

        # Analyze chunk content
        log_level = self._determine_log_level(content)
        pipeline_stage = self._extract_pipeline_stage(content)
        diagnostic_score = self._calculate_diagnostic_score(content)
        timestamp = self._extract_timestamp(content)

        return LogChunk(
            build=build,
            chunk_id=f"{build.job_name}:{build.build_number}:chunk:{chunk_id}",
            content=content,
            start_line=start_line,
            end_line=end_line,
            log_level=log_level,
            pipeline_stage=pipeline_stage,
            timestamp=timestamp,
            diagnostic_score=diagnostic_score,
        )

    def _is_noise_line(self, line: str) -> bool:
        """Check if line is noise that doesn't help with diagnostics"""
        for pattern in self.noise_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                return True
        return False

    def _is_chunk_boundary(self, line: str) -> bool:
        """Detect semantic boundaries for chunk splitting"""
        boundaries = [
            r"\[Pipeline\] \w+",  # Pipeline stage boundaries
            r"^\+\s+",  # Shell command start
            r"Starting build job",
            r"Finished: (SUCCESS|FAILURE|UNSTABLE|ABORTED)",
            r"\[INFO\] BUILD (SUCCESS|FAILURE)",
            r"STEP \d+:",
        ]

        for pattern in boundaries:
            if re.search(pattern, line):
                return True
        return False

    def _determine_log_level(self, content: str) -> str:
        """Determine the severity level of chunk content"""
        for pattern in self.error_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return "ERROR"

        for pattern in self.warning_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return "WARN"

        return "INFO"

    def _extract_pipeline_stage(self, content: str) -> Optional[str]:
        """Extract pipeline stage name from content"""
        stage_patterns = [
            r"\[Pipeline\] stage\s*\{\s*\(([^)]+)\)",
            r"STEP \d+: ([^\n]+)",
            r"Running in stage: ([^\n]+)",
        ]

        for pattern in stage_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return None

    def _extract_timestamp(self, content: str) -> Optional[str]:
        """Extract timestamp from content"""
        timestamp_patterns = [
            r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
            r"(\d{2}:\d{2}:\d{2})",
        ]

        for pattern in timestamp_patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(1)

        return None

    def _calculate_diagnostic_score(self, content: str) -> float:
        """Calculate diagnostic value score (0-1)"""
        score = 0.1  # Base score for any content

        # High value indicators
        if re.search(r"(Exception|Error|FAILED)", content, re.IGNORECASE):
            score += 0.7

        # Stack traces
        if re.search(r"at\s+[\w.]+\(.*:\d+\)", content):
            score += 0.5

        # Build failures
        if re.search(r"BUILD FAILED", content, re.IGNORECASE):
            score += 0.8

        # Test failures
        if re.search(r"(test.*failed|assertion.*failed)", content, re.IGNORECASE):
            score += 0.6

        # Exit codes
        if re.search(r"(exit|return).*code.*[1-9]", content, re.IGNORECASE):
            score += 0.4

        # Performance issues
        if re.search(r"(timeout|out of memory|oom)", content, re.IGNORECASE):
            score += 0.6

        return min(score, 1.0)
