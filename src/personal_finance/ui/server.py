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
    visual_lines,
    visuals,
)
from personal_finance.ui import charts, writes

LOOPBACK_ADDRESS = "127.0.0.1"
# Each scenario input kind's route, in the order the routes declare them (M18.2).
SCENARIO_INPUT_ROUTES = tuple(path for path in writes.WRITE_ROUTES
                              if path.startswith("/scenario/input/"))

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

# The page's look (D-083). Colours are tokens, set again for dark mode; the page has no script, so
# the system's setting alone chooses.
STYLESHEET = """\
:root {
  --page: #f5f5f7; --surface: #ffffff; --sidebar: #ececf0; --hover: rgba(0, 0, 0, 0.06);
  --border: #e1e1e6; --border-strong: #c7c7cc; --text: #1d1d1f; --muted: #6e6e73;
  --accent: #0a62d0; --accent-fill: #0a62d0; --on-accent: #ffffff;
  --positive: #1a7f37; --negative: #c4281c; --warning: #8f5400;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root {
    --page: #161618; --surface: #202023; --sidebar: #1b1b1e; --hover: rgba(255, 255, 255, 0.07);
    --border: #333338; --border-strong: #4a4a50; --text: #f5f5f7; --muted: #a1a1a6;
    --accent: #6aaaff; --accent-fill: #2f6fde; --on-accent: #ffffff;
    --positive: #4cc46b; --negative: #ff7b6e; --warning: #f0b14a;
    color-scheme: dark;
  }
}
body { margin: 0; background: var(--page); color: var(--text);
       font: 14px/1.5 -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
       font-variant-numeric: tabular-nums; }
a { color: var(--accent); }
.app { display: grid; grid-template-columns: 220px minmax(0, 1fr); min-height: 100vh; }
.sidebar { position: sticky; top: 0; height: 100vh; box-sizing: border-box; overflow-y: auto;
           padding: 18px 12px; background: var(--sidebar); border-right: 1px solid var(--border); }
.brand { display: block; padding: 0 10px 6px; font-size: 18px; font-weight: 700;
         color: var(--text); text-decoration: none; }
.nav-heading { margin: 18px 10px 4px; font-size: 11px; font-weight: 600; letter-spacing: 0.06em;
               text-transform: uppercase; color: var(--muted); }
.nav-link { display: block; padding: 5px 10px; border-radius: 6px; color: var(--text);
            text-decoration: none; }
.nav-link:hover { background: var(--hover); }
.nav-link[aria-current="page"] { background: var(--accent-fill); color: var(--on-accent);
                                 font-weight: 600; }
main { min-width: 0; max-width: 1100px; padding: 28px 36px 64px; }
h1 { margin: 0 0 18px; font-size: 26px; letter-spacing: -0.01em; }
h2 { margin: 32px 0 10px; font-size: 17px; }
h3 { margin: 18px 0 8px; font-size: 14px; }
.notice { color: var(--muted); }
.toolbar form { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 10px 16px;
                margin: 0 0 18px; padding: 12px 14px; background: var(--surface);
                border: 1px solid var(--border); border-radius: 10px; }
.toolbar label { display: flex; flex-direction: column; gap: 4px; }
label { font-size: 12px; font-weight: 500; color: var(--muted); }
input, select, textarea { font: inherit; font-size: 13px; color: var(--text);
                          background: var(--surface); border: 1px solid var(--border-strong);
                          border-radius: 6px; padding: 5px 8px; }
input:focus, select:focus, textarea:focus, button:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 1px; }
button { font: inherit; font-size: 13px; font-weight: 600; padding: 6px 14px; cursor: pointer;
         color: var(--on-accent); background: var(--accent-fill); border: 1px solid transparent;
         border-radius: 6px; }
button:hover { filter: brightness(1.1); }
form[action$="undo"] button, form[action$="uncover"] button {
  color: var(--negative); background: transparent; border-color: var(--negative); }
.report { margin: 0 0 18px; padding: 14px 18px; background: var(--surface);
          border: 1px solid var(--border); border-radius: 10px;
          font: 12.5px/1.6 ui-monospace, Menlo, monospace; }
.report:empty { display: none; }
.line, .hint-line { white-space: pre-wrap; overflow-wrap: anywhere; }
.chart { margin: 0 0 16px; padding: 14px 16px; background: var(--surface);
         border: 1px solid var(--border); border-radius: 10px; }
.chart svg { display: block; max-width: 100%; height: auto; }
.actions form[method="post"] { display: grid; gap: 10px; max-width: 640px; margin: 0 0 12px;
                               padding: 14px 16px; background: var(--surface);
                               border: 1px solid var(--border); border-radius: 10px; }
.actions form[method="post"] button { justify-self: start; }
.actions form[method="get"] { display: flex; flex-wrap: wrap; align-items: flex-end;
                              gap: 10px 16px; margin: 0 0 16px; }
.field { display: grid; gap: 4px; }
.field textarea { box-sizing: border-box; width: 100%; font-family: ui-monospace, Menlo, monospace; }
.field input { max-width: 100%; box-sizing: border-box; }
@media (max-width: 760px) {
  .app { grid-template-columns: minmax(0, 1fr); }
  .sidebar { position: static; height: auto; border-right: 0;
             border-bottom: 1px solid var(--border); }
  .nav-group { display: flex; flex-wrap: wrap; gap: 2px; }
  .nav-heading { width: 100%; }
  main { padding: 20px 16px 48px; }
}
"""

