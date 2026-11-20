"""The accounts and members, obligations, and settings and backups sections, and the planning
writes on them (M17.2b, WB1 to WB3, D-073 points 2 and 3, the M17.2 slice plan).

Each page is its commands' lines, one after another, without creation times (F2). Each browser
write equals the same CLI command on a copy of the ledger.
"""

import re

import pytest
from local_ui_client import page_text
from test_local_ui import unchanged_state
from test_local_ui_transaction_writes import all_post_forms, assert_browser_equals_cli
from test_local_ui_writes import Browser
from test_safe_to_spend import AS_OF, ledger, planned  # noqa: F401, fixtures

from personal_finance.ui import server as ui_server

TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
SECTION_COMMANDS = {
    "/accounts": [("account", "liquidity", "show"), ("account", "links"),
                  ("household", "members"), ("household", "share", "show")],
    "/obligations": [("obligations",), ("obligation", "coverage", "--as-of", AS_OF)],
    "/settings": [("setting", "show"), ("storage",)],
}


def printed(ledger, words):
    code, out, err = ledger.run(*words)
    return out if code == 0 else f"Not available: {err.strip().removeprefix('Error: ')}\n"


def page_forms(browser, page, action=None):
    response = browser.get(page)
    assert response.status == 200, response.text
    return [form["fields"] for form in all_post_forms(response.body)
            if action is None or form["action"] == action]


def forms_of(page, action, **matching):
    def chosen(browser):
        found = [fields for fields in page_forms(browser, page, action)
                 if all(fields[name] == value for name, value in matching.items())]
        assert len(found) == 1, found
        return {action: found[0]}
    return chosen


def revision_in(out, pattern):
    return re.search(pattern, out, re.MULTILINE)[1]


class TestSectionsEqualTheirCommands:  # WB1
    def test_each_section_is_its_commands_without_creation_times(self, planned):
        browser = Browser(planned.path)
        try:
            for page, commands in SECTION_COMMANDS.items():
                target = f"{page}?as_of={AS_OF}" if page == "/obligations" else page
                shown = page_text(browser.get(target).body)
                expected = "".join(printed(planned, words) for words in commands)
                assert shown == ui_server.without_creation_times(expected), page
                assert TIMESTAMP.search(expected), f"the control: {page}'s commands show one"
                assert not TIMESTAMP.search(shown), page
        finally:
            browser.close()

    def test_a_section_command_that_refuses_shows_its_message(self, tmp_path, capsys):
        from test_safe_to_spend import SafeLedger

        bare = SafeLedger(tmp_path, capsys)
        browser = Browser(bare.path)
        try:
            shown = page_text(browser.get("/obligations").body)
        finally:
            browser.close()
        assert shown.endswith(printed(bare, ("obligation", "coverage")))
        assert "Not available:" in shown

    def test_every_section_is_in_the_navigation(self, planned):
        browser = Browser(planned.path)
        try:
            body = browser.get("/").text
        finally:
            browser.close()
        for page in SECTION_COMMANDS:
            assert f'href="{page}"' in body


