"""The sync server on loopback with no network, for the sync tests (D-076, the M20 slice plans).

LoopbackSyncServer is the test-only hook point 4 names: it binds 127.0.0.1, which the real
server's address check refuses and nothing under src/ can reach. A connection reaches it over
socket.socketpair(), which needs no connect, so the suite's socket guard stays: the server's half
goes through the real TLS handshake and the real handler in a thread.
"""

import json
import re
import socket
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from sync_reference_client import ReferenceClient
from test_decisions import Ledger

from personal_finance.db.migrate import connect
from personal_finance.snapshot.files import build_in_one_read, verified
from personal_finance.sync import devices, identity
from personal_finance.sync.pairing import pairing_payload
from personal_finance.sync.server import PAIR, SERVE, SyncServer, tls_context

LOOPBACK = "127.0.0.1"
PAIRING_NOW = datetime(2026, 5, 4, 17, 0, tzinfo=timezone.utc)
DEVICE_TOKEN = r"dv1-[0-9a-f]{16}"


class LoopbackSyncServer(SyncServer):
    @staticmethod
    def checked_address(address: str) -> None:
        assert address == LOOPBACK, address


class Clock:
    """The wall clock the pairing window reads, moved by hand."""

    def __init__(self, now=PAIRING_NOW):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class Connections:
    """connect() for the reference client: each call a socketpair whose other half the server
    handles in a thread, through TLS and its handler."""

    def __init__(self, server):
        self.server = server
        self.threads = []

    def __call__(self):
        client, served = socket.socketpair()

        def serve():
            try:
                wrapped = self.server.tls_wrapped(served)
            except OSError:
                return
            self.server.process_request(wrapped, (LOOPBACK, 50000))

        thread = threading.Thread(target=serve)
        thread.start()
        self.threads.append(thread)
        return client

    def wait(self):
        for thread in self.threads:
            thread.join(timeout=30)
            assert not thread.is_alive()


def served_here(server, client_action, connections_expected=1):
    """client_action(connect) run in a thread while this thread serves its connections: for a
    server holding the CLI's own connection, which only its thread may use."""
    import queue

    pending, outcome = queue.Queue(), {}

    def connect():
        client, served = socket.socketpair()
        pending.put(served)
        return client

    def act():
        try:
            outcome["result"] = client_action(connect)
        except BaseException as error:
            outcome["error"] = error

    thread = threading.Thread(target=act)
    thread.start()
    for _ in range(connections_expected):
        served = pending.get(timeout=30)
        try:
            wrapped = server.tls_wrapped(served)
        except OSError:
            continue
        server.process_request(wrapped, (LOOPBACK, 50000))
    thread.join(timeout=30)
    if "error" in outcome:
        raise outcome["error"]
    return outcome["result"]


def raw_exchange(server, data: bytes, context=None) -> bytes:
    """Bytes sent as one connection, over TLS when a client context is given, and every byte
    the server sent back before closing."""
    connections = Connections(server)
    client = connections()
    try:
        if context is None:
            client.sendall(data)
            client.shutdown(socket.SHUT_WR)
            received = b"".join(iter(lambda: client.recv(65536), b""))
        else:
            with context.wrap_socket(client) as tls:
                tls.sendall(data)
                received = b"".join(iter(lambda: tls.recv(65536), b""))
    finally:
        client.close()
        connections.wait()
    return received


class SyncLedger(Ledger):
    """A ledger with a sync identity, and helpers to pair and serve on loopback."""

    def make_identity(self):
        code, out, err = self.run("sync", "identity", "create")
        assert (code, err) == (0, ""), err
        return self.identity()

    def identity(self):
        conn = self.conn()
        try:
            return identity.current_identity(conn)
        finally:
            conn.close()

    @property
    def sync_folder(self):
        return identity.sync_folder_beside(self.path)

    def context(self):
        conn = self.conn()
        try:
            key_path, certificate_path = identity.checked_identity_files(
                identity.required_identity(conn), self.sync_folder)
        finally:
            conn.close()
        return tls_context(certificate_path, key_path)

    def server_conn(self):
        """The server's session connection, as connect() makes it, usable from the thread a
        socketpair's request is handled in: requests are handled one at a time."""
        conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=rw", uri=True,
                               autocommit=True, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def pairing_server(self, clock=None, name="Phone", minutes=2):
        """A pair-mode server with its window open, and the pairing payload."""
        clock = clock or Clock()
        conn = self.server_conn()
        server = LoopbackSyncServer(LOOPBACK, 0, self.context(), conn, mode=PAIR,
                                    minutes=minutes, utc_now=clock, device_name=name)
        current = identity.required_identity(conn)
        window = devices.open_window(conn, current, LOOPBACK, server.server_port, clock())
        server.window_id = window.window_id
        server.window = window
        server.payload = pairing_payload(LOOPBACK, server.server_port,
                                         current.certificate_sha256, window.pairing_secret)
        return server

    def serving_server(self, as_of, window_days=90, minutes=10, snapshot_id=None,
                       generated_at="2026-05-04T17:00:00.000Z"):
        conn = self.server_conn()
        data = build_in_one_read(conn, as_of, window_days,
                                 snapshot_id or "5b1f0a52-8f0e-4c55-9d7a-2f6b9e1c3d40",
                                 generated_at)
        return LoopbackSyncServer(LOOPBACK, 0, self.context(), conn, mode=SERVE,
                                  minutes=minutes, utc_now=Clock(), document=verified(data),
                                  snapshot=data)

    def paired_client(self, install_folder, name="Phone"):
        """A reference client paired through a real pairing window."""
        install_folder.mkdir(exist_ok=True)
        server = self.pairing_server(name=name)
        connections = Connections(server)
        client = ReferenceClient(install_folder, connections)
        answer = client.pair(server.payload)
        connections.wait()
        server.server_close()
        server.conn.close()
        assert answer.status == 200, answer
        return client

    def connected(self, client, server):
        """The client, now talking to this server."""
        client.connect = Connections(server)
        return client

    def table(self, name):
        conn = connect(self.path)
        try:
            return conn.execute(f"SELECT * FROM {name}").fetchall()
        finally:
            conn.close()

    def revoke_token(self, device_id):
        _, out, _ = self.run("sync", "devices")
        return re.search(rf"Device {device_id}: .*revoke revision ({DEVICE_TOKEN})", out)[1]

    def rotate_token(self):
        _, out, _ = self.run("sync", "identity", "show")
        return re.search(rf"Rotate revision: ({DEVICE_TOKEN})", out)[1]


def body_of(received: bytes):
    return json.loads(received.partition(b"\r\n\r\n")[2])
