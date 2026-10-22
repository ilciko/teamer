-- La review si può annullare, ma UNIQUE(person_id, cycle_id) non guardava
-- `voided`: dopo un void il reinserimento andava in IntegrityError. Serve un
-- indice parziale, e in SQLite un vincolo di tabella si toglie solo
-- ricostruendola. Le FK dei figli (goal_review, wellbeing_entry, attachment)
-- puntano per nome: dopo il RENAME tornano valide.
PRAGMA foreign_keys=OFF;
BEGIN;

CREATE TABLE performance_review_new (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    cycle_id INTEGER NOT NULL REFERENCES review_cycle(id),
    review_date DATE,
    overall_rating INTEGER,
    overall_employee_comment TEXT,
    overall_tl_comment TEXT,
    growth_self_comment TEXT,
    growth_tl_comment TEXT,
    synthesis_employee_comment TEXT,
    synthesis_tl_comment TEXT,
    status TEXT NOT NULL DEFAULT 'bozza',
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT
);

INSERT INTO performance_review_new SELECT * FROM performance_review;
DROP TABLE performance_review;
ALTER TABLE performance_review_new RENAME TO performance_review;

-- una sola review viva per persona/ciclo; le annullate non danno fastidio
CREATE UNIQUE INDEX idx_review_persona_ciclo
    ON performance_review(person_id, cycle_id) WHERE voided = 0;

COMMIT;
PRAGMA foreign_keys=ON;
