-- Superseding chains. Rules are in docs/decisions.md D-048.

-- A decision now stays superseded while anything superseding it has not been undone. Before, the
-- first decision of a chain of two applied again once its successor was superseded in turn, so an
-- account holding such a chain may have been derived from the wrong decisions. Clearing its marker
-- makes it stale: commands refuse it until reconcile re-derives it (D-035). Nothing else changes.
DELETE FROM account_reconciliation
WHERE account_id IN (
    SELECT newer.account_id
    FROM decision newer
    JOIN decision middle ON middle.id = newer.supersedes_decision_id
    WHERE middle.supersedes_decision_id IS NOT NULL
);
