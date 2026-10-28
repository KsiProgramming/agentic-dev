"""A run's artifact store, mirrored into its sandbox (4.3): every version is written to Postgres,
the source of truth, then copied read-only to the sandbox's `artifacts_dir`, so tool nodes and
agents can read it as a file."""

import logging
from collections.abc import Mapping

from pydantic import JsonValue

from agentic_engine.artifacts import Artifact, ArtifactRef, ArtifactStore
from agentic_sandbox import Sandbox, SandboxError

log = logging.getLogger("agentic_worker.artifacts")


class MirroredArtifactStore:
    """Implements `ArtifactStore` over `store`, copying each version it stores into `sandbox`.
    A copy that fails is logged, not raised: the store has the artifact, and the next attempt
    copies it again (`mirror_all`)."""

    def __init__(self, store: ArtifactStore, sandbox: Sandbox) -> None:
        self._store = store
        self._sandbox = sandbox

    async def put(
        self,
        name: str,
        node_id: str,
        content: str,
        output_schema: Mapping[str, JsonValue] | None = None,
    ) -> ArtifactRef:
        ref = await self._store.put(name, node_id, content, output_schema)
        await self._copy(name, content)
        return ref

    async def get(self, name: str, version: int | None = None) -> Artifact | None:
        return await self._store.get(name, version)

    async def latest(self) -> list[ArtifactRef]:
        return await self._store.latest()

    async def total_bytes(self) -> int:
        return await self._store.total_bytes()

    async def mirror_all(self) -> None:
        """Copy the latest version of each artifact into the sandbox: a fresh sandbox (the run's
        worker restarted) has none, and a kept one may miss a copy that failed."""
        for ref in await self._store.latest():
            artifact = await self._store.get(ref.name, ref.version)
            if artifact is not None:
                await self._copy(artifact.name, artifact.content)

    async def _copy(self, name: str, content: str) -> None:
        try:
            await self._sandbox.put_artifact(name, content.encode())
        except (SandboxError, ValueError) as e:
            log.warning("artifact %s was not copied into the sandbox: %s", name, e)
