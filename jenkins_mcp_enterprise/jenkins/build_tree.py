"""Canonical build tree helpers.

This module centralizes how we represent Jenkins build/sub-build hierarchies.

Why this exists:
- Multiple parts of the codebase previously produced "sub-build" data in slightly
  different shapes (flat lists, different tree shapes, different field names).
- Tools and diagnostics should share one canonical subtree model so clients see
  consistent output.

The canonical representation is a JSON-serializable dict node:

{
  "job_name": str,
  "build_number": int,
  "status": str,
  "url": str | None,
  "depth": int,
  "children": [node, ...],

  # Optional annotations (added by annotate_build_tree):
  "parent_job_name": str | None,
  "parent_build_number": int | None,
  "failed": bool,
}

The Jenkins discovery layer (see `SubBuildDiscoverer.get_build_hierarchy`) returns
most of these fields already; `annotate_build_tree` adds the optional ones.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


BuildTreeNode = Dict[str, Any]


def flatten_build_tree(node: BuildTreeNode) -> List[BuildTreeNode]:
    """Flatten a build tree (pre-order traversal) into a list of node dicts."""
    result: List[BuildTreeNode] = [node]
    for child in node.get("children", []) or []:
        result.extend(flatten_build_tree(child))
    return result


def annotate_build_tree(
    node: BuildTreeNode,
    *,
    failure_statuses: Optional[Set[str]] = None,
    status_unknown_placeholder: str = "UNKNOWN",
    _parent: Optional[Tuple[str, int]] = None,
    _depth: Optional[int] = None,
) -> BuildTreeNode:
    """Annotate a build tree in-place and return it.

    Adds:
    - depth (if missing)
    - parent_job_name / parent_build_number
    - failed

    This is intentionally non-opinionated about where the tree came from.
    """
    if failure_statuses is None:
        failure_statuses = {"FAILURE", "UNSTABLE", "ABORTED"}

    job_name = node.get("job_name", "")
    build_number = int(node.get("build_number", 0))

    if _depth is None:
        node_depth = int(node.get("depth", 0) or 0)
    else:
        node_depth = int(_depth)
        node["depth"] = node_depth

    if _parent is None:
        node["parent_job_name"] = node.get("parent_job_name")
        node["parent_build_number"] = node.get("parent_build_number")
    else:
        parent_job, parent_build = _parent
        node["parent_job_name"] = parent_job
        node["parent_build_number"] = parent_build

    status = node.get("status") or status_unknown_placeholder
    node["status"] = status
    url = node.get("url") or None
    node["url"] = url

    node["failed"] = bool(status in failure_statuses)
    # Backward compatibility: remove older field if present
    node.pop("is_failure", None)
    # Output hygiene: we no longer emit display_text to save tokens
    node.pop("display_text", None)

    children = node.get("children", []) or []
    normalized_children: List[BuildTreeNode] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        normalized_children.append(child)

    node["children"] = normalized_children

    for child in node["children"]:
        annotate_build_tree(
            child,
            failure_statuses=failure_statuses,
            status_unknown_placeholder=status_unknown_placeholder,
            _parent=(job_name, build_number),
            _depth=node_depth + 1,
        )

    return node


def build_tree_index(node: BuildTreeNode) -> Dict[Tuple[str, int], BuildTreeNode]:
    """Build a lookup dict keyed by (job_name, build_number)."""
    index: Dict[Tuple[str, int], BuildTreeNode] = {}
    for n in flatten_build_tree(node):
        key = (n.get("job_name", ""), int(n.get("build_number", 0)))
        index[key] = n
    return index


def prune_build_tree_to_failure_paths(
    node: BuildTreeNode,
    *,
    include_if_no_failures: bool = True,
) -> BuildTreeNode:
    """Return a pruned copy of `node` that only includes paths leading to failures.

    Kept nodes are:
    - any node with `failed == True`, and
    - any ancestor of such a node.

    If no failures exist anywhere in the tree:
    - when `include_if_no_failures` is True, returns a shallow copy of the root with `children=[]`
    - otherwise returns an empty-root tree (children=[]).

    Notes:
    - This assumes the tree has already been annotated (see [`annotate_build_tree()`](jenkins_mcp_enterprise/jenkins/build_tree.py:48))
      so `failed` is available.
    - Depth values are preserved (they represent true nesting depth even after pruning).
    """

    def _prune(n: BuildTreeNode) -> Optional[BuildTreeNode]:
        children = n.get("children", []) or []
        pruned_children: List[BuildTreeNode] = []
        for c in children:
            if not isinstance(c, dict):
                continue
            pc = _prune(c)
            if pc is not None:
                pruned_children.append(pc)

        is_failure = bool(n.get("failed", False))

        # Keep this node if it is a failure or if it leads to a failure.
        if is_failure or pruned_children:
            out = dict(n)
            out["children"] = pruned_children
            return out

        return None

    pruned = _prune(node)
    if pruned is not None:
        return pruned

    # No failures anywhere
    out = dict(node)
    out["children"] = []
    return out if include_if_no_failures else out
