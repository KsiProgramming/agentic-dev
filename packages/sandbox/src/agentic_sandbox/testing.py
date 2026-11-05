"""Test helpers shared by the sandbox and worker test suites."""

import subprocess
from collections.abc import Generator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import docker
from docker.errors import DockerException, ImageNotFound
from docker.models.containers import Container

from agentic_sandbox.docker_backend import DEFAULT_IMAGE, NugetEgress

# `packages/sandbox`, which holds the sandbox image's Dockerfile.
_PACKAGE_DIR = Path(__file__).resolve().parents[2]
# `packages/egress-proxy`, the NuGet egress proxy's image (4.8).
_PROXY_DIR = _PACKAGE_DIR.parent / "egress-proxy"
PROXY_IMAGE = "agentic-dev/egress-proxy:dev"

SAMPLE_FILES: Mapping[str, str] = {
    "README.md": "# Hello repo\n",
    "src/app.py": "print('hello')\n",
    "src/pkg/__init__.py": "",
    "src/pkg/deep/mod.py": "X = 1\n",
    "docs/guide.md": "Read me.\n",
}


def make_repo(
    path: Path, files: Mapping[str, str] = SAMPLE_FILES, *, links: Mapping[str, str] | None = None
) -> Path:
    """A git repo at `path` with one commit holding `files` and the symlinks `links` (name to
    target); returns `path`."""
    for name, text in files.items():
        file = path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
    for name, target in (links or {}).items():
        (path / name).symlink_to(target)
    git = ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "-C", str(path)]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], check=True)
    return path


def ensure_sandbox_image(client: docker.DockerClient, image: str = DEFAULT_IMAGE) -> str:
    """`image`, built from `packages/sandbox/Dockerfile` first if the daemon lacks it (as compose
    and CI do before tests); returns `image`."""
    try:
        client.images.get(image)
    except ImageNotFound:
        client.images.build(path=str(_PACKAGE_DIR), tag=image, rm=True)
    return image


@dataclass(frozen=True)
class EgressForTests:
    """A NuGet egress proxy started for a test: what the sandbox manager takes, and the proxy's
    container (its log names every host it refused)."""

    nuget: NugetEgress
    proxy: Container

    def refused_hosts(self) -> set[str]:
        log = self.proxy.logs().decode("utf-8", "replace")
        return {
            line.rsplit('"', 2)[-2]
            for line in log.splitlines()
            if "Proxying refused on filtered domain" in line and line.count('"') >= 2
        }


@contextmanager
def nuget_egress(client: docker.DockerClient) -> Generator[EgressForTests]:
    """The NuGet egress proxy, as compose runs it: on its own internal network (no route out)
    and on the default bridge. Builds its image if the daemon lacks it; removes both after."""
    try:
        client.images.get(PROXY_IMAGE)
    except ImageNotFound:
        client.images.build(path=str(_PROXY_DIR), tag=PROXY_IMAGE, rm=True)
    name = f"agentic-nuget-test-{uuid4().hex[:8]}"
    network = client.networks.create(name, internal=True)
    proxy: Container | None = None
    try:
        proxy = client.containers.run(PROXY_IMAGE, name=name, detach=True, network=name)
        client.networks.get("bridge").connect(proxy)  # pyright: ignore[reportUnknownMemberType]
        yield EgressForTests(NugetEgress(name, f"http://{name}:3128"), proxy)
    finally:
        if proxy is not None:
            with suppress(DockerException):
                proxy.remove(force=True)
        network.remove()
