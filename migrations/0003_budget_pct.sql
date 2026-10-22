-- Livello contrattuale 9 (mancava)
INSERT INTO lookup (category, code, label, sort_order) VALUES ('livello','9','9',9);

-- Budget aumenti in percentuale: % sul monte RAL delle persone incluse.
-- La platea è uno snapshot gestibile: di default esclude gli assunti dell'anno del budget.
ALTER TABLE ral_budget ADD COLUMN pct REAL;
ALTER TABLE ral_budget ADD COLUMN year INTEGER;

CREATE TABLE ral_budget_member (
    id INTEGER PRIMARY KEY,
    budget_id INTEGER NOT NULL REFERENCES ral_budget(id),
    person_id INTEGER NOT NULL REFERENCES person(id),
    ral_snapshot REAL NOT NULL DEFAULT 0,
    included INTEGER NOT NULL DEFAULT 1,
    auto_reason TEXT,
    UNIQUE (budget_id, person_id)
);
