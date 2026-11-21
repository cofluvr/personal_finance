"""Financial scenarios and their dated inputs (D-074 points 1 and 2, the M18.1 slice plan).

A scenario is a name, whether its uncertain inputs count, and its inputs, all append-only (G2).
Changing an input is undo then add. The baseline is the active plan, read live and never copied,
so an input replacing an entry that no longer applies is target_changed: disclosed, left out of
every projection, and never moved to another entry (point 1). Every write runs under one write
lock with its sc1 token, and changes no ledger table (G1). Nothing here reads the clock.
"""

import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date

from personal_finance.planning.entries import (
    checked_cadence,
    in_one_write,
    parsed_amount,
    parsed_date,
    refuse_unless_revision,
)
from personal_finance.planning.loans import parsed_rate
from personal_finance.planning.schedules import (
    Cadence,
    cadence_dates,
    on_cadence,
    parsed_cadence,
)
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reconcile.household_effects import parse_percent
from personal_finance.reports.category_rule_evidence import digest

# Bump whenever the material below changes, so an old token can never appear current.
SCENARIO_REVISION_VERSION = 1

INCOME = "income"
BONUS = "bonus"
EXPENSE = "expense"
ANNUAL_EXPENSE = "annual_expense"
PURCHASE = "purchase"
HOME_PURCHASE = "home_purchase"
LOAN_PAYOFF = "loan_payoff"
BORROWING = "borrowing"
KINDS = (INCOME, BONUS, EXPENSE, ANNUAL_EXPENSE, PURCHASE, HOME_PURCHASE, LOAN_PAYOFF, BORROWING)
ONCE_KINDS = (BONUS, PURCHASE, HOME_PURCHASE, LOAN_PAYOFF, BORROWING)
# Money in, the rest money out (point 2: the amount is positive, signed by kind).
MONEY_IN_KINDS = (INCOME, BONUS, BORROWING)
ONCE = "once"

SOURCE = "income_source"
OBLIGATION = "recurring_obligation"
FUND = "fund"
# What each kind may replace (point 2).
REPLACES = {INCOME: SOURCE, EXPENSE: OBLIGATION, ANNUAL_EXPENSE: FUND}

# Input states (the M18.1 slice plan point 4).
ACTIVE = "active"
UNDONE = "undone"
TARGET_CHANGED = "target_changed"

ADD_INPUT = "add_input"
UNDO_INPUT = "undo_input"
UNDO_SCENARIO = "undo"

# The options each kind takes, by their names as typed. --from is every kind's.
KIND_OPTIONS = {
    INCOME: {"--amount", "--to", "--cadence", "--anchor", "--replaces", "--uncertain", "--gross",
             "--take-home-percent", "--account", "--match"},
    BONUS: {"--amount", "--uncertain", "--confirmed", "--gross", "--take-home-percent"},
    EXPENSE: {"--amount", "--to", "--cadence", "--anchor", "--replaces", "--uncertain",
              "--account", "--match"},
    ANNUAL_EXPENSE: {"--amount", "--to", "--cadence", "--replaces", "--uncertain"},
    PURCHASE: {"--amount", "--uncertain"},
    HOME_PURCHASE: {"--price", "--down-payment", "--closing-costs", "--loan-rate",
                    "--loan-months", "--ownership-costs", "--uncertain"},
    LOAN_PAYOFF: {"--amount", "--loan", "--uncertain"},
    BORROWING: {"--amount", "--loan-rate", "--loan-months", "--uncertain"},
}
KIND_REQUIRES = {
    INCOME: ("--amount", "--cadence"),
    BONUS: ("--amount",),
    EXPENSE: ("--amount", "--cadence"),
    ANNUAL_EXPENSE: ("--amount", "--cadence"),
    PURCHASE: ("--amount",),
    HOME_PURCHASE: ("--price", "--down-payment", "--closing-costs", "--loan-rate",
                    "--loan-months", "--ownership-costs"),
    LOAN_PAYOFF: ("--amount", "--loan"),
    BORROWING: ("--amount", "--loan-rate", "--loan-months"),
}
# Cadences fixed by an anchor that must be typed: which week, or which months.
ANCHORED_CADENCES = ("weekly", "biweekly", "quarterly", "every_months")

