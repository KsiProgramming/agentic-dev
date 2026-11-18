from httpx import ASGITransport, AsyncClient

from agentic_api import create_app


async def test_lists_the_templates_with_their_options() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/templates")

    assert response.status_code == 200
    docs, audit, team, sdd, sdd_file, jira = response.json()
    assert (docs["id"], docs["name"]) == ("generate-docs", "Generate docs")
    properties = docs["parameters"]["properties"]
    assert set(properties) == {"output_dir", "include", "extra_instructions"}
    assert properties["output_dir"]["default"] == "docs"
    assert docs["requires"] == ["claude", "github"]
    assert (audit["id"], audit["name"]) == ("audit-codebase", "Audit codebase")
    assert audit["parameters"]["properties"]["reviewers"]["maximum"] == 3
    assert audit["requires"] == ["claude", "github"]
    assert docs["input"] is None and audit["input"] is None
    assert (team["id"], team["name"]) == ("plan-build-review", "Plan, build and review")
    assert team["input"]["required"] is True
    assert team["input"]["label"] == "What should the team change?"
    assert team["parameters"]["properties"]["max_passes"]["maximum"] == 3
    assert (jira["id"], jira["name"]) == ("jira-issue-answer", "Answer a Jira issue")
    assert jira["requires"] == ["claude", "github", "jira"]
    assert jira["input"]["required"] is True
    assert jira["input"]["example"] == "PROJ-12"
    assert jira["input"]["kind"] == "jira_issue"
    assert (sdd["id"], sdd["name"]) == ("sdd", "Build from a Jira issue")
    assert sdd["requires"] == ["claude", "github", "jira"]
    assert (sdd["input"]["required"], sdd["input"]["kind"]) == (True, "jira_issue")
    assert set(sdd["parameters"]["properties"]) == {
        "max_passes",
        "max_revisions",
        "move_to",
        "spec_model",
        "planner_model",
        "engineer_model",
        "reviewer_model",
    }
    assert (sdd_file["id"], sdd_file["name"]) == ("sdd-spec-file", "Build from a spec file")
    assert sdd_file["requires"] == ["claude", "github"]
    assert (sdd_file["input"]["required"], sdd_file["input"]["kind"]) == (True, "spec_file")
    assert "move_to" not in sdd_file["parameters"]["properties"]
