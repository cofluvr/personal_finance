"""The local review UI: read-only pages served on 127.0.0.1 alone (D-062).

Every page shows the lines of the same builder its CLI command prints, so the UI computes nothing
of its own. Nothing here writes a file, logs a request or prints: only the CLI prints (D-037).
Every request opens the ledger read-only through open_ledger, so a real ledger's gate runs on each
one (D-058). W1 allows this module, and no other, to import from `http`, and only these two
classes (D-062 point 1).
"""

import hmac
import html
import re
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer

from personal_finance.cli import (
    UNEXPECTED_ERROR,
    CommandError,
    explained_error,
    find_account,
    open_ledger,
    validated_month,
)
from personal_finance.reports.report_text import (
    account_choices,
    monthly_report_lines,
    totals_report_lines,
)

LOOPBACK_ADDRESS = "127.0.0.1"

CONTENT_SECURITY_POLICY = (
    "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; "
    "base-uri 'none'"
)

SECURITY_HEADERS = (
    ("Content-Security-Policy", CONTENT_SECURITY_POLICY),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Cache-Control", "no-store"),
)

STYLESHEET = """\
body { font-family: -apple-system, system-ui, sans-serif; margin: 0; color: #1d1d1f;
       background: #ffffff; }
nav { padding: 12px 16px; border-bottom: 1px solid #d2d2d7; }
nav a { margin-right: 16px; }
main { padding: 16px; max-width: 1100px; }
form { margin: 0 0 16px; }
.report { font-family: ui-monospace, Menlo, monospace; font-size: 13px; }
.line, .hint-line { white-space: pre-wrap; overflow-wrap: anywhere; }
.notice { color: #6e6e73; }
@media (prefers-color-scheme: dark) {
  body { color: #f5f5f7; background: #1d1d1f; }
  nav { border-color: #424245; }
  a { color: #64a8ff; }
  .notice { color: #a1a1a6; }
}
"""

NAVIGATION = (
    ("/", "Totals"),
    ("/monthly", "Monthly"),
)

# What each page accepts in its address. A value is an ID or a month and nothing else, refused
# before it reaches a query, so no address needs decoding.
PAGE_PARAMETERS = {
    "/": {"account"},
    "/monthly": {"account", "from", "to"},
    "/style.css": set(),
}
QUERY_VALUE = re.compile(r"[A-Za-z0-9_-]{0,100}")

SIGNED_OUT = (
    "This page needs the address pf ui printed, opened once in this browser. Restart pf ui for a "
    "new one."
)
WRONG_HOST = "This server answers only at the address pf ui printed."
FOREIGN_ORIGIN = "Requests from other sites are refused."
READ_ONLY = "This interface is read-only. Decisions are made with pf review in the terminal."
NOT_FOUND = "There is no such page."
BAD_ADDRESS = "This address holds a value the interface does not accept."
UNREADABLE = "This request could not be read."


class LoopbackServer(HTTPServer):
    """One request at a time, on 127.0.0.1 at a port the system picks, with one launch's
    secrets: a key that works once, for a cookie every other request needs."""

    allow_reuse_address = False

    def __init__(self, ledger_path):
        self.ledger_path = ledger_path
        self.launch_key = secrets.token_urlsafe(32)
        self.launch_key_used = False
        self.session_value = secrets.token_urlsafe(32)
        super().__init__((LOOPBACK_ADDRESS, 0), ReviewRequestHandler)

    def server_bind(self):
        # HTTPServer.server_bind looks up a name for the address (socket.getfqdn). Skip it, so
        # launching consults no resolver.
        super(HTTPServer, self).server_bind()
        self.server_name, self.server_port = self.server_address[:2]

    def handle_error(self, request, client_address):
        """The default prints a traceback to stderr, which could quote financial data (D-037).
        The handler answers every error it can, so this is reached only when the client has
        gone, with nothing left to say."""

    @property
    def origin(self) -> str:
        return f"http://{LOOPBACK_ADDRESS}:{self.server_port}"

    @property
    def launch_address(self) -> str:
        return f"{self.origin}/start?key={self.launch_key}"

    @property
    def session_cookie_name(self) -> str:
        # Cookies are not kept apart by port, so each launch's name carries its own.
        return f"pf_session_{self.server_port}"