NAME_BLANK = "a scenario needs a name that is not blank. Nothing was changed."
SCENARIO_NOT_FOUND = "scenario not found. Run scenarios. Nothing was changed."
SCENARIO_NOT_ACTIVE = "this scenario has already been undone. Nothing was changed."
INPUT_NOT_FOUND = (
    "input not found in this scenario. Run scenario show. Nothing was changed."
)
INPUT_NOT_ACTIVE = "this input has already been undone. Nothing was changed."
KIND_UNKNOWN = (
    "--kind must be income, bonus, expense, annual_expense, purchase, home_purchase, "
    "loan_payoff or borrowing. Nothing was changed."
)
OPTION_NOT_TAKEN = "{option} is not taken by a {kind} input. Nothing was changed."
OPTION_REQUIRED = "a {kind} input needs {option}. Nothing was changed."
AMOUNT_INVALID = "{option} must be an amount of zero or more, such as 250.00. Nothing was changed."
TO_BEFORE_FROM = "--to must be no earlier than --from. Nothing was changed."
ANNUAL_ONLY = "an annual_expense's --cadence is annual:MM-DD. Nothing was changed."
ANCHOR_REQUIRED = (
    "a weekly, biweekly, quarterly or every-N-months cadence needs --anchor, one of its dates. "
    "Nothing was changed."
)
ANCHOR_NOT_TAKEN = (
    "a monthly, semimonthly or annual cadence names its own days, so --anchor is not taken. "
    "Nothing was changed."
)
ANCHOR_OFF_CADENCE = "--anchor must be one of the cadence's own dates. Nothing was changed."
GROSS_NEEDS_PERCENT = (
    "--gross needs --take-home-percent, the share of the gross amount received. Nothing was "
    "changed."
)
PERCENT_NEEDS_GROSS = "--take-home-percent is given only with --gross. Nothing was changed."
TAKE_HOME_RANGE = (
    "--take-home-percent must be a percentage from 1 to 100, with at most two decimals, such as "
    "72.5. Nothing was changed."
)
UNCERTAIN_AND_CONFIRMED = "give --uncertain or --confirmed, not both. Nothing was changed."
REPLACED_WRONG_KIND = (
    "a {kind} input replaces {expected} only, and {entry} is not one. Nothing was changed."
)
REPLACED_NOT_APPLYING = (
    "{entry} does not apply now: it is undone or superseded, so nothing can replace it. "
    "Nothing was changed."
)
REPLACED_NOT_RESERVE = (
    "fund {entry} is not a reserve: an annual_expense replaces a reserve only. Nothing was "
    "changed."
)
DOWN_PAYMENT_ABOVE_PRICE = "--down-payment must be no more than --price. Nothing was changed."
LOAN_MONTHS_INVALID = "--loan-months must be a whole number from 1 to 600. Nothing was changed."
NO_LOAN_TERMS = (
    "{account} has no loan terms, so nothing can pay it off. Run loan terms add first. Nothing "
    "was changed."
)
ACCOUNT_AND_MATCH = (
    "--account and --match are given together, for promoting the input to a source or an "
    "obligation. Nothing was changed."
)
ACCOUNT_ON_REPLACEMENT = (
    "a replacement is promoted onto the entry it replaces, so --account and --match are not "
    "taken. Nothing was changed."
)
MATCH_BLANK = "--match must not be blank. Nothing was changed."
STALE_SCENARIO_REVISION = (
    "this revision does not match the scenario as it is now. Nothing was changed. Run scenario "
    "show and check it again."
)


