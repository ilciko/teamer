-- Utenti e audit.
-- Il DB è cifrato con una chiave di sistema su file (solo IT); la password di login
-- è dell'utente e qui ne sta solo l'hash scrypt. Ruoli: admin (site admin, IT: utenti,
-- audit, backup, aggiornamenti, nessun dato del personale) e director (il COO: tutto il
-- resto). Gli utenti si modificano in place e si disattivano, non si cancellano:
-- l'audit punta a loro.
CREATE TABLE app_user (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT,
    role TEXT NOT NULL CHECK (role IN ('admin', 'director')),
    password_hash TEXT NOT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    public_mode INTEGER NOT NULL DEFAULT 0,
    failed_logins INTEGER NOT NULL DEFAULT 0,
    locked_until DATETIME,
    last_login_at DATETIME,
    password_changed_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Append-only: nessuna route aggiorna o cancella. username è copiato perché resti
-- leggibile anche per i tentativi con un nome inesistente (user_id NULL).
CREATE TABLE audit_event (
    id INTEGER PRIMARY KEY,
    at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    user_id INTEGER REFERENCES app_user(id),
    username TEXT,
    event TEXT NOT NULL,
    detail TEXT,
    ip TEXT
);
CREATE INDEX idx_audit_event_at ON audit_event(at);
CREATE INDEX idx_audit_event_user ON audit_event(user_id);
