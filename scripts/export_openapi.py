"""Write the API's OpenAPI spec to web/openapi.json (input for `pnpm gen:api`)."""

import json
from pathlib import Path

from agentic_api import create_app

OUT = Path(__file__).resolve().parents[1] / "web" / "openapi.json"


def main() -> None:
    spec = create_app().openapi()
    OUT.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