class ReviewRequestHandler(BaseHTTPRequestHandler):
    # A stalled client holds the one request at a time for no longer than this, in seconds.
    timeout = 10
    # http.server answers a request it cannot read, or one naming no version, as HTTP/0.9, which
    # has no status line or headers. Answering as HTTP/1.0 keeps every response's headers.
    default_request_version = "HTTP/1.0"

    def version_string(self) -> str:
        return "pf"

    def log_message(self, format, *args):
        """No request logging: log_request and log_error both come here (D-037)."""

    def send_error(self, code, message=None, explain=None):
        """http.server's own refusals, such as a malformed request line, as a fixed page that
        repeats nothing from the request."""
        self.send_page(code, "Refused", notice=UNREADABLE)

    def __getattr__(self, name):
        # http.server looks up do_<METHOD> for each request. Every method but GET is refused,
        # its body unread, so nothing can be written through this server.
        if name.startswith("do_"):
            return self.refuse_method
        raise AttributeError(name)

    def refuse_method(self):
        self.send_page(405, "Refused", notice=READ_ONLY, extra_headers=(("Allow", "GET"),))

    def do_GET(self):
        try:
            self.answer_get()
        except Exception as error:
            message = explained_error(error)
            self.send_page(500 if message == UNEXPECTED_ERROR else 400, "Refused", notice=message)

    def answer_get(self):
        server = self.server
        if self.headers.get_all("Host") != [f"{LOOPBACK_ADDRESS}:{server.server_port}"]:
            return self.send_page(421, "Refused", notice=WRONG_HOST)
        if self.headers.get_all("Origin") not in (None, [server.origin]):
            return self.send_page(403, "Refused", notice=FOREIGN_ORIGIN)

        path, _, query = self.path.partition("?")
        if path == "/start":
            return self.start_session(query)
        if not self.has_session():
            return self.send_page(403, "Signed out", notice=SIGNED_OUT)
        if path not in PAGE_PARAMETERS:
            return self.send_page(404, "Not found", notice=NOT_FOUND)
        parameters = parsed_query(query, PAGE_PARAMETERS[path])
        if parameters is None:
            return self.send_page(400, "Refused", notice=BAD_ADDRESS)
        if path == "/style.css":
            return self.send_body(200, STYLESHEET.encode(), "text/css; charset=utf-8")
        conn = open_ledger(server.ledger_path, read_only=True)
        try:
            self.answer_page(conn, path, parameters)
        finally:
            conn.close()

    def start_session(self, query):
        server = self.server
        parameters = parsed_query(query, {"key"}) or {}
        if server.launch_key_used or not same_secret(parameters.get("key", ""), server.launch_key):
            return self.send_page(403, "Signed out", notice=SIGNED_OUT)
        server.launch_key_used = True
        cookie = (f"{server.session_cookie_name}={server.session_value}; HttpOnly; "
                  "SameSite=Strict; Path=/")
        self.send_body(303, b"", "text/plain; charset=utf-8",
                       extra_headers=(("Set-Cookie", cookie), ("Location", "/")))

    def has_session(self) -> bool:
        name = self.server.session_cookie_name
        for header in self.headers.get_all("Cookie") or []:
            for pair in header.split(";"):
                key, _, value = pair.strip().partition("=")
                if key == name and same_secret(value, self.server.session_value):
                    return True
        return False

    def answer_page(self, conn, path, parameters):
        account_id = parameters.get("account") or None
        if account_id is not None:
            account_id = find_account(conn, account_id)
        if path == "/":
            form = account_form(conn, "/", account_id)
            return self.send_page(200, "Totals", totals_report_lines(conn, account_id), form=form)
        first_month = validated_month("from", parameters.get("from") or None)
        last_month = validated_month("to", parameters.get("to") or None)
        if first_month and last_month and first_month > last_month:
            raise CommandError("from is after to. Nothing was changed.")
        form = account_form(conn, "/monthly", account_id, first_month, last_month)
        lines = monthly_report_lines(conn, account_id, first_month, last_month)
        self.send_page(200, "Monthly report", lines, form=form)

    def send_page(self, status, heading, lines=(), *, notice="", form="", after="",
                  extra_headers=()):
        body = render_page(heading, lines, notice=notice, form=form, after=after)
        self.send_body(status, body.encode("utf-8"), "text/html; charset=utf-8",
                       extra_headers=extra_headers)

    def send_body(self, status, body, content_type, *, extra_headers=()):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (*SECURITY_HEADERS, *extra_headers):
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)


