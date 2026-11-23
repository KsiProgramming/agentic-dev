"""Protected paths (13.5): what a writer can read but never change.

The platform's own list is always on, with no switch: only a workflow's `protect.allow` exempts a
node, and then a gate must follow it. A workflow adds its own patterns in `protect.paths`; the
files an earlier writer changed are frozen for a writer that `start_from` it (see `RunState`)."""

from agentic_runtime.paths import first_match

PLATFORM_PROTECTED: tuple[tuple[str, str], ...] = (
    (".github/workflows/**", "CI: a writer that edits the pipeline decides what is checked"),
    (".github/actions/**", "CI: a composite action runs inside the pipeline"),
    ("**/.editorconfig", "analyzer config: it turns .NET and editor rules on and off"),
    ("**/.globalconfig", "analyzer config: it sets the severity of analyzer rules"),
    ("**/*.globalconfig", "analyzer config: it sets the severity of analyzer rules"),
    ("**/*.ruleset", "analyzer config: it sets the severity of .NET analyzer rules"),
    ("**/Directory.Build.props", "build config: it holds analyzer and warning settings"),
    ("**/Directory.Build.targets", "build config: it holds analyzer and warning settings"),
    ("**/ruff.toml", "analyzer config: it selects the Python lint rules"),
    ("**/.ruff.toml", "analyzer config: it selects the Python lint rules"),
    ("**/biome.json", "analyzer config: it selects the JavaScript lint rules"),
    ("**/biome.jsonc", "analyzer config: it selects the JavaScript lint rules"),
    ("**/.shellcheckrc", "analyzer config: it disables shell checks"),
    ("**/.gitleaks.toml", "scanner config: it sets what counts as a secret"),
    ("**/.gitleaksignore", "scanner config: it hides findings"),
)
"""The globs every writer is refused, each with why, in one place (shown wherever the rules are)."""

PLATFORM_GLOBS: tuple[str, ...] = tuple(glob for glob, _ in PLATFORM_PROTECTED)

ANALYZER_CONFIG_GLOBS: tuple[str, ...] = tuple(
    glob for glob, why in PLATFORM_PROTECTED if not why.startswith("CI")
)
"""The analyzer and scanner config among the defaults: what the evidence step reads from the
base (`scan.lint config: "base"`)."""


def platform_rule(path: str) -> str | None:
    """The platform default glob that protects `path`, or None."""
    return first_match(PLATFORM_GLOBS, path)
