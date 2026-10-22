-- Teamer schema v1 — 28 tabelle in 4 aree (vedi docs/schema_team_tool.md)
-- Convenzione: le tabelle a eventi hanno created_at, voided, void_reason;
-- le viste "stato attuale" filtrano voided = 0.

-- ============ AREA 1 — CORE / ORGANIGRAMMA ============

CREATE TABLE person (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    avatar BLOB,
    hire_date DATE,
    birth_date DATE,
    email TEXT,
    status TEXT NOT NULL DEFAULT 'attivo',
    end_date DATE,
    notes TEXT
);

CREATE TABLE team (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_team_id INTEGER REFERENCES team(id),
    lead_person_id INTEGER REFERENCES person(id),
    description TEXT
);

CREATE TABLE person_assignment (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    team_id INTEGER NOT NULL REFERENCES team(id),
    manager_person_id INTEGER REFERENCES person(id),
    role_type TEXT NOT NULL DEFAULT 'ic',
    start_date DATE NOT NULL,
    end_date DATE,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT
);

CREATE TABLE employment (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    livello TEXT,
    ccnl TEXT,
    tipo_contratto TEXT,
    smartwork TEXT,
    timbratura_scheme TEXT,
    part_time_pct REAL NOT NULL DEFAULT 100,
    weekly_hours REAL,
    start_date DATE NOT NULL,
    end_date DATE,
    note TEXT,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT
);

CREATE TABLE lookup (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,
    code TEXT NOT NULL,
    label TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (category, code)
);

CREATE TABLE app_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- ============ AREA 2 — VALUTAZIONI E OBIETTIVI ============

CREATE TABLE review_cycle (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    year INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'aperto',
    note TEXT
);

