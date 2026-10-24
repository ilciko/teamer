-- Tappa 3 del profilo HR: la cessazione la registra HR, il director decide se sostituire.
-- Una cessazione senza posizione di sostituzione né decisione resta «da decidere».
-- La decisione «non sostituire» è append-only: si annulla (voided), non si cancella.
CREATE TABLE replacement_decision (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    decision TEXT NOT NULL DEFAULT 'non_sostituire' CHECK (decision IN ('non_sostituire')),
    note TEXT,
    decided_by INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id),
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT
);
CREATE INDEX idx_replacement_decision_person ON replacement_decision(person_id, voided);

-- variazioni di RAL da CCNL (scatti, rinnovi): le registra HR direttamente
INSERT OR IGNORE INTO lookup (category, code, label, sort_order) VALUES ('change_type', 'ccnl', 'Variazione CCNL', 5);
