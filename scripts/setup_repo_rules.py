"""Apply the merge rules for main to the GitHub repository, through the `gh` CLI.

- Pull requests merge by squash only, the squash commit takes the PR title and body, and
  the head branch is deleted after the merge.
- A ruleset on the default branch: no direct pushes, force pushes or deletion; every change
  goes through a PR whose required checks (every CI and PR-checks job) have all passed on a
  branch that is up to date with main; conversations resolved. Nobody bypasses it.

Usage:
  python scripts/setup_repo_rules.py            apply (needs repo admin: `gh auth login`)
  python scripts/setup_repo_rules.py --dry-run  print what would be sent

Running it again updates the ruleset in place.
"""

import io
import json
import re
import subprocess
import sys
from typing import Any, cast

GITHUB_REMOTE = re.compile(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$")
RULESET_NAME = "main: squash PRs with all checks green"
# GitHub Actions' app id, so a check of the same name from another app does not count.
GITHUB_ACTIONS_APP_ID = 15368
# Every job of ci.yml and pr-checks.yml; test_setup_repo_rules keeps the list in sync.
REQUIRED_CHECKS = [
    "Python (lint, types, tests)",
    "Sandbox image (arm64 build)",
    "Web (lint, types, unit tests)",
    "API contract (generated client is up to date)",
    "Compose smoke test + e2e",
    "CHANGELOG.md updated",
    "Roadmap phase marked done",
]

REPO_SETTINGS: dict[str, object] = {
    "allow_squash_merge": True,
    "allow_merge_commit": False,
    "allow_rebase_merge": False,
    "allow_auto_merge": False,
    "delete_branch_on_merge": True,
    "squash_merge_commit_title": "PR_TITLE",
    "squash_merge_commit_message": "PR_BODY",
}


def ruleset() -> dict[str, object]:
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "required_linear_history"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": True,
                    "allowed_merge_methods": ["squash"],
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [
                        {"context": name, "integration_id": GITHUB_ACTIONS_APP_ID}
                        for name in REQUIRED_CHECKS
                    ],
                },
            },
        ],
    }


def _gh(*args: str, payload: object = None) -> Any:
    result = subprocess.run(
        ["gh", *args],
        input=None if payload is None else json.dumps(payload),
        capture_output=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        sys.exit(f"gh {' '.join(args)} failed:\n{result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def origin_repo() -> str:
    """`owner/name` of the origin remote, so --dry-run works without `gh auth login`."""
    url = subprocess.run(
        ["git", "remote", "get-url", "origin"], check=True, capture_output=True, encoding="utf-8"
    ).stdout.strip()
    match = GITHUB_REMOTE.search(url)
    if match is None:
        sys.exit(f"origin is not a GitHub remote: {url}")
    return match.group(1)


def main(dry_run: bool) -> int:
    repo = origin_repo()
    if dry_run:
        print(f"PATCH repos/{repo}\n{json.dumps(REPO_SETTINGS, indent=2)}")
        print(f"ruleset\n{json.dumps(ruleset(), indent=2)}")
        return 0

    _gh("api", "-X", "PATCH", f"repos/{repo}", "--input", "-", payload=REPO_SETTINGS)
    print("Repository: squash merge only, PR title and body as the commit, branches deleted.")

    existing = cast(list[dict[str, Any]], _gh("api", f"repos/{repo}/rulesets"))
    match = next((r for r in existing if r.get("name") == RULESET_NAME), None)
    if match is None:
        _gh("api", "-X", "POST", f"repos/{repo}/rulesets", "--input", "-", payload=ruleset())
        print(f"Created ruleset {RULESET_NAME!r}.")
    else:
        path = f"repos/{repo}/rulesets/{match['id']}"
        _gh("api", "-X", "PUT", path, "--input", "-", payload=ruleset())
        print(f"Updated ruleset {RULESET_NAME!r}.")

    secrets = cast(list[dict[str, str]], _gh("secret", "list", "--json", "name"))
    if not any(s["name"] == "ROADMAP_BOT_TOKEN" for s in secrets):
        print(
            "Warning: secret ROADMAP_BOT_TOKEN is not set. When the roadmap job commits to a PR "
            "branch with the default token, CI does not run on that commit and the PR cannot "
            "merge until someone pushes again. Mark the phase locally (complete-phase skill) "
            "or set the secret."
        )
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    args = sys.argv[1:]
    if args not in ([], ["--dry-run"]):
        sys.exit(__doc__)
    sys.exit(main(dry_run=args == ["--dry-run"]))
