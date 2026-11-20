"""The browser write pipeline (D-073 point 1, M17.1): a security change, approved as one.

Steps 1 and 2, the exact Host and the session cookie, are the server's, shared with every GET.
W1 is unchanged: the body is decoded here, by a strict decoder of the form encoding, and
nothing of `urllib` is imported. This module holds steps 3 to 8 as functions over what the request said, so each refuses alone,
and step 9's command line. Every refusal is a fixed notice that repeats nothing from the request
(D-037). The write itself is the CLI's own command, run by the server (step 9), so a browser
decision is the terminal's, refusals included.
"""

import hashlib
import hmac
import re
from typing import NamedTuple

MAXIMUM_BODY_BYTES = 8192
MAXIMUM_FIELD_COUNT = 50
FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"
FORM_TOKEN_FIELD = "form_token"
# An account, item, decision or transaction ID, or a revision token: nothing else is accepted.
# The first character is never "-", so no value can be read as a command-line option.
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")
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


class Refusal(NamedTuple):
    status: int
    notice: str
    extra_headers: tuple = ()


class WriteRoute(NamedTuple):
    # The form's fields, apart from the form token, each required.
    fields: tuple[str, ...]
    # The field naming the item or decision the form decides, which the token binds.
    form_id_field: str
    # The fields holding revision tokens the form shows, which the token binds.
    revision_fields: tuple[str, ...]


# The allowlist (D-073 point 2), as built so far. Each route runs exactly one CLI command.
WRITE_ROUTES = {
    "/review/reject": WriteRoute(("account", "item", "revision", "pairs"), "item",
                                 ("revision",)),
    "/review/confirm": WriteRoute(("account", "item", "revision", "groups"), "item",
                                  ("revision",)),
    "/review/undo": WriteRoute(("account", "decision", "revision"), "decision", ("revision",)),
}


def refuse_route(method: str, path: str) -> Refusal | None:
    """Step 3: a POST to a route on the allowlist. Any other method is 405."""
    if method != "POST":
        return Refusal(405, NOT_ALLOWED, (("Allow", "GET, POST"),))
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
    """Step 7: UTF-8, at most 50 fields, each once, exactly the route's fields and the token."""
    pieces = body.split(b"&") if body else []
    if len(pieces) > MAXIMUM_FIELD_COUNT:
        return Refusal(400, UNREADABLE_FORM)
    form = {}
    for piece in pieces:
        raw_name, separator, raw_value = piece.partition(b"=")
        try:
            name, value = decoded_form_part(raw_name), decoded_form_part(raw_value)
        except (UnicodeDecodeError, ValueError):
            return Refusal(400, UNREADABLE_FORM)
        if not separator or name in form:
            return Refusal(400, UNREADABLE_FORM)
        form[name] = value
    if set(form) != {*route.fields, FORM_TOKEN_FIELD}:
        return Refusal(400, UNREADABLE_FORM)
    for name in (route.form_id_field, "account", *route.revision_fields):
        if not IDENTIFIER.fullmatch(form[name]):
            return Refusal(400, UNREADABLE_FORM)
    return form


def form_token(secret: bytes, path: str, form_id: str, account_id: str,
               revisions: tuple[str, ...]) -> str:
    """HMAC-SHA256 over the route, the form's item or decision, its account and every revision
    token it shows. A unit separator keeps the parts apart, since none of them may hold one."""
    message = "\x1f".join((path, form_id, account_id, *revisions)).encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def refuse_form_token(form: dict[str, str], path: str, secret: bytes,
                      used_tokens: set[str]) -> Refusal | None:
    """Step 8: the token this session's secret gives for the form as shown, never used before.
    It is spent here, before the write, so a resubmitted form refuses whatever the write did."""
    route = WRITE_ROUTES[path]
    given = form[FORM_TOKEN_FIELD]
    expected = form_token(secret, path, form[route.form_id_field], form["account"],
                          tuple(form[name] for name in route.revision_fields))
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


def command_words(path: str, form: dict[str, str], ledger_path) -> list[str] | Refusal:
    """Step 9's command line: the CLI command the route maps to, with the form's values as its
    arguments. Every value was checked above, so none can be read as an option."""
    common = ["--db", str(ledger_path), "--account", form["account"], "--revision",
              form["revision"]]
    if path == "/review/undo":
        return ["review", "undo", form["decision"], *common]
    if path == "/review/reject":
        pairs = listed_ids(form["pairs"], 2)
        if pairs is None:
            return Refusal(400, UNREADABLE_FORM)
        return ["review", "reject", form["item"], *common,
                *(word for pair in pairs for word in ("--pair", *pair))]
    groups = listed_ids(form["groups"], None)
    if groups is None:
        return Refusal(400, UNREADABLE_FORM)
    return ["review", "confirm", form["item"], *common,
            *(word for group in groups for word in ("--group", *group))]
