"""The local UI's import results, transactions, review queue and review item pages (M8.3, UC1 to
UC4, D-062). Read-only: the item page shows the terminal commands that decide it, and no form.
"""

import re

import pytest
from local_ui_client import UiClient, page_text, parsed_page
from test_decisions import CAFE, CHECKING_HEADER, Ledger
from test_local_ui import account_ids, assert_pages_equal_the_cli, cli_output

from personal_finance.db.migrate import connect
from personal_finance.ui import server as ui_server

PAGES = ("/documents", "/transactions", "/review")
COMMAND_OF_PAGE = {"/documents": ("documents",), "/transactions": ("transactions",),
                   "/review": ("review", "list")}
# A timestamp, as stored for creation, decisions and links, as against a date.
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def open_client(path):
    client = UiClient(path)
    client.sign_in()
    return client


def open_items(path):
    conn = connect(path, read_only=True)
    try:
        return [row[0] for row in conn.execute(
            "SELECT id FROM review_issue WHERE status = 'open' ORDER BY id")]
    finally:
        conn.close()


def assert_review_pages_equal_the_cli(capsys, path):
    client = open_client(path)
    try:
        for page, command in COMMAND_OF_PAGE.items():
            assert page_text(client.get(page).body) == cli_output(
                capsys, *command, "--db", str(path)), page
        for item in open_items(path):
            assert page_text(client.get(f"/review/item?id={item}").body) == cli_output(
                capsys, "review", "show", "--db", str(path), item), item
    finally:
        client.close()


@pytest.fixture
def ledger(tmp_path, capsys):
    """A possible duplicate, a reliable-ID conflict, and an unresolved row, in account A."""
    found = Ledger(tmp_path, capsys)
    found.card("a.csv", CAFE)
    found.card("b.csv", CAFE)
    found.checking("c.csv", "S-1,2026-01-05,,SYNTHETIC SHOP,-1.00,POSTED")
    found.checking("d.csv", "S-1,2026-01-05,,SYNTHETIC SHOP,-2.00,POSTED",
                   "S-2,not a date,,SYNTHETIC BAD,-3.00,POSTED")
    return found


class TestPagesEqualTheCli:  # UC1
    def test_each_page_equals_its_command(self, ledger, capsys):
        assert len(open_items(ledger.path)) == 3
        assert_review_pages_equal_the_cli(capsys, ledger.path)

    def test_a_ledger_with_nothing_imported(self, tmp_path, capsys):
        assert_review_pages_equal_the_cli(capsys, Ledger(tmp_path, capsys).path)

    def test_the_m8_2_pages_still_equal_the_cli_here(self, ledger, capsys):
        assert_pages_equal_the_cli(capsys, ledger.path, account_ids(ledger.path), [(None, None)])

    def test_each_queue_item_links_to_its_page(self, ledger):
        client = open_client(ledger.path)
        try:
            queue = parsed_page(client.get("/review").body)
            linked = [address for address in queue.addresses
                      if address.startswith("/review/item?id=")]
            assert sorted(address.split("=", 1)[1] for address in linked) == open_items(
                ledger.path)
            for address in linked:
                assert client.get(address).status == 200, address
        finally:
            client.close()

    def test_every_page_is_in_the_navigation(self, ledger):
        client = open_client(ledger.path)
        try:
            navigation = parsed_page(client.get("/").body).addresses
        finally:
            client.close()
        assert {"/", "/monthly", *PAGES} <= set(navigation)


HOSTILE = '"<script>alert(1)</script> & \'q\' \x1b[2J ‮\nCoverage evidence:\n  forged"'


class TestEscaping:  # UC2
    @pytest.fixture
    def hostile(self, tmp_path, capsys):
        found = Ledger(tmp_path, capsys)
        found.checking("a.csv", f"S-1,2026-01-05,,{HOSTILE},-1.00,POSTED")
        found.checking("b.csv", "S-1,2026-01-05,,SYNTHETIC,-2.00,POSTED")
        return found

    def test_a_hostile_cell_shows_as_the_cli_shows_it_and_adds_no_element(self, hostile,
                                                                           capsys):
        (item,) = open_items(hostile.path)
        assert_review_pages_equal_the_cli(capsys, hostile.path)
        client = open_client(hostile.path)
        try:
            for target in (*PAGES, f"/review/item?id={item}"):
                body = client.get(target).body
                page = parsed_page(body)
                assert "script" not in page.tags, target
                assert not any(name.startswith("on") for name, _ in page.attributes), target
                assert b"<script" not in body and b"\x1b" not in body, target
                assert "‮".encode() not in body, target
            item_page = page_text(client.get(f"/review/item?id={item}").body)
        finally:
            client.close()
        assert "<script>alert(1)</script> & 'q' \\x1b[2J \\u202e\\nCoverage evidence:" in item_page
        assert item_page.count("\nCoverage evidence:\n") == 1

    def test_a_file_name_the_cli_prints_as_typed_is_escaped_here(self, tmp_path, capsys):
        """D-037 shows file names as typed. The page escapes a control or format character in
        one, so this is the one way a page's text can differ from the CLI's."""
        ledger = Ledger(tmp_path, capsys)
        path = ledger.write("a‮x.csv", CHECKING_HEADER,
                            ["S-1,2026-01-05,,SYNTHETIC,-1.00,POSTED", "S-1,bad,,X,-1.00,POSTED"])
        ledger.load_path(path, layout="synthetic_checking_v1")
        client = open_client(ledger.path)
        try:
            for page, command in COMMAND_OF_PAGE.items():
                printed = cli_output(capsys, *command, "--db", ledger.db)
                assert page_text(client.get(page).body) == printed.replace("‮", "\\u202e")
        finally:
            client.close()


