import socket

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests must never touch the real sites."""
    def blocked(*a, **k):
        raise RuntimeError("network access is blocked in tests")
    monkeypatch.setattr(socket.socket, "connect", blocked)
