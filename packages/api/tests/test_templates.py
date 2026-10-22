from httpx import ASGITransport, AsyncClient

from agentic_api import create_app


async def test_lists_the_templates_with_their_options() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/templates")

    assert response.status_code == 200
    (docs,) = response.json()
    assert (docs["id"], docs["name"]) == ("generate-docs", "Generate docs")
    properties = docs["parameters"]["properties"]
    assert set(properties) == {"output_dir", "include", "extra_instructions"}
    assert properties["output_dir"]["default"] == "docs"
