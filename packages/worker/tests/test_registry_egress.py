"""Which package registries a worker's jobs can reach (4.8, 13.2)."""

from agentic_sandbox.docker_backend import RegistryEgress
from agentic_worker.main import WorkerSettings, registry_egress


def settings(**env: str) -> WorkerSettings:
    return WorkerSettings.model_validate(env)


def test_no_registry_is_on_by_default() -> None:
    assert registry_egress(settings()) == {}


def test_a_registry_needs_its_network_and_its_proxy() -> None:
    only_network = settings(sandbox_npm_network="agentic-npm")
    only_proxy = settings(sandbox_pypi_proxy="http://egress-proxy-pypi:3128")
    assert registry_egress(only_network) == {}
    assert registry_egress(only_proxy) == {}


def test_each_registry_has_its_own_network_and_proxy() -> None:
    egress = registry_egress(
        settings(
            sandbox_nuget_network="agentic-nuget",
            sandbox_nuget_proxy="http://egress-proxy:3128",
            sandbox_npm_network="agentic-npm",
            sandbox_npm_proxy="http://egress-proxy-npm:3128",
            sandbox_pypi_network="agentic-pypi",
            sandbox_pypi_proxy="http://egress-proxy-pypi:3128",
        )
    )
    assert egress == {
        "nuget": RegistryEgress("agentic-nuget", "http://egress-proxy:3128"),
        "npm": RegistryEgress("agentic-npm", "http://egress-proxy-npm:3128"),
        "pypi": RegistryEgress("agentic-pypi", "http://egress-proxy-pypi:3128"),
    }


def test_nuget_keeps_its_variable_names() -> None:
    egress = registry_egress(
        settings(sandbox_nuget_network="agentic-nuget", sandbox_nuget_proxy="http://p:3128")
    )
    assert set(egress) == {"nuget"}
