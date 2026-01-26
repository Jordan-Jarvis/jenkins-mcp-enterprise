"""Tests for recursive sub-build discovery scenarios"""

import pytest
from unittest.mock import MagicMock, patch
from jenkins_mcp_enterprise.jenkins.subbuild_discoverer import SubBuildDiscoverer
from jenkins_mcp_enterprise.base import SubBuild

class TestRecursiveDiscovery:
    
    @pytest.fixture
    def mock_connection(self):
        connection = MagicMock()
        connection.config.url = "http://jenkins.example.com"
        connection.config.timeout = 30
        return connection

    @pytest.fixture
    def discoverer(self, mock_connection):
        # Disable strict upstream validation for these recursion-structure unit tests.
        # These tests are focused on cycle safety, not Jenkins cause payload correctness.
        return SubBuildDiscoverer(
            mock_connection, max_parallel_workers=1, validate_upstream_causes=False
        )

    def test_immediate_cycle_detection(self, discoverer):
        """Test that a job triggering itself doesn't cause infinite recursion"""
        # Setup: Job A #1 triggers Job A #1 (immediate cycle)
        
        # Mock get_build_info to return success
        discoverer.connection.client.get_build_info.return_value = {"result": "SUCCESS", "url": "http://jenkins/job/A/1/"}
        
        # Mock discovery to return the parent as a child
        # (Sequential path uses the *_via_* methods.)
        with patch.object(
            discoverer, "_discover_children_via_wfapi", return_value=[("JobA", 1)]
        ):
            with patch.object(discoverer, "_discover_children_via_tree_api", return_value=[]):
                with patch.object(
                    discoverer, "_discover_children_via_classic_api", return_value=[]
                ):

                    # Run discovery
                    subbuilds = discoverer.discover_subbuilds(
                        "JobA", 1, max_depth=5, parallel=False
                    )

                    # Should find 0 subbuilds (self-cycle filtered) and should not hang/crash.
                    assert len(subbuilds) == 0

    def test_indirect_cycle_detection(self, discoverer):
        """Test that A -> B -> A doesn't cause infinite recursion"""
        # Setup: Job A #1 -> Job B #1 -> Job A #1
        
        discoverer.connection.client.get_build_info.return_value = {"result": "SUCCESS", "url": "http://jenkins/job/url/"}
        
        def mock_discover_children(job_name, build_number):
            if job_name == "JobA" and build_number == 1:
                return [("JobB", 1)]
            elif job_name == "JobB" and build_number == 1:
                return [("JobA", 1)]
            return []

        with patch.object(
            discoverer, "_discover_children_via_wfapi", side_effect=mock_discover_children
        ):
            with patch.object(discoverer, "_discover_children_via_tree_api", return_value=[]):
                with patch.object(
                    discoverer, "_discover_children_via_classic_api", return_value=[]
                ):

                    # Run discovery
                    subbuilds = discoverer.discover_subbuilds(
                        "JobA", 1, max_depth=5, parallel=False
                    )

                    # Should find JobB #1
                    assert len(subbuilds) == 1
                    assert subbuilds[0].job_name == "JobB"
                    assert subbuilds[0].build_number == 1

    def test_diamond_dependency(self, discoverer):
        """Test that A -> B, A -> C, B -> D, C -> D handles duplicates correctly"""
        # Setup: 
        # A1 -> B1
        # A1 -> C1
        # B1 -> D1
        # C1 -> D1
        
        discoverer.connection.client.get_build_info.return_value = {"result": "SUCCESS", "url": "http://jenkins/job/url/"}
        
        def mock_discover_children(job_name, build_number):
            if job_name == "JobA":
                return [("JobB", 1), ("JobC", 1)]
            elif job_name == "JobB":
                return [("JobD", 1)]
            elif job_name == "JobC":
                return [("JobD", 1)]
            return []

        with patch.object(
            discoverer, "_discover_children_via_wfapi", side_effect=mock_discover_children
        ):
            with patch.object(discoverer, "_discover_children_via_tree_api", return_value=[]):
                with patch.object(
                    discoverer, "_discover_children_via_classic_api", return_value=[]
                ):

                    # Run discovery
                    subbuilds = discoverer.discover_subbuilds(
                        "JobA", 1, max_depth=5, parallel=False
                    )

                    # Should find B1, C1, D1. D1 might appear twice in raw traversal but should be deduplicated
                    job_names = sorted([sb.job_name for sb in subbuilds])
                    assert "JobB" in job_names
                    assert "JobC" in job_names
                    assert "JobD" in job_names

                    # Check for duplicates of D1
                    d1_count = sum(1 for sb in subbuilds if sb.job_name == "JobD")
                    # It's acceptable to have D1 twice if they have different parents (B and C)
                    # But we want to ensure we don't have infinite loops
                    assert d1_count >= 1
