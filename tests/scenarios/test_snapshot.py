"""The snapshot's builder and format, using synthetic data only (VA1 to VA5, D-075 points 1 to 3,
5 and 6, the M19.1 slice plan). Creating, verifying and listing are test_snapshot_files.py."""

import copy
import json
import os
import re
import uuid
from datetime import date
from pathlib import Path

import pytest
from test_household import HouseholdLedger
from test_scenario_promotion import PromotionLedger
from test_safe_to_spend import AS_OF

from personal_finance.money import format_cents
from personal_finance.snapshot import builder, canonical, validate

SNAPSHOTS = Path(__file__).parents[1] / "fixtures" / "synthetic" / "snapshots"
FIXTURES = SNAPSHOTS / "v1.1"
# The previous minor, kept to show 1.1 only added optional fields (D-080).
EARLIER_MINOR = SNAPSHOTS / "v1.0"
SNAPSHOT_ID = "0b4a4b64-6f2e-4c4e-9a8e-3c8f9d7c1a22"
GENERATED_AT = "2026-05-04T17:00:00.000Z"
# Every import is given this time, so the last import's date is fixed in a golden fixture.
IMPORTED_AT = "2026-05-02T12:00:00.000Z"
SECTIONS = ("cutoff", "period", "household", "accounts", "months", "budget", "safe_to_spend",
            "funds", "loans", "net_worth", "transactions", "warnings", "review", "assumptions")


class SnapshotLedger(PromotionLedger, HouseholdLedger):
    def snapshot(self, as_of=AS_OF, window_days=90) -> bytes:
        conn = self.conn()
        try:
            return builder.build_snapshot(conn, date.fromisoformat(as_of), window_days,
                                          SNAPSHOT_ID, GENERATED_AT)
        finally:
            conn.close()

    def content(self, **options) -> dict:
        return json.loads(self.snapshot(**options))["content"]

    def fix_import_times(self):
        conn = self.conn()
        try:
            (trigger,) = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'trigger' "
                                      "AND name = 'source_document_no_update'").fetchone()
            conn.execute("DROP TRIGGER source_document_no_update")
            conn.execute("UPDATE source_document SET imported_at = ?", (IMPORTED_AT,))
            conn.execute(trigger)
        finally:
            conn.close()


@pytest.fixture
def deterministic_ids(monkeypatch):
    """uuid4 as a counter, so every ID a ledger generates is the same on every run."""
    counter = iter(range(1, 1_000_000))
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(int=next(counter), version=4))


def household(ledger, members=()):
    """The test ledgers' two members, Alex and Bea, sharing A 50/50, a salary paid into A on 1 May, power paid on 5 April, a
    card with a categorized purchase, a mortgage with terms and an owed balance, a reserve, a
    budget plan and a buffer."""
    assert ledger.set_setting()[0] == 0

    ledger.set_share_ok("Alex=50", "Bea=50")
    ledger.set_default_ok("A")
    ledger.salary = ledger.add_ok()
    ledger.deposit("pay-may.csv", "2026-05-01")
    ledger.observe("A", "2026-05-01", "5000.00")
    ledger.liquid_ok("A")
    ledger.power = ledger.ob_add_ok()
    ledger.pay("power-apr.csv", "2026-04-05")
    ledger.add_typed_account("Mortgage", "loan")
    ledger.add_terms_ok("Mortgage")
    ledger.observe("Mortgage", "2026-04-20", "200000.00", option="--owed")
    ledger.reserve = ledger.add_fund_ok(name="Insurance", kind="reserve", target="1200.00",
                                        cadence="annual:06-10", as_of=AS_OF)
    ledger.budget_plan_ok(from_month="2026-05", allowance="1500.00", as_of=AS_OF, members=members)
    ledger.set_buffer("500.00")
    return ledger


@pytest.fixture
def ledger(tmp_path, capsys, deterministic_ids):
    built = household(SnapshotLedger(tmp_path, capsys))
    built.fix_import_times()
    return built


