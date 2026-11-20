"""The local review UI: pages served on 127.0.0.1 alone (D-062), and the forms on them that
make review decisions (D-073 point 1, M17.1).

Every page shows the lines of the same builder its CLI command prints, so the UI computes nothing
of its own. Nothing here writes a file, logs a request or prints: only the CLI prints (D-037).
Every GET opens the ledger read-only through open_ledger, so a real ledger's gate runs on each
one (D-058). A POST passes the write pipeline in ui/writes.py, then runs the CLI's own command,
whose output is kept in memory for the result page: the command opens through the gate for
writing, and refuses exactly as in the terminal. W1 allows this module, and no other, to import
from `http`, and only these two classes (D-062 point 1).
"""

import contextlib
import hmac
import html
import io
import re
import secrets
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

from personal_finance.cli import (
    SAFE_TO_SPEND_TIMEZONE,
    UNEXPECTED_ERROR,
    CommandError,
    active_decision_undo,
    checked_as_of,
    household_today_if_set,
    explained_error,
    find_account,
    main,
    open_ledger,
    validated_month,
)
from personal_finance.reports.report_text import (
    ReportLines,
    account_choices,
    document_list_lines,
    budget_report_lines,
    dashboard_lines,
    funds_report_lines,
    net_worth_report_lines,
    household_report_lines,
    income_report_lines,
    member_choices,
    monthly_report_lines,
    review_item_report,
    review_queue_lines,
    totals_report_lines,
    transaction_list_lines,
)
from personal_finance.ui import writes

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
    ("/household", "Household"),
    ("/income", "Income"),
    ("/budget", "Budget"),
    ("/funds", "Funds"),
    ("/net-worth", "Net worth"),
    ("/dashboard", "Dashboard"),
    ("/documents", "Import results"),
    ("/transactions", "Transactions"),
    ("/review", "Review queue"),
)

# What each page accepts in its address. A value is an ID or a month and nothing else, refused
# before it reaches a query, so no address needs decoding.
PAGE_PARAMETERS = {
    "/": {"account"},
    "/monthly": {"account", "from", "to"},
    "/household": {"account", "from", "to", "member", "view"},
    "/income": {"account", "from", "to", "as_of"},
    "/budget": {"month", "member", "as_of"},
    "/funds": {"as_of"},
    "/net-worth": {"as_of", "member"},
    "/dashboard": {"as_of"},
    "/documents": set(),
    "/transactions": set(),
    "/review": set(),
    "/review/item": {"id"},
    "/result": {"id"},
    "/transaction": {"id"},
    "/style.css": set(),
}
QUERY_VALUE = re.compile(r"[A-Za-z0-9_-]{0,100}")

SIGNED_OUT = (
    "This page needs the address pf ui printed, opened once in this browser. Restart pf ui for a "
    "new one."
)
WRONG_HOST = "This server answers only at the address pf ui printed."
FOREIGN_ORIGIN = "Requests from other sites are refused."
NOT_FOUND = "There is no such page."
BAD_ADDRESS = "This address holds a value the interface does not accept."
UNREADABLE = "This request could not be read."
CHOOSE_AS_OF = (
    "Give an as-of date, YYYY-MM-DD. Missed and expected depend on it, and the interface reads "
    "no clock."
)
ITEM_NOT_FOUND = "Review item not found. A later import can replace one: see the review queue."
TRANSACTION_NOT_FOUND = "Transaction not found. See the transactions list."
SEVERAL_STATEMENTS = (
    "More than one statement reaches this, so the choice of which to replace is made in the "
    "terminal, with --supersedes."
)
RESULT_NOT_FOUND = "There is no such result in this session. See the review queue."
COMMAND_UNREADABLE = "This form could not be read as a command. Nothing was changed."
# The result pages a session keeps, newest last: older ones are forgotten.
KEPT_RESULT_COUNT = 20
RECORDED_DECISION = re.compile(r"Decision (\S+) recorded:")


