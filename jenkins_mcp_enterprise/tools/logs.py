import json
import re
from typing import Any, Dict, List

from ..base import Build, LogContext, ParameterSpec
from ..cache_manager import CacheManager
from ..exceptions import ToolExecutionError
from ..jenkins.jenkins_client import JenkinsClient
from ..logging_config import get_component_logger
from .base_tools import LogOperationTool
from .common import CommonParameters, JenkinsResolver, LogFetcher

# Get logger for this component
logger = get_component_logger("logs_tools")


class LogContextTool(LogOperationTool):
    """Reads specific line ranges from cached console logs"""

    def __init__(
        self,
        cache_manager: CacheManager,
        jenkins_client: JenkinsClient,
        multi_jenkins_manager=None,
    ):
        super().__init__(cache_manager)
        self.jenkins_client = jenkins_client
        self.multi_jenkins_manager = multi_jenkins_manager
        self.resolver = JenkinsResolver(multi_jenkins_manager, jenkins_client)
        self.log_fetcher = LogFetcher(cache_manager, self.resolver)

    @property
    def name(self) -> str:
        return "get_log_context"

    @property
    def description(self) -> str:
        return "Reads specific line ranges from a cached console log; fetches if missing. IMPORTANT: jenkins_url is required because jobs are load-balanced across multiple Jenkins servers."

    @property
    def parameters(self) -> List[ParameterSpec]:
        return [
            ParameterSpec("job_name", str, "Name of the Jenkins job", required=True),
            ParameterSpec("build_number", int, "Build number", required=True),
            ParameterSpec(
                "jenkins_url",
                str,
                "Jenkins instance URL (e.g., 'https://jenkins.example.com'). REQUIRED - jobs are load-balanced across multiple servers.",
                required=True,
            ),
            ParameterSpec(
                "start_line",
                int,
                "Starting line number (1-based)",
                required=False,
                default=1,
            ),
            ParameterSpec(
                "end_line",
                int,
                "Ending line number (1-based, exclusive)",
                required=False,
            ),
        ]

    def _execute_impl(self, **kwargs) -> Dict[str, Any]:
        job_name = kwargs["job_name"]
        build_number = kwargs["build_number"]
        jenkins_url = kwargs["jenkins_url"]
        start_line = kwargs.get("start_line", 1)
        end_line = kwargs.get("end_line")

        # Fetch the log file using common fetcher
        log_path, error = self.log_fetcher.fetch_log(
            job_name, build_number, jenkins_url
        )
        if error:
            # The error from fetch_log is a dict with an 'error' key
            error_message = error.get("error", "Unknown error fetching log")
            raise ToolExecutionError(error_message)

        build_obj = Build(job_name=job_name, build_number=build_number)
        lines = self.cache_manager.read_lines(log_path)
        num_total_lines = len(lines)

        MAX_LINES_TO_RETURN = 500

        # Convert to 0-indexed for slicing
        actual_start_0_indexed = max(0, start_line - 1) if start_line else 0
        actual_start_0_indexed = min(actual_start_0_indexed, num_total_lines)

        # Handle end_line
        actual_end_for_slice = end_line if end_line is not None else num_total_lines
        actual_end_for_slice = max(0, actual_end_for_slice)
        actual_end_for_slice = min(actual_end_for_slice, num_total_lines)

        # Apply line limit
        requested_num_lines = actual_end_for_slice - actual_start_0_indexed
        if requested_num_lines > MAX_LINES_TO_RETURN:
            actual_end_for_slice = actual_start_0_indexed + MAX_LINES_TO_RETURN
            actual_end_for_slice = min(actual_end_for_slice, num_total_lines)

        # Extract lines
        if actual_start_0_indexed > actual_end_for_slice:
            selected_lines = []
        else:
            selected_lines = lines[actual_start_0_indexed:actual_end_for_slice]

        # Calculate context end line
        task_actual_end_val = end_line if end_line is not None else num_total_lines
        context_end_line = min(task_actual_end_val, num_total_lines)

        log_context = LogContext(
            build=build_obj,
            start_line=(actual_start_0_indexed + 1),
            end_line=context_end_line,
            lines=selected_lines,
        )

        return {
            "build": {
                "job_name": log_context.build.job_name,
                "build_number": log_context.build.build_number,
            },
            "start_line": log_context.start_line,
            "end_line": log_context.end_line,
            "lines": log_context.lines,
            "total_lines": num_total_lines,
        }