class TestFormat:  # VA1, point 1
    def test_fixed_inputs_give_identical_canonical_bytes(self, ledger):
        first, second = ledger.snapshot(), ledger.snapshot()
        assert first == second
        assert canonical.parsed_canonical(first) == json.loads(first)
        assert canonical.canonical_bytes(json.loads(first)) == first

    def test_the_envelope(self, ledger):
        document = json.loads(ledger.snapshot())
        assert sorted(document) == ["content", "content_sha256", "format", "generated_at",
                                    "schema_version", "snapshot_id"]
        assert (document["format"], document["schema_version"], document["snapshot_id"],
                document["generated_at"]) == ("commoncents-snapshot", builder.SCHEMA_VERSION, SNAPSHOT_ID,
                                              GENERATED_AT)
        assert document["content_sha256"] == canonical.sha256_of(document["content"])

    @pytest.mark.parametrize("value", [1.5, {"a": [0, 2.0]}, {1: "x"}, float("nan"), {"a": b"x"}])
    def test_a_float_or_any_non_json_value_is_refused(self, value):
        with pytest.raises(canonical.NotCanonical):
            canonical.canonical_bytes(value)

    def test_a_float_from_any_section_fails_the_build(self, ledger, monkeypatch):
        monkeypatch.setattr(builder, "review_section", lambda conn: {"possible_duplicate": 0.0})
        with pytest.raises(canonical.NotCanonical, match="float"):
            ledger.snapshot()

    @pytest.mark.parametrize("text", [b'{"a":1.0}', b'{"a": 1}', b'{"b":1,"a":2}', b'{"a":NaN}',
                                      b"\xff"])
    def test_bytes_not_in_canonical_form_are_refused(self, text):
        with pytest.raises(canonical.NotCanonical):
            canonical.parsed_canonical(text)


