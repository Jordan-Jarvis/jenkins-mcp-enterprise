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
import io
from typing import Any, Dict, List, Optional, Tuple

import jenkins

from ..base import Build, ParameterSpec, SubBuild
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

    def _build_hierarchical_structure(
        self, sub_builds: List[SubBuild], parent_node: Dict[str, Any]
    ) -> None:
        """Builds hierarchical folder-like structure by finding children and recursively building their subtrees."""

        # Find direct children of the current parent
        direct_children = sorted(
            [
                sb
                for sb in sub_builds
                if sb.parent_job_name == parent_node["job_name"]
                and sb.parent_build_number == parent_node["build_number"]
            ],
            key=lambda sb: (sb.job_name, sb.build_number),
        )

        for child_sb in direct_children:
            # Generate display text with proper indentation using configuration
            display_config = self.config.config.display.get("hierarchy", {})
            indent_spaces = display_config.get("indent_spaces_per_depth", 4)
            connector = display_config.get("connector_symbol", "└── ")
            prefix_adjustment = display_config.get("prefix_adjustment", 2)

            status_config = self.config.config.display.get("status_display", {})
            status_placeholder = status_config.get("unknown_placeholder", "UNKNOWN")
            url_placeholder = status_config.get("url_placeholder", "No URL")

            prefix_spaces = (
                ((child_sb.depth - 1) * indent_spaces + prefix_adjustment)
                if child_sb.depth > 0
                else 0
            )
            prefix = " " * prefix_spaces

            status_str = child_sb.status or status_placeholder
            url_str = child_sb.url or url_placeholder
            display_text = f"{prefix}{connector}Job: {child_sb.job_name}, Build: #{child_sb.build_number}, Status: {status_str}, URL: {url_str}"

            # Create child node
            failure_indicator = status_config.get("failure_indicator", "FAILURE")

            child_node = {
                "job_name": child_sb.job_name,
                "build_number": child_sb.build_number,
                "status": status_str,
                "url": url_str,
                "depth": child_sb.depth,
                "display_text": display_text,
                "is_failure": status_str == failure_indicator,
                "parent_job_name": child_sb.parent_job_name,
                "parent_build_number": child_sb.parent_build_number,
                "children": [],
            }

            # Add child to parent's children list
            parent_node["children"].append(child_node)

            # Recursively build children for this child
            self._build_hierarchical_structure(sub_builds, child_node)

    def _flatten_build_tree(self, build_node: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Flattens the hierarchical build tree for analysis purposes."""
        result = [build_node]
        for child in build_node.get("children", []):
            result.extend(self._flatten_build_tree(child))
        return result

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

        # Create the main build as the root of the hierarchy
        main_build_entry = {
            "job_name": current_build.job_name,
            "build_number": current_build.build_number,
            "status": main_build_status_str,
            "url": main_build_url_str,
            "depth": 0,
            "display_text": f"Job: {current_build.job_name}, Build: #{current_build.build_number}, Status: {main_build_status_str}, URL: {main_build_url_str}",
            "is_failure": main_build_status_str == "FAILURE",
            "children": [],
        }
        sub_build_info_result["build_tree"] = main_build_entry

        sub_builds_list: List[SubBuild] = []
        try:
            # Use current_build object as per JenkinsClient.list_sub_builds signature
            # Use the provided jenkins_client or fallback to default
            client_to_use = jenkins_client if jenkins_client else self.jenkins_client
            sub_builds_list = client_to_use.list_sub_builds(current_build)
        except jenkins.JenkinsException as e:
            error_msg = f"Error fetching sub-builds for {current_build.job_name} #{current_build.build_number}: {str(e)}"
            sub_build_info_result["errors"].append(error_msg)  # Store error
            sub_build_info_result["guidance"] = (
                f"Could not retrieve sub-build information due to an error: {str(e)}"
            )
            # The tree will only contain the main build string at this point.
            return sub_build_info_result
        except Exception as e:  # Catch other potential errors
            error_msg = f"An unexpected error occurred while fetching sub-builds for {current_build.job_name} #{current_build.build_number}: {str(e)}"
            sub_build_info_result["errors"].append(error_msg)
            sub_build_info_result["guidance"] = (
                "Could not retrieve sub-build information due to an unexpected error."
            )
            return sub_build_info_result

        if not sub_builds_list:
            sub_build_info_result["guidance"] = (
                f"No sub-builds were found for {current_build.job_name} #{current_build.build_number}."
            )
            # Tree already contains main build string
            return sub_build_info_result

        # Build hierarchical structure
        self._build_hierarchical_structure(
            sub_builds_list, sub_build_info_result["build_tree"]
        )

        # Generate guidance based on hierarchical structure
        all_builds = self._flatten_build_tree(sub_build_info_result["build_tree"])
        failed_builds = [b for b in all_builds if b["is_failure"]]

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
        # Step 1: Parse and normalize inputs
        params = self._parse_and_normalize_inputs(kwargs)
        if "error" in params:
            return params

        # Step 2: Initialize result structure
        result = self._initialize_result_structure(params)

        # Step 3: Get build information
        build_info = self._get_build_information(params, result)
        if build_info is None:
            return result

        # Step 4: Check if we should skip successful builds
        if self._should_skip_build(
            build_info, params["skip_successful_builds"], result
        ):
            return result

        # Step 5: Process build hierarchy and logs
        self._process_build_analysis(params, build_info, result)

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
            "log_cached_path": "",
            "vector_indexing_status": "NOT_ATTEMPTED",
            "heuristic_findings": [],
            "semantic_search_highlights": [],
            "errors": [],
            "sub_build_information": {"build_tree": {}, "guidance": "", "errors": []},
            "build_summary": "",
            "error_analysis": [],
            "recommendations": [],
            "context_stats": {
                "total_tokens": 0,
                "truncated": False,
                "chunks_analyzed": 0,
                "high_value_chunks": 0,
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
                "Build completed successfully; no issues were detected",
                "To analyze successful builds, set skip_successful_builds=False",
            ]
            return True
        return False

    def _process_build_analysis(
        self, params: Dict[str, Any], build: Build, result: Dict[str, Any]
    ):
        """Process the main build analysis including hierarchy and logs"""
        # Get jenkins client for sub-build discovery
        jenkins_client = self.get_jenkins_client(params["instance_id"])

        # Get sub-build information
        sub_build_info = self._get_sub_build_information(build, jenkins_client)
        result["sub_build_information"] = sub_build_info

        # Build hierarchy for analysis - extract all builds from the tree
        hierarchy_dicts = self._flatten_build_tree(sub_build_info["build_tree"])

        # Convert hierarchy dictionaries to Build objects for processing
        hierarchy_builds = []
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
            log_processor = StreamingLogProcessor()
            log_chunks = self._process_logs_parallel_sync(
                hierarchy_builds,
                log_processor,
                jenkins_client,
                params["skip_successful_builds"],
                result,
            )
            result["context_stats"]["chunks_analyzed"] = len(log_chunks)

            # Generate analysis components
            result["build_summary"] = self._generate_build_summary(
                build, hierarchy_builds
            )
            result["semantic_search_highlights"] = self._generate_semantic_highlights(
                log_chunks, self.vector_manager, build
            )
            result["error_analysis"] = self._extract_key_failure_patterns(log_chunks)
            result["recommendations"] = self._generate_recommendations(
                hierarchy_builds, log_chunks
            )

            result["log_analysis_status"] = "COMPLETED"

        except Exception as e:
            result["log_analysis_status"] = "ERROR"
            result["errors"].append(f"Log processing failed: {str(e)}")
            logger.error(f"Log processing error: {e}")

    def _generate_build_summary(self, root_build: Build, hierarchy: List[Build]) -> str:
        """Generate concise build summary"""
        failed_builds = [b for b in hierarchy if b.status == "FAILURE"]

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

    def _generate_semantic_highlights(
        self, chunks: List, vector_manager, root_build: Build
    ) -> List[str]:
        """Generate semantic search highlights for stack traces, failing tests, etc."""
        highlights = []

        if not vector_manager or getattr(
            vector_manager, "vector_search_disabled", True
        ):
            # Fallback: extract key patterns from high-scoring chunks
            return self._extract_key_failure_patterns(chunks)

        try:
            # Get search queries from configuration
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
                            job_name = result.get("payload", {}).get(
                                "job_name", "unknown"
                            )
                            build_num = result.get("payload", {}).get(
                                "build_number", "unknown"
                            )
                            score = result.get("score", 0)

                            preview_length = (
                                self.config.config.semantic_search.max_content_preview
                            )
                            highlight = (
                                f"{job_name} #{build_num} "
                                f"(relevance: {score:.2f})\n"
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
            "max_chunks_for_analysis", 10
        )
        failure_patterns = self.config.get_failure_patterns()
        max_patterns = self.config.config.failure_patterns.max_fallback_patterns
        max_preview = self.config.config.failure_patterns.max_pattern_preview

        for chunk in chunks[:max_chunks]:
            content = chunk.content.lower()

            # Look for configured failure patterns
            if any(pattern in content for pattern in failure_patterns):
                pattern = (
                    f"{chunk.build.job_name} #{chunk.build.build_number}\n"
                    f"{chunk.content[:max_preview]}..."
                )
                patterns.append(pattern)

        return patterns[:max_patterns]

    def _generate_recommendations(
        self, failure_hierarchy: List[Build], chunks: List
    ) -> List[str]:
        """Generate actionable recommendations based on failure patterns"""
        failed_builds = [b for b in failure_hierarchy if b.status == "FAILURE"]

        if not failed_builds:
            return ["No build failures detected in this pipeline"]

        # Analyze failure patterns across chunks
        max_content_chunks = self.config.config.build_processing.chunks.get(
            "max_chunks_for_content", 20
        )
        all_content = " ".join([c.content.lower() for c in chunks[:max_content_chunks]])

        # Generate pattern-based recommendations
        recommendations = self._get_pattern_recommendations(all_content)

        # Add priority guidance
        priority_rec = self._get_priority_recommendation(failed_builds)
        if priority_rec:
            recommendations.append(priority_rec)

        # Add investigation guidance
        recommendations.append(self._get_investigation_guidance())

        return recommendations[: self.config.config.recommendations.max_recommendations]

    def _get_pattern_recommendations(self, content: str) -> List[str]:
        """Extract recommendations based on error patterns in content"""
        recommendations = []

        # Get pattern recommendations from configuration
        pattern_configs = self.config.get_pattern_recommendations()

        for _, pattern_config in pattern_configs.items():
            if self._matches_pattern_conditions(content, pattern_config.conditions):
                recommendations.append(pattern_config.message)

        return recommendations

    def _matches_pattern_conditions(self, content: str, conditions: List) -> bool:
        """Check if content matches pattern conditions"""
        for condition in conditions:
            if isinstance(condition, str):
                # Single string condition
                if condition.lower() in content:
                    return True
            elif isinstance(condition, list):
                # OR condition - any item in the list matches
                if any(cond.lower() in content for cond in condition):
                    return True
        return False

    def _get_priority_recommendation(self, failed_builds: List[Build]) -> Optional[str]:
        """Generate priority recommendation based on failed builds"""
        priority_config = self.config.config.recommendations.priority_jobs
        pattern = priority_config.get("app_pattern", "app")
        max_builds = priority_config.get("max_priority_builds", 3)
        message_template = priority_config.get("priority_message_template", "")

        deepest_failures = [b for b in failed_builds if pattern in b.job_name]

        if deepest_failures:
            app_builds = ", ".join(
                [f"#{b.build_number}" for b in deepest_failures[:max_builds]]
            )
            return message_template.format(
                job_pattern=pattern, build_numbers=app_builds
            )

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
        return all_chunks

    def _process_single_build_logs(
        self,
        build: Build,
        processor: StreamingLogProcessor,
        jenkins_client: JenkinsClient,
    ) -> Tuple[List, Optional[str]]:
        """Process logs for a single build (thread-safe)"""
        chunks = []
        log_path = None

        try:
            # Check if logs are already cached first
            try:
                log_path = self.cache_manager.fetch(jenkins_client, build)

                # Check if cached file exists and is not empty
                if log_path.exists() and log_path.stat().st_size > 0:
                    logger.info(
                        f"Using cached logs for {build.job_name}#{build.build_number}"
                    )
                    with open(log_path, "r", errors="ignore") as f:
                        log_stream = io.StringIO(f.read())
                else:
                    # Cache miss - need to fetch from Jenkins
                    logger.info(
                        f"Cache miss for {build.job_name}#{build.build_number}, fetching from Jenkins"
                    )
                    # Re-fetch through cache manager
                    log_path = self.cache_manager.fetch(jenkins_client, build)
                    with open(log_path, "r", errors="ignore") as f:
                        log_stream = io.StringIO(f.read())

            except Exception as cache_e:
                logger.warning(
                    f"Cache check failed for {build.job_name}#{build.build_number}: {cache_e}"
                )
                # If cache fails, return empty chunks
                return chunks, str(log_path) if log_path else None

            # Stream process logs into semantic chunks
            chunks = list(processor.process_streaming(log_stream, build))
            logger.info(
                f"Processed {len(chunks)} chunks from {build.job_name}#{build.build_number}"
            )

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
