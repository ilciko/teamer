-- Proprietari: le tabelle "del director" (configurazione, contenitori, team) prendono
-- owner_user_id. Il default teamer_owner() è una funzione registrata sulla connessione
-- della sessione (app/db.py): la riga nuova prende il proprietario da sola. NULL = dati
-- «da assegnare»: dopo questa migrazione tutto l'esistente lo è, finché l'admin non lo
-- assegna a un director (Amministrazione → Dati da assegnare). Un default con funzione
-- non si aggiunge con ALTER: le tabelle si ricostruiscono (come nella 0012), con le
-- UNIQUE della configurazione allargate al proprietario. Vedi docs/perimetri.md.
PRAGMA foreign_keys=OFF;
BEGIN;

-- lookup
CREATE TABLE lookup_new (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,
    code TEXT NOT NULL,
    label TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id),
    UNIQUE (owner_user_id, category, code)
);
INSERT INTO lookup_new (id, category, code, label, sort_order, active) SELECT id, category, code, label, sort_order, active FROM lookup;
DROP TABLE lookup;
ALTER TABLE lookup_new RENAME TO lookup;
CREATE INDEX idx_lookup_owner ON lookup(owner_user_id);

-- ninebox_weight
CREATE TABLE ninebox_weight_new (
    id INTEGER PRIMARY KEY,
    role_type TEXT NOT NULL,
    seniority TEXT NOT NULL,
    perf_adj REAL NOT NULL DEFAULT 0,
    pot_adj REAL NOT NULL DEFAULT 0,
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id),
    UNIQUE (owner_user_id, role_type, seniority)
);
INSERT INTO ninebox_weight_new (role_type, seniority, perf_adj, pot_adj) SELECT role_type, seniority, perf_adj, pot_adj FROM ninebox_weight;
DROP TABLE ninebox_weight;
ALTER TABLE ninebox_weight_new RENAME TO ninebox_weight;
CREATE INDEX idx_ninebox_weight_owner ON ninebox_weight(owner_user_id);

-- weight_mapping
CREATE TABLE weight_mapping_new (
    id INTEGER PRIMARY KEY,
    box_number INTEGER NOT NULL,
    weight REAL NOT NULL DEFAULT 0,
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id),
    UNIQUE (owner_user_id, box_number)
);
INSERT INTO weight_mapping_new (box_number, weight) SELECT box_number, weight FROM weight_mapping;
DROP TABLE weight_mapping;
ALTER TABLE weight_mapping_new RENAME TO weight_mapping;
CREATE INDEX idx_weight_mapping_owner ON weight_mapping(owner_user_id);

-- evaluation_model
CREATE TABLE evaluation_model_new (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 1,
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id)
);
INSERT INTO evaluation_model_new (id, name, type, config, active) SELECT id, name, type, config, active FROM evaluation_model;
DROP TABLE evaluation_model;
ALTER TABLE evaluation_model_new RENAME TO evaluation_model;
CREATE INDEX idx_evaluation_model_owner ON evaluation_model(owner_user_id);

-- bonus_factor
CREATE TABLE bonus_factor_new (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    code TEXT NOT NULL,
    factor REAL NOT NULL,
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id),
    UNIQUE (owner_user_id, kind, code)
);
INSERT INTO bonus_factor_new (kind, code, factor) SELECT kind, code, factor FROM bonus_factor;
DROP TABLE bonus_factor;
ALTER TABLE bonus_factor_new RENAME TO bonus_factor;
CREATE INDEX idx_bonus_factor_owner ON bonus_factor(owner_user_id);

-- benefit_type
CREATE TABLE benefit_type_new (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    value_kind TEXT NOT NULL DEFAULT 'boolean',
    enum_options TEXT,
    is_cost INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id)
);
INSERT INTO benefit_type_new (id, name, value_kind, enum_options, is_cost, active) SELECT id, name, value_kind, enum_options, is_cost, active FROM benefit_type;
DROP TABLE benefit_type;
ALTER TABLE benefit_type_new RENAME TO benefit_type;
CREATE INDEX idx_benefit_type_owner ON benefit_type(owner_user_id);