class FilterErrorsTool(LogOperationTool):
    """Scans cached logs for regex patterns with context"""

    def __init__(
        self,
        cache_manager: CacheManager,
        jenkins_client: JenkinsClient,
        multi_jenkins_manager=None,
    ):
        super().__init__(cache_manager)
        self.jenkins_client = jenkins_client
        self.multi_jenkins_manager = multi_jenkins_manager
        self.resolver = JenkinsResolver(multi_jenkins_manager, jenkins_client)
        self.log_fetcher = LogFetcher(cache_manager, self.resolver)

    @property
    def name(self) -> str:
        return "filter_errors_grep"

    @property
    def description(self) -> str:
        return "Intelligently scans logs with relevance scoring, reverse search, and deduplication. Use 'preset:critical' for high-priority errors or 'preset:all' for broad search. IMPORTANT: jenkins_url is required because jobs are load-balanced across multiple Jenkins servers."

    @property
    def parameters(self) -> List[ParameterSpec]:
        return CommonParameters.standard_build_params() + [
            ParameterSpec(
                "pattern",
                str,
                "Regex pattern or preset:name (presets: critical, errors, warnings, exceptions, build, connection, all)",
                required=True,
            ),
            ParameterSpec(
                "window",
                int,
                "Number of context lines around matches",
                required=False,
                default=5,
            ),
            ParameterSpec(
                "reverse_search",
                bool,
                "Search from bottom to top (latest errors first)",
                required=False,
                default=True,
            ),
            ParameterSpec(
                "max_results",
                int,
                "Maximum number of results to return",
                required=False,
                default=10,
            ),
            ParameterSpec(
                "score_threshold",
                float,
                "Minimum relevance score (0.0-1.0)",
                required=False,
                default=0.3,
            ),
        ]

    # Generic error patterns - not specific to any technology
    ERROR_PRESETS = {
        "critical": r"ERROR|FAILED|FATAL|Exception|BUILD FAILED",
        "errors": r"error:|failed:|exception:|FAILED|ERROR",
        "warnings": r"warning:|warn:|WARN",
        "exceptions": r"Exception|exception.*in|stack.*trace|caused.*by",
        "build": r"build.*failed|compilation.*failed|BUILD FAILED",
        "connection": r"connection|timeout|refused|network|unreachable",
        "all": r"error|fail|exception|warn|timeout|refused|unable|cannot|denied|missing|not.*found",
    }

    def _execute_impl(self, **kwargs) -> Dict[str, Any]:
        job_name = kwargs["job_name"]
        build_number = kwargs["build_number"]
        jenkins_url = kwargs["jenkins_url"]
        pattern = kwargs["pattern"]
        window = kwargs["window"]
        reverse_search = kwargs.get("reverse_search", True)
        max_results = kwargs.get("max_results", 10)
        score_threshold = kwargs.get("score_threshold", 0.3)

        # Fetch the log file using common fetcher
        log_path, error = self.log_fetcher.fetch_log(
            job_name, build_number, jenkins_url
        )
        if error:
            return error

        build_obj = Build(job_name=job_name, build_number=build_number)
        all_lines = self.cache_manager.read_lines(log_path)
        num_total_lines = len(all_lines)

        # Handle preset patterns
        original_pattern = pattern
        if pattern.startswith("preset:"):
            preset_name = pattern[7:]  # Remove "preset:" prefix
            if preset_name in self.ERROR_PRESETS:
                pattern = self.ERROR_PRESETS[preset_name]
                logger.info(f"Using preset '{preset_name}': {pattern}")
            else:
                available_presets = ", ".join(self.ERROR_PRESETS.keys())
                raise ToolExecutionError(
                    f"Unknown preset '{preset_name}'. Available presets: {available_presets}"
                )

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            logger.error(f"Invalid regex pattern '{pattern}': {e}")
            raise ToolExecutionError(f"Invalid regex pattern '{pattern}': {e}") from e

        # Find all matches with scoring
        all_matches = []
        search_range = (
            reversed(range(num_total_lines))
            if reverse_search
            else range(num_total_lines)
        )

        for i in search_range:
            line_content = all_lines[i]
            match = regex.search(line_content)
            if match:
                # Calculate relevance score
                score = self._calculate_relevance_score(
                    line_content, i, num_total_lines, reverse_search
                )

                if score >= score_threshold:
                    all_matches.append(
                        {
                            "line_index": i,
                            "line_content": line_content,
                            "score": score,
                            "match_object": match,
                        }
                    )

        # Sort by score (highest first) and limit results
        all_matches.sort(key=lambda x: x["score"], reverse=True)
        top_matches = all_matches[:max_results]

        # Create error blocks with deduplication
        error_blocks = []
        used_ranges = []

        for match_info in top_matches:
            i = match_info["line_index"]
            score = match_info["score"]

            # Determine context window
            slice_start_0idx = max(0, i - window)
            slice_end_0idx = min(num_total_lines, i + window + 1)

            # Check for overlap with existing ranges (deduplication)
            overlaps = any(
                not (slice_end_0idx <= start or slice_start_0idx >= end)
                for start, end in used_ranges
            )

            if not overlaps:
                used_ranges.append((slice_start_0idx, slice_end_0idx))

                context_lines = all_lines[slice_start_0idx:slice_end_0idx]
                log_ctx_start_line = slice_start_0idx + 1
                log_ctx_end_line = slice_start_0idx + len(context_lines)

                error_block = {
                    "build": {
                        "job_name": build_obj.job_name,
                        "build_number": build_obj.build_number,
                    },
                    "pattern": original_pattern,
                    "match_line": i + 1,
                    "relevance_score": round(score, 3),
                    "match_text": match_info["line_content"].strip(),
                    "context": {
                        "start_line": log_ctx_start_line,
                        "end_line": log_ctx_end_line,
                        "lines": context_lines,
                    },
                }
                error_blocks.append(error_block)

        return {
            "build": {
                "job_name": build_obj.job_name,
                "build_number": build_obj.build_number,
            },
            "pattern": original_pattern,
            "resolved_pattern": pattern if original_pattern != pattern else None,
            "search_direction": "bottom-to-top" if reverse_search else "top-to-bottom",
            "total_matches_found": len(all_matches),
            "matches_returned": len(error_blocks),
            "score_threshold": score_threshold,
            "error_blocks": error_blocks,
        }

    def _calculate_relevance_score(
        self, line_content: str, line_index: int, total_lines: int, reverse_search: bool
    ) -> float:
        """Calculate relevance score for error lines"""
        score = 0.0
        line_lower = line_content.lower()

        # Base score for different error types
        if any(
            term in line_lower
            for term in ["build failed", "compilation failed", "fatal"]
        ):
            score += 0.9
        elif any(term in line_lower for term in ["error:", "exception:", "failed:"]):
            score += 0.7
        elif any(term in line_lower for term in ["warning:", "warn:"]):
            score += 0.3
        else:
            score += 0.1

        # Generic keyword scoring - not technology specific
        critical_keywords = {
            "fatal": 0.3,
            "critical": 0.3,
            "severe": 0.3,
            "timeout": 0.2,
            "connection refused": 0.2,
            "unreachable": 0.2,
            "out of memory": 0.3,
            "heap space": 0.3,
            "memory": 0.1,
            "permission denied": 0.2,
            "access denied": 0.2,
            "not found": 0.2,
            "missing": 0.2,
            "unable": 0.1,
            "stack trace": 0.2,
            "caused by": 0.2,
        }

        for keyword, boost in critical_keywords.items():
            if keyword in line_lower:
                score += boost

        # Position-based scoring (later lines are more relevant in reverse search)
        if reverse_search:
            # Lines near the end get higher scores
            position_ratio = (total_lines - line_index) / total_lines
            score += position_ratio * 0.2
        else:
            # Lines near the beginning get higher scores
            position_ratio = line_index / total_lines
            score += position_ratio * 0.2

        # Penalize noise patterns
        noise_patterns = [
            "downloading",
            "extracting",
            "connecting to",
            "cached",
            "loading library",
        ]
        if any(noise in line_lower for noise in noise_patterns):
            score *= 0.5

        return min(score, 1.0)  # Cap at 1.0