@dataclass(frozen=True)
class ScenarioInput:
    input_id: str
    scenario_id: str
    kind: str
    amount_cents: int
    from_date: str
    to_date: str | None
    # ONCE, or the cadence as typed.
    cadence: str
    anchor: str | None
    replaces_kind: str | None
    replaces_id: str | None
    uncertain: bool
    gross: bool
    take_home_basis_points: int | None
    down_payment_cents: int | None = None
    closing_costs_cents: int | None = None
    ownership_costs_cents: int | None = None
    loan_rate_millionths: int | None = None
    loan_months: int | None = None
    loan_terms_id: str | None = None
    account_id: str | None = None
    match_text: str | None = None
    created_at: str | None = None
    undone_at: str | None = None
    # ACTIVE, UNDONE or TARGET_CHANGED, worked out against the plan when loaded.
    state: str = ACTIVE

    @property
    def money_in(self) -> bool:
        return self.kind in MONEY_IN_KINDS

    @property
    def take_home_cents(self) -> int:
        """The amount received: gross times the take-home share, rounded down once (G8)."""
        if not self.gross:
            return self.amount_cents
        return self.amount_cents * self.take_home_basis_points // 10_000

    def material(self) -> dict:
        found = asdict(self)
        found.pop("created_at")
        found.pop("undone_at")
        return found


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    name: str
    include_uncertain: bool
    created_at: str
    undone_at: str | None = None
    # In the order made, undone ones included.
    inputs: tuple[ScenarioInput, ...] = field(default_factory=tuple)

    @property
    def applies(self) -> bool:
        return self.undone_at is None

    @property
    def state(self) -> str:
        return UNDONE if self.undone_at else ACTIVE

    def counted(self, input_: ScenarioInput) -> bool:
        """Whether an input enters this scenario's projection (point 2, conservative defaults)."""
        return input_.state == ACTIVE and (self.include_uncertain or not input_.uncertain)


# What the inputs may name, applying now.

@dataclass(frozen=True)
class Targets:
    """The entries a replacement or a payoff may name, by what applies now."""

    applying_sources: frozenset[str]
    applying_obligations: frozenset[str]
    active_funds: dict[str, str]
    active_loan_terms: dict[str, str]
    # Every ID on record of each kind, applying or not, to tell a wrong kind from a stale one.
    every_source: frozenset[str]
    every_obligation: frozenset[str]
    # Every fund's kind, by ID.
    every_fund: dict[str, str]


def load_targets(conn: sqlite3.Connection) -> Targets:
    def ids(sql):
        return frozenset(row[0] for row in conn.execute(sql))

    applying_sources = ids(
        """SELECT source.id FROM income_source source
           WHERE NOT EXISTS (SELECT 1 FROM income_source_event undone
                             WHERE undone.source_id = source.id AND undone.event = 'undone')
             AND NOT EXISTS (SELECT 1 FROM income_source newer
                             WHERE newer.supersedes_id = source.id
                               AND NOT EXISTS (SELECT 1 FROM income_source_event gone
                                               WHERE gone.source_id = newer.id
                                                 AND gone.event = 'undone'))""")
    applying_obligations = ids(
        """SELECT obligation.id FROM recurring_obligation obligation
           WHERE NOT EXISTS (SELECT 1 FROM recurring_obligation_event undone
                             WHERE undone.obligation_id = obligation.id
                               AND undone.event = 'undone')
             AND NOT EXISTS (SELECT 1 FROM recurring_obligation newer
                             WHERE newer.supersedes_id = obligation.id
                               AND NOT EXISTS (SELECT 1 FROM recurring_obligation_event gone
                                               WHERE gone.obligation_id = newer.id
                                                 AND gone.event = 'undone'))""")
    active_funds = dict(conn.execute(
        """SELECT fund.id, fund.kind FROM fund
           WHERE NOT EXISTS (SELECT 1 FROM fund_event undone
                             WHERE undone.fund_id = fund.id AND undone.event = 'undone')"""))
    active_loan_terms = dict(conn.execute(
        """SELECT terms.id, terms.account_id FROM loan_terms terms
           WHERE NOT EXISTS (SELECT 1 FROM loan_terms_event undone
                             WHERE undone.terms_id = terms.id AND undone.event = 'undone')"""))
    return Targets(applying_sources, applying_obligations, active_funds, active_loan_terms,
                   ids("SELECT id FROM income_source"), ids("SELECT id FROM recurring_obligation"),
                   dict(conn.execute("SELECT id, kind FROM fund")))