class TestContents:  # VA2, point 2
    def test_every_section_is_present_and_valid(self, ledger):
        document = json.loads(ledger.snapshot())
        assert sorted(document["content"]) == sorted(SECTIONS)
        schema = validate.load_schema()
        assert validate.validate(document, schema) == []
        assert validate.unknown_fields(document, schema["document"]) == []
        assert validate.unreconciled(document["content"]) == []

    def test_numbers_agree_with_their_commands(self, ledger):
        content = ledger.content()
        worth = ledger.run("report", "net-worth", "--as-of", AS_OF)[1]
        assert content["net_worth"]["total_cents"] == -19_500_000
        assert format_cents(content["net_worth"]["total_cents"]) in worth
        safe = ledger.run("safe-to-spend", "--as-of", AS_OF)[1]
        today = re.search(r"today (\S+), this week (\S+)$", safe.splitlines()[0])
        assert (content["safe_to_spend"]["today_cents"],
                content["safe_to_spend"]["week_cents"]) == tuple(
            int(value.replace(".", "")) for value in today.groups())
        budget = ledger.run("report", "budget", "--month", "2026-05", "--as-of", AS_OF)[1]
        assert content["budget"]["target_cents"] == 150_000 and "1500.00" in budget
        monthly = ledger.run("report", "monthly")[1]
        assert [month["month"] for month in content["months"]] == ["2026-02", "2026-03",
                                                                  "2026-04", "2026-05"]
        for month in content["months"]:
            assert format_cents(month["net_cents"]) in monthly, month["month"]
        funds = ledger.run("report", "funds", "--as-of", AS_OF)[1]
        (fund,) = content["funds"]
        assert fund["name"] == "Insurance" and format_cents(
            fund["planned_contribution_cents"]) in funds

    def test_household_months_match_the_household_report(self, ledger):
        content = ledger.content()
        months = content["household"]["months"]
        assert [month["month"] for month in months] == ["2026-02", "2026-04", "2026-05"]
        assert months[-1]["household"] == {"transactions": 1, "out_cents": 0,
                                           "in_cents": 250_000}
        assert [member["in_cents"] for member in months[-1]["members"]] == [125_000, 125_000]
        report = ledger.run("report", "household")[1]
        net = re.search(r"^Net account movement +(\S+) +(\S+) +(\S+) +(\S+)$", report,
                        re.MULTILINE).groups()
        for position in (0, 1):
            moved = sum(member["in_cents"] - member["out_cents"] for month in months
                        for member in month["members"] if member["member_index"] == position)
            assert format_cents(moved) == net[position]
        assert format_cents(sum(month["household"]["in_cents"] - month["household"]["out_cents"]
                                for month in months)) == net[3]
        assert content["household"]["share"] == [{"member_index": 0, "basis_points": 5000},
                                                 {"member_index": 1, "basis_points": 5000}]

    def test_an_account_with_no_default_is_unattributed_by_month(self, ledger):
        ledger.add_typed_account("C", "checking")
        ledger.deposit("gift.csv", "2026-05-02", amount="40.00", account="C")
        content = ledger.content()
        may = content["household"]["months"][-1]
        assert may["unattributed"] == {"transactions": 1, "out_cents": 0, "in_cents": 4_000}
        assert may["household"]["in_cents"] == 254_000
        assert validate.unreconciled(content) == []

    def test_the_window_holds_its_days_only(self, ledger):
        content = ledger.content(window_days=10)
        assert [each["date"] for each in content["transactions"]] == ["2026-05-01"]
        (paycheck,) = content["transactions"]
        assert paycheck["member_parts"] == [{"member_index": 0, "amount_cents": 125_000},
                                            {"member_index": 1, "amount_cents": 125_000}]
        assert paycheck["financial_type"] == "income" and paycheck["account_index"] == 0
        wide = ledger.content(window_days=90)
        assert [each["date"] for each in wide["transactions"]] == ["2026-04-05", "2026-05-01"]
        assert (wide["period"]["window_first_day"], wide["period"]["window_last_day"]) == (
            "2026-02-04", "2026-05-04")
        for days in (0, 367):
            with pytest.raises(ValueError):
                ledger.content(window_days=days)

    def test_provisional_reasons_are_listed_with_their_details(self, ledger):
        content = ledger.content(as_of="2026-05-20")
        reasons = {reason["reason"]: reason["details"]
                   for reason in content["safe_to_spend"]["reasons"]}
        assert reasons["stale_observation"] == ["A observed 2026-05-01"]
        assert {"kind": "provisional", "detail": "stale_observation: A observed 2026-05-01"} \
            in content["warnings"]
        assert validate.validate(json.loads(ledger.snapshot(as_of="2026-05-20")),
                                 validate.load_schema()) == []

    def test_missing_is_null_never_zero(self, tmp_path, capsys, deterministic_ids):
        bare = SnapshotLedger(tmp_path, capsys)
        content = bare.content()
        assert content["budget"] is None and content["safe_to_spend"] is None
        assert content["household"]["timezone"] is None and content["household"]["share"] is None
        (account,) = content["cutoff"]["accounts"]
        assert account["latest_observation_date"] is None
        assert account["transaction_complete_through"] is None
        assert {"kind": "no_timezone", "detail": "the household timezone is not set: budget "
                "pace and safe to spend are left out"} in content["warnings"]


def sentinel_ledger(tmp_path, capsys):
    """Sentinels in every excluded field: an institution and last4, a file name, an external
    ID and raw row, a source description a correction replaces."""
    ledger = SnapshotLedger(tmp_path, capsys)
    assert ledger.set_setting()[0] == 0
    assert ledger.run("account", "add", "--name", "B", "--type", "checking", "--institution",
                      "SENTINELBANK", "--last4", "9876")[0] == 0
    paid = ledger.deposit("SENTINELFILE.csv", "2026-05-01", text="SENTINELDESC PAYROLL",
                          account="B")
    ledger.correct_ok(paid, "description", "Payroll", account="B")
    return ledger


