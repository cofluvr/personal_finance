import socket

import pytest

from personal_finance.db.migrate import connect, create_database


class NetworkBlocked(RuntimeError):
    pass


def _blocked(*args, **kwargs):
    raise NetworkBlocked("network access is not allowed in tests")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail any test that tries to reach the network (A19)."""
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "ledger.db"
    create_database(path)
    return path


@pytest.fixture
def conn(db_path):
    connection = connect(db_path)
    yield connection
    connection.close()
