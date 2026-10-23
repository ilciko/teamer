-- Ruolo `hr`: profilo aziendale trasversale (vede le persone di tutti i director; in questa
-- versione in sola lettura, le scritture arrivano nelle tappe successive). Il CHECK sul ruolo
-- non si modifica con ALTER: la tabella si ricostruisce, come nella 0028.
PRAGMA foreign_keys=OFF;
BEGIN;

CREATE TABLE app_user_new (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT,
    role TEXT NOT NULL CHECK (role IN ('admin', 'director', 'hr')),
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
INSERT INTO app_user_new (id, username, display_name, role, password_hash, must_change_password, active,
                          public_mode, failed_logins, locked_until, last_login_at, password_changed_at, created_at)
    SELECT id, username, display_name, role, password_hash, must_change_password, active,
           public_mode, failed_logins, locked_until, last_login_at, password_changed_at, created_at FROM app_user;
DROP TABLE app_user;
ALTER TABLE app_user_new RENAME TO app_user;

COMMIT;
PRAGMA foreign_keys=ON;