class TestExclusions:  # VA3, point 3
    def test_no_sentinel_reaches_the_snapshot(self, tmp_path, capsys):
        ledger = sentinel_ledger(tmp_path, capsys)
        data = ledger.snapshot().decode("utf-8")
        conn = ledger.conn()
        try:
            hidden = [value for (value,) in conn.execute(
                "SELECT id FROM source_record UNION SELECT id FROM source_document "
                "UNION SELECT content_sha256 FROM source_document UNION SELECT id FROM account")]
        finally:
            conn.close()
        for sentinel in ("SENTINELBANK", "9876", "SENTINELFILE", "SENTINELDESC", *hidden):
            assert sentinel not in data, sentinel
        # No creation timestamp: the only time in the bytes is generated_at.
        assert re.findall(r"\d{4}-\d\d-\d\dT\d\d:\d\d", data) == [GENERATED_AT[:16]]
        assert "Payroll" in data

    def test_the_control_holds_every_sentinel_in_the_ledger(self, tmp_path, capsys):
        ledger = sentinel_ledger(tmp_path, capsys)
        dumped = "\n".join(ledger.conn().iterdump())
        for sentinel in ("SENTINELBANK", "9876", "SENTINELFILE", "SENTINELDESC"):
            assert sentinel in dumped, sentinel

    def test_no_excluded_key_is_written(self, ledger):
        content = ledger.content()
        assert validate.excluded_keys(content) == []
        content["transactions"][0]["created_at"] = "x"
        content["accounts"][0]["last4"] = "1234"
        assert validate.excluded_keys(content) == ["content.accounts[0].last4",
                                                   "content.transactions[0].created_at"]


def mutated(document, path, value):
    changed = copy.deepcopy(document)
    target = changed
    for key in path[:-1]:
        target = target[key]
    if value is KeyError:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return changed


class TestSchema:  # VA4, points 5 and 6
    def test_every_money_field_declares_its_kind(self):
        schema = validate.load_schema()
        assert validate.undeclared_money(schema["document"]) == []
        bad = copy.deepcopy(schema)
        del bad["document"]["fields"]["content"]["fields"]["net_worth"]["fields"][
            "total_cents"]["value_kind"]
        assert validate.undeclared_money(bad["document"]) == [
            "snapshot.content.net_worth.total_cents"]

    def test_the_golden_fixtures_validate(self):
        schema = validate.load_schema()
        fixtures = sorted(FIXTURES.glob("*.json"))
        assert fixtures
        for fixture in fixtures:
            document = canonical.parsed_canonical(fixture.read_bytes())
            assert validate.validate(document, schema) == [], fixture.name
            assert validate.unreconciled(document["content"]) == [], fixture.name

    @pytest.mark.parametrize("path, value, error", [
        (("content", "review", "possible_duplicate"), "0", "is not a integer"),
        (("content", "review", "possible_duplicate"), True, "is not a integer"),
        (("content", "review"), KeyError, "snapshot.content.review is missing"),
        (("content", "net_worth", "total_cents"), None, "is null, and may not be"),
        (("format",), "other", "snapshot.format is not one of its values"),
        (("content", "period", "month"), "May", "is not of its pattern"),
        (("content", "period", "month"), "2026-05x", "is not of its pattern"),
    ])
    def test_each_mutation_is_refused(self, path, value, error):
        schema = validate.load_schema()
        document = canonical.parsed_canonical(sorted(FIXTURES.glob("*.json"))[0].read_bytes())
        errors = validate.validate(mutated(document, path, value), schema)
        assert errors and any(error in found for found in errors), errors

    def test_an_unknown_major_is_refused_and_a_minor_accepted(self):
        schema = validate.load_schema()
        document = canonical.parsed_canonical(sorted(FIXTURES.glob("*.json"))[0].read_bytes())
        (error,) = validate.validate(mutated(document, ("schema_version",), "2.0"), schema)
        assert error.startswith("schema version 2.0 is not supported: this code reads 1.x")
        later = mutated(document, ("schema_version",), "1.7")
        later["content"]["review"]["new_optional_field"] = 3
        assert validate.validate(later, schema) == []

    def test_a_broken_reconciliation_is_found(self, ledger):
        content = ledger.content()
        content["months"][0]["net_cents"] += 1
        content["household"]["months"][0]["unattributed"]["out_cents"] += 1
        assert len(validate.unreconciled(content)) == 2


