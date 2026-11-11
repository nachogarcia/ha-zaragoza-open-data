"""Let the live tests reach the internet.

Home Assistant's test package (pytest-homeassistant) blocks sockets and DNS for every
test; the ``enable_socket`` mark alone does not lift the host allow-list or the DNS
patch.
"""

from collections.abc import Callable
import socket

import pytest
import pytest_socket

# Captured at import (collection), before the plugin patches DNS for a test.
_REAL_GETADDRINFO = socket.getaddrinfo
_ANYWHERE = ["0.0.0.0/0", "::/0"]


@pytest.fixture(autouse=True)
def internet(monkeypatch: pytest.MonkeyPatch) -> None:
    """Allow real connections and DNS for the duration of one live test."""
    pytest_socket.enable_socket()
    pytest_socket.socket_allow_hosts(_ANYWHERE)
    real: Callable[..., object] = _REAL_GETADDRINFO
    monkeypatch.setattr(socket, "getaddrinfo", real)
