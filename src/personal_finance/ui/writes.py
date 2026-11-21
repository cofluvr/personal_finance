"""The browser write pipeline (D-073 point 1, M17.1): a security change, approved as one.

Steps 1 and 2, the exact Host and the session cookie, are the server's, shared with every GET.
This module holds steps 3 to 8 as functions over what the request said, so each refuses alone,
and step 9's command line, built from the route's declaration alone (M17.2 slice plan point 1).
W1 is unchanged: the body is decoded here, by a strict decoder of the form encoding, and nothing
of `urllib` is imported. Every refusal is a fixed notice that repeats nothing from the request
(D-037). The write itself is the CLI's own command, run by the server, so a browser decision is
the terminal's, refusals included.
"""

import hashlib
import hmac
import re
import unicodedata
from typing import NamedTuple

from personal_finance.reconcile.classification_effects import FINANCIAL_TYPES
from personal_finance.reconcile.correction_effects import CORRECTABLE_FIELDS

MAXIMUM_BODY_BYTES = 8192
FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"
FORM_TOKEN_FIELD = "form_token"
# An account, item, decision or transaction ID, or a revision token. The first character is
# never "-", so no value could be read as a command-line option even written apart.
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")
AMOUNT = re.compile(r"-?[0-9]{1,12}(\.[0-9]{1,2})?")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
MONTH = re.compile(r"[0-9]{4}-[0-9]{2}")
MAXIMUM_TEXT_LENGTH = 200
MAXIMUM_LIST_LINES = 50

NOT_A_WRITE = "This address takes no form."
NOT_ALLOWED = "Only pages and the forms they show are answered."
FOREIGN_REQUEST = "Requests from other sites are refused."
NOT_A_FORM = "Only a form this interface showed is accepted."
TOO_LARGE = "This form is larger than the interface accepts."
UNREADABLE_FORM = "This form could not be read. Reload the page and try again."
FORM_EXPIRED = (
    "This form has already been used, or was not shown in this session. Reload the page for a "
    "current one. Nothing was changed."
)
VALUE_REFUSED = (
    "A value in this form is not one the interface accepts: IDs, amounts such as -12.50, dates "
    "as YYYY-MM-DD, months as YYYY-MM, and text of up to 200 printable characters. Nothing was "
    "changed."
)

# Field kinds.
ID, CHOICE, AMOUNT_KIND, DATE_KIND, MONTH_KIND, TEXT = (
    "id", "choice", "amount", "date", "month", "text")
PAIR_LINES, GROUP_LINES = "pair_lines", "group_lines"


class Refusal(NamedTuple):
    status: int
    notice: str
    extra_headers: tuple = ()


class Field(NamedTuple):
    name: str
    kind: str
    # The CLI option it fills, such as "--type", or None for the command's positional argument.
    option: str | None
    required: bool = True
    choices: tuple[str, ...] = ()


class WriteRoute(NamedTuple):
    # The CLI command's words, before its arguments.
    words: tuple[str, ...]
    # Fixed by the page and bound by the form token. A field with no option is positional, and
    # positionals follow the words in the order declared, hidden before typed.
    hidden: tuple[Field, ...]
    # Typed or chosen by the person.
    typed: tuple[Field, ...] = ()
    # Options the route always gives, such as --none.
    flags: tuple[str, ...] = ()

    @property
    def field_names(self) -> set[str]:
        return {field.name for field in (*self.hidden, *self.typed)}


def target(name: str) -> Field:
    return Field(name, ID, None)


ACCOUNT = Field("account", ID, "--account")
REVISION = Field("revision", ID, "--revision")
BUFFER_KEY = Field("key", CHOICE, None, choices=("checking_buffer_cents",))
SUPERSEDES = (Field("supersedes", ID, "--supersedes", required=False),
              Field("supersedes_revision", ID, "--supersedes-revision", required=False))

