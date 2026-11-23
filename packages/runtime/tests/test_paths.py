import pytest

from agentic_runtime.paths import first_match, glob_problem, matches, normalise


@pytest.mark.parametrize(
    ("glob", "path", "expected"),
    [
        ("**/.editorconfig", ".editorconfig", True),
        ("**/.editorconfig", "src/app/.editorconfig", True),
        ("**/.editorconfig", "src/.editorconfig.bak", False),
        (".github/workflows/**", ".github/workflows/ci.yml", True),
        (".github/workflows/**", ".github/workflows/a/b.yml", True),
        (".github/workflows/**", ".github/other.yml", False),
        ("**/*.globalconfig", "a/b/x.globalconfig", True),
        ("*.py", "a.py", True),
        ("*.py", "src/a.py", False),
        ("tests/**/test_?.py", "tests/unit/test_a.py", True),
        ("tests/**/test_?.py", "tests/test_a.py", True),
        ("tests/**/test_?.py", "tests/test_ab.py", False),
        ("**", "anything/at/all", True),
        ("**/Directory.Build.props", "DIRECTORY.build.PROPS", True),
        (".GitHub/Workflows/**", ".github/workflows/ci.yml", True),
    ],
)
def test_glob_matching(glob: str, path: str, expected: bool) -> None:
    assert matches(glob, path) is expected


@pytest.mark.parametrize("path", ["./.editorconfig", ".\\.editorconfig", "a/../.editorconfig"])
def test_paths_are_normalised_before_matching(path: str) -> None:
    expected = path != "a/../.editorconfig"
    assert matches("**/.editorconfig", path) is expected


def test_a_path_that_leaves_the_repo_matches_nothing() -> None:
    assert normalise("../x") is None
    assert normalise("/etc/passwd") is None
    assert normalise("C:\\x") is None
    assert matches("**", "../x") is False
    assert matches("**", "/x") is False


@pytest.mark.parametrize(
    "glob", ["", "  ", "/abs/*", "C:/x", "../x", "a/../b", "[ab]", "{a,b}", "/", "./"]
)
def test_malformed_globs_are_refused(glob: str) -> None:
    assert glob_problem(glob) is not None


@pytest.mark.parametrize("glob", ["tests/**", "**/*.cs", "ruff.toml", "a?b"])
def test_good_globs_are_accepted(glob: str) -> None:
    assert glob_problem(glob) is None


def test_first_match_names_the_pattern() -> None:
    assert first_match(["a/**", "**/*.py"], "b/c.py") == "**/*.py"
    assert first_match(["a/**"], "b/c.py") is None
