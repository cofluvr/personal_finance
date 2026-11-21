"""The eight visuals as script-free SVG, each drawn from the rows of the table beneath it (WC3,
D-073 point 6), using synthetic data only."""

import re
import xml.etree.ElementTree as ElementTree

import pytest
from local_ui_client import page_text, parsed_page
from test_local_ui_writes import Browser
from test_safe_to_spend import AS_OF, ledger, planned  # noqa: F401, fixtures

SVG = "{http://www.w3.org/2000/svg}"
TITLES = ("Spending by category", "Spending over time", "Budget, 2026-05: target against actual",
          "Goal progress", "Household comparison", "Income and spending",
          "Debt history, as observed", f"Net worth as of {AS_OF}, by account")


def owe(ledger, account, day, owed):
    code, _, err = ledger.run("balance", "record", "--account", account, "--date", day,
                              "--owed", owed)
    assert code == 0, err


@pytest.fixture
def page(planned):
    planned.add_typed_account("Card", "credit_card")
    owe(planned, "Card", "2026-04-30", "320.00")
    owe(planned, "Card", "2026-05-02", "150.00")
    browser = Browser(planned.path)
    try:
        response = browser.get(f"/visuals?as_of={AS_OF}")
    finally:
        browser.close()
    assert response.status == 200, response.text
    return response


def charts_of(body: bytes) -> list[ElementTree.Element]:
    return [ElementTree.fromstring(svg) for svg in re.findall(rb"<svg .*?</svg>", body)]


def table_cells(text: str) -> dict[str, set[str]]:
    """Each chart's title and the marks its table rows give: label, one series and value, and
    any note."""
    found, title = {}, None
    for line in text.splitlines():
        if not line.startswith("  "):
            title = line.removesuffix(":")
            found[title] = set()
            continue
        if line.startswith("  ("):
            continue
        label, _, rest = line.strip().partition(": ")
        note = re.search(r" \(.*\)$", rest)
        values = rest[:note.start()] if note else rest
        for cell in values.split(", "):
            found[title].add(f"{label}: {cell}{note[0] if note else ''}")
    return found


class TestTheTable:  # WC3
    def test_the_page_equals_the_command(self, planned, page):
        assert page_text(page.body) == planned.run("report", "visuals", "--as-of", AS_OF)[1]

    def test_every_visual_is_there_in_order(self, page):
        titles = [line.removesuffix(":") for line in page_text(page.body).splitlines()
                  if not line.startswith("  ")]
        assert titles == list(TITLES)


class TestTheCharts:  # WC3
    def test_each_marks_value_is_its_table_cell(self, page):
        cells = table_cells(page_text(page.body))
        drawn = {}
        for svg in charts_of(page.body):
            title = svg.find(f"{SVG}title").text
            drawn[title] = {rect.find(f"{SVG}title").text for rect in svg.iter(f"{SVG}rect")
                            if rect.find(f"{SVG}title") is not None}
        assert drawn, "the control: something is drawn"
        for title, marks in drawn.items():
            assert marks == cells[title], title
        assert {title for title, rows in cells.items() if rows} == set(drawn)

    def test_the_figures_are_the_reports(self, planned, page):
        cells = table_cells(page_text(page.body))
        assert "Card, 2026-05-02: owed 150.00" in cells["Debt history, as observed"]
        assert "Actual: amount 100.00" in cells["Budget, 2026-05: target against actual"]
        assert any(cell.startswith("Rainy: assigned 1000.00") for cell in cells["Goal progress"])
        assert any("(valued 2026-04-30)" in cell
                   for cell in cells[f"Net worth as of {AS_OF}, by account"])

    def test_no_script_event_style_or_outside_reference(self, page):
        body = page.body.decode()
        parsed = parsed_page(page.body)
        assert "script" not in parsed.tags and "style" not in parsed.tags
        assert not any(name.startswith("on") or name == "style" for name, _ in parsed.attributes)
        for svg in charts_of(page.body):
            for element in svg.iter():
                assert not any(name.endswith("href") or name in ("src", "style")
                               or name.startswith("on") for name in element.attrib), element
        assert "url(" not in body and "<foreignObject" not in body

    def test_an_undone_observation_is_not_drawn(self, planned):
        planned.add_typed_account("Card", "credit_card")
        owe(planned, "Card", "2026-05-01", "90.00")
        shown = planned.run("balance", "list", "--account", "Card")[1]
        observation, token = re.search(r"^Observation (\S+):.*\n  Token: (\S+)$", shown,
                                       re.MULTILINE).groups()
        code, _, err = planned.run("balance", "undo", "--account", "Card", "--observation",
                                   observation, "--token", token)
        assert code == 0, err
        out = planned.run("report", "visuals", "--as-of", AS_OF)[1]
        assert "Card, 2026-05-01" not in out

    def test_a_label_holding_markup_is_text(self, planned):
        planned.add_typed_account("<script>x</script>", "credit_card")
        owe(planned, "<script>x</script>", "2026-05-01", "1.00")
        browser = Browser(planned.path)
        try:
            response = browser.get(f"/visuals?as_of={AS_OF}")
        finally:
            browser.close()
        assert b"<script>" not in response.body
        assert "script" not in parsed_page(response.body).tags

    def test_a_visual_with_nothing_draws_nothing_and_says_so(self, tmp_path, capsys):
        from test_safe_to_spend import SafeLedger

        bare = SafeLedger(tmp_path, capsys)
        out = bare.run("report", "visuals", "--as-of", AS_OF)[1]
        assert "  (no card or loan balance is observed)" in out
        browser = Browser(bare.path)
        try:
            body = browser.get(f"/visuals?as_of={AS_OF}").body
        finally:
            browser.close()
        titles = {svg.find(f"{SVG}title").text for svg in charts_of(body)}
        assert "Debt history, as observed" not in titles


def test_the_page_asks_for_a_date_with_no_timezone(tmp_path, capsys):
    from test_decisions import Ledger
    from personal_finance.ui.server import CHOOSE_AS_OF

    browser = Browser(Ledger(tmp_path, capsys).path)
    try:
        assert CHOOSE_AS_OF in browser.get("/visuals").text
    finally:
        browser.close()
