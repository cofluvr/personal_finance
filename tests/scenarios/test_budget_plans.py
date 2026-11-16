"""Settings and budget plans stated by a person, end to end, using synthetic data only (BA2 to BA4,
D-069 points 1, 2 and 6, D-067 G2 to G4 and G7), and "today" read from the household timezone by
the M12 commands that took --as-of as required (M12.1 slice plan point 1)."""

import re
from datetime import datetime, timezone

import pytest
from local_ui_client import UiClient, page_text
from planning_digest import evidence_digest
from test_decisions import BUDGET_TABLES
from test_obligations import ObligationLedger

from personal_finance import cli
from personal_finance.db.backups import logical_digest
from personal_finance.planning import budgets, settings
from personal_finance.planning.budgets import (
    ALLOWANCE_INVALID,
    CATEGORY_UNKNOWN,
    CLOSED_MONTH,
    MEMBER_UNKNOWN,
    MEMBERS_MISSING,
    MEMBERS_NOT_SUMMING,
    MONTH_INVALID,
    MONTH_TAKEN,
    PART_INVALID,
    PLAN_REFUSALS,
    STALE_BUDGET_PREVIEW,
    STALE_BUDGET_REVISION,
    STALE_SUPERSEDED_REVISION,
    SUPERSEDES_PAIR,
    UNDO_CLOSED_MONTH,
    UNDO_MONTH_TAKEN,
    load_plans,
    plan_in_effect,
)
from personal_finance.ui.server import CHOOSE_AS_OF
from personal_finance.planning.settings import (
    ALREADY_SET,
    KEY_UNKNOWN,
    NOT_SET,
    STALE_SETTING_REVISION,
    ZONE_UNKNOWN,
    setting_revision,
)

AS_OF = "2026-03-15"
ZONE = "America/Chicago"
SETTING_TOKEN = r"st1-[0-9a-f]{16}"
BUDGET_TOKEN = r"bp1-[0-9a-f]{16}"
# 03:00 UTC on 1 March is still 28 February in Chicago.
CHICAGO_EVENING = datetime(2026, 3, 1, 3, 0, tzinfo=timezone.utc)


class BudgetLedger(ObligationLedger):
    def __init__(self, folder, capsys):
        super().__init__(folder, capsys)
        for name in ("Alex", "Bea"):
            assert self.run("household", "member", "add", name)[0] == 0
        for name in ("Dining", "Groceries"):
            assert self.run("category", "add", name)[0] == 0
        self.card("c1.csv", "03/02/2026,SYNTHETIC CAFE,6.50,")

    # Settings.

    def settings_shown(self):
        code, out, err = self.run("setting", "show")
        assert (code, err) == (0, ""), err
        return out

    def setting_token(self, key="household_timezone"):
        return re.search(rf"Setting {key}: .*\n  Revision: ({SETTING_TOKEN})",
                         self.settings_shown())[1]

    def set_setting(self, value=ZONE, key="household_timezone", revision=None):
        return self.run("setting", "set", key, value, "--revision",
                        revision or self.setting_token(key))

    def undo_setting(self, key="household_timezone", revision=None):
        return self.run("setting", "undo", key, "--revision", revision or self.setting_token(key))

    # Budget plans.

    def plan_words(self, from_month="2026-03", allowance="1500.00", members=(), categories=(),
                   supersedes=None, supersedes_revision=None, correct=False, as_of=AS_OF):
        words = ["--from", from_month, "--allowance", allowance]
        for member in members:
            words += ["--member", member]
        for category in categories:
            words += ["--category", category]
        if supersedes is not None:
            words += ["--supersedes", supersedes, "--supersedes-revision",
                      supersedes_revision or self.plan_token(supersedes, "Supersede")]
        if correct:
            words.append("--correct-closed-month")
        if as_of is not None:
            words += ["--as-of", as_of]
        return words

    def plan_preview(self, **options):
        return self.run("budget", "preview", *self.plan_words(**options))

    def plan_preview_ok(self, **options):
        code, out, err = self.plan_preview(**options)
        assert (code, err) == (0, ""), err
        return out

    def plan_preview_revision(self, **options):
        return re.search(rf"Revision: ({BUDGET_TOKEN})", self.plan_preview_ok(**options))[1]

    def set_plan(self, revision=None, **options):
        return self.run("budget", "set", *self.plan_words(**options), "--revision",
                        revision or self.plan_preview_revision(**options))

    def set_plan_ok(self, **options):
        code, out, err = self.set_plan(**options)
        assert (code, err) == (0, ""), err
        return re.search(r"Budget plan (\S+) recorded", out)[1]

    def plan_shown(self, plan_id):
        code, out, err = self.run("budget", "show", plan_id)
        assert (code, err) == (0, ""), err
        return out

    def plan_token(self, plan_id, kind):
        return re.search(rf"{kind} revision: ({BUDGET_TOKEN})", self.plan_shown(plan_id))[1]

    def undo_plan(self, plan_id, revision=None, as_of=AS_OF):
        words = ["budget", "undo", plan_id, "--revision", revision or self.plan_token(plan_id,
                                                                                         "Undo")]
        return self.run(*words, *(["--as-of", as_of] if as_of else []))

    def plans(self):
        conn = self.conn()
        try:
            return load_plans(conn)
        finally:
            conn.close()

    def budget_tables(self):
        conn = self.conn()
        try:
            return {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                    for table in BUDGET_TABLES}
        finally:
            conn.close()

    def evidence(self):
        conn = self.conn()
        try:
            return evidence_digest(conn)
        finally:
            conn.close()

    def refused(self, attempt, message):
        """The attempt fails with exactly this message, and no table changes."""
        before = (self.budget_tables(), self.evidence())
        code, _, err = attempt()
        assert (code, err.strip()) == (2, f"Error: {message}"), err
        assert (self.budget_tables(), self.evidence()) == before


