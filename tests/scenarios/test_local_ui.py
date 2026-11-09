"""The local UI's server, its protections, and its totals and monthly pages (M8.2, UB2 to UB8,
D-062). UB1, W1's allowance, is in tests/unit/test_no_network_imports.py.

Requests go to the real handler over a socket pair (local_ui_client), so no test connects to
anything and the suite's socket guard is unchanged.
"""

import socket
import sqlite3
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from local_ui_client import UiClient, page_text, parsed_page
from test_csv_pdf_matching import NOVEMBER, OCTOBER, load_csv, load_pdf
from test_decisions import CAFE, Ledger
from test_monthly_report import build, generated_ledger, rows
from test_real_ledger import (  # noqa: F401, vault is a fixture
    RealLedger,
    place_on_volume,
    probe_recording,
    vault,
)
from test_us_bank_activity_pdf import LAST4, add_account

from personal_finance.cli import UNEXPECTED_ERROR, main
from personal_finance.db.backups import logical_digest
from personal_finance.db.migrate import connect, create_database
from personal_finance.ingest import pipeline
from personal_finance.reconcile.apply import ReconcileResult
from personal_finance.ui import server as ui_server

SENTINEL = "SENTINELMERCHANT 98765.43"
CONTENT_SECURITY_POLICY = ("default-src 'none'; style-src 'self'; form-action 'self'; "
                           "frame-ancestors 'none'; base-uri 'none'")
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
}


@pytest.fixture
def ledger(tmp_path, capsys):
    """Two accounts, a possible duplicate in A, and B left unreconciled."""
    found = Ledger(tmp_path, capsys)
    found.card("a.csv", CAFE)
    found.card("b.csv", CAFE)
    found.add_account("B")
    return found


@pytest.fixture
def client(ledger):
    found = UiClient(ledger.path)
    found.sign_in()
    yield found
    found.close()


def unchanged_state(path):
    conn = connect(path, read_only=True)
    try:
        return path.read_bytes(), logical_digest(conn)
    finally:
        conn.close()


def cli_output(capsys, *words):
    capsys.readouterr()
    assert main(list(words)) == 0
    return capsys.readouterr().out


class TestLoopbackOnly:  # UB2
    def test_it_listens_on_127_0_0_1_over_ipv4_with_reuse_off_and_looks_up_no_name(
            self, ledger, monkeypatch):
        def no_lookup(*args, **kwargs):
            raise AssertionError("a name lookup")

        monkeypatch.setattr(socket, "getfqdn", no_lookup)
        monkeypatch.setattr(socket, "gethostbyaddr", no_lookup)
        client = UiClient(ledger.path)
        try:
            listening = client.server.socket
            assert listening.family == socket.AF_INET
            address, port = listening.getsockname()
            assert address == "127.0.0.1" and port > 0
            assert listening.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 0
        finally:
            client.close()

    def test_http_servers_own_bind_would_look_up_a_name_as_the_control(self, monkeypatch):
        def no_lookup(*args, **kwargs):
            raise AssertionError("a name lookup")

        monkeypatch.setattr(socket, "getfqdn", no_lookup)
        with pytest.raises(AssertionError, match="a name lookup"):
            HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)

    def test_each_launch_gets_its_own_port_and_secrets(self, ledger):
        first, second = UiClient(ledger.path), UiClient(ledger.path)
        try:
            assert first.server.server_port != second.server.server_port
            assert first.server.launch_key != second.server.launch_key
            assert first.server.session_value != second.server.session_value
        finally:
            first.close()
            second.close()

    @pytest.mark.parametrize("option", [["--host", "0.0.0.0"], ["--port", "8000"]])
    def test_pf_ui_takes_no_host_or_port(self, ledger, option):
        with pytest.raises(SystemExit) as exit_info:
            main(["ui", "--db", ledger.db, *option])
        assert exit_info.value.code == 2

    def test_pf_ui_prints_the_launch_address_and_stops_on_ctrl_c(self, ledger, capsys,
                                                                 monkeypatch):
        def stop(self):
            raise KeyboardInterrupt

        monkeypatch.setattr(ui_server.LoopbackServer, "serve_forever", stop)
        capsys.readouterr()
        assert main(["ui", "--db", ledger.db]) == 0
        out = capsys.readouterr().out
        assert "on 127.0.0.1 only" in out
        assert "  http://127.0.0.1:" in out and "/start?key=" in out
        assert out.endswith("Stopped.\n")

    def test_pf_ui_refuses_an_unsafe_real_ledger_before_any_port_opens(self, vault, capsys,
                                                                       monkeypatch):
        real = RealLedger(vault, capsys)
        place_on_volume(monkeypatch, probe_recording("unencrypted_disk_image"))
        launched = []
        monkeypatch.setattr(ui_server.LoopbackServer, "__init__",
                            lambda *args: launched.append(args))
        capsys.readouterr()
        assert main(["ui", "--db", real.db]) == 2
        captured = capsys.readouterr()
        assert "reported encrypted" in captured.err
        assert captured.out == "" and launched == []