CREATE TABLE evaluation_model (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE evaluation (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    model_id INTEGER NOT NULL REFERENCES evaluation_model(id),
    cycle_id INTEGER REFERENCES review_cycle(id),
    eval_date DATE NOT NULL,
    overall_score REAL,
    status TEXT NOT NULL DEFAULT 'bozza',
    note TEXT,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT
);

CREATE TABLE evaluation_item (
    id INTEGER PRIMARY KEY,
    evaluation_id INTEGER NOT NULL REFERENCES evaluation(id),
    competency TEXT NOT NULL,
    self_score REAL,
    manager_score REAL,
    weight REAL NOT NULL DEFAULT 1,
    self_note TEXT,
    manager_note TEXT
);

CREATE TABLE ninebox_assessment (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    evaluation_id INTEGER REFERENCES evaluation(id),
    eval_date DATE NOT NULL,
    role_type TEXT NOT NULL,
    seniority TEXT NOT NULL,
    raw_perf REAL NOT NULL,
    raw_pot REAL NOT NULL,
    adj_perf REAL NOT NULL,
    adj_pot REAL NOT NULL,
    perf_level TEXT NOT NULL,
    pot_level TEXT NOT NULL,
    box_number INTEGER NOT NULL,
    weights_snapshot TEXT NOT NULL,
    answers TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT
);

CREATE TABLE ninebox_weight (
    role_type TEXT NOT NULL,
    seniority TEXT NOT NULL,
    perf_adj REAL NOT NULL DEFAULT 0,
    pot_adj REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (role_type, seniority)
);

CREATE TABLE weight_mapping (
    box_number INTEGER PRIMARY KEY,
    weight REAL NOT NULL DEFAULT 0
);

CREATE TABLE goal (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    cycle_id INTEGER NOT NULL REFERENCES review_cycle(id),
    category TEXT NOT NULL DEFAULT 'professionale',
    description TEXT NOT NULL,
    weight_pct REAL NOT NULL,
    note TEXT,
    status TEXT NOT NULL DEFAULT 'attivo',
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT
);

CREATE TABLE performance_review (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    cycle_id INTEGER NOT NULL REFERENCES review_cycle(id),
    review_date DATE,
    overall_rating INTEGER,
    overall_employee_comment TEXT,
    overall_tl_comment TEXT,
    growth_self_comment TEXT,
    growth_tl_comment TEXT,
    synthesis_employee_comment TEXT,
    synthesis_tl_comment TEXT,
    status TEXT NOT NULL DEFAULT 'bozza',
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT,
    UNIQUE (person_id, cycle_id)
);

CREATE TABLE goal_review (
    id INTEGER PRIMARY KEY,
    goal_id INTEGER NOT NULL REFERENCES goal(id),
    review_id INTEGER NOT NULL REFERENCES performance_review(id),
    self_score REAL,
    tl_score REAL,
    note TEXT,
    UNIQUE (goal_id, review_id)
);

CREATE TABLE wellbeing_entry (
    id INTEGER PRIMARY KEY,
    review_id INTEGER NOT NULL UNIQUE REFERENCES performance_review(id),
    workload_rating TEXT,
    workload_employee_comment TEXT,
    workload_tl_comment TEXT,
    satisfaction_rating TEXT,
    satisfaction_employee_comment TEXT,
    satisfaction_tl_comment TEXT,
    wlb_resources INTEGER,
    wlb_resources_note TEXT,
    wlb_time_difficulty INTEGER,
    wlb_time_note TEXT,
    wlb_balance INTEGER,
    wlb_balance_note TEXT,
    tl_comment TEXT
);

-- ============ AREA 3 — RETRIBUZIONE ============

CREATE TABLE ral_budget (
    id INTEGER PRIMARY KEY,
    period TEXT NOT NULL,
    cycle_id INTEGER REFERENCES review_cycle(id),
    total_cap REAL NOT NULL,
    description TEXT
);

CREATE TABLE ral_event (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    budget_id INTEGER REFERENCES ral_budget(id),
    effective_date DATE NOT NULL,
    amount REAL NOT NULL,
    delta REAL NOT NULL DEFAULT 0,
    change_type TEXT NOT NULL DEFAULT 'aumento',
    reason TEXT,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT
);

CREATE TABLE ral_projection (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    scenario TEXT NOT NULL,
    target_date DATE NOT NULL,
    projected_amount REAL NOT NULL,
    note TEXT,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT
);

CREATE TABLE benefit_type (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    value_kind TEXT NOT NULL DEFAULT 'boolean',
    enum_options TEXT,
    is_cost INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE benefit_assignment (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    benefit_type_id INTEGER NOT NULL REFERENCES benefit_type(id),
    value TEXT,
    effective_date DATE NOT NULL,
    end_date DATE,
    reason TEXT,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT
);

CREATE TABLE incentive (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    inc_date DATE NOT NULL,
    amount REAL NOT NULL,
    reason TEXT,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT
);

CREATE TABLE bonus_pool (
    id INTEGER PRIMARY KEY,
    period TEXT NOT NULL,
    cycle_id INTEGER REFERENCES review_cycle(id),
    total_cap REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'bozza'
);

CREATE TABLE bonus_allocation (
    id INTEGER PRIMARY KEY,
    pool_id INTEGER NOT NULL REFERENCES bonus_pool(id),
    person_id INTEGER NOT NULL REFERENCES person(id),
    weight REAL NOT NULL DEFAULT 0,
    proposed_amount REAL,
    final_amount REAL,
    note TEXT,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT,
    UNIQUE (pool_id, person_id)
);

-- ============ AREA 4 — INTERAZIONI E DOCUMENTI ============

CREATE TABLE meeting_note (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    note_date DATE NOT NULL,
    type TEXT NOT NULL DEFAULT '1:1',
    title TEXT,
    body TEXT,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE action_item (
    id INTEGER PRIMARY KEY,
    meeting_note_id INTEGER REFERENCES meeting_note(id),
    person_id INTEGER NOT NULL REFERENCES person(id),
    description TEXT NOT NULL,
    due_date DATE,
    status TEXT NOT NULL DEFAULT 'aperto',
    closed_date DATE,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE attachment (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    review_id INTEGER REFERENCES performance_review(id),
    filename TEXT NOT NULL,
    mime TEXT,
    content BLOB NOT NULL,
    note TEXT,
    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Ricerca full-text sulle note (contentless-delete non serve: content=meeting_note)
CREATE VIRTUAL TABLE meeting_note_fts USING fts5(
    title, body, content='meeting_note', content_rowid='id'
);
CREATE TRIGGER meeting_note_ai AFTER INSERT ON meeting_note BEGIN
    INSERT INTO meeting_note_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;
CREATE TRIGGER meeting_note_ad AFTER DELETE ON meeting_note BEGIN
    INSERT INTO meeting_note_fts(meeting_note_fts, rowid, title, body) VALUES ('delete', old.id, old.title, old.body);
END;
CREATE TRIGGER meeting_note_au AFTER UPDATE ON meeting_note BEGIN
    INSERT INTO meeting_note_fts(meeting_note_fts, rowid, title, body) VALUES ('delete', old.id, old.title, old.body);
    INSERT INTO meeting_note_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;

-- ============ INDICI ============

CREATE INDEX idx_assignment_person ON person_assignment(person_id, end_date);
CREATE INDEX idx_assignment_team ON person_assignment(team_id, end_date);
CREATE INDEX idx_employment_person ON employment(person_id, end_date);
CREATE INDEX idx_ral_person ON ral_event(person_id, effective_date);
CREATE INDEX idx_benefit_person ON benefit_assignment(person_id, end_date);
CREATE INDEX idx_ninebox_person ON ninebox_assessment(person_id, eval_date);
CREATE INDEX idx_goal_person_cycle ON goal(person_id, cycle_id);
CREATE INDEX idx_note_person ON meeting_note(person_id, note_date);
CREATE INDEX idx_action_person ON action_item(person_id, status);

-- ============ SEED — CONFIG ============

INSERT INTO lookup (category, code, label, sort_order) VALUES
    ('role_type','ic','Collaboratore / Specialist',1),
    ('role_type','tl','Referente / Team Lead',2),
    ('role_type','mgr','Manager / Responsabile',3),
    ('role_type','sr','Senior Manager / Director+',4),
    ('seniority','new','Nuovo nel ruolo (< 12 mesi)',1),
    ('seniority','mid','In ruolo (1–3 anni)',2),
    ('seniority','sen','Consolidato (> 3 anni)',3),
    ('livello','operaio','Operaio',1),
    ('livello','impiegato','Impiegato',2),
    ('livello','quadro','Quadro',3),
    ('livello','dirigente','Dirigente',4),
    ('tipo_contratto','indeterminato','Indeterminato',1),
    ('tipo_contratto','determinato','Determinato',2),
    ('tipo_contratto','apprendistato','Apprendistato',3),
    ('tipo_contratto','collaborazione','Collaborazione',4),
    ('smartwork','no','No',1),
    ('smartwork','parziale','Parziale',2),
    ('smartwork','full','Full remote',3),
    ('timbratura','esente','Esente',1),
    ('timbratura','4_timbrate','4 timbrate',2),
    ('timbratura','solo_presenza','Solo presenza',3),
    ('change_type','assunzione','Assunzione',1),
    ('change_type','aumento','Aumento',2),
    ('change_type','promozione','Promozione',3),
    ('change_type','adeguamento','Adeguamento',4),
    ('meeting_type','1:1','1:1',1),
    ('meeting_type','review','Review',2),
    ('meeting_type','feedback','Feedback',3),
    ('meeting_type','altro','Altro',4),
    ('goal_category','professionale','Professionale',1),
    ('goal_category','personale','Personale',2),
    ('workload','molto_inferiore','Decisamente inferiore alle aspettative',1),
    ('workload','inferiore','Inferiore alle aspettative',2),
    ('workload','in_linea','In linea alle aspettative',3),
    ('workload','superiore','Superiore alle aspettative',4),
    ('satisfaction','per_nulla','Per nulla soddisfatto/a',1),
    ('satisfaction','poco','Poco soddisfatto/a',2),
    ('satisfaction','soddisfatto','Soddisfatto/a',3),
    ('satisfaction','molto','Molto soddisfatto/a',4),
    ('overall_rating','1','1 — Serve un forte miglioramento',1),
    ('overall_rating','2','2 — Serve miglioramento',2),
    ('overall_rating','3','3 — Soddisfa le aspettative',3),
    ('overall_rating','4','4 — Supera le aspettative',4),
    ('overall_rating','5','5 — Eccezionale',5);

-- Aggiustamenti 9-box: riproducono l'artefatto HTML (new = penalità/bonus per ruolo,
-- mid = neutro, sen = -0.10/-0.10 che nell'artefatto era hardcoded)
INSERT INTO ninebox_weight (role_type, seniority, perf_adj, pot_adj) VALUES
    ('ic','new',-0.40,0.10), ('tl','new',-0.25,0.15), ('mgr','new',-0.10,0.20), ('sr','new',0.00,0.25),
    ('ic','mid',0,0), ('tl','mid',0,0), ('mgr','mid',0,0), ('sr','mid',0,0),
    ('ic','sen',-0.10,-0.10), ('tl','sen',-0.10,-0.10), ('mgr','sen',-0.10,-0.10), ('sr','sen',-0.10,-0.10);

INSERT INTO weight_mapping (box_number, weight) VALUES
    (1,0),(2,0.5),(3,0.5),(4,1.0),(5,1.0),(6,1.5),(7,1.5),(8,2.0),(9,3.0);

INSERT INTO app_meta (key, value) VALUES ('schema_version', '1');