@pytest.fixture
def ledger(tmp_path, capsys):
    return BudgetLedger(tmp_path, capsys)


@pytest.fixture
def clock(monkeypatch):
    """The CLI's one clock read, fixed (G7)."""
    monkeypatch.setattr(cli, "current_utc_time", lambda: CHICAGO_EVENING)


# BA2: settings.

class TestSettings:  # BA2
    def test_show_lists_the_seeded_key_unset_with_its_revision(self, ledger):
        out = ledger.settings_shown()
        assert "Setting household_timezone: not set\n" in out
        assert out.rstrip().endswith("Settings: 1 key, 0 set")

    def test_set_undo_and_set_again_keeps_every_value(self, ledger):
        assert ledger.set_setting()[0] == 0
        assert f"Setting household_timezone: {ZONE}, setting " in ledger.settings_shown()
        assert ledger.undo_setting()[0] == 0
        assert "Setting household_timezone: not set" in ledger.settings_shown()
        assert ledger.set_setting("Europe/Paris")[0] == 0
        conn = ledger.conn()
        values = conn.execute("SELECT value FROM ledger_setting ORDER BY created_at").fetchall()
        events = conn.execute("SELECT event FROM ledger_setting_event ORDER BY id").fetchall()
        conn.close()
        assert values == [(ZONE,), ("Europe/Paris",)]
        assert events == [("made",), ("undone",), ("made",)]

    def refused(self, ledger, attempt, message):
        tables = ("ledger_setting", "ledger_setting_event")
        conn = ledger.conn()
        before = ([conn.execute(f"SELECT * FROM {table}").fetchall() for table in tables],
                  evidence_digest(conn))
        conn.close()
        code, _, err = attempt()
        assert (code, err.strip()) == (2, f"Error: {message}"), err
        conn = ledger.conn()
        assert ([conn.execute(f"SELECT * FROM {table}").fetchall() for table in tables],
                evidence_digest(conn)) == before
        conn.close()

    def test_an_unknown_key(self, ledger):
        token = ledger.setting_token()
        self.refused(ledger, lambda: ledger.set_setting(key="currency", revision=token),
                     KEY_UNKNOWN.format(key="currency"))
        self.refused(ledger, lambda: ledger.undo_setting(key="currency", revision=token),
                     KEY_UNKNOWN.format(key="currency"))

    @pytest.mark.parametrize("value", ["Mars/Olympus", "localtime", "/etc/localtime",
                                       "america/chicago", "../zoneinfo/UTC", ""])
    def test_an_unknown_zone(self, ledger, value):
        self.refused(ledger, lambda: ledger.set_setting(value),
                     ZONE_UNKNOWN.format(value=value))

    def test_a_second_active_value(self, ledger):
        token = ledger.setting_token()
        assert ledger.set_setting(revision=token)[0] == 0
        self.refused(ledger, lambda: ledger.set_setting("Europe/Paris", revision=token),
                     ALREADY_SET.format(key="household_timezone"))

    def test_nothing_to_undo(self, ledger):
        self.refused(ledger, lambda: ledger.undo_setting(revision=ledger.setting_token()),
                     NOT_SET.format(key="household_timezone"))

    def test_a_stale_token_for_the_value_and_the_operation(self, ledger):
        set_token = ledger.setting_token()
        assert ledger.set_setting(revision=set_token)[0] == 0
        # The set token, now used for an undo: the operation and value it covers have moved.
        self.refused(ledger, lambda: ledger.undo_setting(revision=set_token),
                     STALE_SETTING_REVISION)
        undo_token = ledger.setting_token()
        # A race: another connection undoes and sets another value between show and undo.
        assert ledger.undo_setting()[0] == 0
        assert ledger.set_setting("Europe/Paris")[0] == 0
        self.refused(ledger, lambda: ledger.undo_setting(revision=undo_token),
                     STALE_SETTING_REVISION)

    def test_the_token_covers_the_key_and_the_value(self, ledger):
        conn = ledger.conn()
        try:
            conn.execute("INSERT INTO ledger_setting_key (setting_key) VALUES ('test_only')")
            assert setting_revision(conn, "test_only") != setting_revision(
                conn, "household_timezone")
            conn.execute("INSERT INTO ledger_setting (id, setting_key, value) "
                         "VALUES ('one', 'test_only', 'x')")
            conn.execute("INSERT INTO ledger_setting_event (setting_id, event) "
                         "VALUES ('one', 'made')")
            conn.execute("INSERT INTO ledger_setting (id, setting_key, value) "
                         "VALUES ('two', 'household_timezone', 'x')")
            conn.execute("INSERT INTO ledger_setting_event (setting_id, event) "
                         "VALUES ('two', 'made')")
            with_x = setting_revision(conn, "test_only")
            conn.execute("INSERT INTO ledger_setting_event (setting_id, event) "
                         "VALUES ('one', 'undone')")
            conn.execute("INSERT INTO ledger_setting (id, setting_key, value) "
                         "VALUES ('three', 'test_only', 'y')")
            conn.execute("INSERT INTO ledger_setting_event (setting_id, event) "
                         "VALUES ('three', 'made')")
            assert setting_revision(conn, "test_only") != with_x
        finally:
            conn.rollback()
            conn.close()

    def test_a_fault_after_the_first_insert_leaves_nothing(self, ledger, monkeypatch):
        token = ledger.setting_token()
        conn = ledger.conn()
        before = logical_digest(conn)
        conn.close()

        def fail(conn, setting_id, event):
            raise RuntimeError("injected")

        monkeypatch.setattr(settings, "insert_setting_event", fail)
        code, _, err = ledger.set_setting(revision=token)
        assert code == 2 and "unexpected" in err
        conn = ledger.conn()
        assert logical_digest(conn) == before
        conn.close()

    def test_no_setting_write_changes_the_evidence(self, ledger):
        before = ledger.evidence()
        assert ledger.set_setting()[0] == 0
        assert ledger.undo_setting()[0] == 0
        assert ledger.evidence() == before

    def test_show_writes_nothing(self, ledger):
        assert ledger.set_setting()[0] == 0
        conn = ledger.conn()
        before = logical_digest(conn)
        conn.close()
        ledger.settings_shown()
        conn = ledger.conn()
        assert logical_digest(conn) == before
        conn.close()