class LoopbackServer(HTTPServer):
    """One request at a time, on 127.0.0.1 at a port the system picks, with one launch's
    secrets: a key that works once, for a cookie every other request needs."""

    allow_reuse_address = False

    def __init__(self, ledger_path):
        self.ledger_path = ledger_path
        self.launch_key = secrets.token_urlsafe(32)
        self.launch_key_used = False
        self.session_value = secrets.token_urlsafe(32)
        # The form tokens' key and the tokens spent, for this launch's one session, in memory
        # only (D-073 point 1, step 8).
        self.form_secret = secrets.token_bytes(32)
        self.used_form_tokens = set()
        # What each successful write printed, by a random result ID, for Post/Redirect/Get.
        self.results = {}
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
        # http.server looks up do_<METHOD> for each request. Every method but GET and POST is
        # refused, its body unread.
        if name.startswith("do_"):
            return self.refuse_method
        raise AttributeError(name)

    def refuse_method(self):
        self.send_page(405, "Refused", notice=writes.NOT_ALLOWED,
                       extra_headers=(("Allow", "GET, POST"),))

    def do_POST(self):
        try:
            self.answer_post()
        except Exception as error:
            message = explained_error(error)
            self.send_page(500 if message == UNEXPECTED_ERROR else 400, "Refused", notice=message)

    def answer_post(self):
        """D-073 point 1's pipeline, in its order. Nothing is read from the body, and no ledger
        is opened, until every step before the form has passed."""
        server = self.server
        if self.headers.get_all("Host") != [f"{LOOPBACK_ADDRESS}:{server.server_port}"]:
            return self.send_page(421, "Refused", notice=WRONG_HOST)
        if not self.has_session():
            return self.send_page(403, "Signed out", notice=SIGNED_OUT)
        refusal = (writes.refuse_route(self.path)
                   or writes.refuse_origin(self.headers.get_all("Origin"), server.origin)
                   or writes.refuse_fetch_metadata(self.headers.get_all("Sec-Fetch-Site"),
                                                   self.headers.get_all("Sec-Fetch-Mode")))
        if refusal:
            return self.send_refusal(refusal)
        length = writes.checked_body_length(self.headers.get_all("Content-Type"),
                                            self.headers.get_all("Content-Length"),
                                            self.headers.get_all("Transfer-Encoding"))
        if isinstance(length, writes.Refusal):
            return self.send_refusal(length)
        body = self.rfile.read(length)
        if len(body) != length:
            return self.send_page(400, "Refused", notice=UNREADABLE)
        form = writes.parsed_form(body, writes.WRITE_ROUTES[self.path])
        if isinstance(form, writes.Refusal):
            return self.send_refusal(form)
        refusal = writes.refuse_form_token(form, self.path, server.form_secret,
                                           server.used_form_tokens)
        if refusal:
            return self.send_refusal(refusal)
        self.run_command(writes.command_words(self.path, form, server.ledger_path))

    def run_command(self, words):
        """Step 9: the CLI's own command, as the terminal runs it, with what it prints kept in
        memory. A success redirects to its result page (Post/Redirect/Get), and a refusal shows
        the CLI's message, which repeats no input (D-037)."""
        code, printed, message = run_in_memory(words)
        if code is None:
            return self.send_page(400, "Refused", notice=COMMAND_UNREADABLE)
        if code != 0:
            return self.send_page(409, "Refused", notice=message or UNEXPECTED_ERROR)
        results = self.server.results
        result_id = secrets.token_urlsafe(16)
        results[result_id] = printed
        while len(results) > KEPT_RESULT_COUNT:
            del results[next(iter(results))]
        self.send_body(303, b"", "text/plain; charset=utf-8",
                       extra_headers=(("Location", f"/result?id={result_id}"),))

    def send_refusal(self, refusal):
        self.send_page(refusal.status, "Refused", notice=refusal.notice,
                       extra_headers=refusal.extra_headers)

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
        if path == "/documents":
            return self.send_page(200, "Import results", document_list_lines(conn))
        if path == "/transactions":
            return self.send_page(200, "Transactions", transaction_list_lines(conn))
        if path == "/review":
            return self.send_page(200, "Review queue", review_queue_lines(conn))
        if path == "/review/item":
            report = review_item_report(conn, parameters.get("id", ""))
            if report is None:
                return self.send_page(404, "Not found", notice=ITEM_NOT_FOUND)
            forms = decision_forms(self.server.form_secret, report)
            hint = decision_hint(self.server.ledger_path, report)
            return self.send_page(200, "Review item", report.lines, after=forms + hint)
        if path == "/result":
            return self.answer_result(conn, parameters.get("id", ""))
        if path == "/transaction":
            return self.answer_transaction(conn, parameters.get("id", ""))
        if path == "/budget":
            return self.answer_budget(conn, parameters)
        if path == "/funds":
            return self.answer_funds(conn, parameters)
        if path == "/net-worth":
            return self.answer_net_worth(conn, parameters)
        if path == "/dashboard":
            return self.answer_dashboard(conn, parameters)
        first_month = validated_month("from", parameters.get("from") or None)
        last_month = validated_month("to", parameters.get("to") or None)
        if first_month and last_month and first_month > last_month:
            raise CommandError("from is after to. Nothing was changed.")
        if path == "/household":
            return self.answer_household(conn, parameters, account_id, first_month, last_month)
        if path == "/income":
            return self.answer_income(conn, parameters, account_id, first_month, last_month)
        form = account_form(conn, "/monthly", account_id, first_month, last_month)
        lines = monthly_report_lines(conn, account_id, first_month, last_month)
        self.send_page(200, "Monthly report", lines, form=form)

    def answer_result(self, conn, result_id):
        """What a write printed, and for a decision still in effect, a form that undoes it with
        its current revision, as review decision show gives it. Reloading writes nothing."""
        kept = self.server.results.get(result_id)
        if kept is None:
            return self.send_page(404, "Not found", notice=RESULT_NOT_FOUND)
        printed = kept
        lines = ReportLines()
        for text in printed.splitlines():
            lines.add(text)
        recorded = RECORDED_DECISION.match(printed)
        after = ""
        undo = recorded and active_decision_undo(conn, recorded.group(1))
        if undo:
            decision_account_id, revision = undo
            after = undo_form(self.server.form_secret, recorded.group(1), decision_account_id,
                              revision)
        self.send_page(200, "Result", lines, after=after)

    def answer_transaction(self, conn, transaction_id):
        """review transaction show's lines, as the terminal prints them, and the forms that
        state or correct what this transaction is (M17.2a). Each statement already applying is
        superseded by its own revision from its show command."""
        db = f"--db={self.server.ledger_path}"
        code, printed, message = run_in_memory(
            ["review", "transaction", "show", transaction_id, db])
        if code is None:
            return self.send_page(404, "Not found", notice=TRANSACTION_NOT_FOUND)
        if code != 0:
            return self.send_page(404, "Not found", notice=message)
        lines = ReportLines()
        for text in printed.splitlines():
            lines.add(text)
        account_id = re.search(r"^  Account: .* \(([^()\s]+)\)$", printed, re.MULTILINE)[1]
        revision = re.search(r"^  Revision: (\S+)$", printed, re.MULTILINE)[1]
        hidden = {"transaction": transaction_id, "account": account_id, "revision": revision}
        secret = self.server.form_secret
        forms = []
        for path, kind, label in (("/transaction/classify", "classification", "Financial type"),
                                  ("/transaction/categorize", "categorization", "Category")):
            superseding = superseded_statement(printed, kind, db)
            if superseding is None:
                forms.append(f'<h3>{label}</h3><p class="notice">{escaped(SEVERAL_STATEMENTS)}'
                             "</p>")
                continue
            forms.append(route_form(secret, path, {**hidden, **superseding}, heading=label))
        for field in writes.CORRECTABLE_FIELDS:
            superseding = superseded_correction(printed, field, db)
            heading = f"Correct the {field.replace('_', ' ')}"
            if superseding is None:
                forms.append(f'<h3>{escaped(heading)}</h3><p class="notice">'
                             f"{escaped(SEVERAL_STATEMENTS)}</p>")
                continue
            forms.append(route_form(secret, "/transaction/correct",
                                    {**hidden, "field": field, **superseding}, heading=heading))
        forms.append(route_form(secret, "/transaction/separate", hidden,
                                heading="Separate its records"))
        accounts = [(choice_id, name) for choice_id, name in account_choices(conn)
                    if choice_id != account_id]
        if accounts:
            forms.append(route_form(secret, "/transaction/one-sided", hidden,
                                    choices={"counterpart_account": accounts},
                                    heading="A transfer whose other side is not imported"))
        self.send_page(200, "Transaction", lines, after="<h2>Deciding this transaction</h2>"
                       + "".join(forms))

    def answer_household(self, conn, parameters, account_id, first_month, last_month):
        """The household report in one view: side by side, one member's by ID, or shared."""
        member = parameters.get("member") or None
        view = parameters.get("view") or None
        members = {member_id for member_id, _ in member_choices(conn)}
        if (member is not None and (not member.isdigit() or int(member) not in members)) or (
                view not in (None, "shared")) or (member is not None and view is not None):
            return self.send_page(400, "Bad address", notice=BAD_ADDRESS)
        member_id = None if member is None else int(member)
        form = household_form(conn, account_id, first_month, last_month, member_id, view)
        lines = household_report_lines(conn, account_id, first_month, last_month, member_id,
                                       view == "shared")
        self.send_page(200, "Household report", lines, form=form)

    def answer_income(self, conn, parameters, account_id, first_month, last_month):
        """The income report as of the date the page is given, else today in the household's
        timezone, read by the CLI's one clock read (G7). With neither, the page asks for one."""
        text = parameters.get("as_of") or None
        form = income_form(conn, account_id, first_month, last_month, text)
        as_of = (household_today_if_set(conn) if text is None
                 else date.fromisoformat(checked_as_of(text)))
        if as_of is None:
            return self.send_page(200, "Income report", notice=CHOOSE_AS_OF, form=form)
        lines = income_report_lines(conn, as_of, account_id, first_month, last_month)
        self.send_page(200, "Income report", lines, form=form)

    def answer_budget(self, conn, parameters):
        """The budget report for a month, the household or one member by ID, as of the date the
        page is given, else today in the household's timezone (G7)."""
        month = validated_month("month", parameters.get("month") or None)
        member = parameters.get("member") or None
        names = dict(member_choices(conn))
        if member is not None and (not member.isdigit() or int(member) not in names):
            return self.send_page(400, "Bad address", notice=BAD_ADDRESS)
        member_id = None if member is None else int(member)
        text = parameters.get("as_of") or None
        form = budget_form(conn, month, member_id, text)
        as_of = (household_today_if_set(conn) if text is None
                 else date.fromisoformat(checked_as_of(text)))
        if as_of is None:
            return self.send_page(200, "Budget report", notice=CHOOSE_AS_OF, form=form)
        lines = budget_report_lines(conn, month or as_of.isoformat()[:7], as_of,
                                    None if member_id is None else names[member_id])
        self.send_page(200, "Budget report", lines, form=form)

    def answer_funds(self, conn, parameters):
        """The funds report as of the date the page is given, else today in the household's
        timezone (G7)."""
        text = parameters.get("as_of") or None
        form = funds_form(text)
        as_of = (household_today_if_set(conn) if text is None
                 else date.fromisoformat(checked_as_of(text)))
        if as_of is None:
            return self.send_page(200, "Funds report", notice=CHOOSE_AS_OF, form=form)
        self.send_page(200, "Funds report", funds_report_lines(conn, as_of), form=form)

    def answer_net_worth(self, conn, parameters):
        """Net worth as of the date the page is given, else today in the household's timezone,
        for the household or one member by ID (G7)."""
        member = parameters.get("member") or None
        names = dict(member_choices(conn))
        if member is not None and (not member.isdigit() or int(member) not in names):
            return self.send_page(400, "Bad address", notice=BAD_ADDRESS)
        member_id = None if member is None else int(member)
        text = parameters.get("as_of") or None
        form = net_worth_form(conn, member_id, text)
        as_of = (household_today_if_set(conn) if text is None
                 else date.fromisoformat(checked_as_of(text)))
        if as_of is None:
            return self.send_page(200, "Net worth", notice=CHOOSE_AS_OF, form=form)
        lines = net_worth_report_lines(conn, as_of.isoformat(),
                                       None if member_id is None else names[member_id])
        self.send_page(200, "Net worth", lines, form=form)

    def answer_dashboard(self, conn, parameters):
        """The dashboard as of the date the page is given, else today in the household's
        timezone (G7). With no timezone set it asks, as pf dashboard refuses."""
        text = parameters.get("as_of") or None
        form = as_of_form("/dashboard", text)
        today = household_today_if_set(conn)
        if today is None:
            return self.send_page(200, "Dashboard", notice=SAFE_TO_SPEND_TIMEZONE, form=form)
        as_of = today if text is None else date.fromisoformat(checked_as_of(text))
        self.send_page(200, "Dashboard", dashboard_lines(conn, as_of), form=form)

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


