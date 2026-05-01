"""Focused tests for sub-build discovery fallbacks."""

from unittest.mock import Mock

from jenkins_mcp_enterprise.jenkins.subbuild_discoverer import SubBuildDiscoverer


class FakeResponse:
    """Minimal response double for Jenkins API calls."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestSubBuildDiscoverer:
    """Validate downstream-project fallback discovery."""

    def test_downstream_projects_match_exact_upstream_build(self):
        connection = Mock()
        connection.config.url = "http://jenkins.example.com"
        connection.config.timeout = 30

        api_payloads = {
            (
                "http://jenkins.example.com/job/root-fanout/api/json",
                "downstreamProjects[fullName,name]",
            ): {
                "downstreamProjects": [
                    {"fullName": "mid-pass"},
                    {"fullName": "mid-to-fail"},
                    {"fullName": "mid-to-unstable"},
                ]
            },
            (
                "http://jenkins.example.com/job/mid-pass/api/json",
                "builds[number]{0,25}",
            ): {"builds": [{"number": 3}, {"number": 2}, {"number": 1}]},
            (
                "http://jenkins.example.com/job/mid-to-fail/api/json",
                "builds[number]{0,25}",
            ): {"builds": [{"number": 2}]},
            (
                "http://jenkins.example.com/job/mid-to-unstable/api/json",
                "builds[number]{0,25}",
            ): {"builds": [{"number": 2}]},
        }

        def session_get(url, params=None, timeout=None):
            key = (url, (params or {}).get("tree"))
            assert key in api_payloads, key
            return FakeResponse(api_payloads[key])

        build_payloads = {
            ("mid-pass", 3): {
                "actions": [
                    {"causes": [{"upstreamProject": "root-fanout", "upstreamBuild": 3}]}
                ],
                "result": "SUCCESS",
                "url": "http://jenkins.example.com/job/mid-pass/3/",
            },
            ("mid-pass", 2): {
                "actions": [
                    {"causes": [{"upstreamProject": "root-fanout", "upstreamBuild": 2}]}
                ],
                "result": "SUCCESS",
                "url": "http://jenkins.example.com/job/mid-pass/2/",
            },
            ("mid-pass", 1): {
                "actions": [
                    {"causes": [{"upstreamProject": "root-fanout", "upstreamBuild": 1}]}
                ],
                "result": "SUCCESS",
                "url": "http://jenkins.example.com/job/mid-pass/1/",
            },
            ("mid-to-fail", 2): {
                "actions": [
                    {"causes": [{"upstreamProject": "root-fanout", "upstreamBuild": 2}]}
                ],
                "result": "SUCCESS",
                "url": "http://jenkins.example.com/job/mid-to-fail/2/",
            },
            ("mid-to-unstable", 2): {
                "actions": [
                    {"causes": [{"upstreamProject": "root-fanout", "upstreamBuild": 2}]}
                ],
                "result": "SUCCESS",
                "url": "http://jenkins.example.com/job/mid-to-unstable/2/",
            },
        }

        connection.session.get.side_effect = session_get
        connection.client.get_build_info.side_effect = (
            lambda job_name, build_number, depth=1: build_payloads[
                (job_name, build_number)
            ]
        )

        discoverer = SubBuildDiscoverer(connection)

        children = discoverer._discover_children_downstream_projects("root-fanout", 2)

        assert children == [
            ("mid-pass", 2),
            ("mid-to-fail", 2),
            ("mid-to-unstable", 2),
        ]

    def test_discover_subbuilds_recurses_through_downstream_projects(self):
        connection = Mock()
        connection.config.url = "http://jenkins.example.com"
        connection.config.timeout = 30

        api_payloads = {
            (
                "http://jenkins.example.com/job/root-fanout/api/json",
                "downstreamProjects[fullName,name]",
            ): {
                "downstreamProjects": [
                    {"fullName": "mid-pass"},
                    {"fullName": "mid-to-fail"},
                    {"fullName": "mid-to-unstable"},
                ]
            },
            (
                "http://jenkins.example.com/job/mid-pass/api/json",
                "builds[number]{0,25}",
            ): {"builds": [{"number": 2}]},
            (
                "http://jenkins.example.com/job/mid-pass/api/json",
                "downstreamProjects[fullName,name]",
            ): {"downstreamProjects": [{"fullName": "leaf-pass"}]},
            (
                "http://jenkins.example.com/job/mid-to-fail/api/json",
                "builds[number]{0,25}",
            ): {"builds": [{"number": 2}]},
            (
                "http://jenkins.example.com/job/mid-to-fail/api/json",
                "downstreamProjects[fullName,name]",
            ): {"downstreamProjects": [{"fullName": "leaf-fail"}]},
            (
                "http://jenkins.example.com/job/mid-to-unstable/api/json",
                "builds[number]{0,25}",
            ): {"builds": [{"number": 2}]},
            (
                "http://jenkins.example.com/job/mid-to-unstable/api/json",
                "downstreamProjects[fullName,name]",
            ): {"downstreamProjects": [{"fullName": "leaf-unstable"}]},
            (
                "http://jenkins.example.com/job/leaf-pass/api/json",
                "builds[number]{0,25}",
            ): {"builds": [{"number": 1}]},
            (
                "http://jenkins.example.com/job/leaf-pass/api/json",
                "downstreamProjects[fullName,name]",
            ): {"downstreamProjects": []},
            (
                "http://jenkins.example.com/job/leaf-fail/api/json",
                "builds[number]{0,25}",
            ): {"builds": [{"number": 1}]},
            (
                "http://jenkins.example.com/job/leaf-fail/api/json",
                "downstreamProjects[fullName,name]",
            ): {"downstreamProjects": []},
            (
                "http://jenkins.example.com/job/leaf-unstable/api/json",
                "builds[number]{0,25}",
            ): {"builds": [{"number": 1}]},
            (
                "http://jenkins.example.com/job/leaf-unstable/api/json",
                "downstreamProjects[fullName,name]",
            ): {"downstreamProjects": []},
        }

        def session_get(url, params=None, timeout=None):
            key = (url, (params or {}).get("tree"))
            assert key in api_payloads, key
            return FakeResponse(api_payloads[key])

        build_payloads = {
            ("root-fanout", 2): {
                "actions": [],
                "result": "SUCCESS",
                "url": "http://jenkins.example.com/job/root-fanout/2/",
            },
            ("mid-pass", 2): {
                "actions": [
                    {"causes": [{"upstreamProject": "root-fanout", "upstreamBuild": 2}]}
                ],
                "result": "SUCCESS",
                "url": "http://jenkins.example.com/job/mid-pass/2/",
            },
            ("mid-to-fail", 2): {
                "actions": [
                    {"causes": [{"upstreamProject": "root-fanout", "upstreamBuild": 2}]}
                ],
                "result": "SUCCESS",
                "url": "http://jenkins.example.com/job/mid-to-fail/2/",
            },
            ("mid-to-unstable", 2): {
                "actions": [
                    {"causes": [{"upstreamProject": "root-fanout", "upstreamBuild": 2}]}
                ],
                "result": "SUCCESS",
                "url": "http://jenkins.example.com/job/mid-to-unstable/2/",
            },
            ("leaf-pass", 1): {
                "actions": [
                    {"causes": [{"upstreamProject": "mid-pass", "upstreamBuild": 2}]}
                ],
                "result": "SUCCESS",
                "url": "http://jenkins.example.com/job/leaf-pass/1/",
            },
            ("leaf-fail", 1): {
                "actions": [
                    {"causes": [{"upstreamProject": "mid-to-fail", "upstreamBuild": 2}]}
                ],
                "result": "FAILURE",
                "url": "http://jenkins.example.com/job/leaf-fail/1/",
            },
            ("leaf-unstable", 1): {
                "actions": [
                    {
                        "causes": [
                            {
                                "upstreamProject": "mid-to-unstable",
                                "upstreamBuild": 2,
                            }
                        ]
                    }
                ],
                "result": "UNSTABLE",
                "url": "http://jenkins.example.com/job/leaf-unstable/1/",
            },
        }

        connection.session.get.side_effect = session_get
        connection.client.get_build_info.side_effect = (
            lambda job_name, build_number, depth=1: build_payloads[
                (job_name, build_number)
            ]
        )

        discoverer = SubBuildDiscoverer(connection)
        discoverer._discover_children_via_wfapi = Mock(return_value=[])
        discoverer._discover_children_via_classic_api = Mock(return_value=[])
        discoverer._discover_children_via_tree_api = Mock(return_value=[])

        subbuilds = discoverer.discover_subbuilds(
            "root-fanout", 2, max_depth=5, parallel=False
        )

        assert [
            (
                subbuild.job_name,
                subbuild.build_number,
                subbuild.parent_job_name,
                subbuild.parent_build_number,
                subbuild.depth,
                subbuild.status,
            )
            for subbuild in subbuilds
        ] == [
            ("mid-pass", 2, "root-fanout", 2, 1, "SUCCESS"),
            ("leaf-pass", 1, "mid-pass", 2, 2, "SUCCESS"),
            ("mid-to-fail", 2, "root-fanout", 2, 1, "SUCCESS"),
            ("leaf-fail", 1, "mid-to-fail", 2, 2, "FAILURE"),
            ("mid-to-unstable", 2, "root-fanout", 2, 1, "SUCCESS"),
            ("leaf-unstable", 1, "mid-to-unstable", 2, 2, "UNSTABLE"),
        ]

    def test_discover_subbuilds_parallel_sets_nested_parent_context(self):
        connection = Mock()
        connection.config.url = "http://jenkins.example.com"
        connection.config.timeout = 30

        api_payloads = {
            (
                "http://jenkins.example.com/job/root-fanout/api/json",
                "downstreamProjects[fullName,name]",
            ): {
                "downstreamProjects": [
                    {"fullName": "mid-pass"},
                    {"fullName": "mid-to-fail"},
                    {"fullName": "mid-to-unstable"},
                ]
            },
            (
                "http://jenkins.example.com/job/mid-pass/api/json",
                "builds[number]{0,25}",
            ): {"builds": [{"number": 2}]},
            (
                "http://jenkins.example.com/job/mid-pass/api/json",
                "downstreamProjects[fullName,name]",
            ): {"downstreamProjects": [{"fullName": "leaf-pass"}]},
            (
                "http://jenkins.example.com/job/mid-to-fail/api/json",
                "builds[number]{0,25}",
            ): {"builds": [{"number": 2}]},
            (
                "http://jenkins.example.com/job/mid-to-fail/api/json",
                "downstreamProjects[fullName,name]",
            ): {"downstreamProjects": [{"fullName": "leaf-fail"}]},
            (
                "http://jenkins.example.com/job/mid-to-unstable/api/json",
                "builds[number]{0,25}",
            ): {"builds": [{"number": 2}]},
            (
                "http://jenkins.example.com/job/mid-to-unstable/api/json",
                "downstreamProjects[fullName,name]",
            ): {"downstreamProjects": [{"fullName": "leaf-unstable"}]},
            (
                "http://jenkins.example.com/job/leaf-pass/api/json",
                "builds[number]{0,25}",
            ): {"builds": [{"number": 1}]},
            (
                "http://jenkins.example.com/job/leaf-pass/api/json",
                "downstreamProjects[fullName,name]",
            ): {"downstreamProjects": []},
            (
                "http://jenkins.example.com/job/leaf-fail/api/json",
                "builds[number]{0,25}",
            ): {"builds": [{"number": 1}]},
            (
                "http://jenkins.example.com/job/leaf-fail/api/json",
                "downstreamProjects[fullName,name]",
            ): {"downstreamProjects": []},
            (
                "http://jenkins.example.com/job/leaf-unstable/api/json",
                "builds[number]{0,25}",
            ): {"builds": [{"number": 1}]},
            (
                "http://jenkins.example.com/job/leaf-unstable/api/json",
                "downstreamProjects[fullName,name]",
            ): {"downstreamProjects": []},
        }

        def session_get(url, params=None, timeout=None):
            key = (url, (params or {}).get("tree"))
            assert key in api_payloads, key
            return FakeResponse(api_payloads[key])

        build_payloads = {
            ("root-fanout", 2): {
                "actions": [],
                "result": "SUCCESS",
                "url": "http://jenkins.example.com/job/root-fanout/2/",
            },
            ("mid-pass", 2): {
                "actions": [
                    {"causes": [{"upstreamProject": "root-fanout", "upstreamBuild": 2}]}
                ],
                "result": "SUCCESS",
                "url": "http://jenkins.example.com/job/mid-pass/2/",
            },
            ("mid-to-fail", 2): {
                "actions": [
                    {"causes": [{"upstreamProject": "root-fanout", "upstreamBuild": 2}]}
                ],
                "result": "SUCCESS",
                "url": "http://jenkins.example.com/job/mid-to-fail/2/",
            },
            ("mid-to-unstable", 2): {
                "actions": [
                    {"causes": [{"upstreamProject": "root-fanout", "upstreamBuild": 2}]}
                ],
                "result": "SUCCESS",
                "url": "http://jenkins.example.com/job/mid-to-unstable/2/",
            },
            ("leaf-pass", 1): {
                "actions": [
                    {"causes": [{"upstreamProject": "mid-pass", "upstreamBuild": 2}]}
                ],
                "result": "SUCCESS",
                "url": "http://jenkins.example.com/job/leaf-pass/1/",
            },
            ("leaf-fail", 1): {
                "actions": [
                    {"causes": [{"upstreamProject": "mid-to-fail", "upstreamBuild": 2}]}
                ],
                "result": "FAILURE",
                "url": "http://jenkins.example.com/job/leaf-fail/1/",
            },
            ("leaf-unstable", 1): {
                "actions": [
                    {
                        "causes": [
                            {
                                "upstreamProject": "mid-to-unstable",
                                "upstreamBuild": 2,
                            }
                        ]
                    }
                ],
                "result": "UNSTABLE",
                "url": "http://jenkins.example.com/job/leaf-unstable/1/",
            },
        }

        connection.session.get.side_effect = session_get
        connection.client.get_build_info.side_effect = (
            lambda job_name, build_number, depth=1: build_payloads[
                (job_name, build_number)
            ]
        )

        discoverer = SubBuildDiscoverer(connection)
        discoverer._discover_children_wfapi = Mock(return_value=[])
        discoverer._discover_children_tree_api = Mock(return_value=[])
        discoverer._discover_children_build_actions = Mock(return_value=[])
        discoverer._discover_children_subbuilds_field = Mock(return_value=[])

        subbuilds = discoverer.discover_subbuilds(
            "root-fanout", 2, max_depth=5, parallel=True
        )

        assert {
            (
                subbuild.job_name,
                subbuild.build_number,
                subbuild.parent_job_name,
                subbuild.parent_build_number,
                subbuild.depth,
                subbuild.status,
            )
            for subbuild in subbuilds
        } == {
            ("mid-pass", 2, "root-fanout", 2, 1, "SUCCESS"),
            ("leaf-pass", 1, "mid-pass", 2, 2, "SUCCESS"),
            ("mid-to-fail", 2, "root-fanout", 2, 1, "SUCCESS"),
            ("leaf-fail", 1, "mid-to-fail", 2, 2, "FAILURE"),
            ("mid-to-unstable", 2, "root-fanout", 2, 1, "SUCCESS"),
            ("leaf-unstable", 1, "mid-to-unstable", 2, 2, "UNSTABLE"),
        }
