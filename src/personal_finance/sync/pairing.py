"""What the phone reads to pair or reconnect (D-076 point 3, the M20.1 slice plan point 4).

The pairing payload is commoncents-pair:v1?address=A&port=P&fingerprint=F&secret=S. A reconnect
code holds the same without the secret. The manual fallback is the address, port and secret as
base32 to type, with the fingerprint's first 16 hex digits to compare on the phone.

The QR code is encoded by segno, the only module that imports it, which is called for
make_qr(...).matrix and nothing else: it never shows, saves, writes or converts. The terminal
drawing is this module's, two rows of modules to a line in half blocks, black on white by ANSI
colours whatever the terminal's own, inside a four-module quiet zone.
"""

import base64
import ipaddress

import segno

PAIRING_SCHEME = "commoncents-pair:v1"
RECONNECT_SCHEME = "commoncents-connect:v1"
QUIET_ZONE = 4
MANUAL_GROUP = 4
DARK_ON_DARK, DARK_ON_LIGHT, LIGHT_ON_DARK, LIGHT_ON_LIGHT = "█", "▀", "▄", " "
BLACK_ON_WHITE = "\033[30;47m"
RESET = "\033[0m"


def pairing_payload(address: str, port: int, fingerprint: str, pairing_secret: str) -> str:
    return (f"{PAIRING_SCHEME}?address={address}&port={port}&fingerprint={fingerprint}"
            f"&secret={pairing_secret}")


def reconnect_payload(address: str, port: int, fingerprint: str) -> str:
    return f"{RECONNECT_SCHEME}?address={address}&port={port}&fingerprint={fingerprint}"


def parsed_payload(payload: str) -> dict:
    """A payload's fields, as the phone reads them: the reference client's, and the tests'."""
    scheme, _, query = payload.partition("?")
    if scheme not in (PAIRING_SCHEME, RECONNECT_SCHEME):
        raise ValueError("not a CommonCents pairing or reconnect code")
    fields = dict(part.split("=", 1) for part in query.split("&"))
    expected = {"address", "port", "fingerprint"} | ({"secret"} if scheme == PAIRING_SCHEME
                                                     else set())
    if set(fields) != expected:
        raise ValueError("the code's fields are not the scheme's")
    return {**fields, "scheme": scheme, "port": int(fields["port"])}


def manual_code(address: str, port: int, pairing_secret: str) -> str:
    """The address, port and secret, 38 bytes as unpadded base32 in groups of four."""
    secret_bytes = base64.urlsafe_b64decode(pairing_secret + "=")
    packed = ipaddress.IPv4Address(address).packed + port.to_bytes(2, "big") + secret_bytes
    text = base64.b32encode(packed).decode("ascii").rstrip("=")
    return "-".join(text[start:start + MANUAL_GROUP] for start in range(0, len(text),
                                                                         MANUAL_GROUP))


def parsed_manual_code(code: str) -> tuple[str, int, str]:
    """(address, port, secret) from a typed manual code."""
    text = code.replace("-", "").upper()
    packed = base64.b32decode(text + "=" * (-len(text) % 8))
    if len(packed) != 38:
        raise ValueError("a manual code is 38 bytes")
    secret = base64.urlsafe_b64encode(packed[6:]).decode("ascii").rstrip("=")
    return str(ipaddress.IPv4Address(packed[:4])), int.from_bytes(packed[4:6], "big"), secret


def qr_matrix(payload: str) -> list[list[bool]]:
    """The QR code's modules, dark as True, inside its quiet zone."""
    modules = [[bool(module) for module in row]
               for row in segno.make_qr(payload, error="m").matrix]
    width = len(modules[0]) + 2 * QUIET_ZONE
    blank = [[False] * width for _ in range(QUIET_ZONE)]
    padded = [[False] * QUIET_ZONE + row + [False] * QUIET_ZONE for row in modules]
    return blank + padded + blank


def qr_lines(payload: str) -> list[str]:
    """The QR code for a terminal: each line two module rows, black on white."""
    matrix = qr_matrix(payload)
    if len(matrix) % 2:
        matrix.append([False] * len(matrix[0]))
    characters = {(True, True): DARK_ON_DARK, (True, False): DARK_ON_LIGHT,
                  (False, True): LIGHT_ON_DARK, (False, False): LIGHT_ON_LIGHT}
    return [BLACK_ON_WHITE + "".join(characters[pair] for pair in zip(top, bottom)) + RESET
            for top, bottom in zip(matrix[0::2], matrix[1::2])]