-- listino_profile
CREATE TABLE listino_profile_new (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL,
    description TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    day_rate REAL,
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id),
    UNIQUE (owner_user_id, code)
);
INSERT INTO listino_profile_new (id, code, description, active, sort_order, day_rate) SELECT id, code, description, active, sort_order, day_rate FROM listino_profile;
DROP TABLE listino_profile;
ALTER TABLE listino_profile_new RENAME TO listino_profile;
CREATE INDEX idx_listino_profile_owner ON listino_profile(owner_user_id);

-- review_cycle
CREATE TABLE review_cycle_new (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    year INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'aperto',
    note TEXT,
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id)
);
INSERT INTO review_cycle_new (id, name, year, status, note) SELECT id, name, year, status, note FROM review_cycle;
DROP TABLE review_cycle;
ALTER TABLE review_cycle_new RENAME TO review_cycle;
CREATE INDEX idx_review_cycle_owner ON review_cycle(owner_user_id);

-- ral_budget
CREATE TABLE ral_budget_new (
    id INTEGER PRIMARY KEY,
    period TEXT NOT NULL,
    cycle_id INTEGER REFERENCES review_cycle(id),
    total_cap REAL NOT NULL,
    description TEXT,
    pct REAL,
    year INTEGER,
    status TEXT NOT NULL DEFAULT 'aperto',
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id)
);
INSERT INTO ral_budget_new (id, period, cycle_id, total_cap, description, pct, year, status) SELECT id, period, cycle_id, total_cap, description, pct, year, status FROM ral_budget;
DROP TABLE ral_budget;
ALTER TABLE ral_budget_new RENAME TO ral_budget;
CREATE INDEX idx_ral_budget_owner ON ral_budget(owner_user_id);

-- bonus_pool
CREATE TABLE bonus_pool_new (
    id INTEGER PRIMARY KEY,
    period TEXT NOT NULL,
    cycle_id INTEGER REFERENCES review_cycle(id),
    total_cap REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'bozza',
    use_box INTEGER NOT NULL DEFAULT 1,
    use_role INTEGER NOT NULL DEFAULT 1,
    use_rating INTEGER NOT NULL DEFAULT 1,
    use_goal INTEGER NOT NULL DEFAULT 1,
    per_head REAL,
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id)
);
INSERT INTO bonus_pool_new (id, period, cycle_id, total_cap, status, use_box, use_role, use_rating, use_goal, per_head) SELECT id, period, cycle_id, total_cap, status, use_box, use_role, use_rating, use_goal, per_head FROM bonus_pool;
DROP TABLE bonus_pool;
ALTER TABLE bonus_pool_new RENAME TO bonus_pool;
CREATE INDEX idx_bonus_pool_owner ON bonus_pool(owner_user_id);

-- hiring_budget
CREATE TABLE hiring_budget_new (
    id INTEGER PRIMARY KEY,
    period TEXT NOT NULL,
    year INTEGER NOT NULL,
    total_cap REAL NOT NULL,
    note TEXT,
    status TEXT NOT NULL DEFAULT 'aperto',
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id)
);
INSERT INTO hiring_budget_new (id, period, year, total_cap, note, status) SELECT id, period, year, total_cap, note, status FROM hiring_budget;
DROP TABLE hiring_budget;
ALTER TABLE hiring_budget_new RENAME TO hiring_budget;
CREATE INDEX idx_hiring_budget_owner ON hiring_budget(owner_user_id);