WRONG_HOSTS = {
    "missing": None,
    "another port": "127.0.0.1:1",
    "no port": "127.0.0.1",
    "localhost": "localhost:{port}",
    "LOCALHOST": "LOCALHOST:{port}",
    "trailing dot": "127.0.0.1.:{port}",
    "a foreign name": "attacker.example:{port}",
    "IPv6 loopback": "[::1]:{port}",
}


class TestHost:  # UB3
    @pytest.mark.parametrize("host", WRONG_HOSTS.values(), ids=WRONG_HOSTS.keys())
    def test_any_other_host_is_refused_before_the_cookie_or_ledger(self, client, monkeypatch,
                                                                   host):
        opened = []
        monkeypatch.setattr(ui_server, "open_ledger", lambda *args, **kwargs: opened.append(1))
        given = host.format(port=client.server.server_port) if host else None
        response = client.get("/", host=given)
        assert response.status == 421
        assert parsed_page(response.body).report_lines == []
        assert opened == []

    def test_a_repeated_host_is_refused(self, client):
        response = client.get("/", headers=[("Host", client.host)])
        assert response.status == 421

    def test_the_exact_host_is_answered_as_the_control(self, client):
        assert client.get("/").status == 200

    def test_a_rebound_name_with_the_cookie_is_still_refused(self, client):
        """DNS rebinding: a page at another name resolving to 127.0.0.1 sends that name."""
        response = client.get("/", host=f"attacker.example:{client.server.server_port}")
        assert response.status == 421


class TestSession:  # UB4
    @pytest.mark.parametrize("target", ["/", "/monthly", "/style.css", "/no-such-page"])
    def test_without_the_cookie_every_route_is_refused_with_no_data(self, ledger, target):
        client = UiClient(ledger.path)
        try:
            response = client.get(target)
            assert response.status == 403
            assert parsed_page(response.body).report_lines == []
            assert b"SYNTHETIC" not in response.body
        finally:
            client.close()

    @pytest.mark.parametrize("query", ["", "?key=", "?key=wrong", "?key={key}x", "?key={key}&key={key}",
                                       "?key={key}&account=a", "?other={key}"])
    def test_a_wrong_or_missing_launch_key_is_refused(self, ledger, query):
        client = UiClient(ledger.path)
        try:
            response = client.get("/start" + query.format(key=client.server.launch_key))
            assert response.status == 403
            assert response.header("Set-Cookie") is None
            assert client.server.launch_key_used is False
        finally:
            client.close()

    def test_the_launch_key_works_once_for_a_strict_http_only_cookie(self, ledger):
        client = UiClient(ledger.path)
        try:
            response = client.sign_in()
            assert response.header("Location") == "/"
            name = f"pf_session_{client.server.server_port}"
            assert response.header("Set-Cookie") == (
                f"{name}={client.server.session_value}; HttpOnly; SameSite=Strict; Path=/")
            assert client.get("/").status == 200
            again = client.get(f"/start?key={client.server.launch_key}", cookie=False)
            assert again.status == 403 and again.header("Set-Cookie") is None
        finally:
            client.close()

    def test_another_launchs_cookie_or_a_changed_value_is_refused(self, ledger):
        first, second = UiClient(ledger.path), UiClient(ledger.path)
        try:
            second.sign_in()
            name = f"pf_session_{first.server.server_port}"
            for cookie in (second.cookie, f"{name}={second.server.session_value}",
                           f"{name}={first.server.session_value}x", f"{name}="):
                assert first.get("/", headers=[("Cookie", cookie)]).status == 403
            assert first.get("/", headers=[("Cookie", f"{name}={first.server.session_value}")]
                             ).status == 200
        finally:
            first.close()
            second.close()

    def test_secrets_are_random_and_compared_in_constant_time(self):
        source = Path(ui_server.__file__).read_text()
        assert source.count("secrets.token_urlsafe(32)") == 2
        assert "hmac.compare_digest(" in source
        assert source.count("same_secret(") == 3


