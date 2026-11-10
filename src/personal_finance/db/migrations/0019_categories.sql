-- Spending categories, named by a person. Rules are in docs/decisions.md D-063.

-- Append-only: no rename, merge or delete, so whatever is categorized keeps meaning what it meant.
-- A parent is a top-level category, so the list is one level deep. Uncategorized is never stored:
-- it is the absence of a category that applies. Names are compared exactly.
CREATE TABLE category (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE CHECK (trim(name) <> '' AND name <> 'uncategorized'),
    parent_id   INTEGER REFERENCES category (id),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TRIGGER category_parent_is_top_level BEFORE INSERT ON category
WHEN NEW.parent_id IS NOT NULL
 AND NOT EXISTS (SELECT 1 FROM category parent
                 WHERE parent.id = NEW.parent_id AND parent.parent_id IS NULL)
BEGIN SELECT RAISE(ABORT, 'a category''s parent must be an existing top-level category'); END;

CREATE TRIGGER category_no_update BEFORE UPDATE ON category
BEGIN SELECT RAISE(ABORT, 'category is append-only'); END;
CREATE TRIGGER category_no_delete BEFORE DELETE ON category
BEGIN SELECT RAISE(ABORT, 'category is append-only'); END;
CREATE TRIGGER category_no_replace BEFORE INSERT ON category
WHEN EXISTS (SELECT 1 FROM category WHERE id = NEW.id OR name = NEW.name)
BEGIN SELECT RAISE(ABORT, 'category is append-only'); END;

-- PRD §10's starting list, in its order, which is the order categories are listed in.
INSERT INTO category (name) VALUES
    ('Housing'),
    ('Utilities and communications'),
    ('Food'),
    ('Transportation'),
    ('Health'),
    ('Shopping and household'),
    ('Entertainment'),
    ('Travel'),
    ('Gifts and donations'),
    ('Insurance'),
    ('Interest and financial fees'),
    ('Other');