-- hiring_transfer
CREATE TABLE hiring_transfer_new (
    id INTEGER PRIMARY KEY,
    from_budget_id INTEGER NOT NULL REFERENCES hiring_budget(id),
    to_budget_id INTEGER NOT NULL REFERENCES hiring_budget(id),
    amount REAL NOT NULL DEFAULT 0,
    note TEXT,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT,
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id)
);
INSERT INTO hiring_transfer_new (id, from_budget_id, to_budget_id, amount, note, created_at, voided, void_reason) SELECT id, from_budget_id, to_budget_id, amount, note, created_at, voided, void_reason FROM hiring_transfer;
DROP TABLE hiring_transfer;
ALTER TABLE hiring_transfer_new RENAME TO hiring_transfer;
CREATE INDEX idx_transfer_to ON hiring_transfer(to_budget_id, voided);
CREATE INDEX idx_hiring_transfer_owner ON hiring_transfer(owner_user_id);

-- reorg_scenario
CREATE TABLE reorg_scenario_new (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'bozza',
    effective_date DATE,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    approved_at DATETIME,
    applied_at DATETIME,
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id)
);
INSERT INTO reorg_scenario_new (id, name, description, status, effective_date, created_at, approved_at, applied_at) SELECT id, name, description, status, effective_date, created_at, approved_at, applied_at FROM reorg_scenario;
DROP TABLE reorg_scenario;
ALTER TABLE reorg_scenario_new RENAME TO reorg_scenario;
CREATE INDEX idx_reorg_scenario_owner ON reorg_scenario(owner_user_id);

-- hiring_position
CREATE TABLE hiring_position_new (
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
    void_reason TEXT,
    replaces_person_id INTEGER REFERENCES person(id),
    transfer_id INTEGER REFERENCES hiring_transfer(id),
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id)
);
INSERT INTO hiring_position_new (id, budget_id, title, team_id, role_type, expected_ral, expected_start, status, person_id, note, created_at, voided, void_reason, replaces_person_id, transfer_id) SELECT id, budget_id, title, team_id, role_type, expected_ral, expected_start, status, person_id, note, created_at, voided, void_reason, replaces_person_id, transfer_id FROM hiring_position;
DROP TABLE hiring_position;
ALTER TABLE hiring_position_new RENAME TO hiring_position;
CREATE INDEX idx_position_budget ON hiring_position(budget_id, status);
CREATE INDEX idx_hiring_position_owner ON hiring_position(owner_user_id);

-- reorg_team
CREATE TABLE reorg_team_new (
    id INTEGER PRIMARY KEY,
    scenario_id INTEGER NOT NULL REFERENCES reorg_scenario(id) ON DELETE CASCADE,
    team_id INTEGER REFERENCES team(id),
    name TEXT NOT NULL,
    parent_ref INTEGER,
    lead_person_id INTEGER REFERENCES person(id),
    sort_order INTEGER NOT NULL DEFAULT 0,
    removed INTEGER NOT NULL DEFAULT 0,
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id)
);
INSERT INTO reorg_team_new (id, scenario_id, team_id, name, parent_ref, lead_person_id, sort_order, removed) SELECT id, scenario_id, team_id, name, parent_ref, lead_person_id, sort_order, removed FROM reorg_team;
DROP TABLE reorg_team;
ALTER TABLE reorg_team_new RENAME TO reorg_team;
CREATE INDEX idx_reorg_team_owner ON reorg_team(owner_user_id);

-- reorg_move
CREATE TABLE reorg_move_new (
    scenario_id INTEGER NOT NULL REFERENCES reorg_scenario(id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES person(id),
    team_ref INTEGER NOT NULL,
    role_type TEXT NOT NULL,
    hidden INTEGER NOT NULL DEFAULT 0,
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id),
    PRIMARY KEY (scenario_id, person_id)
);
INSERT INTO reorg_move_new (scenario_id, person_id, team_ref, role_type, hidden) SELECT scenario_id, person_id, team_ref, role_type, hidden FROM reorg_move;
DROP TABLE reorg_move;
ALTER TABLE reorg_move_new RENAME TO reorg_move;
CREATE INDEX idx_reorg_move_owner ON reorg_move(owner_user_id);

