"""
Jenkins Build Failure Diagnostics Tool

This tool provides AI-powered analysis of Jenkins build failures with hierarchical
sub-build discovery and intelligent log processing.

REQUIRED JENKINS PLUGINS FOR FULL FUNCTIONALITY:

Essential Plugins:
- Blue Ocean (blueocean): Required for advanced sub-build discovery
- Pipeline (workflow-aggregator): Core pipeline functionality
- Pipeline: Stage View (pipeline-stage-view): Pipeline visualization

Sub-Build Discovery Plugins:
- Parameterized Trigger (parameterized-trigger): Downstream build detection
- Promoted Builds (promoted-builds): Build promotion workflow tracking
- Build Pipeline (build-pipeline-plugin): Pipeline dependency tracking

The sub-build discovery system uses multiple approaches:
1. Blue Ocean API (/blue/rest/organizations/jenkins/pipelines/{job}/runs/{build}/nodes/)
2. Build actions (hudson.plugins.promoted_builds.BuildInfoExporterAction)
3. Console log parsing (fallback method)

Without these plugins, sub-build discovery will be limited to log parsing only.
"""

import concurrent.futures
import gc
import io
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import jenkins

from ..base import Build, ParameterSpec
from ..jenkins.build_tree import (
    annotate_build_tree,
    flatten_build_tree,
    prune_build_tree_to_failure_paths,
)
from ..cache_manager import CacheManager
from ..diagnostic_config.diagnostic_config import get_diagnostic_config
from ..jenkins.jenkins_client import JenkinsClient
from ..jenkins.job_name_utils import JobNameParser
from ..logging_config import get_component_logger
from ..streaming.log_processor import StreamingLogProcessor
from ..vector_manager import VectorManager
from .base_tools import JenkinsOperationTool

logger = get_component_logger("tools.diagnostics")


# Define the structure for heuristic findings
def create_heuristic_finding(
    category: str,
    pattern_matched: str,
    count: int,
    first_occurrence_line: int,
    recommended_context_window: int,
    log_snippet: str = "",
) -> Dict[str, Any]:
    return {
        "category": category,
        "pattern_matched": pattern_matched,
        "count": count,
        "first_occurrence_line": first_occurrence_line,
        "recommended_context_window": recommended_context_window,
        "log_snippet": log_snippet,
    }


