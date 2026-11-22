# Sync protocol, version 1

For whoever builds the phone's side (D-079's I3). The Mac's side is `src/personal_finance/sync/`,
decided in D-076 and its M20 slice plans in [decisions-m12-m21.md](decisions-m12-m21.md). The
executable specification is `tests/sync_reference_client.py`: an iOS client that behaves as it
does is correct. The snapshot it carries is shared-contract §6's compatibility policy, with its
schema `src/personal_finance/snapshot/schema_v1.json`.

The phone only reads. It fetches the latest snapshot and acknowledges it, and nothing else.

## 1. Transport

- HTTPS on the Mac's private IPv4 address (RFC 1918) and a port, 8443 by default, while the owner
  runs `pf sync pair` or `pf sync serve` in the foreground. There is no discovery.
- **TLS 1.3 only.** The Mac refuses TLS 1.2 and plaintext.
- **No certificate authority.** The Mac's certificate is self-signed (P-256, named curve). The
  phone **pins the SHA-256 of the certificate's DER bytes**, learnt at pairing, and refuses any
  other certificate before sending a byte. Hostname checks do not apply: the pin replaces them.
- One request per connection. Every answer carries `Connection: close` and
  `Cache-Control: no-store`.

## 2. Pairing

The owner runs `pf sync pair --name NAME --address IPV4`. For at most 120 seconds, the Mac shows:

- **A QR code** holding `commoncents-pair:v1?address=A&port=P&fingerprint=F&secret=S`:
  - `A`, the IPv4 address;
  - `P`, the port;
  - `F`, 64 lowercase hex digits, the certificate pin;
  - `S`, the pairing secret, 43 characters of unpadded base64url (32 bytes).
- **A manual code** to type instead: the address (4 bytes), port (2 bytes, big-endian) and
  secret (32 bytes) as unpadded RFC 4648 base32, in groups of four separated by `-`, any case.
  It holds no fingerprint. After the handshake the phone shows the first 16 hex digits of the
  presented certificate's SHA-256, and the person compares them with the terminal's before the
  phone pins it.

The phone connects, pinning `F`, and sends:

```http
POST /v1/pair HTTP/1.1
Content-Type: application/json
Content-Length: N

{"pairing_secret":"S"}
```

| Answer | Body | Meaning |
|---|---|---|
| `200` | `{"device_id": UUID, "device_secret": 43 base64url}` | Paired. Store both in the Keychain, with the pin, address and port |
| `401` | `{"error":"unauthorized"}` | Wrong, expired or used secret |

The window is single-use and closes after a success, 120 seconds, or five failures. The device's
name is the one the owner typed on the Mac. The phone never names itself.

**Reconnecting.** Each `pf sync serve` shows a QR code holding
`commoncents-connect:v1?address=A&port=P&fingerprint=F`, with no secret. When the Mac's address
or port has changed, the phone takes the new ones from it. It does so only when `F` equals the
pin it already holds. A different `F` means the Mac's identity was rotated, and the phone must
pair again.

## 3. Fetching

```http
GET /v1/snapshot/latest HTTP/1.1
Authorization: Bearer <device_id>.<device_secret>
Accept-Snapshot-Major: 1
```

`Accept-Snapshot-Major` lists every major the app reads, as in `1` or `1, 2`.

| Answer | Body | The phone does |
|---|---|---|
| `200` | The snapshot's bytes; header `Snapshot-SHA256` | Section 4 |
| `401` | `{"error":"unauthorized"}` | Unknown, wrong or revoked device: ask the owner to pair again |
| `409` | `{"error":"unsupported_snapshot_major","supported_majors":[1]}` | Show an actionable error naming both versions: update the app or the Mac |
| `503` | `{"error":"busy"}` | The ledger is busy: try again shortly |

Authentication is checked first, so an unauthenticated request never learns the majors. A
revoked device is refused from its next request.

## 4. Checking and installing

In this order. Any failure keeps the last valid snapshot and installs nothing:

1. The SHA-256 of the body equals `Snapshot-SHA256`.
2. The snapshot by shared-contract §6's rules, as `snapshot/files.py`'s `verified` checks it:
   - the bytes are canonical JSON;
   - the envelope;
   - `content_sha256`;
   - the schema of a supported major, ignoring unknown fields;
   - the reconciliations;
   - no excluded key.
3. **Install atomically:** write a new file, flush it to storage, and rename it over the last one.
   On iOS, use file protection `completeUnlessOpen` or stronger.
4. **Only then acknowledge** (section 5).

**Freshness** is the snapshot's own `content.cutoff`, never the time of the sync. A sync succeeding
says nothing about how current the bank data is (shared-contract §5).

## 5. Acknowledging

```http
POST /v1/ack HTTP/1.1
Authorization: Bearer <device_id>.<device_secret>
Content-Type: application/json
Content-Length: N

{"snapshot_id":"UUID","content_sha256":"64 hex"}
```

| Answer | Meaning |
|---|---|
| `204` | Recorded, once per device and snapshot. Repeating it is harmless |
| `400` `{"error":"not_delivered"}` | No such delivery to this device |
| `401` | As in section 3 |

## 6. Strictness

The Mac answers anything else with a fixed body that repeats nothing from the request:

| Request | Answer |
|---|---|
| Any other method or path, including a query string | `404` `{"error":"not_found"}` |
| JSON that is not exactly the stated string fields: unknown or repeated fields, numbers, non-UTF-8 | `400` `{"error":"bad_request"}` |
| A body on a `GET`, `Transfer-Encoding`, or a bad `Content-Length` | `400` `{"error":"bad_request"}` |
| A body over 4 KB | `413` `{"error":"body_too_large"}` |
| Headers over 8 KB or 100 lines | `431` `{"error":"headers_too_large"}` |

A serve session ends after its minutes (10 by default, at most 60), on Ctrl-C, or after 10
authentication failures. The phone should expect the Mac to be unreachable most of the time.

## 7. Versions

This document is protocol version 1, named in the pairing scheme `commoncents-pair:v1` and the
paths `/v1/`. A change to any request, answer or rule here is a new version, with new paths.
Snapshot versions are separate, and follow shared-contract §6.
