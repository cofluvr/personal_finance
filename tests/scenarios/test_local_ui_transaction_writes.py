"""The transaction page, and transaction and record writes from the browser (M17.2a, WB1 to
WB3, D-073 points 2 and 3, the M17.2 slice plan).

Each browser write is compared with the same CLI command on a copy of the ledger: the same rows,
apart from new IDs and times, and the same printed lines. Refusals are the CLI's.
"""

import html
import re
import shutil

import pytest
from local_ui_client import page_text, parsed_page
from test_decisions import CAFE, Ledger
from test_local_ui import cli_output, unchanged_state
from test_separations import SeparationLedger, merged_two
from test_local_ui_writes import Browser, UUID, canonical_rows, post_forms, stored_values

from personal_finance.cli import main
from personal_finance.db.migrate import connect
from personal_finance.ui import server as ui_server
from personal_finance.ui import writes

ALLOWLIST = {
    "/review/reject", "/review/confirm", "/review/undo", "/review/complete", "/review/dismiss",
    "/transaction/classify", "/transaction/categorize", "/transaction/correct",
    "/transaction/separate", "/transaction/one-sided", "/transaction/tag",
    "/transaction/tag-none", "/setting/buffer-set", "/setting/buffer-undo", "/account/liquidity-set",
    "/account/liquidity-undo", "/obligation/covers-loan", "/obligation/covers-fund",
    "/obligation/uncover",
}
# Terminal only (D-073 point 2, and the M17.2 slice plan point 7): no route runs these.
TERMINAL_ONLY = [
    ("init",), ("migrate",), ("import",), ("reconcile",), ("account", "add"),
    ("account", "link"), ("backup",), ("archive",), ("storage",), ("export",), ("sync",),
    ("review", "allocate"), ("review", "consume"), ("review", "breakdown"),
    ("review", "transfer", "match"), ("review", "coverage"), ("category", "rule"),
    ("balance", "record"), ("review", "classification", "undo"),
]


def account_id(ledger, name):
    conn = connect(ledger.path, read_only=True)
    try:
        return conn.execute("SELECT id FROM account WHERE display_name = ?", (name,)).fetchone()[0]
    finally:
        conn.close()


def transaction_ids(ledger):
    code, out, err = ledger.run("transactions")
    assert code == 0, err
    return [line.split()[0] for line in out.splitlines() if UUID.match(line.split()[0])]


def transaction_page(browser, transaction_id):
    response = browser.get(f"/transaction?id={transaction_id}")
    assert response.status == 200, response.text
    return response


def revision_of(ledger, transaction_id):
    code, out, err = ledger.run("review", "transaction", "show", transaction_id)
    assert code == 0, err
    return re.search(r"^  Revision: (\S+)$", out, re.MULTILINE)[1]


def new_values(before, path):
    return {value for value in stored_values(path) - before
            if isinstance(value, str) and UUID.fullmatch(value)}


def assert_browser_equals_cli(ledger, tmp_path, capsys, route, fields, cli_words,
                              forms=None):
    """Post the page's form for route with fields typed, and run cli_words on a copy made
    first. The rows, apart from new IDs and times, and the printed lines are the same."""
    copy = tmp_path / "copy.db"
    shutil.copyfile(ledger.path, copy)
    before = stored_values(ledger.path)
    capsys.readouterr()
    assert main([*cli_words, "--db", str(copy)]) == 0
    printed = capsys.readouterr().out
    browser = Browser(ledger.path)
    try:
        form = (forms or (lambda found: found))(browser)[route]
        response = browser.post(route, {**form, **fields})
        assert response.status == 303, html.unescape(response.text)
        shown = page_text(browser.get(response.header("Location")).body)
    finally:
        browser.close()
    made_here, made_there = new_values(before, ledger.path), new_values(before, copy)
    assert len(made_here) == len(made_there)
    assert canonical_rows(ledger.path, made_here, before) == canonical_rows(copy, made_there,
                                                                            before)
    for here, there in zip(sorted(made_here), sorted(made_there)):
        printed = printed.replace(there, here)
    assert sorted(shown.splitlines()) == sorted(printed.splitlines()) or all(
        UUID.sub("<id>", left) == UUID.sub("<id>", right)
        for left, right in zip(shown.splitlines(), printed.splitlines()))