# The allowlist (D-073 point 2), as built so far. Each route runs exactly one CLI command.
WRITE_ROUTES = {
    "/review/reject": WriteRoute(("review", "reject"), (target("item"), ACCOUNT, REVISION),
                                 (Field("pairs", PAIR_LINES, "--pair"),)),
    "/review/confirm": WriteRoute(("review", "confirm"), (target("item"), ACCOUNT, REVISION),
                                  (Field("groups", GROUP_LINES, "--group"),)),
    "/review/undo": WriteRoute(("review", "undo"), (target("decision"), ACCOUNT, REVISION)),
    "/review/complete": WriteRoute(
        ("review", "complete"), (target("item"), ACCOUNT, REVISION),
        (Field("amount", AMOUNT_KIND, "--amount", required=False),
         Field("transaction_date", DATE_KIND, "--transaction-date", required=False),
         Field("posting_date", DATE_KIND, "--posting-date", required=False),
         Field("description", TEXT, "--description", required=False))),
    "/review/dismiss": WriteRoute(("review", "dismiss"), (target("item"), ACCOUNT, REVISION)),
    "/transaction/classify": WriteRoute(
        ("review", "classify"), (target("transaction"), ACCOUNT, REVISION, *SUPERSEDES),
        (Field("type", CHOICE, "--type", choices=tuple(FINANCIAL_TYPES)),)),
    "/transaction/categorize": WriteRoute(
        ("review", "categorize"), (target("transaction"), ACCOUNT, REVISION, *SUPERSEDES),
        (Field("category", TEXT, "--category"),)),
    "/transaction/correct": WriteRoute(
        ("review", "correct"),
        (target("transaction"), ACCOUNT, REVISION,
         Field("field", CHOICE, "--field", choices=CORRECTABLE_FIELDS), *SUPERSEDES),
        (Field("value", TEXT, "--value"),)),
    "/transaction/separate": WriteRoute(
        ("review", "separate"), (target("transaction"), ACCOUNT, REVISION),
        (Field("groups", GROUP_LINES, "--group"),)),
    "/transaction/tag": WriteRoute(
        ("review", "tag"), (target("transaction"), ACCOUNT, REVISION, *SUPERSEDES),
        (Field("tags", TEXT, "--tags"),)),
    "/transaction/tag-none": WriteRoute(
        ("review", "tag"), (target("transaction"), ACCOUNT, REVISION, *SUPERSEDES),
        flags=("--none",)),
    "/transaction/one-sided": WriteRoute(
        ("review", "transfer", "one-sided"), (target("transaction"), ACCOUNT, REVISION),
        (Field("counterpart_account", ID, "--counterpart-account"),)),
    # M17.2b. The buffer is the one setting the browser may make: the timezone changes what
    # "today" means, so it stays in the terminal (point 2).
    "/setting/buffer-set": WriteRoute(
        ("setting", "set"), (BUFFER_KEY, REVISION), (Field("buffer", AMOUNT_KIND, None),)),
    "/setting/buffer-undo": WriteRoute(("setting", "undo"), (BUFFER_KEY, REVISION)),
    "/account/liquidity-set": WriteRoute(("account", "liquidity", "set"), (ACCOUNT, REVISION)),
    "/account/liquidity-undo": WriteRoute(("account", "liquidity", "undo"), (ACCOUNT, REVISION)),
    "/obligation/covers-loan": WriteRoute(
        ("obligation", "covers"), (target("obligation"), REVISION),
        (Field("loan", ID, "--loan"),)),
    "/obligation/covers-fund": WriteRoute(
        ("obligation", "covers"), (target("obligation"), REVISION),
        (Field("fund", ID, "--fund"),)),
    "/obligation/uncover": WriteRoute(("obligation", "uncover"), (target("obligation"), REVISION)),
}


def refuse_route(path: str) -> Refusal | None:
    """Step 3: a route on the allowlist. Any method but GET and POST is refused by the server
    before this, with 405."""
    if path not in WRITE_ROUTES:
        return Refusal(404, NOT_A_WRITE)
    return None


def refuse_origin(origins: list[str] | None, expected_origin: str) -> Refusal | None:
    """Step 4: one Origin, exactly this server's. A missing, foreign or null one is refused."""
    if origins != [expected_origin]:
        return Refusal(403, FOREIGN_REQUEST)
    return None


def refuse_fetch_metadata(sites: list[str] | None, modes: list[str] | None) -> Refusal | None:
    """Step 5: Sec-Fetch-Site, if sent, is same-origin, and Sec-Fetch-Mode, if sent, navigate."""
    if sites is not None and sites != ["same-origin"]:
        return Refusal(403, FOREIGN_REQUEST)
    if modes is not None and modes != ["navigate"]:
        return Refusal(403, FOREIGN_REQUEST)
    return None


def checked_body_length(content_types: list[str] | None, lengths: list[str] | None,
                        transfer_encodings: list[str] | None) -> Refusal | int:
    """Step 6: a plain form's content type, one length within the limit, and no transfer
    encoding. Returns the length to read, so the body stays unread when refused."""
    if content_types != [FORM_CONTENT_TYPE]:
        return Refusal(415, NOT_A_FORM)
    if transfer_encodings is not None:
        return Refusal(413, TOO_LARGE)
    if lengths is None or len(lengths) != 1 or not lengths[0].isascii() or (
            not lengths[0].isdigit()):
        return Refusal(413, TOO_LARGE)
    length = int(lengths[0])
    if length > MAXIMUM_BODY_BYTES:
        return Refusal(413, TOO_LARGE)
    return length


PERCENT_ESCAPE = re.compile(rb"%([0-9A-Fa-f]{2})")


