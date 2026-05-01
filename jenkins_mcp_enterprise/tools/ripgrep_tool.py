import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from ..base import ParameterSpec
from ..cache_manager import CacheManager
from ..exceptions import ToolExecutionError
from ..jenkins.jenkins_client import JenkinsClient
from ..logging_config import get_component_logger
from ..utils import find_ripgrep
from .base_tools import LogOperationTool
from .common import CommonParameters, JenkinsResolver, LogFetcher

# Get logger for this component
logger = get_component_logger("ripgrep_tool")


class RipgrepSearchTool(LogOperationTool):
    """Advanced ripgrep-based search tool for navigating large Jenkins logs with context"""

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
        return "ripgrep_search"

    @property
    def description(self) -> str:
        return "Fast pattern search in Jenkins logs with before/after context lines. Supports regex, case-insensitive search, and line number ranges. IMPORTANT: jenkins_url is required because jobs are load-balanced across multiple Jenkins servers."

    @property
    def parameters(self) -> List[ParameterSpec]:
        return CommonParameters.standard_build_params() + [
            ParameterSpec(
                "pattern", str, "Search pattern (regex supported)", required=True
            ),
            ParameterSpec(
                "before_context",
                int,
                "Number of lines to show before match",
                required=False,
                default=3,
            ),
            ParameterSpec(
                "after_context",
                int,
                "Number of lines to show after match",
                required=False,
                default=3,
            ),
            ParameterSpec(
                "case_sensitive",
                bool,
                "Case sensitive search",
                required=False,
                default=False,
            ),
            ParameterSpec(
                "invert_match",
                bool,
                "Show lines that do NOT match",
                required=False,
                default=False,
            ),
            ParameterSpec(
                "max_count",
                int,
                "Maximum number of matches to return",
                required=False,
                default=50,
            ),
            ParameterSpec(
                "max_output_lines",
                int,
                "Maximum total output lines to return",
                required=False,
                default=1000,
            ),
            ParameterSpec(
                "line_range",
                str,
                "Line range to search (e.g., '1000-2000')",
                required=False,
            ),
        ]

    def _execute_impl(self, **kwargs) -> Dict[str, Any]:
        job_name = kwargs["job_name"]
        build_number = kwargs["build_number"]
        jenkins_url = kwargs["jenkins_url"]
        pattern = kwargs["pattern"]
        before_context = kwargs.get("before_context", 3)
        after_context = kwargs.get("after_context", 3)
        case_sensitive = kwargs.get("case_sensitive", False)
        invert_match = kwargs.get("invert_match", False)
        max_count = kwargs.get("max_count", 50)
        max_output_lines = kwargs.get("max_output_lines", 1000)
        line_range = kwargs.get("line_range")

        # Fetch the log file using common fetcher
        log_path, error = self.log_fetcher.fetch_log(
            job_name, build_number, jenkins_url
        )
        if error:
            return error

        # Find ripgrep using common utility
        rg_path = find_ripgrep()
        if not rg_path:
            raise ToolExecutionError("ripgrep (rg) is not installed or not in PATH")

        cmd = [rg_path]

        # Add basic options
        cmd.extend(["--json"])  # JSON output for structured parsing
        cmd.extend(["-n"])  # Line numbers

        # Context lines
        if before_context > 0:
            cmd.extend(["-B", str(before_context)])
        if after_context > 0:
            cmd.extend(["-A", str(after_context)])

        # Case sensitivity
        if not case_sensitive:
            cmd.extend(["-i"])

        # Invert match
        if invert_match:
            cmd.extend(["-v"])

        # Max count
        cmd.extend(["-m", str(max_count)])

        # Line range
        if line_range:
            # Parse line range
            try:
                if "-" in line_range:
                    start, end = line_range.split("-")
                    start_line = int(start.strip())
                    end_line = int(end.strip())
                    # Create a temporary file with just the line range
                    temp_file = self._extract_line_range(
                        Path(str(log_path)), start_line, end_line
                    )
                    log_path = temp_file
                else:
                    raise ValueError("Line range must be in format 'start-end'")
            except ValueError as e:
                raise ToolExecutionError(f"Invalid line range format: {e}")

        # Add pattern and file
        cmd.extend([pattern, str(log_path)])

        # Execute ripgrep
        try:
            logger.info(f"Executing ripgrep command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode not in [0, 1]:  # 0 = matches found, 1 = no matches
                logger.error(f"Ripgrep failed: {result.stderr}")
                raise ToolExecutionError(f"Ripgrep execution failed: {result.stderr}")

            # Parse JSON output
            matches = self._parse_ripgrep_json(result.stdout, max_output_lines)

            # Clean up temp file if created
            if line_range and "temp_file" in locals():
                os.unlink(temp_file)

            return {
                "build": {"job_name": job_name, "build_number": build_number},
                "pattern": pattern,
                "search_options": {
                    "case_sensitive": case_sensitive,
                    "invert_match": invert_match,
                    "before_context": before_context,
                    "after_context": after_context,
                    "line_range": line_range,
                },
                "total_matches": len(matches),
                "matches": matches,
            }

        except subprocess.TimeoutExpired:
            raise ToolExecutionError("Ripgrep search timed out after 30 seconds")
        except Exception as e:
            logger.error(f"Unexpected error during ripgrep execution: {e}")
            raise ToolExecutionError(f"Search failed: {str(e)}")

    def _extract_line_range(
        self, log_path: Path, start_line: int, end_line: int
    ) -> Path:
        """Extract a specific line range to a temporary file"""
        import tempfile

        # Create temp file
        temp_fd, temp_path = tempfile.mkstemp(suffix=".log", prefix="jenkins_range_")

        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as infile:
                with os.fdopen(temp_fd, "w", encoding="utf-8") as outfile:
                    for i, line in enumerate(infile, 1):
                        if start_line <= i <= end_line:
                            outfile.write(line)
                        elif i > end_line:
                            break
        except Exception as e:
            os.unlink(temp_path)
            raise ToolExecutionError(f"Failed to extract line range: {e}")

        return Path(temp_path)

    def _parse_ripgrep_json(
        self, json_output: str, max_output_lines: int = 1000
    ) -> List[Dict[str, Any]]:
        """Parse ripgrep JSON output into structured matches"""
        matches = []
        current_match = None
        context_lines = []
        total_output_lines = 0

        for line in json_output.strip().split("\n"):
            if not line:
                continue

            try:
                data = json.loads(line)
                msg_type = data.get("type")

                if msg_type == "match":
                    # Save previous match if exists
                    if current_match:
                        current_match["context_lines"] = context_lines
                        matches.append(current_match)
                        context_lines = []

                    # Start new match
                    match_data = data["data"]
                    current_match = {
                        "line_number": match_data["line_number"],
                        "line_text": match_data["lines"]["text"].rstrip("\n"),
                        "match_start": (
                            match_data["submatches"][0]["start"]
                            if match_data.get("submatches")
                            else None
                        ),
                        "match_end": (
                            match_data["submatches"][0]["end"]
                            if match_data.get("submatches")
                            else None
                        ),
                        "context_lines": [],
                    }

                elif msg_type == "context" and current_match:
                    # Add context line
                    context_data = data["data"]
                    context_lines.append(
                        {
                            "line_number": context_data["line_number"],
                            "line_text": context_data["lines"]["text"].rstrip("\n"),
                            "is_before": context_data["line_number"]
                            < current_match["line_number"],
                        }
                    )

            except json.JSONDecodeError:
                logger.warning(f"Failed to parse ripgrep JSON line: {line}")
                continue

        # Don't forget the last match
        if current_match:
            current_match["context_lines"] = context_lines
            matches.append(current_match)

        # Format matches with context
        formatted_matches = []
        for match in matches:
            # Sort context lines by line number
            before_lines = sorted(
                [c for c in match["context_lines"] if c["is_before"]],
                key=lambda x: x["line_number"],
            )
            after_lines = sorted(
                [c for c in match["context_lines"] if not c["is_before"]],
                key=lambda x: x["line_number"],
            )

            # Check if we would exceed max output lines
            match_total_lines = 1 + len(before_lines) + len(after_lines)
            if total_output_lines + match_total_lines > max_output_lines:
                # Add truncation notice
                if formatted_matches:
                    formatted_matches.append(
                        {
                            "truncated": True,
                            "message": f"Output truncated at {max_output_lines} lines. {len(matches) - len(formatted_matches)} matches omitted.",
                        }
                    )
                break

            total_output_lines += match_total_lines

            formatted_match = {
                "match_line_number": match["line_number"],
                "match_text": match["line_text"],
                "before_context": [
                    f"{c['line_number']}: {c['line_text']}" for c in before_lines
                ],
                "after_context": [
                    f"{c['line_number']}: {c['line_text']}" for c in after_lines
                ],
            }

            # Add match highlighting info if available
            if match.get("match_start") is not None:
                formatted_match["match_position"] = {
                    "start": match["match_start"],
                    "end": match["match_end"],
                }

            formatted_matches.append(formatted_match)

        return formatted_matches


class NavigateLogTool(LogOperationTool):
    """Navigate to specific sections of logs using ripgrep patterns"""

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
        return "navigate_log"

    @property
    def description(self) -> str:
        return "Jump to specific sections in logs using patterns (for example, 'Building module X' or 'Stage: Deploy'). Shows surrounding context. IMPORTANT: jenkins_url is required because jobs are load-balanced across multiple Jenkins servers."

    @property
    def parameters(self) -> List[ParameterSpec]:
        return CommonParameters.standard_build_params() + [
            ParameterSpec(
                "section_pattern",
                str,
                "Pattern identifying the section (e.g., 'Stage:', 'Building:', 'Testing:')",
                required=True,
            ),
            ParameterSpec(
                "occurrence",
                int,
                "Which occurrence to navigate to (1-based)",
                required=False,
                default=1,
            ),
            ParameterSpec(
                "context_lines",
                int,
                "Number of lines to show around the section",
                required=False,
                default=20,
            ),
        ]

    def _execute_impl(self, **kwargs) -> Dict[str, Any]:
        job_name = kwargs["job_name"]
        build_number = kwargs["build_number"]
        jenkins_url = kwargs["jenkins_url"]
        section_pattern = kwargs["section_pattern"]
        occurrence = kwargs.get("occurrence", 1)
        context_lines = kwargs.get("context_lines", 20)

        # Fetch the log file using common fetcher
        log_path, error = self.log_fetcher.fetch_log(
            job_name, build_number, jenkins_url
        )
        if error:
            return error

        # Find ripgrep using common utility
        rg_path = find_ripgrep()
        if not rg_path:
            raise ToolExecutionError("ripgrep (rg) is not installed or not in PATH")

        # Use ripgrep to find all occurrences with line numbers
        cmd = [rg_path, "-n", "--no-heading", section_pattern, str(log_path)]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 1:  # No matches
                return {
                    "build": {"job_name": job_name, "build_number": build_number},
                    "section_pattern": section_pattern,
                    "found": False,
                    "message": f"No matches found for pattern: {section_pattern}",
                }

            # Parse matches
            matches = []
            for line in result.stdout.strip().split("\n"):
                if ":" in line:
                    line_num, content = line.split(":", 1)
                    matches.append(
                        {"line_number": int(line_num), "content": content.strip()}
                    )

            if occurrence > len(matches):
                return {
                    "build": {"job_name": job_name, "build_number": build_number},
                    "section_pattern": section_pattern,
                    "found": True,
                    "total_occurrences": len(matches),
                    "requested_occurrence": occurrence,
                    "message": f"Only {len(matches)} occurrences found, but occurrence {occurrence} was requested",
                }

            # Get the target match
            target_match = matches[occurrence - 1]
            target_line = target_match["line_number"]

            # Read context around the target
            all_lines = self.cache_manager.read_lines(log_path)
            start_line = max(1, target_line - context_lines)
            end_line = min(len(all_lines), target_line + context_lines)

            context = []
            for i in range(start_line - 1, end_line):
                line_num = i + 1
                prefix = ">>>" if line_num == target_line else "   "
                context.append(f"{prefix} {line_num}: {all_lines[i].rstrip()}")

            return {
                "build": {"job_name": job_name, "build_number": build_number},
                "section_pattern": section_pattern,
                "found": True,
                "total_occurrences": len(matches),
                "navigated_to_occurrence": occurrence,
                "target_line": target_line,
                "context": {
                    "start_line": start_line,
                    "end_line": end_line,
                    "lines": context,
                },
                "all_occurrences": [
                    f"Line {m['line_number']}: {m['content'][:80]}..."
                    for m in matches[:10]  # Show first 10
                ],
            }

        except subprocess.TimeoutExpired:
            raise ToolExecutionError("Navigation search timed out after 30 seconds")
        except Exception as e:
            logger.error(f"Unexpected error during navigation: {e}")
            raise ToolExecutionError(f"Navigation failed: {str(e)}")