# BA2: every planning command needing today refuses with no zone set, naming the command to run.

def m12_ledger(ledger):
    """A paycheck under a source and a bill under an obligation, each with its ID."""
    ledger.deposit("p1.csv", "2026-01-02")
    ledger.pay("b1.csv", "2026-01-05")
    return ledger.add_ok(), ledger.ob_add_ok()


def commands_needing_today(source, obligation, plan_words):
    return [
        ("income", "source", "show", source),
        ("income", "terms", source, "--effective-from", "2026-04-01", "--amount", "2600.00",
         "--revision", "in1-0000000000000000"),
        ("obligation", "show", obligation),
        ("obligation", "terms", obligation, "--effective-from", "2026-04-05", "--amount", "90.00",
         "--revision", "ob1-0000000000000000"),
        ("report", "income"),
        ("budget", "preview", *plan_words),
        ("budget", "set", *plan_words, "--revision", "bp1-0000000000000000"),
        ("budget", "undo", "no-such-plan", "--revision", "bp1-0000000000000000"),
    ]


class TestToday:  # BA2, G7, M12.1 slice plan point 1
    def test_each_command_needing_today_refuses_with_no_zone(self, ledger):
        source, obligation = m12_ledger(ledger)
        plan_words = ledger.plan_words(as_of=None)
        before = (ledger.budget_tables(), ledger.evidence())
        for words in commands_needing_today(source, obligation, plan_words):
            code, _, err = ledger.run(*words)
            assert (code, err.strip()) == (2, f"Error: {cli.TIMEZONE_NEEDED}"), words
        assert "setting set household_timezone" in cli.TIMEZONE_NEEDED
        assert (ledger.budget_tables(), ledger.evidence()) == before

    def test_today_is_the_household_day_not_the_utc_day(self, ledger, clock):
        assert ledger.set_setting()[0] == 0
        assert cli.household_today(ledger.conn()).isoformat() == "2026-02-28"
        # February is today's month in Chicago, so it is not closed.
        assert "Changes the plan in effect for: 2026-02 onward" in ledger.plan_preview_ok(from_month="2026-02", as_of=None)
        code, _, err = ledger.plan_preview(from_month="2026-01", as_of=None)
        assert err.strip() == f"Error: {CLOSED_MONTH.format(month='2026-01')}"

    def test_the_m12_commands_read_today_when_not_given(self, ledger, clock):
        source, obligation = m12_ledger(ledger)
        assert ledger.set_setting()[0] == 0
        for words in (("income", "source", "show", source), ("obligation", "show", obligation),
                      ("report", "income")):
            without = ledger.run(*words)
            assert without[0] == 0, without
            assert without == ledger.run(*words, "--as-of", "2026-02-28"), words
            assert without != ledger.run(*words, "--as-of", "2026-03-01"), words

    def test_terms_read_today_for_the_closed_month(self, ledger, clock):
        source, obligation = m12_ledger(ledger)
        assert ledger.set_setting()[0] == 0
        code, _, err = ledger.run("income", "terms", source, "--effective-from", "2026-01-30",
                                  "--amount", "2600.00", "--revision", ledger.token(source,
                                                                                    "Terms"))
        assert code == 2 and "closed" in err
        assert ledger.run("income", "terms", source, "--effective-from", "2026-02-13", "--amount",
                          "2600.00", "--revision", ledger.token(source, "Terms"))[0] == 0
        code, _, err = ledger.run("obligation", "terms", obligation, "--effective-from",
                                  "2026-01-30", "--amount", "90.00", "--revision",
                                  ledger.ob_token(obligation, "Terms"))
        assert code == 2 and "closed" in err

    def test_the_income_page_reads_today_once_a_zone_is_set(self, ledger, clock):
        m12_ledger(ledger)
        client = UiClient(ledger.path)
        client.sign_in()
        try:
            # With no zone, the page asks for a date, as before M13.1.
            assert CHOOSE_AS_OF in client.get("/income").text
            assert ledger.set_setting()[0] == 0
            assert CHOOSE_AS_OF not in client.get("/income").text
            assert page_text(client.get("/income").body) == page_text(
                client.get("/income?as_of=2026-02-28").body)
        finally:
            client.close()


