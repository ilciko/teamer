-- Perimetri (docs/perimetri.md): una persona è nel perimetro del director se la sua
-- ultima assegnazione valida sta in uno dei suoi team. Chi non ha ancora nessuna
-- assegnazione (censita «team: dopo») resta del director che l'ha creata:
-- owner_user_id col default teamer_owner() come nella 0028. NULL = da assegnare.
PRAGMA foreign_keys=OFF;
BEGIN;

CREATE TABLE person_new (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    avatar BLOB,
    hire_date DATE,
    birth_date DATE,
    email TEXT,
    status TEXT NOT NULL DEFAULT 'attivo',
    end_date DATE,
    notes TEXT,
    report_excluded INTEGER NOT NULL DEFAULT 0,
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id)
);
INSERT INTO person_new (id, full_name, avatar, hire_date, birth_date, email, status, end_date, notes, report_excluded)
    SELECT id, full_name, avatar, hire_date, birth_date, email, status, end_date, notes, report_excluded FROM person;
DROP TABLE person;
ALTER TABLE person_new RENAME TO person;
CREATE INDEX idx_person_owner ON person(owner_user_id);

COMMIT;
PRAGMA foreign_keys=ON;
