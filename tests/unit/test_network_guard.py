import socket
import urllib.request

import pytest


def test_socket_connect_is_blocked():
    with socket.socket() as sock:
        with pytest.raises(RuntimeError, match="network access"):
            sock.connect(("127.0.0.1", 9))


def test_name_lookup_is_blocked():
    with pytest.raises(RuntimeError, match="network access"):
        socket.getaddrinfo("example.invalid", 80)


def test_high_level_clients_are_blocked():
    with pytest.raises(Exception, match="network access"):
        urllib.request.urlopen("http://example.invalid/")