@pytest.fixture
def ledger(tmp_path, capsys):
    """One purchase in account A, and account B for transfers."""
    found = Ledger(tmp_path, capsys)
    found.card("a.csv", CAFE)
    found.add_account("B")
    return found


def page_forms(transaction_id):
    return lambda browser: post_forms(transaction_page(browser, transaction_id).body)


class TestTheTransactionPage:  # WB1
    def test_the_list_links_each_transaction_to_a_page_equal_to_its_command(self, ledger,
                                                                            capsys):
        browser = Browser(ledger.path)
        try:
            listed = parsed_page(browser.get("/transactions").body).addresses
            linked = [address.split("=", 1)[1] for address in listed
                      if address.startswith("/transaction?id=")]
            assert linked == transaction_ids(ledger) and linked
            for transaction_id in linked:
                assert page_text(transaction_page(browser, transaction_id).body) == cli_output(
                    capsys, "review", "transaction", "show", transaction_id, "--db", ledger.db)
        finally:
            browser.close()

    def test_an_unknown_transaction_repeats_nothing(self, ledger):
        browser = Browser(ledger.path)
        try:
            for transaction_id in ("SENTINELTRANSACTION", ""):
                response = browser.get(f"/transaction?id={transaction_id}")
                assert response.status == 404
                assert "SENTINEL" not in response.text
        finally:
            browser.close()

    def test_its_forms_carry_its_account_and_revision(self, ledger):
        (transaction_id,) = transaction_ids(ledger)
        browser = Browser(ledger.path)
        try:
            forms = page_forms(transaction_id)(browser)
        finally:
            browser.close()
        assert set(forms) == {"/transaction/classify", "/transaction/categorize",
                              "/transaction/correct", "/transaction/separate",
                              "/transaction/one-sided", "/transaction/tag",
                              "/transaction/tag-none"}
        for form in forms.values():
            assert form["transaction"] == transaction_id
            assert form["revision"] == revision_of(ledger, transaction_id)


