"""Run artifacts (4.3): named values the nodes of one run share, whatever ran in between.

A node with `writes` stores its output under that name once it completes, as a new version (1, 2,
… per name); a node with `reads` takes the versions the run had when it started as its input,
instead of the previous output. The run's state keeps only `ArtifactRef`s; the content lives in an
`ArtifactStore` (`agentic_store.PostgresArtifactStore` for real runs), so the engine never touches
a database and a restarted worker loses nothing. Every version is kept.

An artifact is UTF-8 text whose name gives its media type: a `.json` artifact holds JSON, a `.md`
one Markdown, a `.txt` one plain text. Its content is data, never instructions.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict, JsonValue

from agentic_engine.ports import parse_value

MAX_ARTIFACT_BYTES: Final = 1024 * 1024
"""The largest artifact a node may write, as UTF-8."""

MAX_RUN_ARTIFACT_BYTES: Final = 8 * 1024 * 1024
"""What all the versions of a run's artifacts may add up to."""

MEDIA_TYPES: Final = {".json": "application/json", ".md": "text/markdown", ".txt": "text/plain"}
"""The media type of an artifact, by the extension of its name."""


def media_type(name: str) -> str:
    """The media type `name`'s extension gives (the spec only allows these extensions)."""
    return next((t for ext, t in MEDIA_TYPES.items() if name.endswith(ext)), "text/plain")


