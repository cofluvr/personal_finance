-- Pairing and local-network sync (D-076 point 7, the M20 slice plans). The Mac's identity, each
-- pairing window, each paired device, and each delivery and acknowledgement. Only hashes of
-- secrets are stored, and no snapshot content. Every table is append-only.

CREATE TABLE sync_identity (
    identity_id         TEXT PRIMARY KEY CHECK (length(identity_id) = 36),
    certificate_sha256  TEXT NOT NULL UNIQUE CHECK (length(certificate_sha256) = 64
                                                    AND certificate_sha256 NOT GLOB '*[^0-9a-f]*'),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE sync_identity_event (
    identity_id  TEXT NOT NULL REFERENCES sync_identity (identity_id),
    event        TEXT NOT NULL CHECK (event IN ('retired')),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (identity_id, event)
) STRICT;

CREATE TABLE pairing_window (
    window_id      TEXT PRIMARY KEY CHECK (length(window_id) = 36),
    identity_id    TEXT NOT NULL REFERENCES sync_identity (identity_id),
    secret_sha256  TEXT NOT NULL UNIQUE CHECK (length(secret_sha256) = 64
                                               AND secret_sha256 NOT GLOB '*[^0-9a-f]*'),
    address        TEXT NOT NULL CHECK (length(address) BETWEEN 7 AND 15
                                        AND address NOT GLOB '*[^0-9.]*'),
    port           INTEGER NOT NULL CHECK (port BETWEEN 1024 AND 65535),
    closes_at      TEXT NOT NULL CHECK (closes_at GLOB
        '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'),
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE pairing_window_event (
    event_id    INTEGER PRIMARY KEY,
    window_id   TEXT NOT NULL REFERENCES pairing_window (window_id),
    event       TEXT NOT NULL CHECK (event IN ('failed', 'used', 'closed')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE paired_device (
    device_id      TEXT PRIMARY KEY CHECK (length(device_id) = 36),
    name           TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 64),
    secret_sha256  TEXT NOT NULL UNIQUE CHECK (length(secret_sha256) = 64
                                               AND secret_sha256 NOT GLOB '*[^0-9a-f]*'),
    identity_id    TEXT NOT NULL REFERENCES sync_identity (identity_id),
    window_id      TEXT NOT NULL UNIQUE REFERENCES pairing_window (window_id),
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE paired_device_event (
    device_id   TEXT NOT NULL REFERENCES paired_device (device_id),
    event       TEXT NOT NULL CHECK (event IN ('revoked')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (device_id, event)
) STRICT;

-- One delivery per device and snapshot: serving it again records nothing new.
CREATE TABLE sync_delivery (
    delivery_id     TEXT PRIMARY KEY CHECK (length(delivery_id) = 36),
    device_id       TEXT NOT NULL REFERENCES paired_device (device_id),
    snapshot_id     TEXT NOT NULL REFERENCES snapshot_record (snapshot_id),
    content_sha256  TEXT NOT NULL CHECK (length(content_sha256) = 64
                                         AND content_sha256 NOT GLOB '*[^0-9a-f]*'),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (device_id, snapshot_id)
) STRICT;

CREATE TABLE sync_acknowledgement (
    delivery_id  TEXT PRIMARY KEY REFERENCES sync_delivery (delivery_id),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TRIGGER sync_identity_no_update BEFORE UPDATE ON sync_identity
BEGIN SELECT RAISE(ABORT, 'sync_identity is append-only'); END;
CREATE TRIGGER sync_identity_no_delete BEFORE DELETE ON sync_identity
BEGIN SELECT RAISE(ABORT, 'sync_identity is append-only'); END;
CREATE TRIGGER sync_identity_event_no_update BEFORE UPDATE ON sync_identity_event
BEGIN SELECT RAISE(ABORT, 'sync_identity_event is append-only'); END;
CREATE TRIGGER sync_identity_event_no_delete BEFORE DELETE ON sync_identity_event
BEGIN SELECT RAISE(ABORT, 'sync_identity_event is append-only'); END;
CREATE TRIGGER pairing_window_no_update BEFORE UPDATE ON pairing_window
BEGIN SELECT RAISE(ABORT, 'pairing_window is append-only'); END;
CREATE TRIGGER pairing_window_no_delete BEFORE DELETE ON pairing_window
BEGIN SELECT RAISE(ABORT, 'pairing_window is append-only'); END;
CREATE TRIGGER pairing_window_event_no_update BEFORE UPDATE ON pairing_window_event
BEGIN SELECT RAISE(ABORT, 'pairing_window_event is append-only'); END;
CREATE TRIGGER pairing_window_event_no_delete BEFORE DELETE ON pairing_window_event
BEGIN SELECT RAISE(ABORT, 'pairing_window_event is append-only'); END;
CREATE TRIGGER paired_device_no_update BEFORE UPDATE ON paired_device
BEGIN SELECT RAISE(ABORT, 'paired_device is append-only'); END;
CREATE TRIGGER paired_device_no_delete BEFORE DELETE ON paired_device
BEGIN SELECT RAISE(ABORT, 'paired_device is append-only'); END;
CREATE TRIGGER paired_device_event_no_update BEFORE UPDATE ON paired_device_event
BEGIN SELECT RAISE(ABORT, 'paired_device_event is append-only'); END;
CREATE TRIGGER paired_device_event_no_delete BEFORE DELETE ON paired_device_event
BEGIN SELECT RAISE(ABORT, 'paired_device_event is append-only'); END;
CREATE TRIGGER sync_delivery_no_update BEFORE UPDATE ON sync_delivery
BEGIN SELECT RAISE(ABORT, 'sync_delivery is append-only'); END;
CREATE TRIGGER sync_delivery_no_delete BEFORE DELETE ON sync_delivery
BEGIN SELECT RAISE(ABORT, 'sync_delivery is append-only'); END;
CREATE TRIGGER sync_acknowledgement_no_update BEFORE UPDATE ON sync_acknowledgement
BEGIN SELECT RAISE(ABORT, 'sync_acknowledgement is append-only'); END;
CREATE TRIGGER sync_acknowledgement_no_delete BEFORE DELETE ON sync_acknowledgement
BEGIN SELECT RAISE(ABORT, 'sync_acknowledgement is append-only'); END;

-- INSERT OR REPLACE would delete a row without firing its delete trigger: refuse any insert that
-- meets an existing key. A window's used and closed events are each once only.
CREATE TRIGGER sync_identity_no_replace BEFORE INSERT ON sync_identity
WHEN EXISTS (SELECT 1 FROM sync_identity WHERE identity_id = NEW.identity_id
                                            OR certificate_sha256 = NEW.certificate_sha256)
BEGIN SELECT RAISE(ABORT, 'sync_identity is append-only'); END;
CREATE TRIGGER sync_identity_event_no_replace BEFORE INSERT ON sync_identity_event
WHEN EXISTS (SELECT 1 FROM sync_identity_event WHERE identity_id = NEW.identity_id
                                                  AND event = NEW.event)
BEGIN SELECT RAISE(ABORT, 'sync_identity_event is append-only'); END;
CREATE TRIGGER pairing_window_no_replace BEFORE INSERT ON pairing_window
WHEN EXISTS (SELECT 1 FROM pairing_window WHERE window_id = NEW.window_id
                                             OR secret_sha256 = NEW.secret_sha256)
BEGIN SELECT RAISE(ABORT, 'pairing_window is append-only'); END;
CREATE TRIGGER pairing_window_event_no_replace BEFORE INSERT ON pairing_window_event
WHEN EXISTS (SELECT 1 FROM pairing_window_event
             WHERE event_id = NEW.event_id
                OR (window_id = NEW.window_id AND event = NEW.event
                    AND NEW.event IN ('used', 'closed')))
BEGIN SELECT RAISE(ABORT, 'pairing_window_event is append-only'); END;
CREATE TRIGGER paired_device_no_replace BEFORE INSERT ON paired_device
WHEN EXISTS (SELECT 1 FROM paired_device WHERE device_id = NEW.device_id
                                            OR secret_sha256 = NEW.secret_sha256
                                            OR window_id = NEW.window_id)
BEGIN SELECT RAISE(ABORT, 'paired_device is append-only'); END;
CREATE TRIGGER paired_device_event_no_replace BEFORE INSERT ON paired_device_event
WHEN EXISTS (SELECT 1 FROM paired_device_event WHERE device_id = NEW.device_id
                                                  AND event = NEW.event)
BEGIN SELECT RAISE(ABORT, 'paired_device_event is append-only'); END;
CREATE TRIGGER sync_delivery_no_replace BEFORE INSERT ON sync_delivery
WHEN EXISTS (SELECT 1 FROM sync_delivery
             WHERE delivery_id = NEW.delivery_id
                OR (device_id = NEW.device_id AND snapshot_id = NEW.snapshot_id))
BEGIN SELECT RAISE(ABORT, 'sync_delivery is append-only'); END;
CREATE TRIGGER sync_acknowledgement_no_replace BEFORE INSERT ON sync_acknowledgement
WHEN EXISTS (SELECT 1 FROM sync_acknowledgement WHERE delivery_id = NEW.delivery_id)
BEGIN SELECT RAISE(ABORT, 'sync_acknowledgement is append-only'); END;
