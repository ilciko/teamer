-- Piano aumenti: proposte con ciclo di vita (HR) prima di diventare eventi RAL reali.
-- Più righe per persona/budget = più step (tranche).

CREATE TABLE ral_proposal (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    budget_id INTEGER REFERENCES ral_budget(id),
    amount REAL NOT NULL DEFAULT 0,        -- delta proposto (0 ammesso: solo cambio livello)
    effective_date DATE,                   -- decorrenza prevista, propria della riga
    new_livello TEXT,                      -- eventuale passaggio di livello
    status TEXT NOT NULL DEFAULT 'bozza',  -- bozza/proposta/approvata/applicata/respinta
    note TEXT,
    proposed_at DATE,                      -- quando inviata a HR
    decided_at DATE,                       -- quando approvata o respinta
    ral_event_id INTEGER REFERENCES ral_event(id),
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT
);

CREATE INDEX idx_proposal_budget ON ral_proposal(budget_id, status);
CREATE INDEX idx_proposal_person ON ral_proposal(person_id, status);

INSERT INTO lookup (category, code, label, sort_order) VALUES
    ('proposal_status','bozza','Bozza',1),
    ('proposal_status','proposta','Proposta a HR',2),
    ('proposal_status','approvata','Approvata',3),
    ('proposal_status','applicata','Applicata',4),
    ('proposal_status','respinta','Respinta',5);
