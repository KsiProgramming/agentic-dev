"""Throwaway probe for the Copilot SDK (phase 8.1). Untested: never run.

Run in its own virtualenv, outside the uv workspace:

    python -m venv .venv && .venv/bin/pip install github-copilot-sdk
    COPILOT_PROBE_TOKEN=<a user token: gho_, ghu_ or github_pat_> python copilot_probe.py

The token is read from the environment only. Never paste it into this file.
Based on the snippet at https://pypi.org/project/github-copilot-sdk/ ; check the
SDK's current API first (its names may have changed).
"""

import asyncio
import os

from copilot import CopilotClient, PermissionHandler, define_tool
from pydantic import BaseModel, Field


class EchoParams(BaseModel):
    text: str = Field(description="Text to echo back")


@define_tool(description="Echo the text back")
async def echo(params: EchoParams) -> str:
    return params.text


async def main() -> None:
    token = os.environ["COPILOT_PROBE_TOKEN"]
    # An explicit token turns off the signed-in-user default (docs, "Authentication methods").
    client = CopilotClient(github_token=token)
    async with await client.create_session(
        on_permission_request=PermissionHandler.approve_all,
        tools=[echo],
    ) as session:
        # Print every event type and its fields' names, never values that could hold the token.
        session.on(lambda event: print(type(event).__name__, sorted(vars(event))))
        await session.send_and_wait("Call the echo tool with the text 'ping', then say done.")


if __name__ == "__main__":
    asyncio.run(main())