# BA3: budget set's refusals, each alone, and each changing nothing.

class TestBudgetRefusals:  # BA3
    def test_a_plan_is_recorded_and_shown(self, ledger):
        out = ledger.plan_preview_ok(members=("Alex=900", "Bea=600.00"),
                                categories=("Dining=200", "Groceries=1400"))
        assert "Budget plan preview: from 2026-03, discretionary allowance, planned 1500.00 a " \
               "month" in out
        assert "  Members, planned: Alex 900.00, Bea 600.00" in out
        assert "  Category allowances, planned: Dining 200.00, Groceries 1400.00" in out
        assert ("  Warning: the category allowances exceed the household allowance by 100.00. "
                "Categories overlap members, so the plan is accepted.") in out
        plan = ledger.set_plan_ok(members=("Alex=900", "Bea=600.00"),
                                  categories=("Dining=200", "Groceries=1400"))
        shown = ledger.plan_shown(plan)
        assert f"Budget plan {plan}\n  Status: active\n" in shown
        assert "  In effect: 2026-03 onward" in shown

    @pytest.mark.parametrize("options, message", [
        ({"members": ("Alex=900", "Bea=500")},
         MEMBERS_NOT_SUMMING.format(total="1400.00", allowance="1500.00")),
        ({"members": ("Alex=1500",)}, MEMBERS_MISSING.format(names="Bea")),
        ({"members": ("Alex=900", "Bea=500", "Cy=100")}, MEMBER_UNKNOWN.format(name="Cy")),
        ({"categories": ("Nowhere=10",)}, CATEGORY_UNKNOWN.format(name="Nowhere")),
        ({"allowance": "-1.00"}, ALLOWANCE_INVALID),
        ({"allowance": "1.005"}, ALLOWANCE_INVALID),
        ({"members": ("Alex=1600", "Bea=-100")}, PART_INVALID.format(option="--member")),
        ({"categories": ("Dining=-1",)}, PART_INVALID.format(option="--category")),
        ({"categories": ("Dining=1", "Dining=2")}, PART_INVALID.format(option="--category")),
        ({"categories": ("Dining",)}, PART_INVALID.format(option="--category")),
        ({"from_month": "2026-13"}, MONTH_INVALID),
        ({"from_month": "2026-3"}, MONTH_INVALID),
        ({"from_month": "2026-02"}, CLOSED_MONTH.format(month="2026-02")),
    ])
    def test_what_was_typed(self, ledger, options, message):
        ledger.refused(lambda: ledger.plan_preview(**options), message)
        ledger.refused(lambda: ledger.set_plan(revision="bp1-0000000000000000", **options),
                       message)

    def test_a_closed_month_with_the_flag_is_a_disclosed_correction(self, ledger):
        plan = ledger.set_plan_ok(from_month="2026-02", correct=True)
        assert "  Corrects a closed month: from 2026-02," in ledger.plan_shown(plan)
        assert ledger.plans()[0].corrected_closed_month
        # The flag where nothing closed changes is not a correction.
        later = ledger.set_plan_ok(from_month="2026-04", correct=True)
        assert not next(plan for plan in ledger.plans() if plan.plan_id == later
                        ).corrected_closed_month

    def test_a_second_plan_for_a_month_supersedes(self, ledger):
        plan = ledger.set_plan_ok()
        ledger.refused(lambda: ledger.plan_preview(allowance="1600.00"),
                       MONTH_TAKEN.format(plan=plan, month="2026-03"))

    def test_supersedes_and_its_revision_are_given_together(self, ledger):
        plan = ledger.set_plan_ok(from_month="2026-04")
        ledger.refused(lambda: ledger.run("budget", "preview", "--from", "2026-04",
                                          "--allowance", "1.00", "--supersedes", plan,
                                          "--as-of", AS_OF), SUPERSEDES_PAIR)

    def test_a_stale_token(self, ledger):
        revision = ledger.plan_preview_revision()
        ledger.refused(lambda: ledger.set_plan(revision=revision, allowance="1500.01"),
                       STALE_BUDGET_PREVIEW)

    @pytest.mark.parametrize("change", [
        {"allowance": "1499.00"}, {"from_month": "2026-04"},
        {"members": ("Alex=750", "Bea=750")}, {"categories": ("Dining=100",)},
    ])
    def test_the_token_covers_every_field_typed(self, ledger, change):
        revision = ledger.plan_preview_revision()
        ledger.refused(lambda: ledger.set_plan(revision=revision, **change), STALE_BUDGET_PREVIEW)

    def test_the_token_covers_the_months_a_plan_affects(self, ledger):
        revision = ledger.plan_preview_revision()
        # A race: another connection records a later plan, so this one now ends in May.
        ledger.set_plan_ok(from_month="2026-06")
        assert "Changes the plan in effect for: 2026-03 to 2026-05" in ledger.plan_preview_ok()
        ledger.refused(lambda: ledger.set_plan(revision=revision), STALE_BUDGET_PREVIEW)

    def test_the_token_covers_the_correction(self, ledger):
        revision = ledger.plan_preview_revision(from_month="2026-04", correct=True)
        assert ledger.set_plan(revision=revision, from_month="2026-04", correct=True)[0] == 0
        revision = ledger.plan_preview_revision(from_month="2026-02", correct=True, as_of="2026-04-01")
        ledger.refused(lambda: ledger.set_plan(revision=revision, from_month="2026-02",
                                               correct=True, as_of="2026-02-01"),
                       STALE_BUDGET_PREVIEW)

    def test_the_token_covers_the_superseded_plan(self, ledger):
        plan = ledger.set_plan_ok(from_month="2026-04")
        supersede = ledger.plan_token(plan, "Supersede")
        revision = ledger.plan_preview_revision(from_month="2026-04", allowance="1.00",
                                           supersedes=plan)
        # The plan it supersedes now holds fewer months.
        ledger.set_plan_ok(from_month="2026-06")
        ledger.refused(lambda: ledger.set_plan(revision=revision, from_month="2026-04",
                                               allowance="1.00", supersedes=plan,
                                               supersedes_revision=supersede),
                       STALE_SUPERSEDED_REVISION)
        assert ledger.plan_token(plan, "Supersede") != supersede

    def test_a_fault_after_the_first_insert_leaves_nothing(self, ledger, monkeypatch):
        revision = ledger.plan_preview_revision(members=("Alex=900", "Bea=600"))
        conn = ledger.conn()
        before = logical_digest(conn)
        conn.close()

        def fail(conn, plan_id, checked):
            raise RuntimeError("injected")

        monkeypatch.setattr(budgets, "insert_parts", fail)
        code, _, err = ledger.set_plan(revision=revision, members=("Alex=900", "Bea=600"))
        assert code == 2 and "unexpected" in err
        conn = ledger.conn()
        assert logical_digest(conn) == before
        conn.close()

    def test_no_budget_write_changes_the_evidence(self, ledger):
        before = ledger.evidence()
        plan = ledger.set_plan_ok(members=("Alex=900", "Bea=600"), categories=("Dining=50",))
        newer = ledger.set_plan_ok(allowance="1.00", supersedes=plan)
        assert ledger.undo_plan(newer)[0] == 0
        assert ledger.undo_plan(plan)[0] == 0
        assert ledger.evidence() == before

    def test_read_commands_write_nothing(self, ledger):
        plan = ledger.set_plan_ok()
        conn = ledger.conn()
        before = logical_digest(conn)
        conn.close()
        for words in (("budgets",), ("budget", "show", plan),
                      ("budget", "preview", *ledger.plan_words(from_month="2026-05"))):
            assert ledger.run(*words)[0] == 0
        conn = ledger.conn()
        assert logical_digest(conn) == before
        conn.close()

    def test_names_are_escaped(self, ledger):
        assert ledger.run("category", "add", "Eat\x1b[31m")[0] == 0
        out = ledger.plan_preview_ok(categories=("Eat\x1b[31m=5",))
        assert "\x1b" not in out


