-- Note 1:1 e azioni con l'autore (docs/perimetri.md, classe `authored`): ognuno vede e scrive
-- solo le proprie, a prescindere dal perimetro della persona. Quando la persona esce dal
-- perimetro, le note restano a chi le ha scritte, in sola lettura; non passano a nessuno.
-- author_user_id col default teamer_owner() come nella 0028 (l'ALTER non accetta il default
-- con funzione: le tabelle si ricostruiscono). Le righe esistenti vanno al director titolare
-- attuale della persona: il team dell'ultima assegnazione valida, altrimenti chi l'ha creata.
-- NULL = da assegnare (Amministrazione → Dati da assegnare).
PRAGMA foreign_keys=OFF;
BEGIN;

CREATE TABLE meeting_note_new (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    note_date DATE NOT NULL,
    type TEXT NOT NULL DEFAULT '1:1',
    title TEXT,
    body TEXT,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at DATETIME,
    archived_at DATETIME,
    author_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id)
);
INSERT INTO meeting_note_new (id, person_id, note_date, type, title, body, created_at, updated_at, archived_at,
                              author_user_id)
    SELECT mn.id, mn.person_id, mn.note_date, mn.type, mn.title, mn.body, mn.created_at, mn.updated_at,
           mn.archived_at,
           COALESCE((SELECT t.owner_user_id FROM person_assignment pa JOIN team t ON t.id = pa.team_id
                      WHERE pa.person_id = mn.person_id AND pa.voided = 0
                      ORDER BY pa.start_date DESC, pa.id DESC LIMIT 1),
                    (SELECT p.owner_user_id FROM person p WHERE p.id = mn.person_id))
      FROM meeting_note mn;
DROP TABLE meeting_note;
ALTER TABLE meeting_note_new RENAME TO meeting_note;
CREATE INDEX idx_note_person ON meeting_note(person_id, note_date);
CREATE INDEX idx_note_author ON meeting_note(author_user_id);

CREATE TABLE action_item_new (
    id INTEGER PRIMARY KEY,
    meeting_note_id INTEGER REFERENCES meeting_note(id),
    person_id INTEGER NOT NULL REFERENCES person(id),
    description TEXT NOT NULL,
    due_date DATE,
    status TEXT NOT NULL DEFAULT 'aperto',
    closed_date DATE,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    author_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id)
);
INSERT INTO action_item_new (id, meeting_note_id, person_id, description, due_date, status, closed_date, created_at,
                             author_user_id)
    SELECT a.id, a.meeting_note_id, a.person_id, a.description, a.due_date, a.status, a.closed_date, a.created_at,
           COALESCE((SELECT t.owner_user_id FROM person_assignment pa JOIN team t ON t.id = pa.team_id
                      WHERE pa.person_id = a.person_id AND pa.voided = 0
                      ORDER BY pa.start_date DESC, pa.id DESC LIMIT 1),
                    (SELECT p.owner_user_id FROM person p WHERE p.id = a.person_id))
      FROM action_item a;
DROP TABLE action_item;
ALTER TABLE action_item_new RENAME TO action_item;
CREATE INDEX idx_action_person ON action_item(person_id, status);
CREATE INDEX idx_action_author ON action_item(author_user_id);

COMMIT;
PRAGMA foreign_keys=ON;