def decoded_form_part(part: bytes) -> str:
    """One name or value of a form body: "+" is a space and %XX a byte, then strict UTF-8. A
    "%" that starts no escape raises ValueError, and invalid UTF-8 UnicodeDecodeError."""
    spaced = part.replace(b"+", b" ")
    if spaced.count(b"%") != len(PERCENT_ESCAPE.findall(spaced)):
        raise ValueError("malformed escape")
    return PERCENT_ESCAPE.sub(lambda match: bytes([int(match.group(1), 16)]),
                              spaced).decode("utf-8")


def parsed_form(body: bytes, route: WriteRoute) -> Refusal | dict[str, str]:
    """Step 7: UTF-8, each field once, exactly the route's fields and the token, each value of
    its field's kind. Point 1's limit of 50 fields is met by that: no route has more than ten."""
    form = {}
    for piece in body.split(b"&") if body else []:
        raw_name, separator, raw_value = piece.partition(b"=")
        try:
            name, value = decoded_form_part(raw_name), decoded_form_part(raw_value)
        except (UnicodeDecodeError, ValueError):
            return Refusal(400, UNREADABLE_FORM)
        if not separator or name in form:
            return Refusal(400, UNREADABLE_FORM)
        form[name] = value
    if set(form) != {*route.field_names, FORM_TOKEN_FIELD}:
        return Refusal(400, UNREADABLE_FORM)
    for field in (*route.hidden, *route.typed):
        if not acceptable(field, form[field.name]):
            return Refusal(400, VALUE_REFUSED)
    return form


def printable_text(text: str) -> bool:
    """Text a person types: no control or format character, so nothing can hide in it."""
    return all(unicodedata.category(char) not in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp")
               for char in text)


def acceptable(field: Field, value: str) -> bool:
    """A value of the field's kind. Empty only where the field is optional, as an option not
    given."""
    if value == "":
        return not field.required
    if field.option is None and value.startswith("-"):
        # A positional is written apart, so it could be read as an option.
        return False
    if field.kind == ID:
        return bool(IDENTIFIER.fullmatch(value))
    if field.kind == CHOICE:
        return value in field.choices
    if field.kind == AMOUNT_KIND:
        return bool(AMOUNT.fullmatch(value))
    if field.kind == DATE_KIND:
        return bool(DATE.fullmatch(value))
    if field.kind == MONTH_KIND:
        return bool(MONTH.fullmatch(value))
    if field.kind == TEXT:
        return len(value) <= MAXIMUM_TEXT_LENGTH and printable_text(value) and (
            value == value.strip())
    if field.kind in (PAIR_LINES, GROUP_LINES):
        return listed_ids(value, 2 if field.kind == PAIR_LINES else None) is not None
    raise AssertionError(field.kind)


def form_token(secret: bytes, path: str, hidden: dict[str, str]) -> str:
    """HMAC-SHA256 over the route and every hidden field the form shows, in the route's fixed
    order. A unit separator keeps the parts apart, since no accepted value may hold one."""
    parts = [path, *(hidden[field.name] for field in WRITE_ROUTES[path].hidden)]
    return hmac.new(secret, "\x1f".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()


def refuse_form_token(form: dict[str, str], path: str, secret: bytes,
                      used_tokens: set[str]) -> Refusal | None:
    """Step 8: the token this session's secret gives for the form as shown, never used before.
    It is spent here, before the command runs, so a resubmitted form refuses whatever the
    command did."""
    given = form[FORM_TOKEN_FIELD]
    expected = form_token(secret, path, form)
    if given in used_tokens or not hmac.compare_digest(given.encode("utf-8"),
                                                       expected.encode("utf-8")):
        return Refusal(403, FORM_EXPIRED)
    used_tokens.add(given)
    return None


def listed_ids(text: str, ids_per_line: int | None) -> list[list[str]] | None:
    """A textarea's lines, each of IDs separated by spaces: exactly ids_per_line of them, or at
    least one when None. Blank lines are skipped. None when anything else is there."""
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        ids = line.split()
        if not ids:
            continue
        if any(not IDENTIFIER.fullmatch(each) for each in ids) or (
                ids_per_line is not None and len(ids) != ids_per_line):
            return None
        lines.append(ids)
    if not lines or len(lines) > MAXIMUM_LIST_LINES:
        return None
    return lines


def command_words(path: str, form: dict[str, str], ledger_path) -> list[str]:
    """Step 9's command line, from the route's declaration and the checked form alone. Every
    option is written as --name=value, so no value can be read as an option whatever it holds,
    and an empty optional field is an option not given. Lists are IDs, each option repeated."""
    route = WRITE_ROUTES[path]
    fields = (*route.hidden, *route.typed)
    words = [*route.words, *(form[field.name] for field in fields if field.option is None),
             f"--db={ledger_path}"]
    for field in fields:
        value = form[field.name]
        if value == "" or field.option is None:
            continue
        if field.kind in (PAIR_LINES, GROUP_LINES):
            for ids in listed_ids(value, 2 if field.kind == PAIR_LINES else None):
                words += [field.option, *ids]
        else:
            words.append(f"{field.option}={value}")
    return [*words, *route.flags]