# The sidebar: each group's heading, then its pages (D-083 point 1).
NAVIGATION_GROUPS = (
    ("Overview", (("/dashboard", "Dashboard"), ("/", "Totals"), ("/net-worth", "Net worth"),
                  ("/visuals", "Visuals"))),
    ("Money", (("/monthly", "Monthly"), ("/budget", "Budget"), ("/income", "Income"),
               ("/household", "Household"), ("/funds", "Funds"),
               ("/obligations", "Obligations"))),
    ("Activity", (("/transactions", "Transactions"), ("/review", "Review queue"),
                  ("/documents", "Import results"))),
    ("Planning", (("/scenarios", "Scenarios"),)),
    ("Setup", (("/accounts", "Accounts and members"), ("/settings", "Settings and backups"))),
)
# A page reached from another, such as one review item, marks that page in the sidebar.
NAVIGATION_PARENTS = {"/review/item": "/review", "/transaction": "/transactions",
                      "/scenario": "/scenarios", "/scenario/compare": "/scenarios"}
CURRENT_PAGE = ' aria-current="page"'

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
    "/accounts": set(),
    "/obligations": {"as_of"},
    "/settings": set(),
    "/visuals": {"as_of"},
    "/scenarios": set(),
    "/scenario": {"id"},
    "/scenario/compare": {"id", "months", "as_of"},
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
        parameters = (search_parameters(query) if path == "/transactions"
                      else parsed_query(query, PAGE_PARAMETERS[path]))
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
            return self.answer_transactions(conn, parameters)
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
        if path == "/visuals":
            return self.answer_visuals(conn, parameters)
        if path == "/scenarios":
            return self.answer_scenarios()
        if path == "/scenario":
            return self.answer_scenario(parameters.get("id", ""))
        if path == "/scenario/compare":
            return self.answer_scenario_compare(conn, parameters)
        if path in SECTIONS:
            return self.answer_section(conn, path, parameters)
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

    def answer_visuals(self, conn, parameters):
        """The eight visuals as SVG, each over the table pf report visuals prints for it, as of
        the date given, else today in the household's timezone (G7)."""
        text = parameters.get("as_of") or None
        form = as_of_form("/visuals", text)
        as_of = (household_today_if_set(conn) if text is None
                 else date.fromisoformat(checked_as_of(text)))
        if as_of is None:
            return self.send_page(200, "Visuals", notice=CHOOSE_AS_OF, form=form)
        drawn = visuals(conn, as_of)
        svgs = "".join(f'<div class="chart">{charts.chart_svg(chart)}</div>' for chart in drawn)
        self.send_page(200, "Visuals", visual_lines(conn, as_of, drawn), form=form,
                       figures=svgs)

    def printed_lines(self, words) -> tuple[ReportLines | None, str, str]:
        """A command run in memory, as its lines, else None with its refusal."""
        code, printed, message = run_in_memory([*words, f"--db={self.server.ledger_path}"])
        if code != 0:
            return None, printed, message or BAD_ADDRESS
        lines = ReportLines()
        for text in without_creation_times(printed).splitlines():
            lines.add(text)
        return lines, printed, ""

    def answer_scenarios(self):
        """pf scenarios as it prints, a link to each scenario, and the form adding one."""
        lines, printed, _ = self.printed_lines(["scenarios"])
        links = "".join(f'<p><a href="/scenario?id={escaped(found)}">Open scenario '
                        f"{escaped(found)}</a></p>"
                        for found in SCENARIO_ROW.findall(printed))
        add = route_form(self.server.form_secret, "/scenario/add", {}, heading="Add a scenario")
        self.send_page(200, "Scenarios", lines, after=links + add)

    def answer_scenario(self, scenario_id):
        """pf scenario show as it prints, and point 5's forms: an input form for each kind, each
        input's undo, the scenario's undo, and the comparison by GET, which writes nothing."""
        lines, printed, message = self.printed_lines(["scenario", "show", scenario_id])
        if lines is None:
            return self.send_page(404, "Not found", notice=message)
        secret = self.server.form_secret
        forms = [comparison_form(scenario_id, None, None)]
        added = SCENARIO_INPUT_REVISION.search(printed)
        if added:
            forms.append("<h2>Adding an input</h2>")
            for path in SCENARIO_INPUT_ROUTES:
                kind = path.removeprefix("/scenario/input/")
                forms.append(route_form(secret, path,
                                        {"scenario": scenario_id, "revision": added[1]},
                                        heading=kind.replace("_", " ").capitalize()))
        undone = [route_form(secret, "/scenario/input-undo",
                             {"scenario": scenario_id, "input": row["id"],
                              "revision": row["revision"]}, heading=f"Input {row['id']}")
                  for row in SCENARIO_INPUT_UNDO.finditer(printed)]
        if undone:
            forms += ["<h2>Undoing an input</h2>", *undone]
        scenario_undo = SCENARIO_UNDO_REVISION.search(printed)
        if scenario_undo:
            forms.append(route_form(secret, "/scenario/undo",
                                    {"scenario": scenario_id, "revision": scenario_undo[1]},
                                    heading="Undoing the scenario"))
        self.send_page(200, "Scenario", lines, after="".join(forms))

    def answer_scenario_compare(self, conn, parameters):
        """pf scenario compare as it prints: recalculated on every GET, nothing stored (point 5).
        As of the date given, else today in the household's timezone (G7)."""
        scenario_id = parameters.get("id", "")
        months = parameters.get("months") or "24"
        as_of = parameters.get("as_of") or None
        form = comparison_form(scenario_id, months, as_of)
        if as_of is None and household_today_if_set(conn) is None:
            return self.send_page(200, "Scenario comparison", notice=CHOOSE_AS_OF, form=form)
        dated = [] if as_of is None else [f"--as-of={as_of}"]
        lines, _, message = self.printed_lines(["scenario", "compare", scenario_id,
                                                f"--months={months}", *dated])
        if lines is None:
            return self.send_page(400, "Refused", notice=message, form=form)
        self.send_page(200, "Scenario comparison", lines, form=form)

    def answer_transactions(self, conn, parameters):
        """pf transactions with the filters given, run in memory, so the page and the command
        never differ (D-073 point 4), and a form that searches by GET."""
        form = search_form(conn, parameters)
        after = export_hint(self.server.ledger_path, parameters)
        if not parameters:
            return self.send_page(200, "Transactions", transaction_list_lines(conn), form=form,
                                  after=after)
        words = ["transactions", f"--db={self.server.ledger_path}",
                 *(f"--{name}={value}" for name, value in parameters.items())]
        code, printed, message = run_in_memory(words)
        if code != 0:
            return self.send_page(400, "Refused", notice=message or BAD_ADDRESS, form=form)
        lines = ReportLines()
        for text in printed.splitlines():
            found = TRANSACTION_ROW.match(text)
            lines.add(text, linked_transaction_id=found and found[1])
        self.send_page(200, "Transactions", lines, form=form, after=after)

    def answer_section(self, conn, path, parameters):
        """A section of PRD §18 as its commands print it, one after another, without creation
        times (F2, D-073 point 3), and the forms point 2 allows there."""
        heading, commands = SECTIONS[path]
        db = f"--db={self.server.ledger_path}"
        as_of = parameters.get("as_of") or None
        if as_of is not None:
            checked_as_of(as_of)
        lines, printed_by_command = ReportLines(), {}
        for key, words in commands:
            dated = ["--as-of", as_of] if as_of and key == "coverage" else []
            code, printed, message = run_in_memory([*words, db, *dated])
            printed = without_creation_times(printed if code == 0
                                             else f"Not available: {message}\n")
            printed_by_command[key] = printed
            for text in printed.splitlines():
                lines.add(text)
        secret = self.server.form_secret
        forms = SECTION_FORMS[path](secret, printed_by_command, account_choices(conn))
        form = as_of_form(path, as_of) if path == "/obligations" else ""
        self.send_page(200, heading, lines, form=form, after=forms)

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
                                  ("/transaction/categorize", "categorization", "Category"),
                                  ("/transaction/tag", "tagging", "Tags")):
            superseding = superseded_statement(printed, kind, db)
            if superseding is None:
                forms.append(f'<h3>{label}</h3><p class="notice">{escaped(SEVERAL_STATEMENTS)}'
                             "</p>")
                continue
            forms.append(route_form(secret, path, {**hidden, **superseding}, heading=label))
            if path == "/transaction/tag":
                forms.append(route_form(secret, "/transaction/tag-none",
                                        {**hidden, **superseding}))
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

    def send_page(self, status, heading, lines=(), *, notice="", form="", figures="", after="",
                  extra_headers=()):
        body = render_page(heading, lines, notice=notice, form=form, figures=figures,
                           after=after,
                           # An unreadable request has no path: its page marks none.
                           current_path=getattr(self, "path", "").partition("?")[0])
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


