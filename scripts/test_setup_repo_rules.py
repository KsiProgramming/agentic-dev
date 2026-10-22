import re
from pathlib import Path

from setup_repo_rules import GITHUB_REMOTE, REQUIRED_CHECKS, ruleset

WORKFLOWS = Path(__file__).parent.parent / ".github" / "workflows"
JOB_NAME = re.compile(r"^    name: (.+)$", re.MULTILINE)


def _job_names(workflow: str) -> set[str]:
    return set(JOB_NAME.findall((WORKFLOWS / workflow).read_text(encoding="utf-8")))


def test_every_ci_and_pr_check_job_is_required() -> None:
    assert _job_names("ci.yml") | _job_names("pr-checks.yml") == set(REQUIRED_CHECKS)


def test_ruleset_allows_only_squash_and_has_no_bypass() -> None:
    rules = {rule["type"]: rule for rule in ruleset()["rules"]}  # type: ignore[union-attr]
    assert rules["pull_request"]["parameters"]["allowed_merge_methods"] == ["squash"]
    assert rules["required_status_checks"]["parameters"]["strict_required_status_checks_policy"]
    assert ruleset()["bypass_actors"] == []


def test_github_remote_parses_https_and_ssh() -> None:
    for url in (
        "https://github.com/KsiProgramming/agentic-dev.git",
        "https://github.com/KsiProgramming/agentic-dev",
        "git@github.com:KsiProgramming/agentic-dev.git",
    ):
        match = GITHUB_REMOTE.search(url)
        assert match is not None
        assert match.group(1) == "KsiProgramming/agentic-dev"