def run_in_memory(words) -> tuple[int | None, str, str]:
    """A CLI command as the terminal runs it, through the same parser, handler and gate, with
    what it prints kept in memory: its exit code (None when its arguments could not be read),
    its output, and its error message without the "Error: " the terminal adds. The server
    answers one request at a time, so redirecting the process's streams is safe."""
    printed, said = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(said):
            code = main(words)
    except SystemExit:
        return None, "", ""
    return code, printed.getvalue(), said.getvalue().strip().removeprefix("Error: ")


def superseded_statement(printed, kind, db) -> dict[str, str] | None:
    """The supersedes fields for a new classification or categorization: empty where none
    reaches the transaction, the one reaching it and its revision from review <kind> show, or
    None where several do or its revision cannot be read."""
    found = re.findall(rf"^    {kind.capitalize()} (\S+): ", printed, re.MULTILINE)
    return supersedes_fields(found, ["review", kind, "show"], db)


def superseded_correction(printed, field, db) -> dict[str, str] | None:
    """The same for a correction of one field, by its correction show."""
    found = re.findall(rf"^    Correction (\S+): {field} corrected to ", printed, re.MULTILINE)
    return supersedes_fields(found, ["review", "correction", "show"], db)


def supersedes_fields(found, show_words, db) -> dict[str, str] | None:
    if not found:
        return {"supersedes": "", "supersedes_revision": ""}
    if len(found) > 1:
        return None
    revision = printed_revision([*show_words, found[0], db])
    return None if revision is None else {"supersedes": found[0],
                                          "supersedes_revision": revision}