CREATION_TIME = re.compile(r", made \d{4}-\d{2}-\d{2}T[0-9:.]+Z")
LIQUIDITY_ROW = re.compile(
    r"^Account (?P<name>.*) \((?:checking|savings), (?P<id>[0-9a-f-]{36})\): .*\n"
    r"  (?P<kind>Undo|Set) revision: (?P<revision>\S+)$", re.MULTILINE)
BUFFER_ROW = re.compile(
    r"^Setting checking_buffer_cents: (?P<state>.*)\n  Revision: (?P<revision>\S+)$",
    re.MULTILINE)
COVERAGE_ROW = re.compile(
    r"^Obligation (?P<id>[0-9a-f-]{36}) \((?P<name>.*)\): .*\n"
    r"  (?P<kind>Covers|Uncover) revision: (?P<revision>\S+)$", re.MULTILINE)


SCENARIO_ROW = re.compile(r"^Scenario (\S+): ", re.MULTILINE)
SCENARIO_INPUT_REVISION = re.compile(r"^Input revision: (\S+)$", re.MULTILINE)
SCENARIO_UNDO_REVISION = re.compile(r"^Undo revision: (\S+)$", re.MULTILINE)
SCENARIO_INPUT_UNDO = re.compile(
    r"^  Input (?P<id>[0-9a-f-]{36}): .*\n    Undo revision: (?P<revision>\S+)$", re.MULTILINE)