class TestReadOnly:  # UB5
    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD",
                                        "TRACE", "CONNECT", "FOO"])
    def test_every_method_but_get_is_refused_and_changes_nothing(self, ledger, client, method,
                                                                 monkeypatch):
        before = unchanged_state(ledger.path)
        opened = []
        monkeypatch.setattr(ui_server, "open_ledger", lambda *args, **kwargs: opened.append(1))
        response = client.request(method, "/", body=b"account=x&confirm=1")
        assert response.status == 405
        assert response.header("Allow") == "GET"
        assert opened == []
        assert unchanged_state(ledger.path) == before

    @pytest.mark.parametrize("origin", ["http://attacker.example", "null",
                                        "http://127.0.0.1:1", "https://127.0.0.1:{port}"])
    def test_a_foreign_origin_is_refused(self, client, origin):
        given = origin.format(port=client.server.server_port)
        assert client.get("/", headers=[("Origin", given)]).status == 403

    def test_this_servers_origin_is_answered_as_the_control(self, client):
        assert client.get("/", headers=[("Origin", client.server.origin)]).status == 200

    def test_pages_leave_the_ledger_unchanged(self, ledger, client):
        before = unchanged_state(ledger.path)
        for target in ("/", "/?account=A", "/monthly", "/monthly?from=2026-01&to=2026-01"):
            assert client.get(target).status == 200, target
        assert unchanged_state(ledger.path) == before

    def test_a_builder_that_tries_to_write_cannot(self, ledger, client, monkeypatch):
        def writing_builder(conn, account_id):
            conn.execute("INSERT INTO account (id, display_name, account_type) "
                         "VALUES ('x', 'x', 'checking')")

        before = unchanged_state(ledger.path)
        monkeypatch.setattr(ui_server, "totals_report_lines", writing_builder)
        response = client.get("/")
        assert response.status == 400
        assert "database error" in response.text
        assert unchanged_state(ledger.path) == before


def every_kind_of_response(client):
    """One response of each status the server sends."""
    key = client.server.launch_key
    return {
        "page": client.get("/"),
        "stylesheet": client.get("/style.css"),
        "redirect": client.get(f"/start?key={key}", cookie=False),
        "signed out": client.get("/", cookie=False),
        "not found": client.get("/no-such-page"),
        "bad address": client.get("/?account=a%20b"),
        "unknown account": client.get("/?account=nope"),
        "method": client.request("POST", "/"),
        "host": client.get("/", host="attacker.example"),
        "unreadable": client.exchange(b"GARBAGE\r\n\r\n"),
    }


class TestHeadersAndAssets:  # UB6
    def test_every_response_carries_the_security_headers(self, ledger):
        client = UiClient(ledger.path)
        try:
            responses = every_kind_of_response(client)
            client.cookie = None
            assert {name: response.status for name, response in responses.items()} == {
                "page": 403, "stylesheet": 403, "redirect": 303, "signed out": 403,
                "not found": 403, "bad address": 403, "unknown account": 403, "method": 405,
                "host": 421, "unreadable": 400}
            client.server.launch_key_used = False
            client.sign_in()
            responses = every_kind_of_response(client)
        finally:
            client.close()
        assert {name: response.status for name, response in responses.items()} == {
            "page": 200, "stylesheet": 200, "redirect": 403, "signed out": 403,
            "not found": 404, "bad address": 400, "unknown account": 400, "method": 405,
            "host": 421, "unreadable": 400}
        for name, response in responses.items():
            for header, value in SECURITY_HEADERS.items():
                assert response.header(header) == value, (name, header)
            assert response.header("Server") == "pf", name

    def test_pages_hold_no_script_inline_style_or_outside_address(self, ledger, client):
        for target in ("/", "/monthly", "/?account=A", "/no-such-page"):
            page = parsed_page(client.get(target).body)
            assert "script" not in page.tags
            assert "style" not in page.tags
            assert "style" not in {name for name, _ in page.attributes}
            assert not any(name.startswith("on") for name, _ in page.attributes)
            assert page.addresses and all(address.startswith("/") and not address.startswith("//")
                                          for address in page.addresses), target
        stylesheet = client.get("/style.css")
        assert stylesheet.header("Content-Type") == "text/css; charset=utf-8"
        assert b"url(" not in stylesheet.body and b"@import" not in stylesheet.body