def target_applies(targets: Targets, kind: str, entry_id: str) -> bool:
    if kind == SOURCE:
        return entry_id in targets.applying_sources
    if kind == OBLIGATION:
        return entry_id in targets.applying_obligations
    if kind == FUND:
        return targets.active_funds.get(entry_id) == "reserve"
    raise ValueError(f"no replaced kind {kind}")


def input_state(input_: ScenarioInput, targets: Targets) -> str:
    if input_.undone_at:
        return UNDONE
    if input_.replaces_kind and not target_applies(targets, input_.replaces_kind,
                                                   input_.replaces_id):
        return TARGET_CHANGED
    if input_.loan_terms_id and input_.loan_terms_id not in targets.active_loan_terms:
        return TARGET_CHANGED
    return ACTIVE


# Loading.

INPUT_COLUMNS = """input.id, input.scenario_id, input.kind, input.amount_cents, input.from_date,
    input.to_date, input.cadence, input.anchor, input.replaces_kind, input.replaces_id,
    input.uncertain, input.gross, input.take_home_basis_points, input.down_payment_cents,
    input.closing_costs_cents, input.ownership_costs_cents, input.loan_rate_millionths,
    input.loan_months, input.loan_terms_id, input.account_id, input.match_text,
    input.created_at, undone.created_at"""


def load_scenarios(conn: sqlite3.Connection) -> tuple[Scenario, ...]:
    """Every scenario on record with its inputs, each input's state worked out against the plan
    as it applies now, in the order made."""
    targets = load_targets(conn)
    inputs_by_scenario = {}
    for row in conn.execute(
            f"""SELECT {INPUT_COLUMNS}
                FROM scenario_input input
                LEFT JOIN scenario_input_event undone
                    ON undone.input_id = input.id AND undone.event = 'undone'
                ORDER BY input.created_at, input.id"""):
        (input_id, scenario_id, kind, amount, from_date, to_date, cadence, anchor, replaces_kind,
         replaces_id, uncertain, gross, take_home, down, closing, ownership, rate, months,
         loan_terms_id, account_id, match_text, created_at, undone_at) = row
        input_ = ScenarioInput(input_id, scenario_id, kind, amount, from_date, to_date, cadence,
                               anchor, replaces_kind, replaces_id, bool(uncertain), bool(gross),
                               take_home, down, closing, ownership, rate, months, loan_terms_id,
                               account_id, match_text, created_at, undone_at)
        input_ = ScenarioInput(**{**vars(input_), "state": input_state(input_, targets)})
        inputs_by_scenario.setdefault(scenario_id, []).append(input_)
    return tuple(
        Scenario(scenario_id, name, bool(include_uncertain), created_at, undone_at,
                 tuple(inputs_by_scenario.get(scenario_id, ())))
        for scenario_id, name, include_uncertain, created_at, undone_at in conn.execute(
            """SELECT scenario.id, scenario.name, scenario.include_uncertain,
                      scenario.created_at, undone.created_at
               FROM scenario
               LEFT JOIN scenario_event undone
                   ON undone.scenario_id = scenario.id AND undone.event = 'undone'
               ORDER BY scenario.created_at, scenario.id"""))