def comparison_form(scenario_id, months, as_of) -> str:
    """A form that shows the comparison by GET, which writes nothing."""
    return ('<form method="get" action="/scenario/compare">'
            f'<input type="hidden" name="id" value="{escaped(scenario_id)}">'
            '<label>Months <input name="months" placeholder="24" size="4" '
            f'value="{escaped(months or "")}"></label>'
            '<label> As of <input type="date" name="as_of" placeholder="YYYY-MM-DD" size="10" '
            f'value="{escaped(as_of or "")}"></label> <button>Compare</button></form>')


def without_creation_times(printed: str) -> str:
    """A command's lines with each ", made <time>" left out: no page shows a creation time
    (F2, D-073 point 3). The one way a section page's text differs from its commands'."""
    return CREATION_TIME.sub("", printed)


def accounts_forms(secret, printed, accounts) -> str:
    forms = []
    for row in LIQUIDITY_ROW.finditer(printed.get("liquidity", "")):
        path = "/account/liquidity-undo" if row["kind"] == "Undo" else "/account/liquidity-set"
        forms.append(route_form(secret, path, {"account": row["id"],
                                               "revision": row["revision"]},
                                heading=f"Account {row['name']}"))
    return "<h2>Liquidity</h2>" + "".join(forms) if forms else ""


