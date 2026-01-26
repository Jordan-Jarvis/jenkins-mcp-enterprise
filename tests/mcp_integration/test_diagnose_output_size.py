"""Regression tests: diagnose_build_failure output must be size-bounded.

We had a real-world case where `diagnose_build_failure` returned multi-million-token
payloads because `error_analysis.errors[].match_text` contained entire ~1MB chunks.

These tests ensure the tool never returns unbounded log blobs.
"""

import json

import pytest

from .mcp_test_client import MCPTestClient


@pytest.mark.asyncio
async def test_diagnose_build_failure_error_analysis_is_bounded(seeded_jenkins_test_env):
    config = seeded_jenkins_test_env.config
    jenkins_url = config["jenkins"]["url"]

    async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
        result = await client.call_tool(
            "diagnose_build_failure",
            {
                "job_name": "QA_JOBS/master",
                "build_number": 9,
                "jenkins_url": jenkins_url,
                # Force processing of all builds (in this fixture there are successes + failures)
                "skip_successful_builds": False,
            },
            timeout=60.0,
        )

        assert "content" in result, f"Expected MCP content envelope, got: {result}"
        data = json.loads(result["content"][0]["text"])

        error_analysis = data.get("error_analysis") or {}
        errors = error_analysis.get("errors") or []

        # No more than 10 error entries by default
        assert len(errors) <= 10

        for e in errors:
            match_text = (e.get("match_text") or "")
            context = (e.get("context") or "")

            # Hard caps to prevent runaway responses
            assert len(match_text) <= 600
            assert len(context) <= 2500

        # Also cap semantic highlights
        highlights = error_analysis.get("semantic_highlights") or []
        assert len(highlights) <= 10
        for h in highlights:
            assert len(h) <= 2000