def find_scenario(conn: sqlite3.Connection, scenario_id: str) -> Scenario:
    found = next((scenario for scenario in load_scenarios(conn)
                  if scenario.scenario_id == scenario_id), None)
    if found is None:
        raise DecisionRefused(SCENARIO_NOT_FOUND)
    return found


def find_active_scenario(conn: sqlite3.Connection, scenario_id: str) -> Scenario:
    scenario = find_scenario(conn, scenario_id)
    if not scenario.applies:
        raise DecisionRefused(SCENARIO_NOT_ACTIVE)
    return scenario


# The token.

def scenario_material(scenario: Scenario) -> dict:
    return {"scenario_id": scenario.scenario_id, "name": scenario.name,
            "include_uncertain": scenario.include_uncertain, "state": scenario.state,
            "inputs": [input_.material() for input_ in scenario.inputs]}


def scenario_revision(scenario: Scenario, operation: str, input_id: str | None = None) -> str:
    """sc1 covers the operation, the input it acts on if any, and the scenario's name, flag and
    state with every input and its state (the M18.1 slice plan point 3)."""
    material = {"operation": operation, "input_id": input_id,
                "scenario": scenario_material(scenario)}
    return f"sc{SCENARIO_REVISION_VERSION}-{digest(material)}"


# Inputs as typed.

@dataclass(frozen=True)
class InputRequest:
    """What a person typed for scenario input add. Account IDs are resolved by the caller."""

    kind: str
    from_date: str
    amount: str | None = None
    to_date: str | None = None
    cadence: str | None = None
    anchor: str | None = None
    replaces: str | None = None
    uncertain: bool = False
    confirmed: bool = False
    gross: bool = False
    take_home_percent: str | None = None
    price: str | None = None
    down_payment: str | None = None
    closing_costs: str | None = None
    loan_rate: str | None = None
    loan_months: str | None = None
    ownership_costs: str | None = None
    loan_account_id: str | None = None
    account_id: str | None = None
    match: str | None = None

    def given(self) -> set[str]:
        """Each option given, by its name as typed."""
        names = {"amount": "--amount", "to_date": "--to", "cadence": "--cadence",
                 "anchor": "--anchor", "replaces": "--replaces", "uncertain": "--uncertain",
                 "confirmed": "--confirmed", "gross": "--gross",
                 "take_home_percent": "--take-home-percent", "price": "--price",
                 "down_payment": "--down-payment", "closing_costs": "--closing-costs",
                 "loan_rate": "--loan-rate", "loan_months": "--loan-months",
                 "ownership_costs": "--ownership-costs", "loan_account_id": "--loan",
                 "account_id": "--account", "match": "--match"}
        return {option for name, option in names.items()
                if getattr(self, name) not in (None, False)}


def amount_typed(text: str, option: str) -> int:
    return parsed_amount(text, AMOUNT_INVALID.format(option=option), least=0)


def annual_anchor(cadence: Cadence, month: int, from_date: str) -> date:
    """Any date of an annual cadence fixes its month: the first on or after from_date."""
    start = date.fromisoformat(from_date)
    for year in (start.year, start.year + 1):
        found = cadence_dates(cadence, date(year, month, 1), max(start, date(year, month, 1)),
                              date(year, 12, 31))
        if found:
            return found[0]
    raise ValueError("an annual cadence with no date in two years")


def stream_cadence(cadence_text: str, anchor_text: str | None,
                   from_date: str) -> tuple[Cadence, date]:
    """A recurring input's cadence and the anchor fixing its dates, refused if mistyped."""
    stated = checked_cadence(cadence_text)
    cadence = stated.cadence
    if cadence.name in ANCHORED_CADENCES:
        if anchor_text is None:
            raise DecisionRefused(ANCHOR_REQUIRED)
        anchor = date.fromisoformat(parsed_date(anchor_text, "--anchor"))
        if not on_cadence(cadence, anchor):
            raise DecisionRefused(ANCHOR_OFF_CADENCE)
        return cadence, anchor
    if anchor_text is not None:
        raise DecisionRefused(ANCHOR_NOT_TAKEN)
    if cadence.name == "annual":
        return cadence, annual_anchor(cadence, stated.month, from_date)
    return cadence, date.fromisoformat(from_date)