class TestWritesEqualTheCli:  # WB3
    def test_classify_then_supersede(self, ledger, tmp_path, capsys):
        (transaction_id,) = transaction_ids(ledger)
        account = account_id(ledger, "A")
        assert_browser_equals_cli(
            ledger, tmp_path, capsys, "/transaction/classify", {"type": "fee"},
            ["review", "classify", transaction_id, "--account", account, "--revision",
             revision_of(ledger, transaction_id), "--type", "fee"],
            page_forms(transaction_id))
        code, out, _ = ledger.run("review", "classifications")
        (classification,) = re.findall(r"^Classification (\S+):", out, re.MULTILINE)
        code, out, _ = ledger.run("review", "classification", "show", classification)
        superseded_revision = re.search(r"^\s*Revision: (\S+)$", out, re.MULTILINE)[1]
        browser = Browser(ledger.path)
        try:
            form = page_forms(transaction_id)(browser)["/transaction/classify"]
        finally:
            browser.close()
        assert (form["supersedes"], form["supersedes_revision"]) == (classification,
                                                                     superseded_revision)
        assert_browser_equals_cli(
            ledger, tmp_path, capsys,
            "/transaction/classify", {"type": "purchase"},
            ["review", "classify", transaction_id, "--account", account, "--revision",
             revision_of(ledger, transaction_id), "--type", "purchase", "--supersedes",
             classification, "--supersedes-revision", superseded_revision],
            page_forms(transaction_id))

    def test_categorize(self, ledger, tmp_path, capsys):
        (transaction_id,) = transaction_ids(ledger)
        account = account_id(ledger, "A")
        assert ledger.run("category", "add", "Coffee & <tea>")[0] == 0
        assert ledger.run("review", "classify", transaction_id, "--account", account,
                          "--revision", revision_of(ledger, transaction_id), "--type",
                          "purchase")[0] == 0
        assert_browser_equals_cli(
            ledger, tmp_path, capsys, "/transaction/categorize", {"category": "Coffee & <tea>"},
            ["review", "categorize", transaction_id, "--account", account, "--revision",
             revision_of(ledger, transaction_id), "--category", "Coffee & <tea>"],
            page_forms(transaction_id))

    @pytest.mark.parametrize("field,value", [("amount", "-7.25"),
                                             ("description", "-- a value like an option"),
                                             ("transaction_date", "2026-01-04")])
    def test_correct_one_field(self, ledger, tmp_path, capsys, field, value):
        (transaction_id,) = transaction_ids(ledger)
        account = account_id(ledger, "A")

        def the_fields_form(browser):
            response = transaction_page(browser, transaction_id)
            parser_forms = [form for form in all_post_forms(response.body)
                            if form["action"] == "/transaction/correct"
                            and form["fields"]["field"] == field]
            return {"/transaction/correct": parser_forms[0]["fields"]}

        assert_browser_equals_cli(
            ledger, tmp_path, capsys, "/transaction/correct", {"value": value},
            ["review", "correct", transaction_id, "--account", account, "--revision",
             revision_of(ledger, transaction_id), "--field", field, f"--value={value}"],
            the_fields_form)

    def test_tag_then_say_none_superseding(self, ledger, tmp_path, capsys):
        (transaction_id,) = transaction_ids(ledger)
        for name in ("Trip", "Work"):
            assert ledger.run("tag", "add", name)[0] == 0
        account = account_id(ledger, "A")
        assert_browser_equals_cli(
            ledger, tmp_path, capsys, "/transaction/tag", {"tags": "Work,Trip"},
            ["review", "tag", transaction_id, "--account", account, "--revision",
             revision_of(ledger, transaction_id), "--tags", "Work,Trip"],
            page_forms(transaction_id))
        out = ledger.run("review", "transaction", "show", transaction_id)[1]
        statement = re.search(r"^    Tag statement (\S+): ", out, re.MULTILINE)[1]
        superseded = re.search(r"^\s*Revision: (\S+)$",
                               ledger.run("review", "tagging", "show", statement)[1],
                               re.MULTILINE)[1]
        assert_browser_equals_cli(
            ledger, tmp_path, capsys, "/transaction/tag-none", {},
            ["review", "tag", transaction_id, "--account", account, "--revision",
             revision_of(ledger, transaction_id), "--none", "--supersedes", statement,
             "--supersedes-revision", superseded],
            page_forms(transaction_id))

    def test_a_one_sided_transfer(self, ledger, tmp_path, capsys):
        (transaction_id,) = transaction_ids(ledger)
        account = account_id(ledger, "A")
        assert ledger.run("review", "classify", transaction_id, "--account", account,
                          "--revision", revision_of(ledger, transaction_id), "--type",
                          "transfer")[0] == 0
        assert_browser_equals_cli(
            ledger, tmp_path, capsys, "/transaction/one-sided",
            {"counterpart_account": account_id(ledger, "B")},
            ["review", "transfer", "one-sided", transaction_id, "--account", account,
             "--revision", revision_of(ledger, transaction_id), "--counterpart-account",
             account_id(ledger, "B")],
            page_forms(transaction_id))

    def test_separate_records_merged_by_coverage(self, tmp_path, capsys):
        ledger = SeparationLedger(tmp_path, capsys)
        transaction_id, records = merged_two(ledger)
        assert len(records) == 2
        assert_browser_equals_cli(
            ledger, tmp_path, capsys, "/transaction/separate",
            {"groups": "\n".join(records.values())},
            ["review", "separate", transaction_id, "--account", "A", "--revision",
             ledger.merge_revision(transaction_id),
             *(word for record in records.values() for word in ("--group", record))],
            page_forms(transaction_id))


