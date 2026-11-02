from httpx import ASGITransport, AsyncClient

from agentic_api import create_app


async def test_health_returns_ok() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_the_web_app_may_send_every_method_the_api_uses() -> None:
    """The builder saves with `PATCH /workflows/{id}` (5.2): a preflight the CORS policy refuses
    blocks it in the browser while every server-side test passes."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            response = await client.options(
                "/workflows/flow",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": method,
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            assert response.status_code == 200, method