def printed_revision(words) -> str | None:
    """The revision a read-only show command prints, as the terminal shows it (M17.2 slice
    plan point 3), or None when it prints none or refuses."""
    code, printed, _ = run_in_memory(words)
    found = re.search(r"^\s*Revision: (\S+)$", printed, re.MULTILINE) if code == 0 else None
    return found[1] if found else None


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
    for linked_id, page in ((line.linked_review_item_id, "/review/item"),
                            (line.linked_transaction_id, "/transaction")):
        if linked_id and linked_id in line.text:
            before, _, after = line.text.partition(linked_id)
            link = f'<a href="{page}?id={escaped(linked_id)}">{escaped(linked_id)}</a>'
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
    if action in ("/monthly", "/household", "/income"):
        months = (
            '<label> From <input name="from" placeholder="YYYY-MM" size="8" '
            f'value="{escaped(first_month or "")}"></label>'
            '<label> To <input name="to" placeholder="YYYY-MM" size="8" '
            f'value="{escaped(last_month or "")}"></label>'
        )
    return (f'<form method="get" action="{action}"><label>Account <select name="account">'
            f'{"".join(options)}</select></label>{months} <button>Show</button></form>')


def household_form(conn, account_id, first_month, last_month, member_id, view) -> str:
    """The monthly form, then a choice of view: side by side, one member, or shared."""
    form = account_form(conn, "/household", account_id, first_month, last_month)
    choices = ['<option value="">Side by side</option>']
    selected = " selected" if view == "shared" else ""
    choices.append(f'<option value="shared"{selected}>Shared</option>')
    members = ['<option value="">Every member</option>']
    for choice_id, name in member_choices(conn):
        selected = " selected" if choice_id == member_id else ""
        members.append(f'<option value="{choice_id}"{selected}>{escaped(name)}</option>')
    views = (f'<label> View <select name="view">{"".join(choices)}</select></label>'
             f'<label> Member <select name="member">{"".join(members)}</select></label>')
    return form.replace(" <button>Show</button>", f"{views} <button>Show</button>")


