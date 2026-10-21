"""`python -m agentic_secrets generate-key <path> [--if-missing]`: create a local master key."""

import argparse
import sys
from pathlib import Path

from agentic_secrets.keys import generate_key_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agentic_secrets")
    commands = parser.add_subparsers(dest="command", required=True)
    gen = commands.add_parser("generate-key", help="write a new random master key file")
    gen.add_argument("path", type=Path)
    gen.add_argument(
        "--if-missing", action="store_true", help="succeed without writing if the file exists"
    )
    args = parser.parse_args(argv)

    path: Path = args.path
    try:
        generate_key_file(path)
    except FileExistsError:
        if args.if_missing:
            print(f"master key already exists at {path}")
            return 0
        print(f"refusing to overwrite the existing master key at {path}", file=sys.stderr)
        return 1
    print(f"wrote a new master key to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