class TestGoldenFixtures:  # VA5, point 5
    def test_the_builder_gives_the_fixture_byte_for_byte(self, ledger):
        fixture = FIXTURES / "household.json"
        built = ledger.snapshot()
        if os.environ.get("PF_WRITE_SNAPSHOT_FIXTURES"):
            fixture.parent.mkdir(parents=True, exist_ok=True)
            fixture.write_bytes(built)
        assert built == fixture.read_bytes(), (
            "the builder's output changed: update the fixture with a minor or major version "
            "bump, by the compatibility policy (D-075 point 5)")

    def test_each_fixture_is_of_the_schema_s_version(self):
        version = validate.load_schema()["schema_version"]
        assert builder.SCHEMA_VERSION == version
        for fixture in FIXTURES.glob("*.json"):
            assert json.loads(fixture.read_bytes())["schema_version"] == version


class TestMembersBudget:  # D-080
    """Snapshot 1.1: each member's budget pace, as report budget --member prints it."""

    def test_a_plan_without_members_parts_gives_nulls_never_zero(self, ledger):
        members = ledger.content()["budget"]["members"]
        assert [member["member_index"] for member in members] == [0, 1]
        for member in members:
            assert member["target_cents"] is None and member["revised_daily_cents"] is None
            assert member["actual_cents"] == 0

    def test_each_member_agrees_with_report_budget(self, tmp_path, capsys, deterministic_ids):
        built = household(SnapshotLedger(tmp_path, capsys), members=("Alex=900.00", "Bea=600.00"))
        built.pay("groceries.csv", "2026-05-02", amount="-40.00", text="SYNTHETIC GROCER")
        content = built.content()
        budget = content["budget"]
        assert sum(member["target_cents"] for member in budget["members"]) == budget["target_cents"]
        labels = {"target_cents": "Target, planned", "remaining_capacity_cents": "Remaining capacity",
                  "original_daily_cents": "Original daily allowance",
                  "revised_daily_cents": "Revised daily allowance",
                  "revised_weekly_cents": "Revised weekly allowance"}
        for member in budget["members"]:
            name = content["household"]["members"][member["member_index"]]["name"]
            code, out, err = built.run("report", "budget", "--month", "2026-05", "--as-of", AS_OF,
                                       "--member", name)
            assert (code, err) == (0, ""), err
            for field, label in labels.items():
                line = next(line for line in out.splitlines() if line.strip().startswith(label))
                assert line.endswith(f": {format_cents(member[field])}"), (name, line)
            assert member["provisional"] is ("Remaining capacity, budget pace, provisional:" in out)
            assert member["provisional"] is False
        # Money out not yet classified rests every member's capacity on a guess (D-069).
        built.deposit("unknown.csv", "2026-05-03", amount="-12.00", text="SYNTHETIC UNKNOWN",
                      financial_type=None)
        for member in built.content()["budget"]["members"]:
            name = content["household"]["members"][member["member_index"]]["name"]
            out = built.run("report", "budget", "--month", "2026-05", "--as-of", AS_OF,
                            "--member", name)[1]
            assert member["provisional"] is True
            assert "Remaining capacity, budget pace, provisional:" in out

    def test_the_earlier_minor_still_validates(self):
        """1.1 only adds optional fields: a 1.0 snapshot on a phone still reads (D-080 point 2)."""
        schema = validate.load_schema()
        earlier = sorted(EARLIER_MINOR.glob("*.json"))
        assert earlier
        for fixture in earlier:
            document = canonical.parsed_canonical(fixture.read_bytes())
            assert document["schema_version"] == "1.0"
            assert validate.validate(document, schema) == [], fixture.name
            assert "members" not in document["content"]["budget"]
