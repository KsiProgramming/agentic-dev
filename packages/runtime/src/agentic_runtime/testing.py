"""Test helpers shared by the runtime and engine test suites."""

import ipaddress
import socket
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, cast


class NetworkBlockedError(RuntimeError):
    """A test tried to reach the network while `block_network()` was active."""


def _is_local(host: object) -> bool:
    if host is None or host == "localhost":
        return True
    if isinstance(host, bytes):
        host = host.decode()
    try:
        return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
    except ValueError:
        return False


@contextmanager
def block_network() -> Generator[None]:
    """Fail any DNS lookup or connection that leaves this machine.

    Loopback and Unix sockets stay allowed: asyncio needs them internally (e.g. socketpair on
    Windows). `NetworkBlockedError` is not an `OSError`, so client retry logic cannot swallow it.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo
    unix = getattr(socket, "AF_UNIX", None)

    def check(sock: socket.socket, address: Any) -> None:
        if sock.family == unix or not isinstance(address, tuple):
            return
        host = cast(tuple[object, ...], address)[0]
        if not _is_local(host):
            raise NetworkBlockedError(f"network access blocked in tests: connect to {address!r}")

    def connect(self: socket.socket, address: Any) -> None:
        check(self, address)
        real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        check(self, address)
        return real_connect_ex(self, address)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_local(host):
            raise NetworkBlockedError(f"network access blocked in tests: resolve {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    setattr(socket.socket, "connect", connect)  # noqa: B010
    setattr(socket.socket, "connect_ex", connect_ex)  # noqa: B010
    setattr(socket, "getaddrinfo", getaddrinfo)  # noqa: B010
    try:
        yield
    finally:
        setattr(socket.socket, "connect", real_connect)  # noqa: B010
        setattr(socket.socket, "connect_ex", real_connect_ex)  # noqa: B010
        setattr(socket, "getaddrinfo", real_getaddrinfo)  # noqa: B010