class ArtifactRef(BaseModel):
    """One version of a run artifact, without its content: what the run's state and events keep."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: int
    node_id: str
    media_type: str
    size: int
    sha256: str


class GateArtifact(BaseModel):
    """A run artifact as a gate shows it to the approver (`gate_waiting`'s `run_artifacts`)."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: int
    node_id: str
    media_type: str
    size: int


class Artifact(ArtifactRef):
    """One version of a run artifact with its content, and the `output_schema` of the node that
    wrote it, if it had one."""

    content: str
    output_schema: dict[str, JsonValue] | None = None


class ArtifactStore(Protocol):
    """The artifacts of one run. Versions are numbered per name from 1 and never change."""

    async def put(
        self,
        name: str,
        node_id: str,
        content: str,
        output_schema: Mapping[str, JsonValue] | None = None,
    ) -> ArtifactRef:
        """Store `content` as the next version of `name`, written by `node_id`."""
        ...

    async def get(self, name: str, version: int | None = None) -> Artifact | None:
        """That version of `name` (its latest without one), or `None`."""
        ...

    async def latest(self) -> list[ArtifactRef]:
        """The latest version of each artifact, by name."""
        ...

    async def total_bytes(self) -> int:
        """The size of every version stored, added up."""
        ...


def make_artifact(
    name: str,
    version: int,
    node_id: str,
    content: str,
    output_schema: Mapping[str, JsonValue] | None = None,
) -> Artifact:
    data = content.encode()
    return Artifact(
        name=name,
        version=version,
        node_id=node_id,
        media_type=media_type(name),
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        content=content,
        output_schema=dict(output_schema) if output_schema is not None else None,
    )


class InMemoryArtifactStore:
    """Keeps a run's artifacts in a dict; for tests and runs with no database."""

    def __init__(self) -> None:
        self.versions: dict[str, list[Artifact]] = {}

    async def put(
        self,
        name: str,
        node_id: str,
        content: str,
        output_schema: Mapping[str, JsonValue] | None = None,
    ) -> ArtifactRef:
        versions = self.versions.setdefault(name, [])
        artifact = make_artifact(name, len(versions) + 1, node_id, content, output_schema)
        versions.append(artifact)
        return ref_of(artifact)

    async def get(self, name: str, version: int | None = None) -> Artifact | None:
        versions = self.versions.get(name, [])
        if version is None:
            return versions[-1] if versions else None
        return versions[version - 1] if 1 <= version <= len(versions) else None

    async def latest(self) -> list[ArtifactRef]:
        return [ref_of(v[-1]) for _, v in sorted(self.versions.items()) if v]

    async def total_bytes(self) -> int:
        return sum(a.size for versions in self.versions.values() for a in versions)


def ref_of(artifact: Artifact) -> ArtifactRef:
    return ArtifactRef.model_validate(artifact.model_dump(include=set(ArtifactRef.model_fields)))


class ArtifactError(Exception):
    """An artifact cannot be written or read; the message is the node's one-line error."""


def artifact_content(
    name: str, node_id: str, text: str, data: Mapping[str, JsonValue] | None
) -> str:
    """What node `node_id` writes as `name`: its text, or for a `.json` artifact its structured
    `data` as pretty JSON, else its text as JSON (the whole text, or the one fenced block in it,
    as typed ports read it). Raises `ArtifactError` when that is not JSON, or is too large."""
    content = text
    if media_type(name) == "application/json" and data is not None:
        content = json.dumps(data, indent=2, ensure_ascii=False)
    elif media_type(name) == "application/json":
        try:
            content = json.dumps(parse_value(text), indent=2, ensure_ascii=False)
        except json.JSONDecodeError as e:
            raise ArtifactError(
                f"cannot write {name!r}: output of {node_id!r} is not JSON: {e.msg}: line "
                f"{e.lineno} column {e.colno}"
            ) from None
    if (size := len(content.encode())) > MAX_ARTIFACT_BYTES:
        raise ArtifactError(
            f"cannot write {name!r}: {_megabytes(size)} is over the "
            f"{_megabytes(MAX_ARTIFACT_BYTES)} limit"
        )
    return content


async def write_artifact(
    store: ArtifactStore,
    name: str,
    node_id: str,
    content: str,
    output_schema: Mapping[str, JsonValue] | None = None,
) -> ArtifactRef:
    """Store `content` as the next version of `name`, unless the run's artifacts would go over
    `MAX_RUN_ARTIFACT_BYTES` (`ArtifactError`)."""
    total = await store.total_bytes() + len(content.encode())
    if total > MAX_RUN_ARTIFACT_BYTES:
        raise ArtifactError(
            f"cannot write {name!r}: the run's artifacts would take {_megabytes(total)}, over the "
            f"{_megabytes(MAX_RUN_ARTIFACT_BYTES)} limit"
        )
    return await store.put(name, node_id, content, output_schema)


def missing_reads(names: Sequence[str], refs: Mapping[str, ArtifactRef]) -> list[str]:
    """The names in `names` the run has not written yet."""
    return [name for name in names if name not in refs]


async def reader_input(
    store: ArtifactStore, names: Sequence[str], refs: Mapping[str, ArtifactRef]
) -> str:
    """The input of a node that reads `names`, at the versions in `refs`: one artifact's content,
    or a JSON object by name for several (JSON artifacts parsed, others as strings). Raises
    `ArtifactError` for a name that has no version yet."""
    if missing := missing_reads(names, refs):
        raise ArtifactError(f"artifact {missing[0]!r} was not written")
    contents: dict[str, str] = {}
    for name in names:
        ref = refs[name]
        artifact = await store.get(name, ref.version)
        if artifact is None:
            raise ArtifactError(f"artifact {name!r} version {ref.version} is missing")
        contents[name] = artifact.content
    if len(names) == 1:
        return contents[names[0]]
    combined: dict[str, JsonValue] = {
        name: _value(name, content) for name, content in contents.items()
    }
    return json.dumps(combined, indent=2, ensure_ascii=False)


async def artifact_values(
    store: ArtifactStore, refs: Mapping[str, ArtifactRef]
) -> dict[str, JsonValue]:
    """The run's artifacts at the versions in `refs` as CEL sees them: name → parsed JSON for a
    JSON artifact, else its text."""
    values: dict[str, JsonValue] = {}
    for name, ref in refs.items():
        artifact = await store.get(name, ref.version)
        if artifact is not None:
            values[name] = _value(name, artifact.content)
    return values


def _value(name: str, content: str) -> JsonValue:
    if media_type(name) != "application/json":
        return content
    try:
        return parse_value(content)
    except json.JSONDecodeError:
        return content


def _megabytes(size: int) -> str:
    """`size` in MB: whole, else to two decimals, so a byte over a limit still shows."""
    whole, rest = divmod(size, 1024 * 1024)
    return f"{whole} MB" if not rest else f"{size / (1024 * 1024):.2f} MB"