# BA4: the plan in effect, and chains.

class TestPlanInEffect:  # BA4
    def test_the_newest_applying_plan_from_a_month_no_later(self, ledger):
        march = ledger.set_plan_ok(from_month="2026-03")
        june = ledger.set_plan_ok(from_month="2026-06", allowance="1800.00")
        april = ledger.set_plan_ok(from_month="2026-04", allowance="1600.00")
        plans = ledger.plans()
        expected = {"2026-02": None, "2026-03": march, "2026-04": april, "2026-05": april,
                    "2026-06": june, "2027-01": june}
        assert {month: (plan_in_effect(plans, month) or None) and
                plan_in_effect(plans, month).plan_id for month in expected} == expected
        assert "  In effect: 2026-04 to 2026-05" in ledger.plan_shown(april)
        assert "  In effect: 2026-03 to 2026-03" in ledger.plan_shown(march)

    def test_supersede_replaces_and_undo_steps_back(self, ledger):
        plan = ledger.set_plan_ok(from_month="2026-04")
        newer = ledger.set_plan_ok(from_month="2026-05", allowance="1.00", supersedes=plan)
        plans = ledger.plans()
        assert plan_in_effect(plans, "2026-04") is None
        assert plan_in_effect(plans, "2026-05").plan_id == newer
        assert f"  Superseded by {newer}, which applies instead." in ledger.plan_shown(plan)
        assert ledger.undo_plan(newer)[0] == 0
        assert plan_in_effect(ledger.plans(), "2026-04").plan_id == plan
        assert "Status: undone" in ledger.plan_shown(newer)

    def test_a_superseded_or_undone_plan_is_refused(self, ledger):
        plan = ledger.set_plan_ok(from_month="2026-04")
        supersede = ledger.plan_token(plan, "Supersede")
        newer = ledger.set_plan_ok(from_month="2026-04", allowance="1.00", supersedes=plan,
                                   supersedes_revision=supersede)
        superseded = PLAN_REFUSALS.superseded.format(newest=newer)
        ledger.refused(lambda: ledger.undo_plan(plan, revision="bp1-0000000000000000"),
                       superseded)
        ledger.refused(lambda: ledger.plan_preview(from_month="2026-05", supersedes=plan,
                                              supersedes_revision=supersede), superseded)
        assert ledger.undo_plan(newer)[0] == 0
        ledger.refused(lambda: ledger.undo_plan(newer, revision="bp1-0000000000000000"),
                       PLAN_REFUSALS.not_active)
        ledger.refused(lambda: ledger.undo_plan("nope", revision="bp1-0000000000000000"),
                       PLAN_REFUSALS.not_found)

    def test_a_stale_undo_token(self, ledger):
        plan = ledger.set_plan_ok(from_month="2026-04")
        undo, supersede = ledger.plan_token(plan, "Undo"), ledger.plan_token(plan, "Supersede")
        assert undo != supersede
        ledger.refused(lambda: ledger.undo_plan(plan, revision=supersede), STALE_BUDGET_REVISION)
        ledger.set_plan_ok(from_month="2026-06")
        ledger.refused(lambda: ledger.undo_plan(plan, revision=undo), STALE_BUDGET_REVISION)

    def test_superseding_a_closed_months_plan_needs_the_flag(self, ledger):
        plan = ledger.set_plan_ok(from_month="2026-03")
        ledger.refused(lambda: ledger.plan_preview(from_month="2026-04", supersedes=plan,
                                              as_of="2026-04-02"),
                       CLOSED_MONTH.format(month="2026-03"))
        newer = ledger.set_plan_ok(from_month="2026-04", supersedes=plan, correct=True,
                                   as_of="2026-04-02")
        assert next(other for other in ledger.plans() if other.plan_id == newer
                    ).corrected_closed_month

    def test_an_undo_that_changes_a_closed_month_is_refused(self, ledger):
        plan = ledger.set_plan_ok(from_month="2026-03")
        ledger.refused(lambda: ledger.undo_plan(plan, as_of="2026-04-01"),
                       UNDO_CLOSED_MONTH.format(month="2026-03"))
        later = ledger.set_plan_ok(from_month="2026-05", as_of="2026-04-01")
        assert ledger.undo_plan(later, as_of="2026-04-01")[0] == 0

    def test_an_undo_that_would_put_two_plans_on_one_month_is_refused(self, ledger):
        plan = ledger.set_plan_ok(from_month="2026-04")
        newer = ledger.set_plan_ok(from_month="2026-05", supersedes=plan)
        other = ledger.set_plan_ok(from_month="2026-04", allowance="1.00")
        ledger.refused(lambda: ledger.undo_plan(newer),
                       UNDO_MONTH_TAKEN.format(restored=plan, month="2026-04", plan=other))

    def test_budgets_lists_every_plan(self, ledger):
        plan = ledger.set_plan_ok(from_month="2026-04")
        newer = ledger.set_plan_ok(from_month="2026-04", allowance="1.00", supersedes=plan)
        code, out, _ = ledger.run("budgets")
        assert code == 0
        assert re.search(rf"Budget plan {plan}: superseded, from 2026-04, discretionary allowance, planned "
                         r"1500\.00 a month, made ", out)
        assert re.search(rf"Budget plan {newer}: active, from 2026-04, discretionary allowance, planned "
                         r"1\.00 a month, made ", out)
        assert "\nBudget plans: 2\n" in out
