-- Budget nuove assunzioni: tetto + posizioni pianificate con ciclo di vita.
-- Impegnato = RAL previste delle posizioni aperte; applicato = RAL reali degli assunti collegati.

CREATE TABLE hiring_budget (
    id INTEGER PRIMARY KEY,
    period TEXT NOT NULL,
    year INTEGER NOT NULL,
    total_cap REAL NOT NULL,
    note TEXT
);

CREATE TABLE hiring_position (
    id INTEGER PRIMARY KEY,
    budget_id INTEGER NOT NULL REFERENCES hiring_budget(id),
    title TEXT NOT NULL,
    team_id INTEGER REFERENCES team(id),
    role_type TEXT DEFAULT 'ic',
    expected_ral REAL NOT NULL DEFAULT 0,
    expected_start DATE,
    status TEXT NOT NULL DEFAULT 'pianificata',
    person_id INTEGER REFERENCES person(id),
    note TEXT,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT
);

CREATE INDEX idx_position_budget ON hiring_position(budget_id, status);

INSERT INTO lookup (category, code, label, sort_order) VALUES
    ('position_status','pianificata','Pianificata',1),
    ('position_status','in_selezione','In selezione',2),
    ('position_status','assunta','Assunta',3),
    ('position_status','annullata','Annullata',4);