def income_form(conn, account_id, first_month, last_month, as_of) -> str:
    """The monthly form, then the as-of date."""
    form = account_form(conn, "/income", account_id, first_month, last_month)
    field = ('<label> As of <input name="as_of" placeholder="YYYY-MM-DD" size="10" '
             f'value="{escaped(as_of or "")}"></label>')
    return form.replace(" <button>Show</button>", f"{field} <button>Show</button>")


def budget_form(conn, month, member_id, as_of) -> str:
    """A form that reloads the budget page by GET: a month, the household or a member, and the
    as-of date."""
    members = ['<option value="">Household</option>']
    for choice_id, name in member_choices(conn):
        selected = " selected" if choice_id == member_id else ""
        members.append(f'<option value="{choice_id}"{selected}>{escaped(name)}</option>')
    return ('<form method="get" action="/budget">'
            '<label>Month <input name="month" placeholder="YYYY-MM" size="8" '
            f'value="{escaped(month or "")}"></label>'
            f'<label> Member <select name="member">{"".join(members)}</select></label>'
            '<label> As of <input name="as_of" placeholder="YYYY-MM-DD" size="10" '
            f'value="{escaped(as_of or "")}"></label> <button>Show</button></form>')


def net_worth_form(conn, member_id, as_of) -> str:
    """A form that reloads the net worth page by GET: the household or a member, and the as-of
    date."""
    members = ['<option value="">Household</option>']
    for choice_id, name in member_choices(conn):
        selected = " selected" if choice_id == member_id else ""
        members.append(f'<option value="{choice_id}"{selected}>{escaped(name)}</option>')
    return ('<form method="get" action="/net-worth">'
            f'<label>Member <select name="member">{"".join(members)}</select></label>'
            '<label> As of <input name="as_of" placeholder="YYYY-MM-DD" size="10" '
            f'value="{escaped(as_of or "")}"></label> <button>Show</button></form>')


