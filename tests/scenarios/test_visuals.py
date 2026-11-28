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


def test_spending_by_category_is_the_ledger_s(planned):
    """Summed from the monthly report's months, it equals the whole ledger's income and spending
    by category, category by category."""
    from personal_finance.reports.totals import income_and_spending
    from personal_finance.reports.visuals import spent, visuals
    from datetime import date

    conn = planned.conn()
    try:
        whole = income_and_spending(conn).spending_by_category
        (chart, *_) = visuals(conn, date.fromisoformat(AS_OF))
        names = dict(conn.execute("SELECT id, name FROM category"))
    finally:
        conn.close()
    assert [(row.label, row.values) for row in chart.rows] == [
        (names.get(category_id, "uncategorized"), (spent(group),)) for category_id, group in whole]
    assert chart.rows


class TestTheDrawing:  # D-083 point 4
    def drawn(self, *rows, series=("balance",)):
        from personal_finance.reports.visuals import Chart, ChartRow
        from personal_finance.ui import charts

        chart = Chart("Signed", series, tuple(ChartRow(label, values) for label, values in rows))
        svg = ElementTree.fromstring(charts.chart_svg(chart))
        zero = svg.find(f"{SVG}line")
        bars = {rect.find(f"{SVG}title").text: rect for rect in svg.iter(f"{SVG}rect")
                if rect.find(f"{SVG}title") is not None}
        labels = [text.text for text in svg.iter(f"{SVG}text")]
        return svg, float(zero.get("x1")), bars, labels, charts

    def test_bars_run_from_the_zero_line_negatives_to_its_left(self):
        svg, zero, bars, labels, charts = self.drawn(("A", (500000,)), ("Card", (-15000,)),
                                                     ("S", (200000,)))
        assert svg.get("width") == "100%" and svg.get("height") is None
        assert svg.get("viewBox").startswith(f"0 0 {charts.WIDTH} ")
        card, first = bars["Card: balance -150.00"], bars["A: balance 5000.00"]
        assert float(card.get("x")) + float(card.get("width")) == zero
        assert float(first.get("x")) == zero == float(bars["S: balance 2000.00"].get("x"))
        widths = {title: float(bar.get("width")) for title, bar in bars.items()}
        assert widths["A: balance 5000.00"] > widths["S: balance 2000.00"] > widths[
            "Card: balance -150.00"]
        assert zero + widths["A: balance 5000.00"] <= charts.WIDTH - charts.VALUE_ROOM
        assert float(card.get("x")) >= charts.LABEL_WIDTH + charts.VALUE_ROOM

    def test_with_no_negative_the_zero_line_is_at_the_labels_edge(self):
        _, zero, bars, _, charts = self.drawn(("A", (100,)), ("B", (0,)))
        assert zero == charts.LABEL_WIDTH
        assert float(bars["B: balance 0.00"].get("width")) == 1

    def test_each_bar_is_labelled_with_its_value(self):
        _, _, bars, labels, _ = self.drawn(("A", (500000, -100)), ("B", (0, 2550)),
                                           series=("in", "out"))
        assert len(bars) == 4
        assert [label for label in labels if label[0].isdigit() or label[0] == "-"] == [
            "5000.00", "-1.00", "0.00", "25.50"]
