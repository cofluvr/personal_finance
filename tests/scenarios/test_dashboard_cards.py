"""The dashboard page's cards and goal chart (D-083 point 3): each shows a figure the dashboard's
own lines print, from the one computation, using synthetic data only."""

import re
import xml.etree.ElementTree as ElementTree
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from local_ui_client import page_text, parsed_page
from test_local_ui_writes import Browser
from test_safe_to_spend import AS_OF, ledger, planned  # noqa: F401, fixtures
from test_visuals import SVG, charts_of, table_cells

from personal_finance.ui import server as ui_server


class CardParser(HTMLParser):
    """Each card's state, link, label, value and detail, in order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards, self._part = [], None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "card" == attributes.get("class"):
            self.cards.append({"state": attributes.get("data-state"),
                               "link": attributes.get("href"), "label": "", "value": "",
                               "detail": "", "badge": ""})
        elif attributes.get("class", "").startswith("card-") or attributes.get("class") == "badge":
            self._part = attributes["class"].removeprefix("card-")

    def handle_endtag(self, tag):
        if tag in ("p", "span"):
            self._part = None

    def handle_data(self, data):
        if self._part and self.cards:
            self.cards[-1][self._part] += data


def dashboard(ledger, as_of=AS_OF):
    browser = Browser(ledger.path)
    try:
        response = browser.get(f"/dashboard?as_of={as_of}")
    finally:
        browser.close()
    assert response.status == 200, response.text
    parser = CardParser()
    parser.feed(response.body.decode())
    return response, {card["label"]: card for card in parser.cards}


class TestTheCards:
    def test_each_figure_is_one_the_lines_print(self, planned):
        response, cards = dashboard(planned)
        text = page_text(response.body)
        assert text == planned.dashboard()
        assert list(cards) == ["Safe to spend today", "Budget left this month",
                               "Net worth, observed", "Income received", "Open review items"]
        lines = text.splitlines()
        assert cards["Safe to spend today"]["value"] == "50.00"
        assert lines[0].endswith(f"today {cards['Safe to spend today']['value']}, this week 350.00")
        assert "This week 350.00, limited by budget" == cards["Safe to spend today"]["detail"]
        assert "Limiting constraint: budget" in text
        budget = next(line for line in lines if line.startswith("Budget pace, 2026-05:"))
        assert (f"remaining capacity {cards['Budget left this month']['value']}, revised daily "
                "50.00, against pace -93.54") in budget
        assert cards["Budget left this month"]["detail"] == "Daily 50.00, at or below pace by 93.54"
        assert f"Net worth, observed: {cards['Net worth, observed']['value']}, 1 not valued" in text
        assert (f"actual {cards['Income received']['value']}, against baseline, planned 5000.00"
                in text)
        assert cards["Income received"]["detail"] == "Of 5000.00 planned, baseline"
        assert (f"Review: {cards['Open review items']['value']} open review items, 0 unconfirmed"
                in text)

    def test_each_cards_state_follows_its_figures_meaning(self, planned):
        _, cards = dashboard(planned)
        assert {label: card["state"] for label, card in cards.items()} == {
            "Safe to spend today": "good",
            "Budget left this month": "good",  # below pace: actual less pace is negative
            "Net worth, observed": "warning",  # one account not valued
            "Income received": "neutral",
            "Open review items": "good"}
        assert cards["Open review items"]["link"] == "/review"
        assert not any(card["badge"] for card in cards.values())



def stand_in_figures(*, today=5000, provisional=False, surplus=100, against_pace=-1,
                     not_valued=(), open_items=0, transfer_kinds=0):
    """Figures with only what the cards read, each defaulting to a good state."""
    view = SimpleNamespace(today_cents=today, week_cents=35000, limiting="budget",
                           liquidity_evaluated=True, surplus_cents=surplus,
                           provisional=provisional)
    pace = SimpleNamespace(remaining_capacity_cents=140000, revised_daily_cents=5000,
                           against_pace_cents=against_pace)
    return SimpleNamespace(
        safe_to_spend=view, budget_pace=pace,
        worth=SimpleNamespace(total_cents=685000, not_valued=not_valued),
        oldest_valuation=None, income_received_cents=0, income_planned_cents=500000,
        open_review_items=open_items, unconfirmed_transfer_kinds=transfer_kinds)


def cards_of(figures):
    parser = CardParser()
    parser.feed(ui_server.dashboard_cards(figures))
    return {card["label"]: card for card in parser.cards}


class TestEachStateAlone:
    def test_the_control_is_good_throughout(self):
        cards = cards_of(stand_in_figures())
        assert {card["state"] for card in cards.values()} == {"good", "neutral"}
        assert cards["Income received"]["state"] == "neutral"

    @pytest.mark.parametrize(("against_pace", "state", "words"), [
        (1, "warning", "above pace by 0.01"), (0, "good", "at or below pace by 0.00"),
        (-1, "good", "at or below pace by 0.01")])
    def test_above_pace_alone_is_a_warning(self, against_pace, state, words):
        card = cards_of(stand_in_figures(against_pace=against_pace))["Budget left this month"]
        assert card["state"] == state
        assert card["detail"] == f"Daily 50.00, {words}"

    @pytest.mark.parametrize(("changes", "label", "badge"), [
        ({"provisional": True}, "Safe to spend today", "Provisional"),
        ({"surplus": -1}, "Safe to spend today", ""),
        ({"not_valued": ("Car",)}, "Net worth, observed", ""),
        ({"open_items": 1}, "Open review items", ""),
        ({"transfer_kinds": 1}, "Open review items", ""),
    ])
    def test_each_warning_alone(self, changes, label, badge):
        cards = cards_of(stand_in_figures(**changes))
        assert [found for found, card in cards.items() if card["state"] == "warning"] == [label]
        assert cards[label]["badge"] == badge

    def test_no_figure_says_so(self):
        card = cards_of(stand_in_figures(today=None))["Safe to spend today"]
        assert (card["value"], card["state"]) == ("Not available", "warning")

    def test_no_plan_is_neutral(self):
        figures = stand_in_figures()
        figures.budget_pace = None
        card = cards_of(figures)["Budget left this month"]
        assert (card["value"], card["state"]) == ("No plan", "neutral")


class TestTheGoalChart:
    def test_its_marks_are_the_visuals_goal_progress(self, planned):
        response, _ = dashboard(planned)
        drawn = charts_of(response.body)
        assert [svg.find(f"{SVG}title").text for svg in drawn] == ["Goal progress"]
        marks = {rect.find(f"{SVG}title").text for rect in drawn[0].iter(f"{SVG}rect")
                 if rect.find(f"{SVG}title") is not None}
        browser = Browser(planned.path)
        try:
            visuals = browser.get(f"/visuals?as_of={AS_OF}").body
        finally:
            browser.close()
        assert marks == table_cells(page_text(visuals))["Goal progress"]
        assert "Rainy: assigned 1000.00" in marks

    def test_the_page_holds_no_script_or_style(self, planned):
        response, _ = dashboard(planned)
        page = parsed_page(response.body)
        assert "script" not in page.tags and "style" not in page.tags
        assert not any(name.startswith("on") or name == "style" for name, _ in page.attributes)
        for svg in charts_of(response.body):
            assert isinstance(svg, ElementTree.Element)
        assert not re.search(rb"url\(", response.body)