def input_cadence(input_: ScenarioInput) -> tuple[Cadence, date]:
    """A stored recurring input's cadence and anchor."""
    return stream_cadence(input_.cadence, input_.anchor, input_.from_date)


def checked_input(conn: sqlite3.Connection, scenario: Scenario,
                  request: InputRequest) -> ScenarioInput:
    """An input as typed, refused for anything it gets wrong, in a fixed order. Nothing is
    written."""
    kind = request.kind
    if kind not in KINDS:
        raise DecisionRefused(KIND_UNKNOWN)
    given = request.given()
    not_taken = sorted(given - KIND_OPTIONS[kind])
    if not_taken:
        raise DecisionRefused(OPTION_NOT_TAKEN.format(option=not_taken[0], kind=kind))
    for option in KIND_REQUIRES[kind]:
        if option not in given:
            raise DecisionRefused(OPTION_REQUIRED.format(kind=kind, option=option))
    from_date = parsed_date(request.from_date, "--from")
    to_date = None
    if request.to_date is not None:
        to_date = parsed_date(request.to_date, "--to")
        if to_date < from_date:
            raise DecisionRefused(TO_BEFORE_FROM)
    if request.uncertain and request.confirmed:
        raise DecisionRefused(UNCERTAIN_AND_CONFIRMED)
    uncertain = request.uncertain or (kind == BONUS and not request.confirmed)
    amount = amount_typed(request.price if kind == HOME_PURCHASE else request.amount,
                          "--price" if kind == HOME_PURCHASE else "--amount")

    cadence, anchor = ONCE, None
    if kind not in ONCE_KINDS:
        if kind == ANNUAL_EXPENSE and not request.cadence.startswith("annual:"):
            raise DecisionRefused(ANNUAL_ONLY)
        stated, fixed_by = stream_cadence(request.cadence, request.anchor, from_date)
        cadence = request.cadence
        anchor = fixed_by.isoformat() if stated.name in ANCHORED_CADENCES else None

    if request.gross and request.take_home_percent is None:
        raise DecisionRefused(GROSS_NEEDS_PERCENT)
    if request.take_home_percent is not None and not request.gross:
        raise DecisionRefused(PERCENT_NEEDS_GROSS)
    take_home = None
    if request.gross:
        take_home = parse_percent(request.take_home_percent)
        if take_home is None or not 100 <= take_home <= 10_000:
            raise DecisionRefused(TAKE_HOME_RANGE)

    replaces_kind = replaces_id = None
    if request.replaces is not None:
        replaces_kind, replaces_id = REPLACES[kind], request.replaces
        refuse_unless_replaceable(load_targets(conn), kind, replaces_kind, replaces_id)

    down = closing = ownership = rate = months = None
    if kind == HOME_PURCHASE:
        down = amount_typed(request.down_payment, "--down-payment")
        closing = amount_typed(request.closing_costs, "--closing-costs")
        ownership = amount_typed(request.ownership_costs, "--ownership-costs")
        if down > amount:
            raise DecisionRefused(DOWN_PAYMENT_ABOVE_PRICE)
    if kind in (HOME_PURCHASE, BORROWING):
        rate = parsed_rate(request.loan_rate)
        if not request.loan_months.isdigit() or not 1 <= int(request.loan_months) <= 600:
            raise DecisionRefused(LOAN_MONTHS_INVALID)
        months = int(request.loan_months)

    loan_terms_id = None
    if kind == LOAN_PAYOFF:
        loan_terms_id = next((terms_id for terms_id, account_id
                              in load_targets(conn).active_loan_terms.items()
                              if account_id == request.loan_account_id), None)
        if loan_terms_id is None:
            (name,) = conn.execute("SELECT display_name FROM account WHERE id = ?",
                                   (request.loan_account_id,)).fetchone()
            raise DecisionRefused(NO_LOAN_TERMS.format(account=name))

    if (request.account_id is None) != (request.match is None):
        raise DecisionRefused(ACCOUNT_AND_MATCH)
    if request.match is not None and not request.match.strip():
        raise DecisionRefused(MATCH_BLANK)
    if request.account_id is not None and replaces_id is not None:
        raise DecisionRefused(ACCOUNT_ON_REPLACEMENT)

    return ScenarioInput("proposed", scenario.scenario_id, kind, amount, from_date, to_date,
                         cadence, anchor, replaces_kind, replaces_id, uncertain, request.gross,
                         take_home, down, closing, ownership, rate, months, loan_terms_id,
                         request.account_id, request.match)