def funds_form(as_of) -> str:
    """A form that reloads the funds page by GET with an as-of date."""
    return as_of_form("/funds", as_of)


def as_of_form(action, as_of) -> str:
    """A form that reloads a page by GET with an as-of date."""
    return (f'<form method="get" action="{action}">'
            '<label>As of <input name="as_of" placeholder="YYYY-MM-DD" size="10" '
            f'value="{escaped(as_of or "")}"></label> <button>Show</button></form>')


# What each typed field is called on its form, and each route's button.
FIELD_LABELS = {
    "pairs": "Pairs that are different events, two transaction IDs a line",
    "groups": "Groups that are one event each, transaction IDs a line, separated by spaces",
    "amount": "Amount, such as -12.50, negative for money out",
    "transaction_date": "Transaction date, YYYY-MM-DD",
    "posting_date": "Posting date, YYYY-MM-DD",
    "description": "Description",
    "type": "Financial type",
    "category": "Category, a name from category list",
    "value": "Corrected value",
    "counterpart_account": "The other account",
}
BUTTONS = {
    "/review/reject": "Reject these pairs",
    "/review/confirm": "Confirm these groups",
    "/review/undo": "Undo this decision",
    "/review/complete": "Complete this row",
    "/review/dismiss": "Dismiss this row",
    "/transaction/classify": "Classify",
    "/transaction/categorize": "Categorize",
    "/transaction/correct": "Correct",
    "/transaction/separate": "Separate these groups",
    "/transaction/one-sided": "Record a one-sided transfer",
}


