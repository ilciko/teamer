-- Premio di ruolo (0.46): HR lo invia ai director («in_approvazione»); ogni director vede le sue
-- persone, può cambiare il ruolo usato per il premio e approva la sua parte; HR chiude.
CREATE TABLE bonus_pool_approval (
    id INTEGER PRIMARY KEY,
    pool_id INTEGER NOT NULL REFERENCES bonus_pool(id),
    user_id INTEGER NOT NULL REFERENCES app_user(id),
    approved_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    note TEXT,
    UNIQUE (pool_id, user_id)
);
