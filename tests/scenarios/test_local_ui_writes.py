"""Review decisions from the browser, and the write pipeline that guards them (M17.1, WA1 to
WA5, D-073 point 1).

Each pipeline step refuses alone, on a request correct in every other respect, and the same
request passes as the control. Requests go to the real handler over a socket pair, so nothing
connects to anything.
"""

import html
import re
import shutil
from html.parser import HTMLParser

import pytest
from local_ui_client import UiClient, page_text, parsed_page
from test_decisions import CAFE, Ledger
from test_local_ui import unchanged_state
from test_real_ledger import (  # noqa: F401, vault is a fixture
    RealLedger,
    place_on_volume,
    probe_recording,
    vault,
)

from personal_finance.cli import main
from personal_finance.db.migrate import connect
from personal_finance.reports.report_text import review_item_report
from personal_finance.ui import server as ui_server
from personal_finance.ui import writes

SENTINEL = "SENTINELVALUE"
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")


class FormParser(HTMLParser):
    """Each form's action and its fields' names and values, hidden or typed."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms = []
        self._textarea = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "form":
            self.forms.append({"method": attributes.get("method"),
                               "action": attributes.get("action"), "fields": {}})
        elif tag == "input" and self.forms and attributes.get("name"):
            self.forms[-1]["fields"][attributes["name"]] = attributes.get("value", "")
        elif tag == "textarea" and self.forms:
            self._textarea = attributes["name"]
            self.forms[-1]["fields"][self._textarea] = ""

    def handle_endtag(self, tag):
        if tag == "textarea":
            self._textarea = None

    def handle_data(self, data):
        if self._textarea:
            self.forms[-1]["fields"][self._textarea] += data


def post_forms(body: bytes) -> dict[str, dict[str, str]]:
    parser = FormParser()
    parser.feed(body.decode("utf-8"))
    return {form["action"]: dict(form["fields"]) for form in parser.forms
            if form["method"] == "post"}


def encoded(fields: dict[str, str]) -> bytes:
    """The browser's form encoding, written out here so the test imports nothing of urllib."""
    def part(text):
        return "".join(
            char if char.isalnum() or char in "-_.~" else
            "+" if char == " " else "".join(f"%{byte:02X}" for byte in char.encode("utf-8"))
            for char in text)
    return "&".join(f"{part(name)}={part(value)}" for name, value in fields.items()).encode()


class Browser(UiClient):
    """A signed-in browser that posts as a same-origin form submission does."""

    def __init__(self, path):
        super().__init__(path)
        self.sign_in()

    @property
    def origin(self):
        return self.server.origin

    def form_headers(self, body, **overrides):
        headers = {"Origin": self.origin, "Sec-Fetch-Site": "same-origin",
                   "Sec-Fetch-Mode": "navigate", "Content-Type": writes.FORM_CONTENT_TYPE,
                   "Content-Length": str(len(body))}
        headers.update(overrides)
        return [(name, value) for name, value in headers.items() if value is not None]

    def post(self, target, fields, *, body=None, cookie=True, host="default", **overrides):
        body = encoded(fields) if body is None else body
        return self.raw_post(target, body, self.form_headers(body, **overrides), cookie=cookie,
                             host=host)

    def raw_post(self, target, body, headers, *, cookie=True, host="default", method="POST"):
        lines = [f"{method} {target} HTTP/1.1"]
        if host is not None:
            lines.append(f"Host: {self.host if host == 'default' else host}")
        if cookie and self.cookie:
            lines.append(f"Cookie: {self.cookie}")
        lines += [f"{name}: {value}" for name, value in headers]
        return self.exchange(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body)

    def item_forms(self, item):
        response = self.get(f"/review/item?id={item}")
        assert response.status == 200
        return post_forms(response.body)


def open_items(path):
    conn = connect(path, read_only=True)
    try:
        return [row[0] for row in conn.execute(
            "SELECT id FROM review_issue WHERE status = 'open' ORDER BY id")]
    finally:
        conn.close()