class TestRecordWrites:  # WB3
    @pytest.fixture
    def unresolved(self, tmp_path, capsys):
        found = Ledger(tmp_path, capsys)
        found.checking("a.csv", "S-2,not a date,,SYNTHETIC BAD,-3.00,POSTED")
        return found

    def item_forms(self, ledger):
        (item,) = ledger.items()
        return lambda browser: browser.item_forms(item)

    def test_complete(self, unresolved, tmp_path, capsys):
        (item,) = unresolved.items()
        assert_browser_equals_cli(
            unresolved, tmp_path, capsys, "/review/complete",
            {"transaction_date": "2026-01-05", "amount": "", "posting_date": "",
             "description": ""},
            ["review", "complete", item, "--account", account_id(unresolved, "A"), "--revision",
             unresolved.revision(item), "--transaction-date", "2026-01-05"],
            self.item_forms(unresolved))

    def test_dismiss(self, unresolved, tmp_path, capsys):
        (item,) = unresolved.items()
        assert_browser_equals_cli(
            unresolved, tmp_path, capsys, "/review/dismiss", {},
            ["review", "dismiss", item, "--account", account_id(unresolved, "A"), "--revision",
             unresolved.revision(item)],
            self.item_forms(unresolved))


def all_post_forms(body):
    from test_local_ui_writes import FormParser

    parser = FormParser()
    parser.feed(body.decode("utf-8"))
    return [form for form in parser.forms if form["method"] == "post"]


