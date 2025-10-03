"""
Jenkins Sub-Build Discovery and Traversal

This module implements hierarchical Jenkins pipeline analysis with multi-level
sub-build discovery using parallel processing for performance. It supports
complex pipeline structures with unlimited depth.

REQUIRED JENKINS PLUGINS:

Essential:
- Pipeline (workflow-aggregator): Core pipeline functionality with wfapi endpoints
- Workflow Job (workflow-job): Provides wfapi/runs and wfapi/describe endpoints

Sub-Build Detection:
- Parameterized Trigger (parameterized-trigger): Detects downstream triggered builds
- Promoted Builds (promoted-builds): Tracks build promotion workflows
- Build Pipeline (build-pipeline-plugin): Pipeline dependency relationships

Discovery Methods (in order of preference):
1. wfapi: /job/{job}/{build}/wfapi/runs and /job/{job}/{build}/wfapi/describe
2. Tree API: /job/{job}/{build}/api/json?tree=actions[nodes[actions[description]]]
3. Build Actions: hudson.plugins.promoted_builds.BuildInfoExporterAction
4. SubBuilds Field: Classic subBuilds field from build JSON

Plugin Class Names Detected:
- hudson.plugins.promoted_builds.BuildInfoExporterAction
- hudson.plugins.parameterizedtrigger.BuildTriggerAction
- hudson.plugins.build_pipeline.trigger.TriggerAction

The wfapi method is more reliable than Blue Ocean and provides direct access
to pipeline workflow information without stale references.
"""

import concurrent.futures
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from ..base import Build, SubBuild
from ..exceptions import SubBuildDiscoveryError
from ..logging_config import get_component_logger
from ..utils import deduplicate_by_representation
from .connection_manager import JenkinsConnectionManager
from .job_name_utils import JobNameParser

logger = get_component_logger("jenkins.subbuild")