-- reorg_position
CREATE TABLE reorg_position_new (
    id INTEGER PRIMARY KEY,
    scenario_id INTEGER NOT NULL REFERENCES reorg_scenario(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    team_ref INTEGER,
    role_type TEXT NOT NULL DEFAULT 'ic',
    internal INTEGER NOT NULL DEFAULT 0,
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id)
);
INSERT INTO reorg_position_new (id, scenario_id, title, team_ref, role_type, internal) SELECT id, scenario_id, title, team_ref, role_type, internal FROM reorg_position;
DROP TABLE reorg_position;
ALTER TABLE reorg_position_new RENAME TO reorg_position;
CREATE INDEX idx_reorg_position_owner ON reorg_position(owner_user_id);

-- reorg_position_move
CREATE TABLE reorg_position_move_new (
    scenario_id INTEGER NOT NULL REFERENCES reorg_scenario(id) ON DELETE CASCADE,
    position_id INTEGER NOT NULL REFERENCES hiring_position(id) ON DELETE CASCADE,
    team_ref INTEGER NOT NULL,
    role_type TEXT NOT NULL,
    hidden INTEGER NOT NULL DEFAULT 0,
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id),
    PRIMARY KEY (scenario_id, position_id)
);
INSERT INTO reorg_position_move_new (scenario_id, position_id, team_ref, role_type, hidden) SELECT scenario_id, position_id, team_ref, role_type, hidden FROM reorg_position_move;
DROP TABLE reorg_position_move;
ALTER TABLE reorg_position_move_new RENAME TO reorg_position_move;
CREATE INDEX idx_reorg_position_move_owner ON reorg_position_move(owner_user_id);

-- team
CREATE TABLE team_new (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_team_id INTEGER REFERENCES team(id),
    lead_person_id INTEGER REFERENCES person(id),
    description TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    archived_at DATETIME,
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id)
);
INSERT INTO team_new (id, name, parent_team_id, lead_person_id, description, sort_order, archived_at) SELECT id, name, parent_team_id, lead_person_id, description, sort_order, archived_at FROM team;
DROP TABLE team;
ALTER TABLE team_new RENAME TO team;
CREATE INDEX idx_team_owner ON team(owner_user_id);

-- bonus_allocation: pool_id facoltativo
CREATE TABLE bonus_allocation_new (
    id INTEGER PRIMARY KEY,
    pool_id INTEGER REFERENCES bonus_pool(id),
    person_id INTEGER NOT NULL REFERENCES person(id),
    weight REAL NOT NULL DEFAULT 0,
    proposed_amount REAL,
    final_amount REAL,
    note TEXT,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT, weight_detail TEXT, included INTEGER NOT NULL DEFAULT 1,
    UNIQUE (pool_id, person_id)
);
INSERT INTO bonus_allocation_new (id, pool_id, person_id, weight, proposed_amount, final_amount, note, created_at, voided, void_reason, weight_detail, included) SELECT id, pool_id, person_id, weight, proposed_amount, final_amount, note, created_at, voided, void_reason, weight_detail, included FROM bonus_allocation;
DROP TABLE bonus_allocation;
ALTER TABLE bonus_allocation_new RENAME TO bonus_allocation;

-- configurazione per director che stava in app_meta
CREATE TABLE user_meta (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL,
    value TEXT,
    owner_user_id INTEGER DEFAULT (teamer_owner()) REFERENCES app_user(id),
    UNIQUE (owner_user_id, key)
);
INSERT INTO user_meta (key, value)
    SELECT key, value FROM app_meta
     WHERE key IN ('default_ccnl', 'ral_stale_amber_years', 'ral_stale_red_years') OR key LIKE 'listino\_%' ESCAPE '\';
DELETE FROM app_meta
 WHERE key IN ('default_ccnl', 'ral_stale_amber_years', 'ral_stale_red_years') OR key LIKE 'listino\_%' ESCAPE '\';

COMMIT;
PRAGMA foreign_keys=ON;