def same_secret(given: str, expected: str) -> bool:
    # Header and address text arrives decoded as Latin-1, so it always encodes back.
    return hmac.compare_digest(given.encode("latin-1"), expected.encode("latin-1"))


def parsed_query(query: str, allowed: set[str]) -> dict[str, str] | None:
    """Each parameter at most once, one the page takes, its value an ID or a month. Else None."""
    parameters = {}
    for pair in query.split("&") if query else []:
        key, separator, value = pair.partition("=")
        if (not separator or key not in allowed or key in parameters
                or not QUERY_VALUE.fullmatch(value)):
            return None
        parameters[key] = value
    return parameters


def escaped(text: str) -> str:
    """For HTML: control and format characters as the CLI's shown() writes them, then HTML's
    special characters. Text the CLI already escaped passes the first step unchanged."""
    visible = "".join(
        char if char.isprintable() else char.encode("unicode_escape").decode() for char in text
    )
    return html.escape(visible, quote=True)


def rendered_line(line) -> str:
    item_id = line.linked_review_item_id
    if item_id and item_id in line.text:
        before, _, after = line.text.partition(item_id)
        link = f'<a href="/review/item?id={escaped(item_id)}">{escaped(item_id)}</a>'
        return f'<div class="line">{escaped(before)}{link}{escaped(after)}</div>'
    return f'<div class="line">{escaped(line.text)}</div>'


def render_page(heading, lines, *, notice="", form="", after="") -> str:
    links = "".join(f'<a href="{path}">{label}</a>' for path, label in NAVIGATION)
    report = "".join(rendered_line(line) for line in lines)
    notice_html = f'<p class="notice">{escaped(notice)}</p>' if notice else ""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>pf</title><link rel="stylesheet" href="/style.css"></head><body>'
        f"<nav>{links}</nav><main><h1>{escaped(heading)}</h1>{notice_html}{form}"
        f'<div class="report">{report}</div>{after}</main></body></html>'
    )


def account_form(conn, action, account_id, first_month=None, last_month=None) -> str:
    """A form that reloads the page by GET, choosing an account and, for months, a range."""
    options = ['<option value="">Every account</option>']
    for choice_id, name in account_choices(conn):
        selected = " selected" if choice_id == account_id else ""
        options.append(f'<option value="{escaped(choice_id)}"{selected}>{escaped(name)}</option>')
    months = ""
    if action == "/monthly":
        months = (
            '<label> From <input name="from" placeholder="YYYY-MM" size="8" '
            f'value="{escaped(first_month or "")}"></label>'
            '<label> To <input name="to" placeholder="YYYY-MM" size="8" '
            f'value="{escaped(last_month or "")}"></label>'
        )
    return (f'<form method="get" action="{action}"><label>Account <select name="account">'
            f'{"".join(options)}</select></label>{months} <button>Show</button></form>')