def settings_forms(secret, printed, accounts) -> str:
    row = BUFFER_ROW.search(printed.get("setting", ""))
    if row is None:
        return ""
    path = "/setting/buffer-set" if row["state"] == "not set" else "/setting/buffer-undo"
    return "<h2>Checking buffer</h2>" + route_form(
        secret, path, {"key": "checking_buffer_cents", "revision": row["revision"]})


def obligations_forms(secret, printed, accounts) -> str:
    forms = []
    for row in COVERAGE_ROW.finditer(printed.get("coverage", "")):
        hidden = {"obligation": row["id"], "revision": row["revision"]}
        heading = f"Obligation {row['name']}"
        if row["kind"] == "Uncover":
            forms.append(route_form(secret, "/obligation/uncover", hidden, heading=heading))
            continue
        forms.append(route_form(secret, "/obligation/covers-loan", hidden,
                                choices={"loan": accounts}, heading=heading))
        forms.append(route_form(secret, "/obligation/covers-fund", hidden))
    return "<h2>What each obligation covers</h2>" + "".join(forms) if forms else ""


# Each section: its heading, the commands it shows in order, and its forms.
SECTIONS = {
    "/accounts": ("Accounts and members", (
        ("liquidity", ("account", "liquidity", "show")), ("links", ("account", "links")),
        ("members", ("household", "members")), ("share", ("household", "share", "show")))),
    "/obligations": ("Obligations", (("obligations", ("obligations",)),
                                     ("coverage", ("obligation", "coverage")))),
    "/settings": ("Settings and backups", (("setting", ("setting", "show")),
                                           ("storage", ("storage",)))),
}
SECTION_FORMS = {"/accounts": accounts_forms, "/obligations": obligations_forms,
                 "/settings": settings_forms}


# How review transaction show names each kind's statements.
STATEMENT_LABELS = {"classification": "Classification", "categorization": "Categorization",
                    "tagging": "Tag statement"}


def superseded_statement(printed, kind, db) -> dict[str, str] | None:
    """The supersedes fields for a new classification, categorization or tag statement: empty
    where none reaches the transaction, the one reaching it and its revision from review <kind>
    show, or None where several do or its revision cannot be read."""
    found = re.findall(rf"^    {STATEMENT_LABELS[kind]} (\S+): ", printed, re.MULTILINE)
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


# What the transactions page takes, and of what kind, as pf transactions does (D-073 point 4).
SEARCH_FIELDS = {"search": writes.TEXT, "account": writes.ID, "from": writes.DATE_KIND,
                 "to": writes.DATE_KIND, "category": writes.TEXT, "tag": writes.TEXT,
                 "min": writes.AMOUNT_KIND, "max": writes.AMOUNT_KIND}
TRANSACTION_ROW = re.compile(r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})  ")


