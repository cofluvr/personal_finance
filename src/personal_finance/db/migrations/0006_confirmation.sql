-- Confirmation and superseding. Rules are in docs/decisions.md D-046.

-- Every decision before this one was a rejection. A decision is active unless it was undone,
-- or an active decision supersedes it, so superseding writes nothing on the old row.
ALTER TABLE decision ADD COLUMN kind TEXT NOT NULL DEFAULT 'reject'
    CHECK (kind IN ('reject', 'confirm'));
ALTER TABLE decision ADD COLUMN supersedes_decision_id TEXT REFERENCES decision (id);

CREATE INDEX decision_supersedes ON decision (supersedes_decision_id);

-- A decision can only replace an earlier one in its own account.
CREATE TRIGGER decision_supersedes_same_account BEFORE INSERT ON decision
WHEN NEW.supersedes_decision_id IS NOT NULL
 AND NOT EXISTS (SELECT 1 FROM decision old
                 WHERE old.id = NEW.supersedes_decision_id AND old.account_id = NEW.account_id)
BEGIN SELECT RAISE(ABORT, 'a decision can only supersede one in its own account'); END;
