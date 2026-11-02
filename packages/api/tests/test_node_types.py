from httpx import ASGITransport, AsyncClient

from agentic_api import create_app
from agentic_engine.nodes import NODE_MANIFESTS


async def test_lists_the_node_manifests_in_palette_order() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/node-types")

    assert response.status_code == 200
    body = response.json()
    assert [m["kind"] for m in body] == [m.kind for m in NODE_MANIFESTS]
    agent = body[0]
    assert (agent["label"], agent["category"], agent["icon"]) == ("Agent", "step", "bot")
    assert {"role", "instructions"} <= set(agent["parameters"]["properties"])
    assert "id" not in agent["parameters"]["properties"]
    assert agent["default"] == {
        "type": "agent",
        "id": "agent",
        "role": "Agent",
        "instructions": "Describe what this agent does.",
        "tools": [],
        "reads": [],
    }
    reduce = body[-1]
    assert reduce["default"]["from"] == "parallel"
    assert reduce["fill"] == {"from": "previous_step"}
    router = next(m for m in body if m["kind"] == "router")
    assert router["slots"] == ["routes[].then", "default"]