def search_parameters(query: str) -> dict[str, str] | None:
    """The transactions page's filters, decoded as a form is and each of its kind, given once.
    An empty one is a filter not given. None when anything else is there."""
    parameters = {}
    for piece in query.split("&") if query else []:
        raw_name, separator, raw_value = piece.encode("latin-1").partition(b"=")
        try:
            name = writes.decoded_form_part(raw_name)
            value = writes.decoded_form_part(raw_value)
        except (UnicodeDecodeError, ValueError):
            return None
        if not separator or name not in SEARCH_FIELDS or name in parameters:
            return None
        if not writes.acceptable(writes.Field(name, SEARCH_FIELDS[name], f"--{name}",
                                              required=False), value):
            return None
        parameters[name] = value
    return {name: value for name, value in parameters.items() if value != ""}


def export_hint(ledger_path, parameters) -> str:
    """The terminal command that exports these transactions. The page offers no download: one
    would land in Downloads, unencrypted and perhaps synced (D-073 point 7)."""
    scope = "".join(f" --{name} {value}" for name, value in parameters.items()
                    if name in ("account", "from", "to"))
    command = f"pf export transactions --db {ledger_path} --out FILE.csv{scope}"
    return ('<p class="notice">To export transactions as CSV, to a private folder outside any '
            'synced or git folder, run in the terminal:</p>'
            f'<div class="report"><div class="hint-line">  {escaped(command)}</div></div>')


def search_form(conn, parameters) -> str:
    """A form that searches the transactions by GET, holding the filters given."""
    def text_input(name, label, size=24):
        value = escaped(parameters.get(name, ""))
        kind = ' type="date"' if SEARCH_FIELDS[name] == writes.DATE_KIND else ""
        return (f'<label> {label} <input{kind} name="{name}" size="{size}" '
                f'value="{value}"></label>')

    accounts = ['<option value="">Every account</option>']
    for choice_id, name in account_choices(conn):
        selected = " selected" if choice_id == parameters.get("account") else ""
        accounts.append(f'<option value="{escaped(choice_id)}"{selected}>{escaped(name)}</option>')
    return ('<form method="get" action="/transactions">'
            + text_input("search", "Description contains", 30)
            + f'<label> Account <select name="account">{"".join(accounts)}</select></label>'
            + text_input("from", "From", 10) + text_input("to", "To", 10)
            + text_input("category", "Category", 16) + text_input("tag", "Tag", 12)
            + text_input("min", "Least amount", 10) + text_input("max", "Greatest amount", 10)
            + " <button>Search</button></form>")


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


def navigation(current_path) -> str:
    """The sidebar, marking the page shown, or the page it was reached from."""
    marked = NAVIGATION_PARENTS.get(current_path, current_path)
    groups = []
    for group_heading, pages in NAVIGATION_GROUPS:
        links = "".join(
            f'<a class="nav-link" href="{path}"{CURRENT_PAGE if path == marked else ""}>'
            f"{label}</a>" for path, label in pages)
        groups.append(f'<div class="nav-group"><p class="nav-heading">{group_heading}</p>'
                      f"{links}</div>")
    return (f'<nav class="sidebar" aria-label="Pages"><a class="brand" href="/dashboard">pf</a>'
            f'{"".join(groups)}</nav>')


def render_page(heading, lines, *, notice="", form="", figures="", after="",
                current_path="") -> str:
    """A page: the sidebar, the heading, any notice, the filter form, any figures drawn from the
    report's own rows, the report's lines, then what follows them (forms that write, hints)."""
    report = "".join(rendered_line(line) for line in lines)
    notice_html = f'<p class="notice">{escaped(notice)}</p>' if notice else ""
    toolbar = f'<div class="toolbar">{form}</div>' if form else ""
    actions = f'<div class="actions">{after}</div>' if after else ""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{escaped(heading)} · pf</title><link rel="stylesheet" href="/style.css">'
        f'</head><body><div class="app">{navigation(current_path)}<main>'
        f"<h1>{escaped(heading)}</h1>{notice_html}{toolbar}{figures}"
        f'<div class="report">{report}</div>{actions}</main></div></body></html>'
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
            '<label> From <input type="month" name="from" placeholder="YYYY-MM" size="8" '
            f'value="{escaped(first_month or "")}"></label>'
            '<label> To <input type="month" name="to" placeholder="YYYY-MM" size="8" '
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
    field = ('<label> As of <input type="date" name="as_of" placeholder="YYYY-MM-DD" size="10" '
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
            '<label>Month <input type="month" name="month" placeholder="YYYY-MM" size="8" '
            f'value="{escaped(month or "")}"></label>'
            f'<label> Member <select name="member">{"".join(members)}</select></label>'
            '<label> As of <input type="date" name="as_of" placeholder="YYYY-MM-DD" size="10" '
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
            '<label> As of <input type="date" name="as_of" placeholder="YYYY-MM-DD" size="10" '
            f'value="{escaped(as_of or "")}"></label> <button>Show</button></form>')