class TestNothingSaidOrKept:  # UB7
    def test_no_request_writes_to_stdout_or_stderr(self, tmp_path, capfd, monkeypatch):
        ledger = Ledger(tmp_path, capfd)
        ledger.card("a.csv", CAFE)
        files_before = sorted(path.name for path in tmp_path.iterdir())
        client = UiClient(ledger.path)
        capfd.readouterr()
        try:
            client.sign_in()
            every_kind_of_response(client)
            client.exchange(b"GET / HTTP/9.9\r\n\r\n")
            client.exchange(b"GET /" + b"x" * 70000 + b" HTTP/1.1\r\n\r\n")

            def crash(*args, **kwargs):
                raise ValueError(SENTINEL)

            monkeypatch.setattr(ui_server, "totals_report_lines", crash)
            response = client.get("/")
        finally:
            client.close()
        assert response.status == 500
        assert UNEXPECTED_ERROR in response.text and "SENTINEL" not in response.text
        assert capfd.readouterr() == ("", "")
        assert sorted(path.name for path in tmp_path.iterdir()) == files_before

    def test_an_error_reaching_the_server_prints_no_traceback(self, tmp_path, capfd):
        """http.server's default handle_error prints the exception, which could quote data."""
        client = UiClient(Ledger(tmp_path, capfd).path)
        capfd.readouterr()
        try:
            try:
                raise ValueError(SENTINEL)
            except ValueError:
                client.server.handle_error(None, ("127.0.0.1", 50000))
        finally:
            client.close()
        assert capfd.readouterr() == ("", "")

    def test_a_real_ledger_is_checked_on_every_request(self, vault, capsys, monkeypatch):
        real = RealLedger(vault, capsys)
        real.card("a.csv", CAFE)
        asked = place_on_volume(monkeypatch, probe_recording("encrypted_disk_image"))
        client = UiClient(real.path)
        try:
            client.sign_in()
            assert client.get("/").status == 200
            assert client.get("/monthly").status == 200
            assert len(asked.diskutil_about) == 2
            place_on_volume(monkeypatch, probe_recording("unencrypted_disk_image"))
            refused = client.get("/")
        finally:
            client.close()
        assert refused.status == 400
        assert "reported encrypted" in refused.text
        assert parsed_page(refused.body).report_lines == []
        assert b"SYNTHETIC" not in refused.body and b"6.50" not in refused.body


def assert_pages_equal_the_cli(capsys, db, accounts, month_ranges):
    client = UiClient(db)
    client.sign_in()
    try:
        for account_id in (None, *accounts):
            account = f"account={account_id}" if account_id else ""
            option = ["--account", account_id] if account_id else []
            assert page_text(client.get(f"/?{account}").body) == cli_output(
                capsys, "totals", "--db", str(db), *option), account_id
            for first, last in month_ranges:
                query = "&".join(part for part in (account, first and f"from={first}",
                                                   last and f"to={last}") if part)
                months = [*(["--from", first] if first else []), *(["--to", last] if last else [])]
                assert page_text(client.get(f"/monthly?{query}").body) == cli_output(
                    capsys, "report", "monthly", "--db", str(db), *option, *months), query
    finally:
        client.close()


def account_ids(db):
    conn = connect(Path(db), read_only=True)
    try:
        return [row[0] for row in conn.execute("SELECT id FROM account ORDER BY id")]
    finally:
        conn.close()


MONTH_RANGES = [(None, None), ("2026-01", "2026-01"), ("2026-02", None), (None, "2026-02")]


