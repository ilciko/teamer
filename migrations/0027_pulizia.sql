-- Pulizia prima dei perimetri per director (docs/perimetri.md):
-- * via le tabelle mai usate dall'app (evaluation, evaluation_item, ral_projection);
--   ninebox_assessment perde evaluation_id, che le puntava e non è mai stato scritto;
-- * via l'indice full-text delle note: un indice FTS5 non si può filtrare per
--   perimetro (chi lo interroga legge tutte le note). La ricerca passa a LIKE.
PRAGMA foreign_keys=OFF;
BEGIN;

DROP TRIGGER IF EXISTS meeting_note_ai;
DROP TRIGGER IF EXISTS meeting_note_ad;
DROP TRIGGER IF EXISTS meeting_note_au;
DROP TABLE IF EXISTS meeting_note_fts;

CREATE TABLE ninebox_assessment_new (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    eval_date DATE NOT NULL,
    role_type TEXT NOT NULL,
    seniority TEXT NOT NULL,
    raw_perf REAL NOT NULL,
    raw_pot REAL NOT NULL,
    adj_perf REAL NOT NULL,
    adj_pot REAL NOT NULL,
    perf_level TEXT NOT NULL,
    pot_level TEXT NOT NULL,
    box_number INTEGER NOT NULL,
    weights_snapshot TEXT NOT NULL,
    answers TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT
);
INSERT INTO ninebox_assessment_new
    SELECT id, person_id, eval_date, role_type, seniority, raw_perf, raw_pot, adj_perf, adj_pot,
           perf_level, pot_level, box_number, weights_snapshot, answers, created_at, voided, void_reason
      FROM ninebox_assessment;
DROP TABLE ninebox_assessment;
ALTER TABLE ninebox_assessment_new RENAME TO ninebox_assessment;
CREATE INDEX idx_ninebox_person ON ninebox_assessment(person_id, eval_date);

DROP TABLE evaluation_item;
DROP TABLE evaluation;
DROP TABLE ral_projection;

COMMIT;
PRAGMA foreign_keys=ON;
