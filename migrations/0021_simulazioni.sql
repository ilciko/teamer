-- Simulazioni di riorganizzazione: prove di organigramma da confrontare e approvare.
--
-- Una simulazione non copia l'organigramma: salva solo le differenze rispetto
-- alla realtà (team nuovi o modificati, spostamenti di persone, posizioni
-- ipotetiche). Lo stato simulato = realtà di oggi + differenze, quindi chi entra o
-- esce nel frattempo compare da solo in ogni simulazione. I riporti non si
-- salvano: si ricalcolano con la stessa regola dell'organigramma reale.
--
-- Riferimento a un team (parent_ref, team_ref): > 0 = team reale (team.id),
-- < 0 = team nuovo della simulazione (-reorg_team.id), NULL = nessuno/radice.
-- Niente FK su questi campi: un team reale eliminato fa solo cadere la modifica.
--
-- Stati: bozza (modificabile) → approvata → applicata (con data: team creati e
-- modificati, spostamenti registrati come nuove assegnazioni) | scartata.

CREATE TABLE reorg_scenario (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'bozza',
    effective_date DATE,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    approved_at DATETIME,
    applied_at DATETIME
);

-- team_id NULL = team nuovo; altrimenti sovrascrive per intero i dati del team reale
CREATE TABLE reorg_team (
    id INTEGER PRIMARY KEY,
    scenario_id INTEGER NOT NULL REFERENCES reorg_scenario(id) ON DELETE CASCADE,
    team_id INTEGER REFERENCES team(id),
    name TEXT NOT NULL,
    parent_ref INTEGER,
    lead_person_id INTEGER REFERENCES person(id),
    sort_order INTEGER NOT NULL DEFAULT 0,
    removed INTEGER NOT NULL DEFAULT 0
);

-- una riga solo per chi cambia team o ruolo rispetto alla realtà
CREATE TABLE reorg_move (
    scenario_id INTEGER NOT NULL REFERENCES reorg_scenario(id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES person(id),
    team_ref INTEGER NOT NULL,
    role_type TEXT NOT NULL,
    PRIMARY KEY (scenario_id, person_id)
);

-- posizioni che esistono solo nella simulazione
CREATE TABLE reorg_position (
    id INTEGER PRIMARY KEY,
    scenario_id INTEGER NOT NULL REFERENCES reorg_scenario(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    team_ref INTEGER,
    role_type TEXT NOT NULL DEFAULT 'ic'
);

INSERT INTO lookup (category, code, label, sort_order) VALUES
    ('reorg_status','bozza','Bozza',1),
    ('reorg_status','approvata','Approvata',2),
    ('reorg_status','applicata','Applicata',3),
    ('reorg_status','scartata','Scartata',4);
