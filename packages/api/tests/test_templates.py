from httpx import ASGITransport, AsyncClient

from agentic_api import create_app


async def test_lists_the_templates_with_their_options() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/templates")

    assert response.status_code == 200
    docs, audit, team = response.json()
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