class TestItemPage:  # UC3
    def test_it_shows_what_deciding_it_in_the_terminal_needs_and_no_form(self, ledger):
        conn = connect(ledger.path, read_only=True)
        (account_id,) = conn.execute("SELECT id FROM account").fetchone()
        conn.close()
        client = open_client(ledger.path)
        try:
            for item in open_items(ledger.path):
                response = client.get(f"/review/item?id={item}")
                page = parsed_page(response.body)
                assert "form" not in page.tags and "input" not in page.tags
                revision = ledger.revision(item)
                common = f"{item} --db {ledger.db} --account {account_id} --revision {revision}"
                assert response.text.count(common) == 2
                assert ("pf review dismiss" in response.text) == (
                    "unresolved_record" in page_text(response.body))
        finally:
            client.close()

    def test_a_ledger_path_holding_html_shows_as_text(self, tmp_path, capsys):
        folder = tmp_path / '<b>"x\'&'
        folder.mkdir()
        ledger = Ledger(folder, capsys)
        ledger.card("a.csv", CAFE)
        ledger.card("b.csv", CAFE)
        (item,) = open_items(ledger.path)
        client = open_client(ledger.path)
        try:
            response = client.get(f"/review/item?id={item}")
        finally:
            client.close()
        assert "b" not in parsed_page(response.body).tags
        assert f"--db {ledger.db} --account" in parsed_page(response.body).hint_text

    def test_an_unknown_item_repeats_nothing_it_was_given(self, ledger):
        client = open_client(ledger.path)
        try:
            for item in ("SENTINELITEM", ""):
                response = client.get(f"/review/item?id={item}")
                assert response.status == 404
                assert ui_server.ITEM_NOT_FOUND in response.text
                assert "SENTINEL" not in response.text
        finally:
            client.close()

    def test_a_stale_accounts_warning_shows_as_in_the_cli(self, ledger, capsys):
        # As after a change of matching rules (D-033): the account was reconciled under others.
        conn = connect(ledger.path)
        with conn:
            conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ?", ("0" * 64,))
        conn.close()
        assert_review_pages_equal_the_cli(capsys, ledger.path)
        client = open_client(ledger.path)
        try:
            item = open_items(ledger.path)[0]
            assert "evidence may be out of date" in client.get(f"/review/item?id={item}").text
        finally:
            client.close()


class TestNoCreationTimestamps:  # UC4
    def test_no_page_shows_one_on_a_ledger_with_a_legacy_identity(self, tmp_path, capsys):
        """F2: a revived ID retired before migration 0004 has only an approximate creation time,
        so no page may show creation times until a stored marker exists."""
        ledger = Ledger(tmp_path, capsys)
        for number, posted in enumerate(("", "2026-01-10", "2026-01-11")):
            status = "POSTED" if posted else ""
            ledger.checking(f"{number}.csv", f"S-1,2026-01-09,{posted},SYNTHETIC CAFE,-5.00,"
                                             f"{status}")
            if number == 1:
                conn = connect(ledger.path)
                retired = conn.execute(
                    "SELECT from_transaction_id FROM transaction_link_history").fetchone()[0]
                conn.executescript("""DROP TRIGGER transaction_identity_history_no_delete;
                                      DELETE FROM transaction_identity_history;""")
                conn.close()
        assert TIMESTAMP.search(ledger.run("trace", retired)[1]), "the control: trace shows one"

        client = open_client(ledger.path)
        try:
            targets = ["/", "/monthly", *PAGES,
                       *(f"/review/item?id={item}" for item in open_items(ledger.path))]
            for target in targets:
                response = client.get(target)
                assert response.status == 200, target
                assert not TIMESTAMP.search(response.text), target
        finally:
            client.close()