def refuse_unless_replaceable(targets: Targets, kind: str, replaces_kind: str,
                              entry_id: str) -> None:
    every = {SOURCE: targets.every_source, OBLIGATION: targets.every_obligation,
             FUND: targets.every_fund}[replaces_kind]
    if entry_id not in every:
        expected = {SOURCE: "an income source", OBLIGATION: "a recurring obligation",
                    FUND: "a reserve"}[replaces_kind]
        raise DecisionRefused(REPLACED_WRONG_KIND.format(kind=kind, expected=expected,
                                                         entry=entry_id))
    if replaces_kind == FUND and targets.every_fund[entry_id] != "reserve":
        raise DecisionRefused(REPLACED_NOT_RESERVE.format(entry=entry_id))
    if not target_applies(targets, replaces_kind, entry_id):
        raise DecisionRefused(REPLACED_NOT_APPLYING.format(entry=entry_id))


# Writes.

def add_scenario(conn: sqlite3.Connection, name: str, include_uncertain: bool) -> str:
    """Record a scenario with no inputs. Nothing is compared or covered yet, so no token."""
    if not name.strip() or name != name.strip():
        raise DecisionRefused(NAME_BLANK)
    return in_one_write(conn, lambda: _add_scenario(conn, name, include_uncertain))


def _add_scenario(conn, name, include_uncertain) -> str:
    scenario_id = str(uuid.uuid4())
    conn.execute("INSERT INTO scenario (id, name, include_uncertain) VALUES (?, ?, ?)",
                 (scenario_id, name, int(include_uncertain)))
    conn.execute("INSERT INTO scenario_event (scenario_id, event) VALUES (?, 'made')",
                 (scenario_id,))
    return scenario_id


def add_input(conn: sqlite3.Connection, scenario_id: str, request: InputRequest,
              revision: str) -> str:
    """Add an input to an active scenario whose sc1 is still current, or refuse and change
    nothing."""
    return in_one_write(conn, lambda: _add_input(conn, scenario_id, request, revision))


def _add_input(conn, scenario_id, request, revision) -> str:
    scenario = find_active_scenario(conn, scenario_id)
    checked = checked_input(conn, scenario, request)
    refuse_unless_revision(scenario_revision(scenario, ADD_INPUT), revision,
                           STALE_SCENARIO_REVISION)
    input_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO scenario_input (id, scenario_id, kind, amount_cents, from_date, to_date,
               cadence, anchor, replaces_kind, replaces_id, uncertain, gross,
               take_home_basis_points, down_payment_cents, closing_costs_cents,
               ownership_costs_cents, loan_rate_millionths, loan_months, loan_terms_id,
               account_id, match_text)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (input_id, scenario_id, checked.kind, checked.amount_cents, checked.from_date,
         checked.to_date, checked.cadence, checked.anchor, checked.replaces_kind,
         checked.replaces_id, int(checked.uncertain), int(checked.gross),
         checked.take_home_basis_points, checked.down_payment_cents, checked.closing_costs_cents,
         checked.ownership_costs_cents, checked.loan_rate_millionths, checked.loan_months,
         checked.loan_terms_id, checked.account_id, checked.match_text))
    conn.execute("INSERT INTO scenario_input_event (input_id, event) VALUES (?, 'made')",
                 (input_id,))
    return input_id


