"""Unit tests for ``tools.jobs`` (find_jobs, get_job_definition, apply_job_edit)."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import requests

from jenkins_mcp_enterprise.tools.jobs import (
    ApplyJobEditTool,
    FindJobsTool,
    GetJobDefinitionTool,
)


def _make_response(*, status_code: int = 200, json_payload=None) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.json.return_value = json_payload if json_payload is not None else {}

    def _raise_for_status():
        if status_code >= 400:
            err = requests.HTTPError(f"HTTP {status_code}")
            err.response = response
            raise err

    response.raise_for_status.side_effect = _raise_for_status
    return response


def _make_jenkins_client(
    *,
    base_url: str = "https://jenkins.example.com",
    timeout: int = 30,
    job_list=None,
    job_xml: str = "<xml />",
    api_response: MagicMock = None,
    validation_payload=None,
) -> MagicMock:
    session = MagicMock()
    session.get.return_value = (
        api_response if api_response is not None else _make_response()
    )
    raw_client = MagicMock()
    raw_client.jenkins_request.return_value = _make_response(
        json_payload=validation_payload
    )

    client = MagicMock()
    client.config = SimpleNamespace(url=base_url, timeout=timeout)
    client.connection = SimpleNamespace(session=session, client=raw_client)
    client.list_jobs.return_value = job_list if job_list is not None else []
    client.get_job_config_xml.return_value = job_xml
    client.reconfig_job_xml.return_value = True
    return client


def _make_manager(
    job_editing_enabled: bool = False, client: MagicMock = None
) -> MagicMock:
    manager = MagicMock()
    manager.settings = {"enable_job_editing": job_editing_enabled}
    manager.get_usage_instructions.return_value = "configure instances"
    manager.resolve_jenkins_url.return_value = "prod"
    manager.get_jenkins_client.return_value = client
    return manager


def _make_cache_manager(tmp_path: Path) -> MagicMock:
    cache_manager = MagicMock()
    cache_manager.config = SimpleNamespace(base_dir=tmp_path)
    return cache_manager


class TestFindJobsTool:
    def test_finds_matching_jobs(self):
        jobs = [
            {
                "fullname": "team-a/service-a",
                "name": "service-a",
                "url": "https://jenkins.example.com/job/team-a/job/service-a/",
                "_class": "org.jenkinsci.plugins.workflow.job.WorkflowJob",
                "color": "blue",
            },
            {
                "fullname": "team-b/other-job",
                "name": "other-job",
                "url": "https://jenkins.example.com/job/team-b/job/other-job/",
                "_class": "hudson.model.FreeStyleProject",
                "color": "disabled",
            },
        ]
        client = _make_jenkins_client(job_list=jobs)
        tool = FindJobsTool(jenkins_client=client)

        result = tool.execute(
            jenkins_url="https://jenkins.example.com",
            query="service",
            limit=10,
        )

        assert result.success is True
        assert result.data["returned_count"] == 1
        assert result.data["jobs"][0]["job_name"] == "team-a/service-a"


class TestGetJobDefinitionTool:
    def test_returns_scm_location_for_scm_pipeline(self, tmp_path):
        response = _make_response(
            json_payload={
                "_class": "org.jenkinsci.plugins.workflow.job.WorkflowJob",
                "displayName": "service-a",
                "url": "https://jenkins.example.com/job/service-a/",
            }
        )
        client = _make_jenkins_client(api_response=response)
        client.get_job_config_xml.return_value = """
<flow-definition plugin=\"workflow-job@1.0\">
  <definition class=\"org.jenkinsci.plugins.workflow.cps.CpsScmFlowDefinition\" plugin=\"workflow-cps@1.0\">
    <scm class=\"hudson.plugins.git.GitSCM\" plugin=\"git@1.0\">
      <userRemoteConfigs>
        <hudson.plugins.git.UserRemoteConfig>
          <url>git@github.com:example/service-a.git</url>
        </hudson.plugins.git.UserRemoteConfig>
      </userRemoteConfigs>
      <branches>
        <hudson.plugins.git.BranchSpec>
          <name>*/main</name>
        </hudson.plugins.git.BranchSpec>
      </branches>
    </scm>
    <scriptPath>ci/Jenkinsfile</scriptPath>
  </definition>
