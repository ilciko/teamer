-- Chiusura e riporto del budget assunzioni.
--
-- Un budget assunzioni non finiva mai: restava a pagina piena anche ad anno
-- concluso. Ora si chiude come il budget aumenti (0008), e la chiusura può
-- portarsi dietro ciò che non è stato speso — le posizioni ancora aperte e una
-- quota di tetto — su un budget esistente o su uno nuovo.
--
-- Il riporto NON viene sommato dentro `total_cap`: resta un record a sé, così
-- il tetto proprio dell'anno e il riporto dell'anno precedente restano leggibili
-- separatamente e un trasferimento sbagliato si annulla (voided=1) senza dover
-- ricalcolare a mano i tetti dei due budget.
ALTER TABLE hiring_budget ADD COLUMN status TEXT NOT NULL DEFAULT 'aperto';

CREATE TABLE hiring_transfer (
    id INTEGER PRIMARY KEY,
    from_budget_id INTEGER NOT NULL REFERENCES hiring_budget(id),
    to_budget_id INTEGER NOT NULL REFERENCES hiring_budget(id),
    amount REAL NOT NULL DEFAULT 0,
    note TEXT,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT
);

CREATE INDEX idx_transfer_to ON hiring_transfer(to_budget_id, voided);

-- La posizione ricorda con quale riporto è arrivata: nel budget nuovo si
-- distingue a colpo d'occhio ciò che viene dall'anno prima.
ALTER TABLE hiring_position ADD COLUMN transfer_id INTEGER REFERENCES hiring_transfer(id);