def undo_input(conn: sqlite3.Connection, scenario_id: str, input_id: str,
               revision: str) -> ScenarioInput:
    """Stop an input counting, keeping it on record, or refuse and change nothing."""
    return in_one_write(conn, lambda: _undo_input(conn, scenario_id, input_id, revision))


def _undo_input(conn, scenario_id, input_id, revision) -> ScenarioInput:
    scenario = find_active_scenario(conn, scenario_id)
    input_ = next((input_ for input_ in scenario.inputs if input_.input_id == input_id), None)
    if input_ is None:
        raise DecisionRefused(INPUT_NOT_FOUND)
    if input_.undone_at:
        raise DecisionRefused(INPUT_NOT_ACTIVE)
    refuse_unless_revision(scenario_revision(scenario, UNDO_INPUT, input_id), revision,
                           STALE_SCENARIO_REVISION)
    conn.execute("INSERT INTO scenario_input_event (input_id, event) VALUES (?, 'undone')",
                 (input_id,))
    return input_


def undo_scenario(conn: sqlite3.Connection, scenario_id: str, revision: str) -> Scenario:
    """Stop a scenario applying, keeping it and its inputs on record, or refuse and change
    nothing. Its promotion, if any, is undone on its own: undoing a scenario changes no plan."""
    return in_one_write(conn, lambda: _undo_scenario(conn, scenario_id, revision))


def _undo_scenario(conn, scenario_id, revision) -> Scenario:
    scenario = find_active_scenario(conn, scenario_id)
    refuse_unless_revision(scenario_revision(scenario, UNDO_SCENARIO), revision,
                           STALE_SCENARIO_REVISION)
    conn.execute("INSERT INTO scenario_event (scenario_id, event) VALUES (?, 'undone')",
                 (scenario_id,))
    return scenario


# Describing an input, the same in the terminal and the UI.

def input_words(input_: ScenarioInput, format_amount, format_rate) -> str:
    """One input in a sentence: its kind, amount, dates, cadence and distinctions."""
    parts = [input_.kind]
    if input_.kind == HOME_PURCHASE:
        parts.append(f"price {format_amount(input_.amount_cents)}, down payment "
                     f"{format_amount(input_.down_payment_cents)}, closing costs "
                     f"{format_amount(input_.closing_costs_cents)}, ownership costs "
                     f"{format_amount(input_.ownership_costs_cents)} a month")
    else:
        parts.append(format_amount(input_.amount_cents)
                     + (" in" if input_.money_in else " out"))
    if input_.loan_rate_millionths is not None:
        parts.append(f"loan {format_rate(input_.loan_rate_millionths)} over "
                     f"{input_.loan_months} months")
    dates = f"from {input_.from_date}"
    if input_.to_date:
        dates += f" to {input_.to_date}"
    parts.append(dates if input_.cadence != ONCE else f"once on {input_.from_date}")
    if input_.cadence != ONCE:
        parts.append(input_.cadence + (f" anchored {input_.anchor}" if input_.anchor else ""))
    if input_.gross:
        whole, fraction = divmod(input_.take_home_basis_points, 100)
        parts.append(f"gross, take-home {whole}.{fraction:02d}%")
    parts.append(f"replaces {input_.replaces_kind.replace('_', ' ')} {input_.replaces_id}"
                 if input_.replaces_id else "additional")
    if input_.loan_terms_id:
        parts.append(f"loan terms {input_.loan_terms_id}")
    parts.append("uncertain" if input_.uncertain else "confirmed")
    if input_.account_id:
        parts.append(f"promoted on account {input_.account_id}")
    return ", ".join(parts)
