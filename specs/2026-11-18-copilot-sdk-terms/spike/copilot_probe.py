"""8.2 spike probe, run against the real SDK 1.0.34 on 2026-11-22. Token from COPILOT_PROBE_TOKEN only; never printed.
Usage: python copilot_probe.py ok   (own token, custom tool)  |  python copilot_probe.py bad   (invalid token)"""
import asyncio
import dataclasses
import os
import sys

from copilot import CopilotClient, define_tool
from pydantic import BaseModel, Field

TOKEN = os.environ["COPILOT_PROBE_TOKEN"]
seen_token = []
calls = []


class EchoParams(BaseModel):
    text: str = Field(description="Text to echo back")


@define_tool(description="Echo the text back. Always use this tool when asked to echo.")
async def echo(params: EchoParams) -> str:
    calls.append(params.text)
    return f"echo:{params.text}"


def short(v, n=140):
    s = repr(v)
    return s if len(s) <= n else s[:n] + "..."


def on_event(ev):
    r = repr(ev)
    if TOKEN in r:
        seen_token.append(type(ev).__name__)
    name = ev.type.value if hasattr(ev.type, "value") else str(ev.type)
    d = ev.data
    if "usage" in name:
        fields = {
            k: v
            for k, v in dataclasses.asdict(d).items()
            if v is not None and not k.startswith("_")
        }
        print("EVENT", name, short(fields, 900))
    elif "tool" in name or "permission" in name:
        print("EVENT", name, short({k: v for k, v in dataclasses.asdict(d).items() if v is not None}, 300))
    else:
        print("EVENT", name)


perm_requests = []


def on_perm(request, invocation):
    perm_requests.append(short(request, 300))
    print("PERMISSION asked:", short(request, 300))
    from copilot import PermissionHandler

    return PermissionHandler.approve_all(request, invocation)


async def run(token, label, prompt, **kw):
    print(f"\n=== {label} ===")
    client = CopilotClient(github_token=token, use_logged_in_user=False, working_directory=os.getcwd())
    try:
        async with client:
            async with await client.create_session(
                on_permission_request=on_perm,
                tools=[echo],
                on_event=on_event,
                streaming=True,
                **kw,
            ) as session:
                ans = await session.send_and_wait(prompt, timeout=90)
                print("ANSWER:", short(getattr(getattr(ans, "data", None), "content", ans), 300))
    except Exception as e:  # noqa: BLE001
        print("ERROR:", type(e).__name__, short(str(e).replace(token, "<token>"), 400))


async def main():
    which = sys.argv[1]
    if which == "ok":
        await run(
            TOKEN,
            "headless, own token, custom tool, built-ins off",
            "Call the echo tool with the text 'ping' and then reply with just the word done.",
            available_tools=["echo"],
        )
    elif which == "bad":
        await run("gho_" + "x" * 36, "invalid token", "Say hi.")
    print("\ncustom tool calls:", calls)
    print("permission requests:", len(perm_requests))
    print("token seen in events:", seen_token or "never")


asyncio.run(main())