def item_transactions(path, item):
    """The item's transactions, as review show lists them."""
    conn = connect(path, read_only=True)
    try:
        report = review_item_report(conn, item)
    finally:
        conn.close()
    return sorted(re.match(r"Transaction \d+ of \d+: (\S+)", line.text)[1]
                  for line in report.lines if re.match(r"Transaction \d+ of \d+: ", line.text))


def account_id_of(path):
    conn = connect(path, read_only=True)
    try:
        return conn.execute("SELECT id FROM account ORDER BY id").fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def ledger(tmp_path, capsys):
    """A possible duplicate in account A, and a stale-free ledger to decide it on."""
    found = Ledger(tmp_path, capsys)
    found.card("a.csv", CAFE)
    found.card("b.csv", CAFE)
    return found


@pytest.fixture
def browser(ledger):
    found = Browser(ledger.path)
    yield found
    found.close()


def reject_fields(browser, ledger):
    (item,) = open_items(ledger.path)
    fields = browser.item_forms(item)["/review/reject"]
    fields["pairs"] = " ".join(item_transactions(ledger.path, item))
    return fields


UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def stored_values(path):
    conn = connect(path, read_only=True)
    try:
        tables = [name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")]
        return {value for table in tables for row in conn.execute(f'SELECT * FROM "{table}"')
                for value in row}
    finally:
        conn.close()


def canonical_rows(path, decision_ids, known=None):
    """Every table's rows, with the new decision's ID and every stored time masked, so a
    browser decision and a terminal one on copies of one ledger compare equal. Given the values
    stored before, an ID made since (a review item rebuilt by an undo) is masked too."""
    conn = connect(path, read_only=True)
    try:
        tables = [name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        rows = {}
        for table in tables:
            found = []
            for row in conn.execute(f'SELECT * FROM "{table}"'):
                found.append(tuple(
                    "<decision>" if value in decision_ids else
                    "<time>" if isinstance(value, str) and TIMESTAMP.match(value) else
                    "<new>" if known is not None and isinstance(value, str)
                    and UUID.fullmatch(value) and value not in known else value
                    for value in row))
            rows[table] = sorted(found, key=repr)
        return rows
    finally:
        conn.close()


def decision_ids(path):
    conn = connect(path, read_only=True)
    try:
        return {row[0] for row in conn.execute("SELECT id FROM decision")}
    finally:
        conn.close()


class TestEachStepRefusesAlone:  # WA1
    def test_the_control_succeeds_with_a_redirect_to_its_result(self, ledger, browser):
        response = browser.post("/review/reject", reject_fields(browser, ledger))
        assert response.status == 303
        assert response.header("Location").startswith("/result?id=")
        assert len(decision_ids(ledger.path)) == 1

    @pytest.mark.parametrize("host", [None, "localhost", "127.0.0.1", "evil.example"])
    def test_step_1_another_host(self, ledger, browser, host):
        fields = reject_fields(browser, ledger)
        before = unchanged_state(ledger.path)
        assert browser.post("/review/reject", fields, host=host).status == 421
        assert unchanged_state(ledger.path) == before

    def test_step_2_no_session(self, ledger, browser):
        fields = reject_fields(browser, ledger)
        before = unchanged_state(ledger.path)
        response = browser.post("/review/reject", fields, cookie=False)
        assert response.status == 403
        assert unchanged_state(ledger.path) == before

    @pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
    def test_step_3_another_method(self, ledger, browser, method):
        fields = reject_fields(browser, ledger)
        body = encoded(fields)
        before = unchanged_state(ledger.path)
        response = browser.raw_post("/review/reject", body, browser.form_headers(body),
                                    method=method)
        assert response.status == 405
        assert unchanged_state(ledger.path) == before

    @pytest.mark.parametrize("target", ["/review", "/review/reject?x=1", "/review/dismiss",
                                        "/backup", "/"])
    def test_step_3_a_route_off_the_allowlist(self, ledger, browser, target):
        fields = reject_fields(browser, ledger)
        before = unchanged_state(ledger.path)
        assert browser.post(target, fields).status == 404
        assert unchanged_state(ledger.path) == before

    @pytest.mark.parametrize("origin", [None, "null", "http://127.0.0.1:1",
                                        "http://localhost", "https://evil.example"])
    def test_step_4_a_missing_null_or_foreign_origin(self, ledger, browser, origin):
        fields = reject_fields(browser, ledger)
        if origin == "http://127.0.0.1:1" and browser.server.server_port == 1:
            pytest.skip("the port itself")
        before = unchanged_state(ledger.path)
        assert browser.post("/review/reject", fields, Origin=origin).status == 403
        assert unchanged_state(ledger.path) == before

    @pytest.mark.parametrize("header,value", [("Sec-Fetch-Site", "cross-site"),
                                              ("Sec-Fetch-Site", "same-site"),
                                              ("Sec-Fetch-Site", "none"),
                                              ("Sec-Fetch-Mode", "cors"),
                                              ("Sec-Fetch-Mode", "no-cors")])
    def test_step_5_fetch_metadata_other_than_a_same_origin_navigation(self, ledger, browser,
                                                                       header, value):
        fields = reject_fields(browser, ledger)
        before = unchanged_state(ledger.path)
        response = browser.post("/review/reject", fields, **{header.replace("-", "_"): None,
                                                            header: value})
        assert response.status == 403
        assert unchanged_state(ledger.path) == before

    def test_step_5_absent_fetch_metadata_is_accepted_as_the_control(self, ledger, browser):
        fields = reject_fields(browser, ledger)
        response = browser.post("/review/reject", fields, **{"Sec-Fetch-Site": None,
                                                            "Sec-Fetch-Mode": None})
        assert response.status == 303

    @pytest.mark.parametrize("content_type", [None, "text/plain", "multipart/form-data",
                                              "application/json",
                                              "application/x-www-form-urlencoded; charset=x"])
    def test_step_6_another_content_type(self, ledger, browser, content_type):
        fields = reject_fields(browser, ledger)
        before = unchanged_state(ledger.path)
        response = browser.post("/review/reject", fields, **{"Content-Type": content_type})
        assert response.status == 415
        assert unchanged_state(ledger.path) == before

    def test_step_6_a_body_over_the_limit_is_refused_unread(self, ledger, browser):
        fields = reject_fields(browser, ledger)
        fields["pairs"] += " " * writes.MAXIMUM_BODY_BYTES
        before = unchanged_state(ledger.path)
        assert browser.post("/review/reject", fields).status == 413
        assert unchanged_state(ledger.path) == before

    @pytest.mark.parametrize("overrides", [{"Content-Length": None},
                                           {"Transfer-Encoding": "chunked"},
                                           {"Content-Length": "-1"},
                                           {"Content-Length": "12x"}])
    def test_step_6_a_missing_length_or_a_transfer_encoding(self, ledger, browser, overrides):
        fields = reject_fields(browser, ledger)
        before = unchanged_state(ledger.path)
        assert browser.post("/review/reject", fields, **overrides).status == 413
        assert unchanged_state(ledger.path) == before

    @pytest.mark.parametrize("change", ["repeat", "unknown", "missing", "bad_escape",
                                        "bad_utf8", "too_many", "option_like", "no_equals"])
    def test_step_7_a_body_not_parsed_strictly(self, ledger, browser, change):
        fields = reject_fields(browser, ledger)
        body = encoded(fields)
        if change == "repeat":
            body += b"&pairs=x"
        elif change == "unknown":
            body += b"&extra=1"
        elif change == "missing":
            body = encoded({name: value for name, value in fields.items() if name != "pairs"})
        elif change == "bad_escape":
            body += b"%zz"
        elif change == "bad_utf8":
            body = body.replace(b"pairs=", b"pairs=%FF")
        elif change == "too_many":
            body += b"".join(b"&f%d=1" % number for number in range(writes.MAXIMUM_FIELD_COUNT))
        elif change == "option_like":
            body = encoded({**fields, "item": "--db"})
        elif change == "no_equals":
            body += b"&lonely"
        before = unchanged_state(ledger.path)
        assert browser.post("/review/reject", fields, body=body).status == 400
        assert unchanged_state(ledger.path) == before

    @pytest.mark.parametrize("pairs", ["", "one", "a b c", "a -b", "a\tb\nc"])
    def test_step_9_a_malformed_list_is_refused_before_any_command(self, ledger, browser,
                                                                     pairs):
        fields = reject_fields(browser, ledger)
        fields["pairs"] = pairs
        before = unchanged_state(ledger.path)
        assert browser.post("/review/reject", fields).status == 400
        assert unchanged_state(ledger.path) == before


class TestFormToken:  # WA2
    def test_a_missing_or_wrong_token(self, ledger, browser):
        fields = reject_fields(browser, ledger)
        before = unchanged_state(ledger.path)
        assert browser.post("/review/reject", {**fields, "form_token": "0" * 64}).status == 403
        assert browser.post("/review/reject", {**fields, "form_token": ""}).status == 403
        missing = {name: value for name, value in fields.items() if name != "form_token"}
        assert browser.post("/review/reject", missing).status == 400
        assert unchanged_state(ledger.path) == before

    @pytest.mark.parametrize("field", ["revision", "account", "item"])
    def test_a_changed_hidden_field_breaks_the_token(self, ledger, browser, field):
        fields = reject_fields(browser, ledger)
        fields[field] = fields[field][:-1] + ("A" if fields[field][-1] != "A" else "B")
        before = unchanged_state(ledger.path)
        assert browser.post("/review/reject", fields).status == 403
        assert unchanged_state(ledger.path) == before

    def test_a_token_for_another_route(self, ledger, browser):
        fields = reject_fields(browser, ledger)
        (item,) = open_items(ledger.path)
        confirm = browser.item_forms(item)["/review/confirm"]
        fields["form_token"] = confirm["form_token"]
        before = unchanged_state(ledger.path)
        assert browser.post("/review/reject", fields).status == 403
        assert unchanged_state(ledger.path) == before

    def test_another_sessions_token(self, ledger, browser):
        fields = reject_fields(browser, ledger)
        other = Browser(ledger.path)
        try:
            other_fields = reject_fields(other, ledger)
            before = unchanged_state(ledger.path)
            assert browser.post("/review/reject", {**fields,
                                                   "form_token": other_fields["form_token"]}
                                ).status == 403
            assert unchanged_state(ledger.path) == before
        finally:
            other.close()

    def test_a_token_is_single_use_even_when_its_write_was_refused(self, ledger, browser):
        fields = reject_fields(browser, ledger)
        fields["pairs"] = "aaaa bbbb"
        refused = browser.post("/review/reject", fields)
        assert refused.status == 409
        before = unchanged_state(ledger.path)
        fields["pairs"] = " ".join(item_transactions(ledger.path, open_items(ledger.path)[0]))
        assert browser.post("/review/reject", fields).status == 403
        assert unchanged_state(ledger.path) == before

    def test_tokens_are_hmac_sha256_compared_in_constant_time(self, monkeypatch):
        compared = []
        original = writes.hmac.compare_digest
        monkeypatch.setattr(writes.hmac, "compare_digest",
                            lambda left, right: compared.append(1) or original(left, right))
        secret = b"k" * 32
        token = writes.form_token(secret, "/review/undo", "d", "a", ("r",))
        assert len(token) == 64
        form = {"form_token": token, "decision": "d", "account": "a", "revision": "r"}
        assert writes.refuse_form_token(form, "/review/undo", secret, set()) is None
        assert compared


class TestTheBrowserDecidesAsTheTerminal:  # WA3
    @pytest.mark.parametrize("route", ["/review/reject", "/review/confirm"])
    def test_the_same_rows_as_the_cli_decision(self, ledger, tmp_path, capsys, route):
        (item,) = open_items(ledger.path)
        transactions = item_transactions(ledger.path, item)
        copy = tmp_path / "copy.db"
        shutil.copyfile(ledger.path, copy)
        account = account_id_of(ledger.path)
        revision = ledger.revision(item)
        if route == "/review/reject":
            words = ["review", "reject", item, "--db", str(copy), "--account", account,
                     "--revision", revision, "--pair", *transactions]
        else:
            words = ["review", "confirm", item, "--db", str(copy), "--account", account,
                     "--revision", revision, "--group", *transactions]
        capsys.readouterr()
        assert main(words) == 0
        printed = capsys.readouterr().out

        browser = Browser(ledger.path)
        try:
            fields = browser.item_forms(item)[route]
            fields["pairs" if route == "/review/reject" else "groups"] = " ".join(transactions)
            response = browser.post(route, fields)
            assert response.status == 303
            result = browser.get(response.header("Location"))
        finally:
            browser.close()
        (made,) = decision_ids(ledger.path)
        (made_by_cli,) = decision_ids(copy)
        assert canonical_rows(ledger.path, {made}) == canonical_rows(copy, {made_by_cli})
        shown = page_text(result.body)
        assert shown == printed.replace(made_by_cli, made)

    def test_undo_from_the_result_page_equals_the_cli_undo(self, ledger, tmp_path, browser):
        fields = reject_fields(browser, ledger)
        response = browser.post("/review/reject", fields)
        result = browser.get(response.header("Location"))
        undo = post_forms(result.body)["/review/undo"]
        (made,) = decision_ids(ledger.path)
        assert undo["decision"] == made
        copy = tmp_path / "copy.db"
        shutil.copyfile(ledger.path, copy)
        known = stored_values(copy)
        assert main(["review", "undo", made, "--db", str(copy), "--account", undo["account"],
                     "--revision", undo["revision"]]) == 0
        response = browser.post("/review/undo", undo)
        assert response.status == 303
        assert canonical_rows(ledger.path, {made}, known) == canonical_rows(copy, {made}, known)

    def test_a_stale_revision_refuses_with_the_clis_message(self, ledger, browser, capsys):
        fields = reject_fields(browser, ledger)
        ledger.card("c.csv", CAFE)  # an import changes the item, so its revision
        before = unchanged_state(ledger.path)
        response = browser.post("/review/reject", fields)
        assert response.status == 409
        capsys.readouterr()
        assert main(["review", "reject", fields["item"], "--db", ledger.db, "--account",
                     fields["account"], "--revision", fields["revision"], "--pair",
                     *fields["pairs"].split()]) == 2
        message = capsys.readouterr().err.removeprefix("Error: ").strip()
        assert message and message in html.unescape(response.text)
        assert unchanged_state(ledger.path) == before

    def test_a_stale_account_refuses_with_the_clis_message_and_never_reconciles(
            self, ledger, browser, capsys):
        fields = reject_fields(browser, ledger)
        conn = connect(ledger.path)
        with conn:
            conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ?", ("0" * 64,))
        conn.close()
        before = unchanged_state(ledger.path)
        response = browser.post("/review/reject", fields)
        assert response.status == 409
        assert "reconcile" in response.text
        assert unchanged_state(ledger.path) == before


class TestPostRedirectGet:  # WA4
    def test_reloading_the_result_writes_nothing_and_a_resubmit_refuses(self, ledger, browser):
        fields = reject_fields(browser, ledger)
        response = browser.post("/review/reject", fields)
        location = response.header("Location")
        after = unchanged_state(ledger.path)
        assert browser.get(location).status == 200
        assert browser.get(location).status == 200
        assert unchanged_state(ledger.path) == after
        assert browser.post("/review/reject", fields).status == 403
        assert unchanged_state(ledger.path) == after

    def test_an_unknown_result_is_not_found(self, browser):
        assert browser.get("/result?id=nothing").status == 404

    def test_no_refusal_repeats_a_value_it_was_given(self, ledger, browser):
        fields = reject_fields(browser, ledger)
        hostile = {**fields, "pairs": f"{SENTINEL}1 {SENTINEL}2"}
        bodies = [
            browser.post("/review/reject", hostile).text,
            browser.post("/review/reject", {**hostile, SENTINEL: "x"}).text,
            browser.post(f"/{SENTINEL}", hostile).text,
            browser.post("/review/reject", hostile, Origin=f"http://{SENTINEL}").text,
            browser.post("/review/reject", {**hostile, "form_token": SENTINEL}).text,
        ]
        for body in bodies:
            assert SENTINEL not in body

    def test_a_get_with_write_parameters_never_writes(self, ledger, browser):
        fields = reject_fields(browser, ledger)
        before = unchanged_state(ledger.path)
        query = "&".join(f"{name}={value}" for name, value in fields.items() if name != "pairs")
        assert browser.get(f"/review/reject?{query}").status == 404
        assert unchanged_state(ledger.path) == before


class TestGateAndSilence:  # WA5
    def test_each_post_opens_its_write_connection_through_the_gate(self, ledger, browser,
                                                                    monkeypatch):
        opened = []
        original = main.__globals__["open_ledger"]

        def recording_open(path, read_only=False):
            opened.append(read_only)
            return original(path, read_only=read_only)

        monkeypatch.setitem(main.__globals__, "open_ledger", recording_open)
        response = browser.post("/review/reject", reject_fields(browser, ledger))
        assert response.status == 303
        assert False in opened

    def test_a_real_ledger_whose_probe_fails_refuses_with_no_write(self, vault, capsys,
                                                                   monkeypatch):
        real = RealLedger(vault, capsys)
        real.card("a.csv", CAFE)
        real.card("b.csv", CAFE)
        place_on_volume(monkeypatch, probe_recording("encrypted_disk_image"))
        browser = Browser(real.path)
        try:
            fields = reject_fields(browser, real)
            before = unchanged_state(real.path)
            place_on_volume(monkeypatch, probe_recording("unencrypted_disk_image"))
            response = browser.post("/review/reject", fields)
        finally:
            browser.close()
        assert response.status == 409
        assert "reported encrypted" in response.text
        assert unchanged_state(real.path) == before

    def test_no_request_writes_to_stdout_or_stderr(self, tmp_path, capfd):
        ledger = Ledger(tmp_path, capfd)
        ledger.card("a.csv", CAFE)
        ledger.card("b.csv", CAFE)
        browser = Browser(ledger.path)
        capfd.readouterr()
        fields = reject_fields(browser, ledger)
        browser.post("/review/reject", {**fields, "pairs": "aaaa bbbb"})
        fields = reject_fields(browser, ledger)
        browser.post("/review/reject", fields)
        browser.post("/review/reject", fields)
        browser.close()
        captured = capfd.readouterr()
        assert captured.out == "" and captured.err == ""

    def test_the_route_table_is_the_allowlist(self):
        assert set(writes.WRITE_ROUTES) == {"/review/reject", "/review/confirm", "/review/undo"}

    def test_an_unresolved_record_keeps_its_terminal_commands_and_no_form(self, tmp_path,
                                                                         capsys):
        ledger = Ledger(tmp_path, capsys)
        ledger.checking("a.csv", "S-2,not a date,,SYNTHETIC BAD,-3.00,POSTED")
        (item,) = open_items(ledger.path)
        browser = Browser(ledger.path)
        try:
            response = browser.get(f"/review/item?id={item}")
        finally:
            browser.close()
        assert post_forms(response.body) == {}
        assert "pf review dismiss" in response.text
        assert parsed_page(response.body).tags.count("form") == 0