class TestPagesEqualTheCli:  # UB8
    def test_a_ledger_with_duplicates_types_a_one_sided_transfer_and_a_stale_account(
            self, tmp_path, capsys, monkeypatch):
        ledger = build(tmp_path, capsys)
        ledger.rows("a.csv", "R1,2026-01-05,2026-01-06,SYNTHETIC PAY,2500.00,POSTED",
                    "R2,2026-01-20,2026-01-21,SYNTHETIC RENT,-1200.00,POSTED",
                    "R3,2026-02-03,,SYNTHETIC MOVE,-50.00,PENDING")
        ledger.card("c1.csv", CAFE, account="Card")
        ledger.card("c2.csv", CAFE, account="Card")
        with monkeypatch.context() as patch:
            patch.setattr(pipeline, "reconcile_account",
                          lambda *args, **kwargs: ReconcileResult(None, 0))
            ledger.card("s.csv", "02/02/2026,SYNTHETIC SAVED,,50.00", account="S")
        assert_pages_equal_the_cli(capsys, ledger.path, account_ids(ledger.path), MONTH_RANGES)

    def test_a_csv_and_a_pdf_counting_once(self, tmp_path, capsys):
        db = tmp_path / "ledger.db"
        create_database(db)
        conn = connect(db)
        add_account(conn, "card", "credit_card", LAST4)
        conn.commit()
        load_csv(conn, tmp_path, OCTOBER + NOVEMBER, period=("2026-10-01", "2026-11-30"))
        load_pdf(conn, tmp_path, OCTOBER)
        conn.close()
        assert_pages_equal_the_cli(capsys, db, ["card"],
                                   [(None, None), ("2026-10", "2026-10"), ("2026-11", None)])

    @settings(max_examples=15, deadline=None,
              suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
    @given(checking_rows=rows, savings_days=st.lists(st.integers(1, 89), max_size=4),
           one_sided=st.booleans())
    def test_generated_ledgers(self, capsys, checking_rows, savings_days, one_sided):
        with tempfile.TemporaryDirectory() as folder:
            ledger = generated_ledger(Path(folder), capsys, checking_rows, savings_days, one_sided)
            assert_pages_equal_the_cli(capsys, ledger.path, account_ids(ledger.path),
                                       MONTH_RANGES)

    def test_names_holding_html_show_as_text(self, tmp_path, capsys):
        ledger = Ledger(tmp_path, capsys)
        ledger.add_account('<b>S&amp;"q\'</b><script>x</script>', "savings")
        ledger.card("s.csv", CAFE, account='<b>S&amp;"q\'</b><script>x</script>')
        client = UiClient(ledger.path)
        client.sign_in()
        try:
            for target in ("/", "/monthly"):
                page = parsed_page(client.get(target).body)
                assert not {"b", "script"} & set(page.tags), target
        finally:
            client.close()
        assert_pages_equal_the_cli(capsys, ledger.path, account_ids(ledger.path), [(None, None)])

    @pytest.mark.parametrize("target", ["/?account=a%20b", "/?account=%3Cx%3E", "/?account=a&account=b",
                                        "/?unknown=1", "/?account", "/monthly?from=2026-01%00",
                                        "/?account=" + "a" * 101])
    def test_an_address_holding_anything_but_ids_and_months_is_refused_unread(
            self, client, monkeypatch, target):
        opened = []
        monkeypatch.setattr(ui_server, "open_ledger", lambda *args, **kwargs: opened.append(1))
        response = client.get(target)
        assert response.status == 400
        assert ui_server.BAD_ADDRESS in response.text
        assert opened == []

    def test_a_refused_account_or_month_shows_the_clis_refusal(self, ledger, client):
        for target, message in (("/?account=nope", "account not found: nope"),
                                ("/monthly?from=2026-13", "from must be a month as YYYY-MM"),
                                ("/monthly?from=2026-02&to=2026-01", "from is after to")):
            response = client.get(target)
            assert response.status == 400, target
            assert message in response.text, target

    def test_the_server_computes_nothing_itself(self):
        """It imports builders and the CLI's ledger opening and messages, and no computation."""
        import ast

        tree = ast.parse(Path(ui_server.__file__).read_text())
        imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        assert {module for module in imported if module.startswith("personal_finance")} == {
            "personal_finance.cli", "personal_finance.reports.report_text"}
        assert "SELECT" not in Path(ui_server.__file__).read_text()
