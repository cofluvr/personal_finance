"""Requests to the local UI's real handler, with no network (D-062 point 1).

A request reaches the server over `socket.socketpair()`, which needs no `connect`, so the suite's
socket guard stays as it is. http.server parses each request exactly as it would one from a
browser. The server is bound to 127.0.0.1 for real, so its port and Host check are the real ones.
"""

import socket
import threading
from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple

from personal_finance.ui.server import LoopbackServer


class Response(NamedTuple):
    status: int
    headers: list[tuple[str, str]]
    body: bytes

    def header(self, name) -> str | None:
        values = [value for key, value in self.headers if key.lower() == name.lower()]
        assert len(values) <= 1, name
        return values[0] if values else None

    @property
    def text(self) -> str:
        return self.body.decode("utf-8")


class UiClient:
    def __init__(self, ledger_path):
        self.server = LoopbackServer(Path(ledger_path))
        self.host = f"127.0.0.1:{self.server.server_port}"
        self.cookie = None

    def close(self):
        self.server.server_close()

    def exchange(self, request: bytes) -> Response:
        """Send raw bytes as one connection, and read the whole answer."""
        client, served = socket.socketpair()

        def serve():
            try:
                self.server.finish_request(served, ("127.0.0.1", 50000))
            finally:
                served.close()

        thread = threading.Thread(target=serve)
        thread.start()
        client.sendall(request)
        try:
            client.shutdown(socket.SHUT_WR)
        except OSError:
            # The server read the whole request, answered and closed first, as it may.
            pass
        received = b"".join(iter(lambda: client.recv(65536), b""))
        client.close()
        thread.join()
        return parsed_response(received)

    def request(self, method, target, *, host="default", cookie=True, headers=(), body=b""):
        lines = [f"{method} {target} HTTP/1.1"]
        if host is not None:
            lines.append(f"Host: {self.host if host == 'default' else host}")
        if cookie and self.cookie:
            lines.append(f"Cookie: {self.cookie}")
        lines += [f"{name}: {value}" for name, value in headers]
        if body:
            lines.append(f"Content-Length: {len(body)}")
        return self.exchange(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body)

    def get(self, target, **options) -> Response:
        return self.request("GET", target, **options)

    def sign_in(self) -> Response:
        response = self.get(f"/start?key={self.server.launch_key}", cookie=False)
        assert response.status == 303, response
        self.cookie = response.header("Set-Cookie").split(";")[0]
        return response


def parsed_response(received: bytes) -> Response:
    head, _, body = received.partition(b"\r\n\r\n")
    status_line, *header_lines = head.decode("latin-1").split("\r\n")
    headers = [tuple(part.strip() for part in line.split(":", 1)) for line in header_lines]
    return Response(int(status_line.split()[1]), headers, body)


class _PageParser(HTMLParser):
    """Each report line's visible text, and every address and attribute the page holds."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.report_lines, self.addresses, self.tags, self.attributes = [], [], [], []
        self.hint_text = ""
        self._line_depth = 0
        self._in_hint = False

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes += attrs
        self.addresses += [value for name, value in attrs if name in ("href", "src", "action")]
        if self._line_depth:
            self._line_depth += 1
        elif tag == "div" and ("class", "line") in attrs:
            self._line_depth = 1
            self.report_lines.append("")
        self._in_hint = tag == "div" and ("class", "hint-line") in attrs

    def handle_endtag(self, tag):
        if self._line_depth:
            self._line_depth -= 1

    def handle_data(self, data):
        if self._line_depth:
            self.report_lines[-1] += data
        if self._in_hint:
            self.hint_text += data


def parsed_page(body: bytes) -> _PageParser:
    parser = _PageParser()
    parser.feed(body.decode("utf-8"))
    parser.close()
    return parser


def page_text(body: bytes) -> str:
    """A page's report as the CLI would print it: one line each, newline-terminated."""
    return "".join(f"{line}\n" for line in parsed_page(body).report_lines)