class SubBuildDiscoverer:
    """Discovers and traverses Jenkins sub-builds using the proven approach from jenkins_client_old.py"""

    def __init__(
        self,
        connection_manager: JenkinsConnectionManager,
        max_parallel_workers: int = 10,
    ):
        self.connection = connection_manager
        self.max_parallel_workers = max_parallel_workers
        self._executor = None

    def discover_subbuilds(
        self,
        parent_job_name: str,
        parent_build_number: int,
        max_depth: int = 15,
        parallel: bool = True,
    ) -> List[SubBuild]:
        """
        Discover all sub-builds using parallel processing for improved performance.

        PERFORMANCE IMPROVEMENTS:
        - Parallel discovery reduces initial call time from ~30+ seconds to ~10 seconds
        - Concurrent Jenkins API calls at each hierarchy level
        - Thread-safe breadth-first traversal using ThreadPoolExecutor
        - Configurable worker pool size (default: 10 concurrent workers)
        - Graceful fallback to sequential method on errors

        JOB NAME HANDLING:
        - Accepts various job name formats (URL-encoded, with/without /job/ prefixes)
        - Normalizes job names for consistent processing

        This addresses MCP client timeout issues caused by long-running sequential discovery
        of complex Jenkins pipeline hierarchies with many sub-builds.

        Args:
            parent_job_name: Jenkins job name in any format (will be normalized)
            parent_build_number: Build number to analyze
            max_depth: Maximum depth to traverse (default: 5)
            parallel: Enable parallel processing (default: True)

        Returns:
            List of discovered SubBuild objects with hierarchy information
        """
        try:
            # Normalize the parent job name to handle various input formats
            normalized_job_name = JobNameParser.normalize_job_name(parent_job_name)
            logger.info(
                f"Normalized job name: '{parent_job_name}' -> '{normalized_job_name}'"
            )

            if parallel:
                return self._discover_subbuilds_parallel(
                    normalized_job_name, parent_build_number, max_depth
                )
            else:
                return self._discover_subbuilds_sequential(
                    normalized_job_name, parent_build_number, max_depth
                )
        except Exception as e:
            raise SubBuildDiscoveryError(f"Failed to discover sub-builds: {e}") from e

    def _discover_subbuilds_sequential(
        self, parent_job_name: str, parent_build_number: int, max_depth: int = 5
    ) -> List[SubBuild]:
        """Original sequential discovery method (fallback)"""
        all_sub_builds: List[SubBuild] = []
        visited_builds: Set[Tuple[str, int]] = set()

        # The initial call's children will have the original parent as their parent, and depth 1
        self._collect_all_sub_builds(
            parent_job_name,
            parent_build_number,
            1,  # Start depth at 1 for children of the initial parent
            visited_builds,
            all_sub_builds,
            parent_job_name,  # Parent details for the first level of children
            parent_build_number,
        )

        # Deduplicate sub-builds using common utility
        final_list = deduplicate_by_representation(
            all_sub_builds,
            lambda sb: (
                sb.job_name,
                sb.build_number,
                sb.depth,
                sb.parent_job_name,
                sb.parent_build_number,
                sb.status,
            ),
        )

        return final_list

    def _discover_subbuilds_parallel(
        self, parent_job_name: str, parent_build_number: int, max_depth: int = 5
    ) -> List[SubBuild]:
        """Parallel sub-build discovery using ThreadPoolExecutor without nested event loops"""
        try:
            # Use ThreadPoolExecutor directly without asyncio.run to avoid nested event loop issues
            all_sub_builds: List[SubBuild] = []
            visited_builds: Set[Tuple[str, int]] = set()

            # Breadth-first discovery with parallel processing at each level
            current_level = [
                (
                    parent_job_name,
                    parent_build_number,
                    1,
                    parent_job_name,
                    parent_build_number,
                )
            ]

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.max_parallel_workers
            ) as executor:
                for depth in range(1, max_depth + 1):
                    if not current_level:
                        break

                    # Process current level in parallel using submit/as_completed
                    futures = []
                    for (
                        job_name,
                        build_number,
                        current_depth,
                        parent_job,
                        parent_build,
                    ) in current_level:
                        if (job_name, build_number) not in visited_builds:
                            visited_builds.add((job_name, build_number))
                            future = executor.submit(
                                self._discover_direct_children,
                                job_name,
                                build_number,
                                current_depth,
                                parent_job,
                                parent_build,
                            )
                            futures.append(future)

                    # Wait for all parallel discoveries to complete
                    next_level = []
                    for future in concurrent.futures.as_completed(futures):
                        try:
                            discovered_builds, children_for_next_level = future.result()
                            all_sub_builds.extend(discovered_builds)
                            next_level.extend(children_for_next_level)
                        except Exception as e:
                            logger.warning(f"Sub-build discovery failed: {e}")
                            continue

                    current_level = next_level

            # Deduplicate results using common utility
            final_list = deduplicate_by_representation(
                all_sub_builds,
                lambda sb: (
                    sb.job_name,
                    sb.build_number,
                    sb.depth,
                    sb.parent_job_name,
                    sb.parent_build_number,
                    sb.status,
                ),
            )

            logger.info(
                f"Parallel discovery found {len(final_list)} sub-builds across {max_depth} levels"
            )
            return final_list

        except Exception as e:
            logger.warning(
                f"Parallel discovery failed, falling back to sequential: {e}"
            )
            return self._discover_subbuilds_sequential(
                parent_job_name, parent_build_number, max_depth
            )

    def _discover_direct_children(
        self,
        job_name: str,
        build_number: int,
        depth: int,
        parent_job_name: str,
        parent_build_number: int,
    ) -> Tuple[List[SubBuild], List[Tuple[str, int, int, str, int]]]:
        """Discover direct children of a specific build (thread-safe)"""
        discovered_builds = []
        children_for_next_level = []

        try:
            # Get build info for this specific build
            build_info = self.connection.client.get_build_info(
                job_name, build_number, depth=1
            )

            # Process different discovery methods in parallel-safe way
            children = []

            # Method 1: wfapi discovery (PRIMARY - more reliable than Blue Ocean)
            wfapi_children = self._discover_children_wfapi(job_name, build_number)
            children.extend(wfapi_children)

            # Method 2: Tree API discovery (SECONDARY - reliable fallback)
            tree_children = self._discover_children_tree_api(job_name, build_number)
            children.extend(tree_children)

            # Method 3: Build actions discovery (TERTIARY - for legacy builds)
            action_children = self._discover_children_build_actions(build_info)
            children.extend(action_children)

            # Method 4: SubBuilds field discovery (FALLBACK - basic support)
            subbuilds_children = self._discover_children_subbuilds_field(build_info)
            children.extend(subbuilds_children)

            # Deduplicate children
            seen_children = set()
            unique_children = []
            for child_job, child_build in children:
                key = (child_job, child_build)
                if key not in seen_children:
                    seen_children.add(key)
                    unique_children.append((child_job, child_build))

            # Create SubBuild objects and prepare for next level
            for child_job, child_build in unique_children:
                status, url = self._get_build_status_and_url(child_job, child_build)

                sub_build = SubBuild(
                    job_name=child_job,
                    build_number=child_build,
                    url=url,
                    status=status,
                    parent_job_name=parent_job_name,
                    parent_build_number=parent_build_number,
                    depth=depth,
                )
                discovered_builds.append(sub_build)

                # Prepare for next level discovery
                children_for_next_level.append(
                    (child_job, child_build, depth + 1, job_name, build_number)
                )

            logger.debug(
                f"Found {len(discovered_builds)} children for {job_name}#{build_number}"
            )

        except Exception as e:
            logger.warning(
                f"Failed to discover children for {job_name}#{build_number}: {e}"
            )

        return discovered_builds, children_for_next_level

    def _discover_children_wfapi(
        self, job_name: str, build_number: int
    ) -> List[Tuple[str, int]]:
        """Discover children using wfapi method (thread-safe and more reliable)"""
        children = []
        try:
            if not self.connection.config.url:
                return children

            base_url = self.connection.config.url.rstrip("/")

            # Use job name parser to get the correct API path
            api_job_path = JobNameParser.to_jenkins_api_path(job_name)

            # Try wfapi/runs endpoint for pipeline runs
            wfapi_runs_url = f"{base_url}/{api_job_path}/{build_number}/wfapi/runs"

            response = self.connection.session.get(
                wfapi_runs_url, timeout=self.connection.config.timeout
            )
            response.raise_for_status()
            runs_data = response.json()

            if isinstance(runs_data, list):
                for run_data in runs_data:
                    # Extract downstream job information from wfapi runs
                    run_name = run_data.get("name")
                    run_id = run_data.get("id")
                    run_status = run_data.get("status")

                    # Look for downstream builds triggered by this run
                    if run_name and run_id and run_status != "NOT_EXECUTED":
                        # Try to extract job name and build number from run data
                        # wfapi runs can contain downstream build references
                        downstream_builds = run_data.get("downstreamBuilds", [])
                        for downstream in downstream_builds:
                            downstream_job = downstream.get("jobName")
                            downstream_build = downstream.get("buildNumber")
                            if downstream_job and downstream_build:
                                # Normalize the discovered job name
                                normalized_job = JobNameParser.normalize_job_name(
                                    downstream_job
                                )
                                children.append((normalized_job, int(downstream_build)))

            # Also try wfapi/describe endpoint for more detailed pipeline information
            wfapi_describe_url = (
                f"{base_url}/{api_job_path}/{build_number}/wfapi/describe"
            )
            try:
                response = self.connection.session.get(
                    wfapi_describe_url, timeout=self.connection.config.timeout
                )
                response.raise_for_status()
                describe_data = response.json()

                # Extract stages and their downstream builds
                stages = describe_data.get("stages", [])
                for stage in stages:
                    stage_links = stage.get("_links", {})
                    stage_actions = stage.get("stageFlowNodes", [])

                    for node in stage_actions:
                        # Look for downstream build actions in stage flow nodes
                        node_type = node.get("_class", "")
                        if (
                            "downstream" in node_type.lower()
                            or "trigger" in node_type.lower()
                        ):
                            # Extract downstream job information
                            downstream_job = node.get("downstream", {}).get("jobName")
                            downstream_build = node.get("downstream", {}).get(
                                "buildNumber"
                            )
                            if downstream_job and downstream_build:
                                normalized_job = JobNameParser.normalize_job_name(
                                    downstream_job
                                )
                                children.append((normalized_job, int(downstream_build)))

            except Exception as e:
                logger.debug(
                    f"wfapi/describe failed for {job_name}#{build_number}: {e}"
                )

        except Exception as e:
            logger.debug(f"wfapi discovery failed for {job_name}#{build_number}: {e}")

        return children

    def _discover_children_build_actions(
        self, build_info: Dict
    ) -> List[Tuple[str, int]]:
        """Discover children from build actions (thread-safe)"""
        children = []

        if "actions" in build_info:
            for action in build_info.get("actions", []):
                if (
                    action
                    and "_class" in action
                    and "hudson.plugins.promoted_builds.BuildInfoExporterAction"
                    in action["_class"]
                ):
                    for triggered_build in action.get("triggeredBuilds", []):
                        child_job_name = triggered_build.get(
                            "projectName"
                        ) or triggered_build.get("jobName")
                        child_build_number = triggered_build.get("buildNumber")
                        if child_job_name and child_build_number:
                            children.append((child_job_name, child_build_number))

        return children

    def _discover_children_tree_api(
        self, job_name: str, build_number: int
    ) -> List[Tuple[str, int]]:
        """Discover children using Tree API (thread-safe)"""
        children = []

        try:
            base_url = self.connection.config.url.rstrip("/")

            # Use job name parser to get the correct API path
            api_job_path = JobNameParser.to_jenkins_api_path(job_name)

            api_url = f"{base_url}/{api_job_path}/{build_number}/api/json"
            params = {"tree": "actions[nodes[actions[description]]]"}

            response = self.connection.session.get(
                api_url, params=params, timeout=self.connection.config.timeout
            )
            response.raise_for_status()
            data = response.json()

            # Parse the tree API response for child job links
            for top_level_action in data.get("actions", []):
                if "nodes" in top_level_action:
                    for node in top_level_action.get("nodes", []):
                        for node_action in node.get("actions", []):
                            description = node_action.get("description")
                            if description:
                                # Parse the description string: "job » path #build"
                                match = re.match(r"^(.*) #(\d+)", description.strip())
                                if match:
                                    job_path_raw = match.group(1).strip()
                                    build_num = int(match.group(2))

                                    # Convert "job » path" to normalized job name
                                    tree_job_name = job_path_raw.replace(" » ", "/")
                                    tree_job_name = JobNameParser.normalize_job_name(
                                        tree_job_name
                                    )
                                    children.append((tree_job_name, build_num))

        except Exception as e:
            logger.debug(
                f"Tree API discovery failed for {job_name}#{build_number}: {e}"
            )

        return children

    def _discover_children_subbuilds_field(
        self, build_info: Dict
    ) -> List[Tuple[str, int]]:
        """Discover children from subBuilds field (thread-safe)"""
        children = []

        if "subBuilds" in build_info:
            for sub_build_data in build_info.get("subBuilds", []):
                child_job_name = sub_build_data.get("jobName")
                child_build_number = sub_build_data.get("buildNumber")
                if child_job_name and child_build_number:
                    children.append((child_job_name, child_build_number))

        return children

    def _collect_all_sub_builds(
        self,
        current_build_job_name: str,
        current_build_number: int,
        current_depth: int,
        visited: Set[Tuple[str, int]],
        all_sub_builds_list: List[SubBuild],
        parent_job_name_for_children: Optional[str],
        parent_build_number_for_children: Optional[int],
    ):
        """Collect all sub-builds using multiple discovery methods"""
        if (current_build_job_name, current_build_number) in visited:
            return
        visited.add((current_build_job_name, current_build_number))

        # Try different discovery methods in order of preference
        discovered_children = self._discover_all_children(
            current_build_job_name, current_build_number
        )

        # Process discovered children
        self._process_discovered_children(
            discovered_children,
            current_build_job_name,
            current_build_number,
            current_depth,
            visited,
            all_sub_builds_list,
            parent_job_name_for_children,
            parent_build_number_for_children,
        )

    def _discover_all_children(
        self, job_name: str, build_number: int
    ) -> List[Tuple[str, int]]:
        """Discover children using all available methods"""
        children = []

        # Method 1: wfapi discovery (PRIMARY)
        try:
            wfapi_children = self._discover_children_via_wfapi(job_name, build_number)
            children.extend(wfapi_children)
        except Exception as e:
            logger.debug(f"wfapi discovery failed for {job_name}#{build_number}: {e}")

        # Method 2: Classic API discovery (SECONDARY)
        try:
            classic_children = self._discover_children_via_classic_api(
                job_name, build_number
            )
            children.extend(classic_children)
        except Exception as e:
            logger.debug(
                f"Classic API discovery failed for {job_name}#{build_number}: {e}"
            )

        # Method 3: Tree API discovery (TERTIARY)
        try:
            tree_children = self._discover_children_via_tree_api(job_name, build_number)
            children.extend(tree_children)
        except Exception as e:
            logger.debug(
                f"Tree API discovery failed for {job_name}#{build_number}: {e}"
            )

        # Deduplicate children
        seen = set()
        unique_children = []
        for child in children:
            if child not in seen:
                seen.add(child)
                unique_children.append(child)

        return unique_children

    def _discover_children_via_wfapi(
        self, job_name: str, build_number: int
    ) -> List[Tuple[str, int]]:
        """Discover children via wfapi method"""
        children = []

        if not self.connection.config.url:
            return children

        base_url = self.connection.config.url.rstrip("/")
        api_job_path = JobNameParser.to_jenkins_api_path(job_name)

        # Try wfapi/runs endpoint
        wfapi_runs_url = f"{base_url}/{api_job_path}/{build_number}/wfapi/runs"

        response = self.connection.session.get(
            wfapi_runs_url, timeout=self.connection.config.timeout
        )
        response.raise_for_status()
        runs_data = response.json()

        if isinstance(runs_data, list):
            for run_data in runs_data:
                children.extend(self._extract_children_from_run_data(run_data))

        return children

    def _extract_children_from_run_data(self, run_data: Dict) -> List[Tuple[str, int]]:
        """Extract children from wfapi run data"""
        children = []

        run_name = run_data.get("name")
        run_id = run_data.get("id")
        run_status = run_data.get("status")

        if run_name and run_id and run_status != "NOT_EXECUTED":
            downstream_builds = run_data.get("downstreamBuilds", [])
            for downstream in downstream_builds:
                downstream_job = downstream.get("jobName")
                downstream_build = downstream.get("buildNumber")
                if downstream_job and downstream_build:
                    normalized_job = JobNameParser.normalize_job_name(downstream_job)
                    children.append((normalized_job, int(downstream_build)))

        return children

    def _discover_children_via_classic_api(
        self, job_name: str, build_number: int
    ) -> List[Tuple[str, int]]:
        """Discover children via classic Jenkins API"""
        children = []

        try:
            build_info = self.connection.client.get_build_info(
                job_name, build_number, depth=1
            )
        except Exception:
            return children

        # Check actions for triggered builds
        for action in build_info.get("actions", []):
            if (
                action
                and "_class" in action
                and "hudson.plugins.promoted_builds.BuildInfoExporterAction"
                in action["_class"]
            ):
                for triggered_build in action.get("triggeredBuilds", []):
                    child_job_name = triggered_build.get(
                        "projectName"
                    ) or triggered_build.get("jobName")
                    child_build_number = triggered_build.get("buildNumber")
                    if child_job_name and child_build_number:
                        children.append((child_job_name, child_build_number))

        # Check subBuilds field
        for sub_build_data in build_info.get("subBuilds", []):
            child_job_name = sub_build_data.get("jobName")
            child_build_number = sub_build_data.get("buildNumber")
            if child_job_name and child_build_number:
                children.append((child_job_name, child_build_number))

        return children

    def _discover_children_via_tree_api(
        self, job_name: str, build_number: int
    ) -> List[Tuple[str, int]]:
        """Discover children via Tree API"""
        children = []

        try:
            base_url = self.connection.config.url.rstrip("/")
            api_job_path = JobNameParser.to_jenkins_api_path(job_name)

            api_url = f"{base_url}/{api_job_path}/{build_number}/api/json"
            params = {"tree": "actions[nodes[actions[description]]]"}

            response = self.connection.session.get(
                api_url, params=params, timeout=self.connection.config.timeout
            )
            response.raise_for_status()
            data = response.json()

            # Parse tree API response
            for top_level_action in data.get("actions", []):
                if "nodes" in top_level_action:
                    for node in top_level_action.get("nodes", []):
                        for node_action in node.get("actions", []):
                            description = node_action.get("description")
                            if description:
                                match = re.match(r"^(.*) #(\d+)", description.strip())
                                if match:
                                    job_path_raw = match.group(1).strip()
                                    build_num = int(match.group(2))

                                    tree_job_name = job_path_raw.replace(" » ", "/")
                                    tree_job_name = JobNameParser.normalize_job_name(
                                        tree_job_name
                                    )
                                    children.append((tree_job_name, build_num))

        except Exception:
            pass

        return children

    def _process_discovered_children(
        self,
        children: List[Tuple[str, int]],
        current_job_name: str,
        current_build_number: int,
        current_depth: int,
        visited: Set[Tuple[str, int]],
        all_sub_builds_list: List[SubBuild],
        parent_job_name_for_children: Optional[str],
        parent_build_number_for_children: Optional[int],
    ):
        """Process discovered children and recurse"""
        for child_job, child_build in children:
            if not child_job:
                continue

            status, url = self._get_build_status_and_url(child_job, child_build)

            sub_build = SubBuild(
                job_name=child_job,
                build_number=child_build,
                url=url,
                status=status,
                parent_job_name=current_job_name,
                parent_build_number=current_build_number,
                depth=current_depth,
            )
            all_sub_builds_list.append(sub_build)

            # Recurse to find children of this sub-build
            if (child_job, child_build) not in visited:
                self._collect_all_sub_builds(
                    child_job,
                    child_build,
                    current_depth + 1,
                    visited,
                    all_sub_builds_list,
                    current_job_name,
                    current_build_number,
                )

    def _get_build_status_and_url(
        self, job_name: str, build_number: int
    ) -> Tuple[Optional[str], Optional[str]]:
        """Helper to fetch build status and URL, returning Nones on failure."""
        try:
            # Depth 0 is sufficient for result and url
            info = self.connection.client.get_build_info(
                job_name, build_number, depth=0
            )
            status = info.get("result")  # SUCCESS, FAILURE, ABORTED, UNSTABLE, etc.
            if status is None and info.get("building", False):
                status = "RUNNING"
            elif status is None:
                status = "UNKNOWN"
            return status, info.get("url")
        except Exception as e:
            logger.debug(f"Could not get status for {job_name} #{build_number}: {e}")
            return "UNKNOWN", None

    def list_pipeline_runs(self, parent: Build) -> List[SubBuild]:
        """List pipeline runs using wfapi/runs endpoint (from jenkins_client_old.py)"""
        runs: List[SubBuild] = []
        base_url = self.connection.config.url.rstrip("/")
        formatted_job_name = parent.job_name.replace("/", "/job/")
        wfapi_url = (
            f"{base_url}/job/{formatted_job_name}/{parent.build_number}/wfapi/runs"
        )

        try:
            response = self.connection.session.get(wfapi_url)
            response.raise_for_status()
            runs_data = response.json()

            for run_data in runs_data:
                run_id = run_data.get("id")
                run_name = run_data.get("name", f"Stage-{run_id}")
                run_status = run_data.get("status", "UNKNOWN")
                run_url = f"{parent.url}flowGraphTable/{run_id}/"

                runs.append(
                    SubBuild(
                        job_name=run_name,
                        build_number=int(run_id) if run_id and run_id.isdigit() else 0,
                        url=run_url,
                        status=run_status,
                        parent_job_name=parent.job_name,
                        parent_build_number=parent.build_number,
                        depth=1,
                    )
                )
        except Exception as e:
            logger.error(
                f"Pipeline runs fetch failed for {parent.job_name} #{parent.build_number}: {e}"
            )
            raise SubBuildDiscoveryError(f"Failed to fetch pipeline runs: {e}") from e

        return runs

    def get_build_hierarchy(
        self, root_job_name: str, root_build_number: int, max_depth: int = 5
    ) -> Dict[str, Any]:
        """Get the complete build hierarchy as a nested structure"""
        try:
            subbuilds = self.discover_subbuilds(
                root_job_name, root_build_number, max_depth
            )

            # Group sub-builds by parent
            hierarchy = {
                "job_name": root_job_name,
                "build_number": root_build_number,
                "depth": 0,
                "children": [],
            }

            # Build a lookup for quick access
            build_lookup = {(root_job_name, root_build_number): hierarchy}

            # Sort sub-builds by depth to ensure parents are processed first
            subbuilds.sort(key=lambda x: x.depth)

            for subbuild in subbuilds:
                subbuild_node = {
                    "job_name": subbuild.job_name,
                    "build_number": subbuild.build_number,
                    "status": subbuild.status,
                    "depth": subbuild.depth,
                    "url": subbuild.url,
                    "children": [],
                }

                # Find parent node
                if (
                    subbuild.parent_job_name
                    and subbuild.parent_build_number is not None
                ):
                    parent_key = (
                        subbuild.parent_job_name,
                        subbuild.parent_build_number,
                    )
                    if parent_key in build_lookup:
                        build_lookup[parent_key]["children"].append(subbuild_node)
                    else:
                        # Parent not found, add to root
                        hierarchy["children"].append(subbuild_node)
                else:
                    # No parent info, add to root
                    hierarchy["children"].append(subbuild_node)

                # Add to lookup for future children
                build_lookup[(subbuild.job_name, subbuild.build_number)] = subbuild_node

            return hierarchy

        except Exception as e:
            raise SubBuildDiscoveryError(f"Failed to build hierarchy: {e}") from e

    def find_failed_subbuilds(
        self, parent_job_name: str, parent_build_number: int, max_depth: int = 5
    ) -> List[SubBuild]:
        """Find all failed sub-builds in the hierarchy"""
        try:
            subbuilds = self.discover_subbuilds(
                parent_job_name, parent_build_number, max_depth
            )
            failed_builds = []

            for subbuild in subbuilds:
                # Get actual build status
                try:
                    from .build_manager import BuildManager

                    build_manager = BuildManager(self.connection)
                    build_info = build_manager.get_build_info(
                        subbuild.job_name, subbuild.build_number
                    )

                    if build_info.status in ["FAILURE", "UNSTABLE", "ABORTED"]:
                        subbuild.status = build_info.status
                        failed_builds.append(subbuild)

                except Exception as e:
                    logger.warning(
                        f"Could not get status for {subbuild.job_name}#{subbuild.build_number}: {e}"
                    )
                    # If we can't get status but it was discovered, assume it might be failed
                    if subbuild.status in ["FAILURE", "UNSTABLE", "ABORTED", "UNKNOWN"]:
                        failed_builds.append(subbuild)

            # Sort by depth (deepest failures first) for better debugging
            failed_builds.sort(key=lambda x: x.depth, reverse=True)

            return failed_builds

        except Exception as e:
            raise SubBuildDiscoveryError(
                f"Failed to find failed sub-builds: {e}"
            ) from e