class TestValuesAndBinding:  # WB3, the slice plan's points 1, 2 and 5
    @pytest.fixture
    def form(self, ledger):
        (transaction_id,) = transaction_ids(ledger)
        browser = Browser(ledger.path)
        response = transaction_page(browser, transaction_id)
        forms = [found["fields"] for found in all_post_forms(response.body)
                 if found["action"] == "/transaction/correct"
                 and found["fields"]["field"] == "description"]
        yield browser, forms[0]
        browser.close()

    @pytest.mark.parametrize("value", ["a\x1bb", "a‮b", "a\nb", " leading", "x" * 201,
                                       ""])
    def test_text_that_could_hide_anything_is_refused_before_any_command(self, ledger, form,
                                                                         value, monkeypatch):
        browser, fields = form
        ran = []
        monkeypatch.setattr(ui_server, "main", lambda words: ran.append(words) or 0)
        response = browser.post("/transaction/correct", {**fields, "value": value})
        assert response.status == 400 and ran == []

    def test_printable_text_of_the_limit_is_accepted_as_the_control(self, ledger, form):
        browser, fields = form
        response = browser.post("/transaction/correct", {**fields, "value": "é" * 200})
        assert response.status == 303

    @pytest.mark.parametrize("field,value", [("field", "amount"), ("supersedes", "abc"),
                                             ("transaction", "abc")])
    def test_every_hidden_field_is_bound_by_the_token(self, ledger, form, field, value):
        browser, fields = form
        before = unchanged_state(ledger.path)
        response = browser.post("/transaction/correct", {**fields, "value": "x",
                                                         field: value})
        assert response.status == 403
        assert unchanged_state(ledger.path) == before

    def test_a_choice_off_its_list_is_refused_before_any_command(self, ledger, monkeypatch):
        (transaction_id,) = transaction_ids(ledger)
        browser = Browser(ledger.path)
        try:
            fields = page_forms(transaction_id)(browser)["/transaction/classify"]
            ran = []
            monkeypatch.setattr(ui_server, "main", lambda words: ran.append(words) or 0)
            response = browser.post("/transaction/classify", {**fields, "type": "gift"})
        finally:
            browser.close()
        assert response.status == 400 and ran == []

    def test_a_correction_supersedes_only_its_own_field(self, ledger):
        (transaction_id,) = transaction_ids(ledger)
        assert ledger.run("review", "correct", transaction_id, "--account", "A", "--revision",
                          revision_of(ledger, transaction_id), "--field", "amount",
                          "--value=-1.00")[0] == 0
        browser = Browser(ledger.path)
        try:
            forms = {form["fields"]["field"]: form["fields"]
                     for form in all_post_forms(transaction_page(browser, transaction_id).body)
                     if form["action"] == "/transaction/correct"}
        finally:
            browser.close()
        assert forms["amount"]["supersedes"]
        assert {field: forms[field]["supersedes"] for field in
                ("transaction_date", "posting_date", "description")} == dict.fromkeys(
                    ("transaction_date", "posting_date", "description"), "")

    def test_the_other_account_is_never_this_one(self, ledger):
        (transaction_id,) = transaction_ids(ledger)
        browser = Browser(ledger.path)
        try:
            body = transaction_page(browser, transaction_id).body.decode()
        finally:
            browser.close()
        select = body.split('<select name="counterpart_account">')[1].split("</select>")[0]
        assert account_id(ledger, "B") in select and account_id(ledger, "A") not in select

    def test_an_amount_or_date_of_the_wrong_shape_is_refused(self, unresolved_item):
        browser, fields = unresolved_item
        for typed in ({"amount": "12,50"}, {"amount": "1e3"}, {"transaction_date": "5/1/2026"},
                      {"posting_date": "2026-1-5"}):
            response = browser.post("/review/complete", {**fields, **typed})
            assert response.status == 400, typed

    @pytest.fixture
    def unresolved_item(self, tmp_path, capsys):
        folder = tmp_path / "unresolved"
        folder.mkdir()
        found = Ledger(folder, capsys)
        found.checking("a.csv", "S-2,not a date,,SYNTHETIC BAD,-3.00,POSTED")
        (item,) = found.items()
        browser = Browser(found.path)
        fields = browser.item_forms(item)["/review/complete"]
        yield browser, fields
        browser.close()

    def test_every_option_is_written_with_its_value_attached(self):
        words = writes.command_words(
            "/transaction/correct",
            {"transaction": "t", "account": "a", "revision": "r", "field": "description",
             "supersedes": "", "supersedes_revision": "", "value": "--db=/elsewhere"},
            "/ledger.db")
        assert words == ["review", "correct", "t", "--db=/ledger.db", "--account=a",
                         "--revision=r", "--field=description", "--value=--db=/elsewhere"]


class TestAllowlist:  # WB2
    def test_the_route_table_is_the_allowlist_as_built(self):
        assert set(writes.WRITE_ROUTES) == ALLOWLIST

    def test_no_route_runs_a_terminal_only_command(self):
        for route in writes.WRITE_ROUTES.values():
            for words in TERMINAL_ONLY:
                assert route.words[:len(words)] != words, (route.words, words)

    def test_settings_routes_take_the_buffer_key_alone(self):
        for route in writes.WRITE_ROUTES.values():
            if route.words[0] == "setting":
                (key,) = [field for field in route.hidden if field.name == "key"]
                assert key.choices == ("checking_buffer_cents",)

    def test_several_statements_reaching_give_no_form(self, monkeypatch):
        monkeypatch.setattr(ui_server, "printed_revision", lambda words: "r1-0000")
        printed = ("    Classification c1: fee, binding one side\n"
                   "    Classification c2: purchase, binding the other\n")
        assert ui_server.superseded_statement(printed, "classification", "--db=x") is None
        assert ui_server.superseded_statement("", "classification", "--db=x") == {
            "supersedes": "", "supersedes_revision": ""}