</flow-definition>
""".strip()
        tool = GetJobDefinitionTool(
            jenkins_client=client,
            cache_manager=_make_cache_manager(tmp_path),
        )

        result = tool.execute(
            job_name="service-a",
            jenkins_url="https://jenkins.example.com",
        )

        assert result.success is True
        data = result.data
        assert data["definition_type"] == "scm_pipeline"
        assert (
            data["source_location"]["repo_url"]
            == "git@github.com:example/service-a.git"
        )
        assert data["source_location"]["script_path"] == "ci/Jenkinsfile"
        assert data["local_edit_path"] is None
        assert "source control" in data["edit_instructions"]

    def test_downloads_inline_script_for_inline_pipeline_when_editing_enabled(
        self, tmp_path
    ):
        response = _make_response(
            json_payload={
                "_class": "org.jenkinsci.plugins.workflow.job.WorkflowJob",
                "displayName": "inline-pipeline",
            }
        )
        client = _make_jenkins_client(
            api_response=response,
            job_xml=(
                "<flow-definition>"
                '<definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition">'
                "<script>pipeline { agent any; stages { stage('x') { steps { echo 'hello' } } } }</script>"
                "</definition>"
                "</flow-definition>"
            ),
        )
        manager = _make_manager(job_editing_enabled=True, client=client)
        tool = GetJobDefinitionTool(
            jenkins_client=client,
            cache_manager=_make_cache_manager(tmp_path),
            multi_jenkins_manager=manager,
        )

        result = tool.execute(
            job_name="team-a/inline-pipeline",
            jenkins_url="https://jenkins.example.com",
            max_inline_script_chars=20,
        )

        assert result.success is True
        data = result.data
        assert data["definition_type"] == "inline_pipeline"
        assert data["pipeline_style"] == "declarative"
        assert data["inline_script_truncated"] is True
        assert data["edit_mode"] == "inline_pipeline_script"
        assert data["local_edit_path"] is not None
        script_path = Path(data["local_edit_path"])
        assert script_path.exists()
        assert (
            script_path.read_text(encoding="utf-8")
            == "pipeline { agent any; stages { stage('x') { steps { echo 'hello' } } } }"
        )
        assert "apply_job_edit" == data["edit_upload_tool"]
        assert "Groovy" in data["edit_instructions"]


class TestApplyJobEditTool:
    def test_uploads_local_inline_script_back_to_jenkins(self, tmp_path):
        workspace_root = tmp_path / "job-definitions"
        script_path = (
            workspace_root / "prod" / "team-a" / "inline-pipeline" / "pipeline.groovy"
        )
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(
            "pipeline { agent any; stages { stage('x') { steps { echo 'updated' } } } }",
            encoding="utf-8",
        )

        client = _make_jenkins_client(
            validation_payload={"status": "success", "message": ""}
        )
        client.get_job_config_xml.return_value = (
            "<flow-definition>"
            '<definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition">'
            "<script>pipeline { agent any; stages { stage('x') { steps { echo 'original' } } } }</script>"
            "</definition>"
            "</flow-definition>"
        )
        manager = _make_manager(job_editing_enabled=True, client=client)
        manager.settings["job_edit_workspace_dir"] = str(workspace_root)
        tool = ApplyJobEditTool(
            jenkins_client=client,
            cache_manager=_make_cache_manager(tmp_path),
            multi_jenkins_manager=manager,
        )

        result = tool.execute(
            job_name="team-a/inline-pipeline",
            jenkins_url="https://jenkins.example.com",
            local_edit_path=str(script_path),
        )

        assert result.success is True
        assert result.data["edit_mode"] == "inline_pipeline_script"
        assert result.data["updated"] is True
        client.reconfig_job_xml.assert_called_once_with(
            "team-a/inline-pipeline",
            "<flow-definition><definition class=\"org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition\"><script>pipeline { agent any; stages { stage('x') { steps { echo 'updated' } } } }</script></definition></flow-definition>",
        )

    def test_uploads_local_xml_back_to_jenkins(self, tmp_path):
        workspace_root = tmp_path / "job-definitions"
        xml_path = workspace_root / "prod" / "team-a" / "inline-pipeline" / "config.xml"
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        xml_path.write_text(
            "<project><description>updated</description></project>", encoding="utf-8"
        )

        client = _make_jenkins_client()
        manager = _make_manager(job_editing_enabled=True, client=client)
        manager.settings["job_edit_workspace_dir"] = str(workspace_root)
        tool = ApplyJobEditTool(
            jenkins_client=client,
            cache_manager=_make_cache_manager(tmp_path),
            multi_jenkins_manager=manager,
        )

        result = tool.execute(
            job_name="team-a/inline-pipeline",
            jenkins_url="https://jenkins.example.com",
            local_edit_path=str(xml_path),
        )

        assert result.success is True
        assert result.data["edit_mode"] == "job_config_xml"
        assert result.data["updated"] is True
        client.reconfig_job_xml.assert_called_once_with(
            "team-a/inline-pipeline",
            "<project><description>updated</description></project>",
        )

    def test_rejects_invalid_declarative_script_before_upload(self, tmp_path):
        workspace_root = tmp_path / "job-definitions"
        script_path = (
            workspace_root / "prod" / "team-a" / "inline-pipeline" / "pipeline.groovy"
        )
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(
            "pipeline { agent any; stages { stage('broken') { steps { echo 'oops' } } }\n",
            encoding="utf-8",
        )

        client = _make_jenkins_client(
            validation_payload={
                "status": "ok",
                "data": {
                    "result": "failure",
                    "errors": [{"error": "expecting '}', found '' @ line 2"}],
                },
            }
        )
        client.get_job_config_xml.return_value = (
            "<flow-definition>"
            '<definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition">'
            "<script>pipeline { agent any; stages { stage('x') { steps { echo 'original' } } } }</script>"
            "</definition>"
            "</flow-definition>"
        )
        manager = _make_manager(job_editing_enabled=True, client=client)
        manager.settings["job_edit_workspace_dir"] = str(workspace_root)
        tool = ApplyJobEditTool(
            jenkins_client=client,
            cache_manager=_make_cache_manager(tmp_path),
            multi_jenkins_manager=manager,
        )

        result = tool.execute(
            job_name="team-a/inline-pipeline",
            jenkins_url="https://jenkins.example.com",
            local_edit_path=str(script_path),
        )

        assert result.success is True
        assert result.data["validation"]["valid"] is False
        assert "rejected" in result.data["error"].lower()
        client.reconfig_job_xml.assert_not_called()

    def test_rejects_edit_path_outside_workspace(self, tmp_path):
        xml_path = tmp_path / "outside.xml"
        xml_path.write_text("<flow-definition />", encoding="utf-8")

        client = _make_jenkins_client()
        manager = _make_manager(job_editing_enabled=True, client=client)
        manager.settings["job_edit_workspace_dir"] = str(tmp_path / "job-definitions")
        tool = ApplyJobEditTool(
            jenkins_client=client,
            cache_manager=_make_cache_manager(tmp_path),
            multi_jenkins_manager=manager,
        )

        result = tool.execute(
            job_name="team-a/inline-pipeline",
            jenkins_url="https://jenkins.example.com",
            local_edit_path=str(xml_path),
        )

        assert result.success is True
        assert "workspace directory" in result.data["error"]