class DiagnoseBuildFailureTool(JenkinsOperationTool):
    """Analyzes build failures with heuristic scanning and semantic search"""

    def __init__(
        self,
        jenkins_client: JenkinsClient,
        cache_manager: CacheManager,
        vector_manager: VectorManager,
        multi_jenkins_manager=None,
    ):
        super().__init__(
            jenkins_client=jenkins_client, multi_jenkins_manager=multi_jenkins_manager
        )
        self.cache_manager = cache_manager
        self.vector_manager = vector_manager
        self.config = get_diagnostic_config()

    @property
    def name(self) -> str:
        return "diagnose_build_failure"

    @property
    def description(self) -> str:
        return (
            "Analyzes a completed (typically failed) Jenkins build. Fetches logs, caches them, "
            "indexes them for semantic search, and runs heuristic scans to identify potential "
            "causes of failure. IMPORTANT: jenkins_url is required because jobs may be load-balanced "
            "across multiple Jenkins servers. Returns a structured summary of findings."
        )

    @property
    def parameters(self) -> List[ParameterSpec]:
        return [
            ParameterSpec(
                "job_name",
                str,
                "Name of the Jenkins job (supports various formats including URL-encoded)",
                required=True,
            ),
            ParameterSpec("build_number", int, "Build number", required=True),
            ParameterSpec(
                "jenkins_url",
                str,
                "Jenkins instance URL (e.g., 'https://jenkins.example.com'). REQUIRED - jobs are load-balanced across multiple servers. Can also be a full build URL.",
                required=True,
            ),
            ParameterSpec(
                "skip_successful_builds",
                bool,
                "Skip log processing for successful builds to improve performance",
                required=False,
                default=True,
            ),
        ]

    # NOTE: Sub-build tree building/flattening is now centralized in
    # [`jenkins_mcp_enterprise.jenkins.build_tree`](jenkins_mcp_enterprise/jenkins/build_tree.py:1).

    def _get_sub_build_information(
        self, current_build: Build, jenkins_client=None
    ) -> Dict[str, Any]:
        """Helper to fetch, format, and generate guidance for sub-builds."""
        sub_build_info_result = {
            "build_tree": {},
            "guidance": "",
            "errors": [],
        }  # Changed to hierarchical structure
        main_build_status_str = current_build.status or "UNKNOWN"
        main_build_url_str = current_build.url or "No URL"

        # Pre-populate the root node so callers always get a consistent shape,
        # even if discovery fails.
        sub_build_info_result["build_tree"] = {
            "job_name": current_build.job_name,
            "build_number": current_build.build_number,
            "status": main_build_status_str,
            "url": current_build.url,
            "depth": 0,
            "children": [],
        }

        try:
            # Canonical: use the Jenkins discovery layer to build a true subtree
            # structure, rather than re-building a tree from a flat list.
            client_to_use = jenkins_client if jenkins_client else self.jenkins_client
            build_tree = client_to_use.get_build_hierarchy(
                current_build.job_name, current_build.build_number, max_depth=15
            )

            # Ensure root node carries the real root build status/url.
            # (SubBuildDiscoverer.get_build_hierarchy historically omitted these for the root.)
            if isinstance(build_tree, dict):
                build_tree["status"] = main_build_status_str
                build_tree["url"] = current_build.url

            # Add common annotations (depth/parent/failed)
            status_config = (self.config.config.display.get("status_display", {}) or {})

            annotate_build_tree(
                build_tree,
                # Treat common non-success end states as failures so pruning/guidance works.
                failure_statuses={"FAILURE", "UNSTABLE", "ABORTED"},
                status_unknown_placeholder=status_config.get(
                    "unknown_placeholder", "UNKNOWN"
                ),
            )

            sub_build_info_result["build_tree"] = build_tree

        except jenkins.JenkinsException as e:
            error_msg = f"Error fetching sub-build hierarchy for {current_build.job_name} #{current_build.build_number}: {str(e)}"
            sub_build_info_result["errors"].append(error_msg)
            sub_build_info_result["guidance"] = (
                f"Could not retrieve sub-build information due to an error: {str(e)}"
            )
            return sub_build_info_result
        except Exception as e:
            error_msg = f"An unexpected error occurred while fetching sub-build hierarchy for {current_build.job_name} #{current_build.build_number}: {str(e)}"
            sub_build_info_result["errors"].append(error_msg)
            sub_build_info_result["guidance"] = (
                "Could not retrieve sub-build information due to an unexpected error."
            )
            return sub_build_info_result

        # Generate guidance based on hierarchical structure
        all_builds = flatten_build_tree(sub_build_info_result["build_tree"])
        failed_builds = [b for b in all_builds if b.get("failed")]

        if len(all_builds) <= 1:
            sub_build_info_result["guidance"] = (
                f"No sub-builds were found for {current_build.job_name} #{current_build.build_number}."
            )
            return sub_build_info_result

        if not failed_builds:
            sub_build_info_result["guidance"] = (
                f"No builds reported a FAILURE status. The issue likely originated in the main build '{current_build.job_name} #{current_build.build_number}'."
            )
        else:
            # Find the deepest failures
            max_depth = max(b["depth"] for b in failed_builds)
            deepest_failures = [b for b in failed_builds if b["depth"] == max_depth]

            if len(deepest_failures) == 1:
                failure = deepest_failures[0]
                failure_info_str = f"'{failure['job_name']} #{failure['build_number']}'"
                sub_build_info_result["guidance"] = (
                    f"The deepest build failure is {failure_info_str} at depth {max_depth}. Consider starting your investigation there. You can access its console log or trigger a new diagnosis for it if necessary."
                )
            else:
                failure_names = [
                    f"'{b['job_name']} #{b['build_number']}' " for b in deepest_failures
                ]
                if len(failure_names) > 1:
                    failure_info_str = (
                        " and ".join([", ".join(failure_names[:-1]), failure_names[-1]])
                        if len(failure_names) > 2
                        else " and ".join(failure_names)
                    )
                else:
                    failure_info_str = failure_names[0]

                sub_build_info_result["guidance"] = (
                    f"The deepest build failures are {failure_info_str.strip()} at depth {max_depth}. Prioritize investigating these. You can access their console logs or trigger new diagnoses for them."
                )

        return sub_build_info_result

    def _execute_impl(self, **kwargs) -> Dict[str, Any]:
        """Execute build failure diagnosis with improved structure"""
        start_time = time.time()
        
        # Step 1: Parse and normalize inputs
        step_start = time.time()
        params = self._parse_and_normalize_inputs(kwargs)
        logger.info(f"TIMING: Step 1 (parse inputs) took {time.time() - step_start:.2f}s")
        if "error" in params:
            return params

        # Step 2: Initialize result structure
        step_start = time.time()
        result = self._initialize_result_structure(params)
        logger.info(f"TIMING: Step 2 (initialize result) took {time.time() - step_start:.2f}s")

        # Step 3: Get build information
        step_start = time.time()
        build_info = self._get_build_information(params, result)
        logger.info(f"TIMING: Step 3 (get build info) took {time.time() - step_start:.2f}s")
        if build_info is None:
            return result

        # Step 4: Check if we should skip successful builds
        step_start = time.time()
        if self._should_skip_build(
            build_info, params["skip_successful_builds"], result
        ):
            logger.info(f"TIMING: Step 4 (check skip) took {time.time() - step_start:.2f}s")
            return result
        logger.info(f"TIMING: Step 4 (check skip) took {time.time() - step_start:.2f}s")

        # Step 5: Process build hierarchy and logs
        step_start = time.time()
        (
            sub_builds,
            error_analysis,
            recommendations,
            build_summary,
        ) = self._process_build_analysis(params, build_info, result)
        logger.info(
            f"TIMING: Step 5 (build analysis) took {time.time() - step_start:.2f}s"
        )

        result["sub_builds"] = sub_builds
        result["error_analysis"] = error_analysis
        result["recommendations"] = recommendations
        result["build_summary"] = build_summary

        total_time = time.time() - start_time
        logger.info(f"TIMING: Total diagnosis execution took {total_time:.2f}s")

        return result

    def _parse_and_normalize_inputs(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Parse and normalize input parameters"""
        job_name = kwargs["job_name"]
        build_number = kwargs["build_number"]
        jenkins_url = kwargs.get("jenkins_url")
        skip_successful_builds = kwargs.get("skip_successful_builds", True)

        # Store original values
        original_values = {
            "job_name": job_name,
            "build_number": build_number,
            "jenkins_url": jenkins_url,
        }

        # Extract from URL if needed
        if jenkins_url and ("/job/" in jenkins_url or "%2F" in jenkins_url):
            extracted_job, extracted_build = JobNameParser.extract_from_url(jenkins_url)
            if extracted_job and extracted_build:
                job_name = extracted_job
                build_number = extracted_build
                if "/job/" in jenkins_url:
                    jenkins_url = jenkins_url.split("/job/")[0]
                logger.info(
                    f"Extracted from URL: job='{job_name}', build={build_number}, base_url='{jenkins_url}'"
                )

        # Normalize job name
        job_name = JobNameParser.normalize_job_name(job_name)
        logger.info(
            f"Normalized job name: '{original_values['job_name']}' -> '{job_name}'"
        )

        # Resolve Jenkins instance
        try:
            instance_id = self.resolve_jenkins_instance(jenkins_url)
        except Exception as e:
            return {
                "job_name": job_name,
                "build_number": build_number,
                "jenkins_url": jenkins_url,
                "original_input": original_values,
                "error": f"Jenkins instance resolution failed: {str(e)}",
                "instructions": self.get_instance_instructions(),
            }

        return {
            "job_name": job_name,
            "build_number": build_number,
            "jenkins_url": jenkins_url,
            "skip_successful_builds": skip_successful_builds,
            "instance_id": instance_id,
            "original_input": original_values,
        }

    def _initialize_result_structure(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Initialize the result structure"""
        return {
            "job_name": params["job_name"],
            "build_number": params["build_number"],
            "overall_status_from_jenkins": "UNKNOWN",
            "log_analysis_status": "PENDING",
            "recommendations": [],
            "build_summary": "",
            "errors": [],
            "sub_build_information": {
                "guidance": "",
                "errors": [],
                "build_tree": {},
            },
        }

    def _get_build_information(
        self, params: Dict[str, Any], result: Dict[str, Any]
    ) -> Optional[Build]:
        """Get build information from Jenkins"""
        try:
            jenkins_client = self.get_jenkins_client(params["instance_id"])
            build_info_dict = jenkins_client.get_build_info_dict(
                params["job_name"], params["build_number"]
            )

            build_url = build_info_dict.get("url")
            build_status = build_info_dict.get(
                "result",
                "IN_PROGRESS" if build_info_dict.get("building") else "UNKNOWN",
            )

            result["overall_status_from_jenkins"] = build_status

            return Build(
                job_name=params["job_name"],
                build_number=params["build_number"],
                status=build_status,
                url=build_url,
            )

        except Exception as e:
            result["overall_status_from_jenkins"] = "ERROR_FETCHING_STATUS"
            result["log_analysis_status"] = "PREREQ_ERROR"
            result["errors"].append(f"Failed to fetch build status: {str(e)}")
            result["sub_build_information"][
                "guidance"
            ] = "Could not retrieve main build status, sub-build analysis aborted."
            result["sub_build_information"]["errors"].append(
                f"Main build status fetch failed: {str(e)}"
            )
            return None

    def _should_skip_build(
        self, build: Build, skip_successful: bool, result: Dict[str, Any]
    ) -> bool:
        """Check if build should be skipped based on success status"""
        if skip_successful and build.status == "SUCCESS":
            result["log_analysis_status"] = "SKIPPED_SUCCESS"
            result["summary"] = (
                f"Build {build.job_name} #{build.build_number} completed successfully. "
                "Diagnosis skipped as requested (skip_successful_builds=True)."
            )
            result["recommendations"] = [
                "✅ Build completed successfully - no issues detected",
                "💡 To analyze successful builds, set skip_successful_builds=False",
            ]
            return True
        return False

    def _get_error_analysis(self, log_chunks: List, root_build: Build) -> Dict[str, Any]:
        """Analyze processed log chunks to extract errors and semantic highlights.

        Critical: this method must NEVER return huge blobs of log content.

        Prior behavior returned `chunk.content` for each chunk containing "ERROR".
        In fast processing mode, chunk.content can be ~1MB, and multiple entries
        can balloon responses into multi-million-token payloads.
        """

        def _truncate(text: str, max_chars: int) -> str:
            if not text:
                return ""
            if len(text) <= max_chars:
                return text
            return text[:max_chars] + "..."

        # Limits (configurable via YAML `error_analysis.*` when present; safe defaults otherwise)
        error_cfg = getattr(self.config.config, "error_analysis", {}) or {}
        ctx_cfg = getattr(self.config.config, "context", None)
        display_trunc = (getattr(self.config.config, "display", {}) or {}).get(
            "truncation", {}
        )

        max_error_entries = int(error_cfg.get("max_error_entries", 10))
        max_error_line_chars = int(error_cfg.get("max_error_line_chars", 500))
        # Use token-based config if available; fall back to a sane ceiling
        max_context_chars = int(
            error_cfg.get(
                "max_error_context_chars",
                (getattr(ctx_cfg, "max_tokens_per_chunk", 500) * 4) if ctx_cfg else 2000,
            )
        )
        context_window = int(error_cfg.get("context_window_lines", 5))
        # Display-level truncation is used as a minimum floor (avoid returning >400 char previews if configured)
        max_context_chars = max(
            int(display_trunc.get("max_display_length", 400)), max_context_chars
        )

        # Focused match patterns (avoid collecting huge "ERROR" blocks)
        # Use word boundaries / common markers to avoid false positives like "logErrors".
        error_line_pattern = re.compile(
            r"(\[ERROR\]|\bERROR\b|\bException\b|\bFAILED\b|\bFATAL\b|\bBUILD FAILED\b|AbortException)",
            re.IGNORECASE,
        )

        # Prefer high-diagnostic chunks first. Do NOT require `chunk.log_level == "ERROR"`
        # because some processors/test logs emit error markers like "[ERROR]" while
        # classifying the chunk as INFO.
        def _chunk_has_error_line(c) -> bool:
            content = (getattr(c, "content", "") or "")
            return bool(content and error_line_pattern.search(content))

        candidate_chunks = [c for c in log_chunks if _chunk_has_error_line(c)]

        # Sort with a small bias for chunks explicitly tagged as ERROR, then by diagnostic_score.
        sorted_chunks = sorted(
            candidate_chunks,
            key=lambda c: (
                1 if getattr(c, "log_level", "") == "ERROR" else 0,
                float(getattr(c, "diagnostic_score", 0.0) or 0.0),
            ),
            reverse=True,
        )

        errors: List[Dict[str, Any]] = []

        for chunk in sorted_chunks:
            if len(errors) >= max_error_entries:
                break

            content = (getattr(chunk, "content", "") or "")
            if not content:
                continue

            # Find a matching line in this chunk and capture a small context window.
            # Prefer a line that contains the literal token "ERROR" (many tests/logs
            # include "[ERROR] ..."), then fall back to other failure indicators.
            lines = content.splitlines()
            match_index: Optional[int] = None
            match_line: str = ""

            error_priority_pattern = re.compile(r"(\[ERROR\]|\bERROR\b)", re.IGNORECASE)

            # Pass 1: prefer explicit ERROR lines
            for i, line in enumerate(lines):
                if error_priority_pattern.search(line):
                    match_index = i
                    match_line = line
                    break

            # Pass 2: broader failure patterns
            if match_index is None:
                for i, line in enumerate(lines):
                    if error_line_pattern.search(line):
                        match_index = i
                        match_line = line
                        break

            if match_index is None:
                continue

            start_i = max(0, match_index - context_window)
            end_i = min(len(lines), match_index + context_window + 1)
            context_snippet = "\n".join(lines[start_i:end_i])

            # Best-effort line number (fast mode uses start_line=0)
            start_line = int(getattr(chunk, "start_line", 0) or 0)
            line_number = start_line + match_index if start_line > 0 else None

            errors.append(
                {
                    "job_name": chunk.build.job_name,
                    "build_number": chunk.build.build_number,
                    "chunk_id": getattr(chunk, "chunk_id", ""),
                    "line_number": line_number,
                    "match_text": _truncate(match_line, max_error_line_chars),
                    "context": _truncate(context_snippet, max_context_chars),
                }
            )

        return {
            "errors": errors,
            "semantic_highlights": self._generate_semantic_highlights(log_chunks, root_build),
        }

    def _process_build_analysis(
        self, params: Dict[str, Any], build: Build, result: Dict[str, Any]
    ) -> Tuple[List[Dict], Dict, List, str]:
        """Process the main build analysis including hierarchy and logs."""
        # Get jenkins client for sub-build discovery
        step_start = time.time()
        jenkins_client = self.get_jenkins_client(params["instance_id"])
        logger.info(f"TIMING: Get Jenkins client took {time.time() - step_start:.2f}s")

        # Get sub-build information
        step_start = time.time()
        sub_build_info = self._get_sub_build_information(build, jenkins_client)
        logger.info(f"TIMING: Sub-build discovery took {time.time() - step_start:.2f}s")

        # Presentation rule:
        # - If skip_successful_builds is True (default), only show the paths that lead to failing builds.
        # - If skip_successful_builds is False, show the full tree.
        presentation_tree = sub_build_info.get("build_tree") or {}
        if params.get("skip_successful_builds", True):
            # Ensure `is_failure` exists (added by annotate_build_tree in _get_sub_build_information).
            presentation_tree = prune_build_tree_to_failure_paths(presentation_tree)

        # Remove parent pointers from the output to save tokens.
        # The hierarchical containment already implies parentage.
        def _strip_parent_fields(n: Dict[str, Any]) -> None:
            if not isinstance(n, dict):
                return
            n.pop("parent_job_name", None)
            n.pop("parent_build_number", None)
            for c in (n.get("children", []) or []):
                if isinstance(c, dict):
                    _strip_parent_fields(c)

        if isinstance(presentation_tree, dict):
            _strip_parent_fields(presentation_tree)

        # Store the pruned/full tree for output.
        sub_build_info["build_tree"] = presentation_tree
        result["sub_build_information"] = sub_build_info

        # Build hierarchy for analysis - extract all builds from the (possibly pruned) tree
        hierarchy_dicts = flatten_build_tree(sub_build_info["build_tree"])

        # Convert hierarchy dictionaries to Build objects for processing
        hierarchy_builds: List[Build] = []
        for build_dict in hierarchy_dicts:
            hierarchy_builds.append(
                Build(
                    job_name=build_dict["job_name"],
                    build_number=build_dict["build_number"],
                    status=build_dict.get("status", "UNKNOWN"),
                    url=build_dict.get("url", ""),
                )
            )

        # Process logs
        try:
            step_start = time.time()
            log_processor = StreamingLogProcessor()
            # Set fast mode when vector search is disabled
            log_processor._vector_search_disabled = getattr(
                self.vector_manager, "vector_search_disabled", True
            )
            logger.info(f"TIMING: Create log processor took {time.time() - step_start:.2f}s")

            step_start = time.time()
            log_chunks = self._process_logs_parallel_sync(
                hierarchy_builds,
                log_processor,
                jenkins_client,
                params["skip_successful_builds"],
                result,
            )
            logger.info(f"TIMING: Parallel log processing took {time.time() - step_start:.2f}s")

            # Generate build summary
            step_start = time.time()
            build_summary = self._generate_build_summary(build, hierarchy_builds)
            logger.info(
                f"TIMING: Generate build summary took {time.time() - step_start:.2f}s"
            )

            # Generate recommendations
            step_start = time.time()
            recommendations = self._generate_recommendations(
                build, hierarchy_dicts, log_chunks
            )
            logger.info(
                f"TIMING: Generate recommendations took {time.time() - step_start:.2f}s"
            )

            # Get error analysis
            # When we are *not* including successful branches (default), focus error extraction
            # on the deepest failing build(s) so we don't match noisy "error-like" lines from
            # the parent pipeline.
            failure_statuses = {"FAILURE", "UNSTABLE", "ABORTED"}
            focused_chunks = log_chunks

            # Always attempt to focus error extraction on the deepest failing build(s)
            # when any failures exist, regardless of whether the caller asked to include
            # successful builds.
            failing_nodes = [
                b
                for b in hierarchy_dicts
                if b.get("failed") or b.get("status") in failure_statuses
            ]
            if failing_nodes:
                max_depth = max(int(b.get("depth") or 0) for b in failing_nodes)
                focus_keys = {
                    (b.get("job_name"), int(b.get("build_number") or 0))
                    for b in failing_nodes
                    if int(b.get("depth") or 0) == max_depth
                }
                candidate = [
                    c
                    for c in log_chunks
                    if (
                        getattr(getattr(c, "build", None), "job_name", None),
                        int(getattr(getattr(c, "build", None), "build_number", 0) or 0),
                    )
                    in focus_keys
                ]
                if candidate:
                    focused_chunks = candidate

            error_analysis = self._get_error_analysis(focused_chunks, build)

            result["log_analysis_status"] = "COMPLETED"

            return hierarchy_dicts, error_analysis, recommendations, build_summary

        except Exception as e:
            result["log_analysis_status"] = "FAILED"
            result["errors"].append(f"Log processing failed: {str(e)}")
            logger.error(f"Log processing failed: {e}", exc_info=True)
            return [], {}, [], ""

    def _generate_build_summary(self, root_build: Build, hierarchy: List[Build]) -> str:
        """Generate concise build summary"""
        failure_statuses = {"FAILURE", "UNSTABLE", "ABORTED"}
        failed_builds = [b for b in hierarchy if b.status in failure_statuses]

        # Get configuration values
        max_failures = self.config.config.summary.max_failures_displayed
        failure_template = self.config.config.summary.failure_list_template
        overflow_template = self.config.config.summary.overflow_message_template
        precision = self.config.config.summary.success_rate_precision

        summary = f"""
BUILD ANALYSIS SUMMARY
======================
Root Pipeline: {root_build.job_name} #{root_build.build_number}
Status: {root_build.status}
URL: {root_build.url}

Pipeline Hierarchy:
- Total Sub-builds: {len(hierarchy)}
- Failed Sub-builds: {len(failed_builds)}
- Success Rate: {((len(hierarchy) - len(failed_builds)) / len(hierarchy) * 100):.{precision}f}%

Primary Failure Points:
"""
        for build in failed_builds[:max_failures]:
            summary += failure_template.format(
                job_name=build.job_name,
                build_number=build.build_number,
                status=build.status,
            )

        if len(failed_builds) > max_failures:
            summary += overflow_template.format(count=len(failed_builds) - max_failures)

        return summary

    # _generate_hierarchy_data removed - functionality integrated into sub_build_information.builds

    def _generate_semantic_highlights(self, chunks: List, root_build: Build) -> List[str]:
        """Generate semantic search highlights (or fall back to pattern extraction)."""
        highlights: List[str] = []

        vector_manager = self.vector_manager
        if not vector_manager or getattr(vector_manager, "vector_search_disabled", True):
            return self._extract_key_failure_patterns(chunks)

        try:
            search_queries = self.config.get_semantic_search_queries()

            for query in search_queries:
                try:
                    results = vector_manager.search_hierarchical(
                        query_text=query,
                        root_build=root_build,
                        min_diagnostic_score=self.config.config.semantic_search.min_diagnostic_score,
                        top_k=self.config.config.semantic_search.max_results_per_query,
                    )

                    for result in results:
                        content = result.get("payload", {}).get("content", "")
                        if (
                            content
                            and len(content)
                            > self.config.config.semantic_search.min_content_length
                        ):
                            job_name = result.get("payload", {}).get("job_name", "unknown")
                            build_num = result.get("payload", {}).get("build_number", "unknown")
                            score = result.get("score", 0)

                            preview_length = self.config.config.semantic_search.max_content_preview
                            highlight = (
                                f"🔍 {job_name} #{build_num} (relevance: {score:.2f})\n"
                                f"{content[:preview_length]}..."
                            )
                            highlights.append(highlight)

                except Exception as e:
                    logger.debug(f"Search failed for '{query}': {e}")
                    continue

            return highlights[: self.config.config.semantic_search.max_total_highlights]

        except Exception as e:
            logger.warning(f"Semantic search failed: {e}")
            return self._extract_key_failure_patterns(chunks)

    def _extract_key_failure_patterns(self, chunks: List) -> List[str]:
        """Fallback: extract key failure patterns from chunks"""
        patterns = []

        # Get configuration values
        max_chunks = self.config.config.build_processing.chunks.get(
            "max_chunks_for_analysis", 20  # Increased for comprehensive analysis
        )
        failure_patterns = self.config.get_failure_patterns()
        max_patterns = self.config.config.failure_patterns.max_fallback_patterns
        max_preview = self.config.config.failure_patterns.max_pattern_preview
        
        # Score and rank chunks based on failure patterns only
        scored_chunks = []
        for chunk in chunks[:max_chunks * 2]:  # Analyze more chunks for better results
            content = chunk.content.lower()
            score = 0
            matched_patterns = []
            
            # Score based on failure patterns
            for pattern in failure_patterns:
                if pattern.lower() in content:
                    score += 2
                    matched_patterns.append(pattern)
            
            # Boost score for stack traces, exceptions, and error codes
            if any(indicator in content for indicator in ['exception', 'error', 'failed', 'stack trace', 'at java.', 'caused by']):
                score += 3
                
            # Boost score for build-specific failures
            if any(build_term in content for build_term in ['build failed', 'compilation error', 'test failed', 'timeout']):
                score += 2
            
            if score > 0:
                scored_chunks.append((score, chunk, matched_patterns))
        
        # Sort by score (highest first) and take the best ones
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        
        for score, chunk, matched_patterns in scored_chunks[:max_patterns]:
            # Create pattern description with relevance info
            relevance_info = f"relevance: {score:.1f}"
            pattern_info = f"patterns: {', '.join(set(matched_patterns[:3]))}" if matched_patterns else ""
            
            pattern = f"🔍 {chunk.build.job_name} #{chunk.build.build_number} ({relevance_info})\n{chunk.content[:max_preview]}..."
            if pattern_info:
                pattern += f"\n📋 {pattern_info}"
            
            patterns.append(pattern)

        return patterns

    def _generate_recommendations(
        self, root_build: Build, hierarchy_dicts: List[Dict[str, Any]], chunks: List
    ) -> List[str]:
        """Generate actionable recommendations based on failure patterns.

        Important:
        - `hierarchy_dicts` contains `depth`/`is_failure` metadata.
        - `chunks` are `LogChunk` objects.
        """
        failure_statuses = {"FAILURE", "UNSTABLE", "ABORTED"}
        failed_builds = [
            b
            for b in hierarchy_dicts
            if b.get("failed") or b.get("status") in failure_statuses
        ]

        if not failed_builds:
            return ["✅ No build failures detected in this pipeline"]

        # Primary content source for pattern matching: cached full console log for the root build.
        content_for_matching: str = ""
        try:
            cache_path = self.cache_manager.get_path(root_build)
            with open(cache_path, "r", encoding="utf-8", errors="ignore") as f:
                content_for_matching = (f.read() or "").lower()
        except FileNotFoundError:
            content_for_matching = ""
        except Exception as e:
            return [f"Error reading log file: {e}"]

        # Fallback: limited content from processed chunks
        if not content_for_matching:
            max_content_chunks = self.config.config.build_processing.chunks.get(
                "max_chunks_for_content", 20
            )
            content_for_matching = " ".join(
                [(c.content or "").lower() for c in chunks[:max_content_chunks]]
            )

        recommendations: List[str] = []

        # Pattern-based recommendations using the configured diagnostic rules
        recommendations.extend(self._get_pattern_recommendations(content_for_matching))

        # Priority guidance based on deepest failure (uses depth from hierarchy dicts)
        priority_rec = self._get_priority_recommendation(failed_builds)
        if priority_rec:
            recommendations.insert(0, priority_rec)

        # Generic guidance if no specific recommendations found
        if not recommendations:
            recommendations.append(
                "No specific failure patterns found. Review the build logs manually for more details."
            )

        # Standard investigation guidance
        recommendations.append(self._get_investigation_guidance())

        return recommendations[: self.config.config.recommendations.max_recommendations]

    def _get_pattern_recommendations(self, content: str) -> List[str]:
        """Extract recommendations with regex capture group interpolation"""
        recommendations = []
        pattern_configs = self.config.get_pattern_recommendations()
        
        for pattern_name, pattern_config in pattern_configs.items():
            matches, captured_groups = self._matches_pattern_conditions(content, pattern_config.conditions)
            
            if matches:
                # Use interpolated message from condition if available
                if "_interpolated_message" in captured_groups:
                    # Skip empty interpolated messages
                    if captured_groups["_interpolated_message"].strip():
                        recommendations.append(captured_groups["_interpolated_message"])
                elif captured_groups and "{" in pattern_config.message:
                    # Interpolate the main message with captured groups
                    interpolated_message = pattern_config.message.format(**captured_groups)
                    if interpolated_message.strip():
                        recommendations.append(interpolated_message)
                else:
                    # No interpolation needed or possible
                    if pattern_config.message.strip():
                        recommendations.append(pattern_config.message)
        
        return recommendations

    def _matches_pattern_conditions(self, content: str, conditions: List) -> Tuple[bool, Dict[str, str]]:
        """
        Enhanced pattern matching with regex capture group support
        
        Args:
            content: The content to match against
            conditions: List of conditions (strings, lists, or regex dicts)
        
        Returns:
            Tuple of (matches: bool, captured_groups: Dict[str, str])
        """
        all_captured_groups = {}
        
        for condition in conditions:
            if isinstance(condition, str):
                # Backward compatible: simple string condition
                if condition.lower() in content.lower():
                    return True, {}
                    
            elif isinstance(condition, list):
                # Backward compatible: OR condition
                if any(cond.lower() in content.lower() for cond in condition):
                    return True, {}
                    
            elif isinstance(condition, dict) and condition.get("type") == "regex":
                # New: regex with capture groups
                pattern = condition["pattern"]
                flags = condition.get("flags", re.IGNORECASE)
                
                try:
                    compiled_pattern = re.compile(pattern, flags)
                    match = compiled_pattern.search(content)
                    
                    if match:
                        # Capture named groups
                        captured_groups = match.groupdict()
                        
                        # Capture numbered groups if no named groups
                        if not captured_groups and match.groups():
                            captured_groups = {f"group_{i}": group or "" for i, group in enumerate(match.groups(), 1)}
                        
                        all_captured_groups.update(captured_groups)
                        
                        # If this condition has a message template, store it for later use
                        if condition.get("message_template"):
                            try:
                                interpolated = condition["message_template"].format(**captured_groups)
                                all_captured_groups["_interpolated_message"] = interpolated
                            except KeyError as e:
                                logger.warning(f"Failed to interpolate message template: missing key {e}")
                            except Exception as e:
                                logger.warning(f"Failed to interpolate message template: {e}")
                        
                        return True, all_captured_groups
                        
                except re.error as e:
                    logger.error(f"Invalid regex pattern '{pattern}': {e}")
                    continue
        
        return False, {}


    def _get_priority_recommendation(self, failed_builds: List[Dict]) -> Optional[str]:
        """Get priority recommendation based on deepest failure"""
        if not failed_builds:
            return None

        # Find the deepest failure(s)
        max_depth = max(b["depth"] for b in failed_builds)
        deepest_failures = [b for b in failed_builds if b["depth"] == max_depth]

        if len(deepest_failures) == 1:
            failure = deepest_failures[0]
            return f"🎯 **Priority**: Start with the deepest failure: '{failure['job_name']} #{failure['build_number']}'."
        else:
            failure_names = [
                f"'{b['job_name']} #{b['build_number']}'" for b in deepest_failures
            ]
            return f"🎯 **Priority**: Investigate the deepest failures: {', '.join(failure_names)}."

        return None

    def _get_investigation_guidance(self) -> str:
        """Return standard investigation guidance"""
        return self.config.get_investigation_guidance()

    def _process_logs_parallel_sync(
        self,
        hierarchy_builds: List[Build],
        processor: StreamingLogProcessor,
        jenkins_client: JenkinsClient,
        skip_successful_builds: bool,
        result: Dict[str, Any],
    ) -> List:
        """Process build logs in parallel using ThreadPoolExecutor (synchronous)"""
        all_chunks = []

        # Filter builds that need processing
        builds_to_process = []
        for build in hierarchy_builds:
            if skip_successful_builds and build.status == "SUCCESS":
                logger.info(
                    f"Skipping successful build {build.job_name}#{build.build_number}"
                )
                continue
            builds_to_process.append(build)

        if not builds_to_process:
            return all_chunks

        # Process builds in parallel batches to avoid overwhelming Jenkins
        max_batch_size = self.config.config.build_processing.parallel.get(
            "max_batch_size", 5
        )
        max_workers = self.config.config.build_processing.parallel.get("max_workers", 5)
        _ = min(
            max_batch_size, len(builds_to_process)
        )  # batch_size calculated but not used

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Create futures for all builds
            futures = []
            for build in builds_to_process:
                future = executor.submit(
                    self._process_single_build_logs, build, processor, jenkins_client
                )
                futures.append((future, build))

            # Wait for all futures to complete
            for future, build in futures:
                try:
                    chunks, log_path = future.result()
                    all_chunks.extend(chunks)
                    if log_path and not result.get("log_cached_path"):
                        result["log_cached_path"] = log_path
                except Exception as e:
                    logger.warning(
                        f"Failed to process logs for {build.job_name}#{build.build_number}: {e}"
                    )
                    result["errors"].append(
                        f"Log processing failed for {build.job_name}#{build.build_number}: {e}"
                    )

        logger.info(
            f"Parallel processing completed: {len(all_chunks)} total chunks from {len(builds_to_process)} builds"
        )
        
        # Force garbage collection after processing large builds to prevent memory accumulation
        if len(builds_to_process) > 3 or len(all_chunks) > 1000:
            logger.info("Running garbage collection after large build processing")
            gc.collect()

        return all_chunks

    def _process_single_build_logs(
        self,
        build: Build,
        processor: StreamingLogProcessor,
        jenkins_client: JenkinsClient,
    ) -> Tuple[List, Optional[str]]:
        """Process logs for a single build (thread-safe)"""
        build_start = time.time()
        chunks = []
        log_path = None

        try:
            # Check if logs are already cached first
            try:
                cache_start = time.time()
                log_path = self.cache_manager.fetch(jenkins_client, build)
                logger.info(f"TIMING: Cache fetch for {build.job_name}#{build.build_number} took {time.time() - cache_start:.2f}s")

                # Check if cached file exists and is not empty
                if log_path.exists() and log_path.stat().st_size > 0:
                    logger.info(
                        f"Using cached logs for {build.job_name}#{build.build_number}"
                    )
                    # Process directly from file without loading into memory
                    file_handle = open(log_path, "r", errors="ignore")
                else:
                    # Cache miss - need to fetch from Jenkins
                    logger.info(
                        f"Cache miss for {build.job_name}#{build.build_number}, fetching from Jenkins"
                    )
                    # Re-fetch through cache manager
                    log_path = self.cache_manager.fetch(jenkins_client, build)
                    file_handle = open(log_path, "r", errors="ignore")

                logger.info(f"Starting chunk processing for {build.job_name}#{build.build_number}")
                processing_start = time.time()

            except Exception as cache_e:
                logger.warning(
                    f"Cache check failed for {build.job_name}#{build.build_number}: {cache_e}"
                )
                # If cache fails, return empty chunks
                return chunks, str(log_path) if log_path else None

            # Stream process logs into semantic chunks
            try:
                # Process chunks as generator to avoid loading all into memory
                # Apply chunk limits to prevent memory accumulation
                max_chunks = self.config.config.build_processing.chunks.get("max_chunks_for_content", 1000)
                chunk_count = 0
                
                for chunk in processor.process_streaming(file_handle, build):
                    if chunk_count >= max_chunks:
                        logger.info(f"Reached max chunk limit ({max_chunks}) for {build.job_name}#{build.build_number}")
                        break
                    chunks.append(chunk)
                    chunk_count += 1
                    
                    # Log progress every 100 chunks to detect hangs
                    if chunk_count % 100 == 0:
                        elapsed = time.time() - processing_start
                        logger.info(f"Progress: {chunk_count} chunks processed in {elapsed:.1f}s for {build.job_name}#{build.build_number}")
                    
                logger.info(
                    f"Processed {chunk_count} chunks from {build.job_name}#{build.build_number} in {time.time() - processing_start:.1f}s"
                )
            finally:
                # Ensure file handle is always closed
                if 'file_handle' in locals():
                    file_handle.close()

        except Exception as e:
            logger.warning(
                f"Failed to process logs for {build.job_name}#{build.build_number}: {e}"
            )
            raise e

        return chunks, str(log_path) if log_path else None

    def _process_logs_sequential(
        self,
        hierarchy_builds: List[Build],
        processor: StreamingLogProcessor,
        jenkins_client: JenkinsClient,
        skip_successful_builds: bool,
        result: Dict[str, Any],
    ) -> List:
        """Sequential log processing (fallback method)"""
        all_chunks = []

        for build in hierarchy_builds:
            try:
                # Skip log processing for successful builds if enabled
                if skip_successful_builds and build.status == "SUCCESS":
                    logger.info(
                        f"Skipping successful build {build.job_name}#{build.build_number}"
                    )
                    continue

                chunks, log_path = self._process_single_build_logs(
                    build, processor, jenkins_client
                )
                all_chunks.extend(chunks)

                if log_path and not result.get("log_cached_path"):
                    result["log_cached_path"] = log_path

            except Exception as e:
                logger.warning(
                    f"Failed to process logs for {build.job_name}#{build.build_number}: {e}"
                )
                result["errors"].append(
                    f"Log processing failed for {build.job_name}#{build.build_number}: {e}"
                )

        return all_chunks
