#!/bin/sh
# Seeds the bare repos the fake GitHub App (AGENTIC_GITHUB=fake) stands in for: its repos
# (agentic_github.FAKE_REPOS) are cloned from and pushed to <root>/<owner>/<name>.git.
# Idempotent: a repo that exists is left as it is, branches pushed by earlier runs included.
# Usage: seed_fixture_repos.sh <root>
set -eu

root="${1:?usage: seed_fixture_repos.sh <root>}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

seed() {
    name="$1"
    shift
    bare="$root/e2e-org/$name.git"
    if [ -d "$bare" ]; then
        echo "fixture $name: exists"
        return
    fi
    src="$work/$name"
    mkdir -p "$src"
    while [ "$#" -gt 0 ]; do
        mkdir -p "$src/$(dirname "$1")"
        printf '%b' "$2" > "$src/$1"
        shift 2
    done
    git -C "$src" init -q -b main
    git -C "$src" add -A
    git -C "$src" -c user.name=fixtures -c user.email=fixtures@agentic.invalid \
        commit -q -m "Initial commit"
    mkdir -p "$root/e2e-org"
    git clone -q --bare "$src" "$bare"
    echo "fixture $name: seeded"
}

seed docs-demo \
    README.md '# Docs demo\n\nA small repo for end-to-end tests of the docs template.\n' \
    pyproject.toml '[tool.uv.workspace]\nmembers = ["packages/*"]\n' \
    packages/core/pyproject.toml '[project]\nname = "core"\nversion = "0.1.0"\n' \
    packages/core/src/core/__init__.py '"""Core helpers."""\n\n\ndef greet(name: str) -> str:\n    return f"Hello, {name}"\n' \
    web/package.json '{ "name": "web", "version": "0.1.0" }\n' \
    web/src/index.ts 'export const title = "Docs demo";\n'

seed private-lib \
    README.md '# Private lib\n' \
    pyproject.toml '[project]\nname = "private-lib"\nversion = "0.1.0"\n'