def funds_form(as_of) -> str:
    """A form that reloads the funds page by GET with an as-of date."""
    return as_of_form("/funds", as_of)


def as_of_form(action, as_of) -> str:
    """A form that reloads a page by GET with an as-of date."""
    return (f'<form method="get" action="{action}">'
            '<label>As of <input type="date" name="as_of" placeholder="YYYY-MM-DD" size="10" '
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
    "tags": "Tags, names from tags separated by commas",
    "buffer": "Checking buffer, an amount such as 500.00",
    "loan": "Covers this loan's payment",
    "fund": "Covers this reserve's purchase, by its fund ID",
    "scenario_name": "Name",
    "include_uncertain": "Count uncertain inputs too",
    "from_date": "From, YYYY-MM-DD",
    "input_amount": "Amount, such as 250.00, money in or out by its kind",
    "to_date": "To, YYYY-MM-DD, inclusive, or empty",
    "cadence": "Cadence, such as monthly:1, biweekly or annual:09-01",
    "anchor": "Anchor, a weekly, biweekly or quarterly cadence's date",
    "replaces": "Replaces this source, obligation or reserve ID, or empty for additional",
    "uncertain": "Uncertain",
    "confirmed": "Confirmed, as a bonus is uncertain unless confirmed",
    "gross": "Gross",
    "take_home_percent": "Take-home percent of a gross amount",
    "price": "Price",
    "down_payment": "Down payment",
    "closing_costs": "Closing costs",
    "loan_rate": "Loan APR, such as 6.5",
    "loan_months": "Loan months",
    "ownership_costs": "Ownership costs a month",
    "payoff_loan": "The loan account, by name or ID",
    "promote_account": "Account a promotion records it on, or empty",
    "promote_match": "Description text a promotion matches, or empty",
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
    "/transaction/tag": "Tag",
    "/transaction/tag-none": "State it has no tags",
    "/setting/buffer-set": "Set the buffer",
    "/setting/buffer-undo": "Undo the buffer",
    "/account/liquidity-set": "Designate liquid",
    "/account/liquidity-undo": "Undo the designation",
    "/obligation/covers-loan": "Link to the loan",
    "/obligation/covers-fund": "Link to the reserve",
    "/obligation/uncover": "Undo the link",
    "/scenario/add": "Add the scenario",
    "/scenario/undo": "Undo the scenario",
    "/scenario/input-undo": "Undo this input",
    **{path: "Add this input" for path in SCENARIO_INPUT_ROUTES},
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
        elif field.kind == writes.FLAG:
            control = (f'<select name="{field.name}"><option value="">No</option>'
                       f'<option value="{writes.FLAG_ON}">Yes</option></select>')
        elif options:
            listed = "".join(f'<option value="{escaped(value)}">{escaped(shown_as)}</option>'
                             for value, shown_as in options)
            control = f'<select name="{field.name}">{listed}</select>'
        elif field.kind == writes.DATE_KIND:
            control = f'<input type="date" name="{field.name}" placeholder="YYYY-MM-DD">'
        else:
            control = f'<input name="{field.name}" size="40">'
        parts.append(f'<label class="field">{label}{control}</label>')
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