class TestPlanningWritesEqualTheCli:  # WB3
    def test_the_buffer_undone_then_set(self, planned, tmp_path, capsys):
        out = planned.run("setting", "show")[1]
        revision = revision_in(out, r"^Setting checking_buffer_cents: .*\n  Revision: (\S+)$")
        assert_browser_equals_cli(
            planned, tmp_path, capsys, "/setting/buffer-undo", {},
            ["setting", "undo", "checking_buffer_cents", "--revision", revision],
            forms_of("/settings", "/setting/buffer-undo"))
        out = planned.run("setting", "show")[1]
        revision = revision_in(out, r"^Setting checking_buffer_cents: .*\n  Revision: (\S+)$")
        assert_browser_equals_cli(
            planned, tmp_path, capsys, "/setting/buffer-set", {"buffer": "750.00"},
            ["setting", "set", "checking_buffer_cents", "750.00", "--revision", revision],
            forms_of("/settings", "/setting/buffer-set"))

    def test_liquidity_set_and_undone(self, planned, tmp_path, capsys):
        out = planned.run("account", "liquidity", "show")[1]
        savings = revision_in(out, r"^Account S \((?:savings), ([0-9a-f-]{36})\)")
        revision = revision_in(out, r"^Account S .*\n  Set revision: (\S+)$")
        assert_browser_equals_cli(
            planned, tmp_path, capsys, "/account/liquidity-set", {},
            ["account", "liquidity", "set", "--account", savings, "--revision", revision],
            forms_of("/accounts", "/account/liquidity-set", account=savings))
        out = planned.run("account", "liquidity", "show")[1]
        revision = revision_in(out, r"^Account S .*\n  Undo revision: (\S+)$")
        assert_browser_equals_cli(
            planned, tmp_path, capsys, "/account/liquidity-undo", {},
            ["account", "liquidity", "undo", "--account", savings, "--revision", revision],
            forms_of("/accounts", "/account/liquidity-undo", account=savings))

    def test_an_obligation_covers_a_reserve_then_uncovers(self, planned, tmp_path, capsys):
        out = planned.run("obligation", "coverage", "--as-of", AS_OF)[1]
        obligation = revision_in(out, r"^Obligation ([0-9a-f-]{36}) \(Power\)")
        revision = revision_in(out, r"^Obligation .* \(Power\): .*\n  Covers revision: (\S+)$")
        assert_browser_equals_cli(
            planned, tmp_path, capsys, "/obligation/covers-fund", {"fund": planned.reserve},
            ["obligation", "covers", obligation, "--fund", planned.reserve, "--revision",
             revision],
            forms_of(f"/obligations?as_of={AS_OF}", "/obligation/covers-fund"))
        out = planned.run("obligation", "coverage", "--as-of", AS_OF)[1]
        revision = revision_in(out, r"^Obligation .* \(Power\): .*\n  Uncover revision: (\S+)$")
        assert_browser_equals_cli(
            planned, tmp_path, capsys, "/obligation/uncover", {},
            ["obligation", "uncover", obligation, "--revision", revision],
            forms_of(f"/obligations?as_of={AS_OF}", "/obligation/uncover"))

    def test_a_refused_link_shows_the_clis_message(self, planned, capsys):
        browser = Browser(planned.path)
        try:
            (fields,) = page_forms(browser, f"/obligations?as_of={AS_OF}",
                                   "/obligation/covers-fund")
            before = unchanged_state(planned.path)
            response = browser.post("/obligation/covers-fund", {**fields, "fund": "nosuchfund"})
        finally:
            browser.close()
        code, _, err = planned.run("obligation", "covers", fields["obligation"], "--fund",
                                   "nosuchfund", "--revision", fields["revision"])
        assert response.status == 409 and code == 2
        import html

        assert err.strip().removeprefix("Error: ") in html.unescape(response.text)
        assert unchanged_state(planned.path) == before


class TestTerminalOnly:  # WB2
    def test_the_timezone_cannot_be_set_from_the_browser(self, planned):
        browser = Browser(planned.path)
        try:
            planned.run("setting", "undo", "checking_buffer_cents", "--revision", revision_in(
                planned.run("setting", "show")[1],
                r"^Setting checking_buffer_cents: .*\n  Revision: (\S+)$"))
            (fields,) = page_forms(browser, "/settings", "/setting/buffer-set")
            before = unchanged_state(planned.path)
            response = browser.post("/setting/buffer-set", {**fields, "key": "household_timezone",
                                                            "buffer": "100.00"})
            body = browser.get("/settings").text
        finally:
            browser.close()
        assert response.status == 400
        assert unchanged_state(planned.path) == before
        assert "household_timezone" not in "".join(
            value for form in all_post_forms(body.encode()) for value in form["fields"].values())

    def test_a_positional_value_like_an_option_is_refused(self, planned):
        planned.run("setting", "undo", "checking_buffer_cents", "--revision", revision_in(
            planned.run("setting", "show")[1],
            r"^Setting checking_buffer_cents: .*\n  Revision: (\S+)$"))
        browser = Browser(planned.path)
        try:
            (fields,) = page_forms(browser, "/settings", "/setting/buffer-set")
            before = unchanged_state(planned.path)
            response = browser.post("/setting/buffer-set", {**fields, "buffer": "-5.00"})
        finally:
            browser.close()
        assert response.status == 400
        assert unchanged_state(planned.path) == before

    @pytest.mark.parametrize("page", list(SECTION_COMMANDS))
    def test_section_pages_leave_the_ledger_unchanged(self, planned, page):
        before = unchanged_state(planned.path)
        browser = Browser(planned.path)
        try:
            assert browser.get(page).status == 200
        finally:
            browser.close()
        assert unchanged_state(planned.path) == before