def route_form(secret, path, hidden, *, choices=None, heading="") -> str:
    """A route's form: its hidden fields as the page fixes them, the token that binds them, and
    an input for each typed field. choices gives a typed field's options by name, as a page
    knows them (an account list), where the route itself fixes none."""
    route = writes.WRITE_ROUTES[path]
    token = writes.form_token(secret, path, hidden)
    parts = [f'<input type="hidden" name="{field.name}" value="{escaped(hidden[field.name])}">'
             for field in route.hidden]
    parts.append(f'<input type="hidden" name="{writes.FORM_TOKEN_FIELD}" value="{token}">')
    for field in route.typed:
        label = escaped(FIELD_LABELS[field.name])
        options = (choices or {}).get(field.name) or [(value, value) for value in field.choices]
        if field.kind in (writes.PAIR_LINES, writes.GROUP_LINES):
            control = f'<textarea name="{field.name}" rows="3" cols="80"></textarea>'
        elif options:
            listed = "".join(f'<option value="{escaped(value)}">{escaped(shown_as)}</option>'
                             for value, shown_as in options)
            control = f'<select name="{field.name}">{listed}</select>'
        else:
            control = f'<input name="{field.name}" size="40">'
        parts.append(f"<label>{label}<br>{control}</label><br>")
    title = f"<h3>{escaped(heading)}</h3>" if heading else ""
    return (f'{title}<form method="post" action="{path}">{"".join(parts)}'
            f"<button>{escaped(BUTTONS[path])}</button></form>")


def decision_forms(secret, report) -> str:
    """The forms that decide a review item, posting what the terminal commands take: reject and
    confirm for a possible duplicate or conflict, complete and dismiss for an unresolved row."""
    hidden = {"item": report.item_id, "account": report.account_id, "revision": report.revision}
    paths = (("/review/complete", "/review/dismiss") if report.kind == "unresolved_record"
             else ("/review/reject", "/review/confirm"))
    return "<h2>Deciding this item</h2>" + "".join(
        route_form(secret, path, hidden) for path in paths)


def undo_form(secret, decision_id, account_id, revision) -> str:
    return route_form(secret, "/review/undo", {"decision": decision_id, "account": account_id,
                                               "revision": revision})


def decision_hint(ledger_path, report) -> str:
    """The terminal commands that decide this item, with its account ID, item ID and revision
    token. D-043's checks are the same from either place."""
    common = (f"{report.item_id} --db {ledger_path} --account {report.account_id} "
              f"--revision {report.revision}")
    if report.kind == "unresolved_record":
        commands = [f"pf review complete {common} with the values to supply",
                    f"pf review dismiss {common}"]
    else:
        commands = [f"pf review confirm {common} --group T ...",
                    f"pf review reject {common} --pair T1 T2"]
    lines = "".join(f'<div class="hint-line">  {escaped(command)}</div>' for command in commands)
    return ('<p class="notice">In the terminal, run one of these:</p>'
            f'<div class="report">{lines}</div>')
