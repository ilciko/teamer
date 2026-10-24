"""Perimetri per director: chi vede cosa (docs/perimetri.md).

Ogni tabella sta in esattamente una classe (`CLASSES`, verificato da tests/test_perimeter.py):

- `owned`: righe del director che le crea (`owner_user_id`, default `teamer_owner()`):
  configurazione, contenitori (cicli, budget, montepremi, simulazioni) e loro figli
  senza persona. NULL = «da assegnare»: non la vede nessuno finché l'admin non la assegna.
- `child`: righe di persona dentro un contenitore (obiettivi, review, proposte, righe di
  budget e premi): visibili se il contenitore lo è (o se staccate, contenitore NULL).
- `team`: il perimetro del director = i team di cui è titolare.
- `person`: dati di fatto della persona, visibili se la persona è nel perimetro: la sua
  ultima assegnazione valida sta in un team del director, oppure non ne ha nessuna e l'ha
  creata lui (`person.owner_user_id`). Seguono la persona.
- `authored`: note 1:1 e azioni (`author_user_id`, default `teamer_owner()`): ognuno vede e
  scrive solo le proprie, a prescindere dal perimetro della persona. Se la persona esce dal
  perimetro restano a chi le ha scritte, in sola lettura (un'azione si può ancora chiudere);
  il nome della persona arriva dalla vista `perim_note_person`.
- `company`: configurazione aziendale (liste valori, catalogo benefit): una per l'istanza,
  la leggono tutti, la scrive solo la gestione aziendale (`app/routers/company.py`).
- `instance`: utenti, audit, schema — solo connessione di sistema.

Sulla connessione di una sessione `install()` crea, in quest'ordine: le tabelle temporanee
del perimetro (`perim_team`, `perim_person`), le guardie (trigger temporanei BEFORE sulle
tabelle reali), poi le viste temporanee omonime con il filtro. Le guardie vanno prima:
dopo, il nome risolverebbe sulla vista. Trigger AFTER INSERT allargano il perimetro quando
il director crea un team o una persona; i cambi fatti dall'admin (assegnazioni,
trasferimenti) fanno salire `REV` e ogni connessione ricarica il perimetro alla richiesta dopo.

**HR** (0.36): la connessione di sessione di HR vede tutto (viste senza filtro su team, persone,
contenitori e figli) ma in sola lettura: l'authorizer nega ogni scrittura su `main` fuori da
`HR_WRITABLE`, niente perimetro da ricaricare. La configurazione (classe `owned`, `CONFIG` senza i
cataloghi) è la sua, di default: le pagine che la leggono trovano una voce sola. Dalla 0.37 HR ha
note e azioni proprie (classe `authored`, con le stesse guardie dei director sull'autore).
"""
from app import db

# ruoli con una connessione di sessione e una configurazione propria
SESSION_ROLES = ("director", "hr")

# sale a ogni cambio di titolarità fatto dall'admin: le connessioni di sessione ricaricano il perimetro
REV = 0


def bump() -> None:
    global REV
    REV += 1

# tabelle "del director": (colonna FK, tabella padre) che deve essere visibile
OWNED = {
    # configurazione
    "ninebox_weight": [], "weight_mapping": [], "evaluation_model": [],
    "bonus_factor": [], "user_meta": [],
    # contenitori
    "review_cycle": [],
    "ral_budget": [("cycle_id", "review_cycle")],
    "bonus_pool": [("cycle_id", "review_cycle")],
    "hiring_budget": [],
    "hiring_transfer": [("from_budget_id", "hiring_budget"), ("to_budget_id", "hiring_budget")],
    "hiring_position": [("budget_id", "hiring_budget"), ("transfer_id", "hiring_transfer"), ("team_id", "team")],
    "reorg_scenario": [],
    "reorg_team": [("scenario_id", "reorg_scenario")],
    "reorg_move": [("scenario_id", "reorg_scenario")],
    "reorg_position": [("scenario_id", "reorg_scenario")],
    "reorg_position_move": [("scenario_id", "reorg_scenario"), ("position_id", "hiring_position")],
}
# righe di persona in un contenitore: (colonna FK, contenitore)
CHILD = {
    "goal": [("cycle_id", "review_cycle")],
    "performance_review": [("cycle_id", "review_cycle")],
    "goal_review": [("goal_id", "goal"), ("review_id", "performance_review")],
    "wellbeing_entry": [("review_id", "performance_review")],
    "ral_proposal": [("budget_id", "ral_budget")],
    "ral_budget_member": [("budget_id", "ral_budget")],
    "bonus_allocation": [("pool_id", "bonus_pool")],
    "bonus_pool_approval": [("pool_id", "bonus_pool")],
}
# contenitori altrui che un director vede comunque (0.46): il premio di ruolo di HR, una volta inviato
# ai director; le righe di persona che ne dipendono (allocazioni) restano filtrate sul suo perimetro
OWNED_SHARED = {"bonus_pool": "(x.kind = 'ruolo' AND x.status != 'bozza')"}
TEAM = ["team"]
PERSON = ["person", "person_assignment", "employment", "ral_event", "benefit_assignment", "incentive",
          "ninebox_assessment", "attachment", "listino_person_param", "replacement_decision"]
# note e azioni: di chi le scrive (`author_user_id`); per le azioni, fuori perimetro si tocca solo lo stato
AUTHORED = {"meeting_note": (), "action_item": ("status", "closed_date")}
COMPANY = ["lookup", "benefit_type", "listino_profile", "bonus_role_factor"]   # listino 0.41, premi di ruolo 0.43
INSTANCE = ["app_meta", "app_user", "audit_event"]

CLASSES = {"owned": list(OWNED), "child": list(CHILD), "team": TEAM, "person": PERSON,
           "authored": list(AUTHORED), "company": COMPANY, "instance": INSTANCE}
# colonna del proprietario (NULL = da assegnare) nelle tabelle che ne hanno una
OWNER_COL = {t: "author_user_id" for t in AUTHORED} | {t: "owner_user_id" for t in [*OWNED, *TEAM, "person"]}

# configurazione: si copia dai default di fabbrica a ogni director nuovo
CONFIG = ["ninebox_weight", "weight_mapping", "evaluation_model", "bonus_factor", "user_meta"]
# chiave naturale delle voci di configurazione (per fondere quella esistente in quella del director)
NATURAL_KEYS = {"ninebox_weight": ("role_type", "seniority"), "weight_mapping": ("box_number",),
                "bonus_factor": ("kind", "code"), "user_meta": ("key",),
                "evaluation_model": ("type", "name")}
# chi punta alle voci dei cataloghi per id (nessuno dalla 0.41: i codici listino sono aziendali)
CATALOG_REFS: dict[str, list] = {}
# configurazione per director che stava in app_meta (tabella user_meta); CCNL predefinito e
# parametri del listino (`listino_*`, 0.41) sono aziendali
SCOPED_META = {"ral_stale_amber_years", "ral_stale_red_years"}


def scoped_meta(key: str) -> bool:
    return key in SCOPED_META


# ---- HR ----

# configurazione che HR legge come propria (di default)
HR_OWN = [t for t in CONFIG if t not in CATALOG_REFS]
# scritture consentite a HR: {tabella: {colonna, ...}} ("*" = tutte, anche INSERT e DELETE;
# altrimenti solo UPDATE di quelle colonne). Dalla 0.39 (tappa 3): le sue note e azioni, la parte
# contrattuale delle persone (solo sua: contratto, RAL, benefit, incentivi, cessazione e decisione
# di sostituzione), le persone nuove, allegati, e — «in veste di director» — budget aumenti e
# assunzioni con le loro righe e le proposte del piano. Restano fuori team, configurazione, cicli,
# 9-box e montepremi (quest'ultimo arriva dopo).
HR_CONTRACT = ["employment", "ral_event", "benefit_assignment", "incentive", "replacement_decision"]
HR_WRITABLE: dict[str, set] = {t: {"*"} for t in [
    *AUTHORED, *HR_CONTRACT, "person", "person_assignment", "attachment",
    "ral_budget", "ral_budget_member", "ral_proposal",
    "hiring_budget", "hiring_position", "hiring_transfer",
    "bonus_pool", "bonus_allocation"]}   # 0.43: il suo montepremi per ruolo


# ---- viste e guardie sulla connessione di una sessione ----

def _cols(conn, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA main.table_info({table})")]


def _hidden(alias: str, refs) -> str:
    """Condizione SQL vera se uno dei riferimenti punta a un contenitore non visibile."""
    return " OR ".join(f"({alias}.{col} IS NOT NULL AND {alias}.{col} NOT IN (SELECT id FROM {parent}))"
                       for col, parent in refs) or "0"


def _guards_owned(t: str, uid: int, refs) -> list[str]:
    mine_new = f"NEW.owner_user_id IS NOT {uid}"
    bad_new = f"{mine_new} OR {_hidden('NEW', refs)}"
    return [
        f"CREATE TEMP TRIGGER _p_{t}_ins BEFORE INSERT ON main.{t} BEGIN "
        f"SELECT RAISE(ABORT, 'fuori perimetro: {t}') WHERE {bad_new}; END",
        f"CREATE TEMP TRIGGER _p_{t}_upd BEFORE UPDATE ON main.{t} BEGIN "
        f"SELECT RAISE(IGNORE) WHERE OLD.owner_user_id IS NOT {uid}; "
        f"SELECT RAISE(ABORT, 'fuori perimetro: {t}') WHERE {bad_new}; END",
        f"CREATE TEMP TRIGGER _p_{t}_del BEFORE DELETE ON main.{t} BEGIN "
        f"SELECT RAISE(IGNORE) WHERE OLD.owner_user_id IS NOT {uid}; END",
    ]


def _guards_child(t: str, refs) -> list[str]:
    return [
        f"CREATE TEMP TRIGGER _p_{t}_ins BEFORE INSERT ON main.{t} BEGIN "
        f"SELECT RAISE(ABORT, 'fuori perimetro: {t}') WHERE {_hidden('NEW', refs)}; END",
        f"CREATE TEMP TRIGGER _p_{t}_upd BEFORE UPDATE ON main.{t} BEGIN "
        f"SELECT RAISE(IGNORE) WHERE {_hidden('OLD', refs)}; "
        f"SELECT RAISE(ABORT, 'fuori perimetro: {t}') WHERE {_hidden('NEW', refs)}; END",
        f"CREATE TEMP TRIGGER _p_{t}_del BEFORE DELETE ON main.{t} BEGIN "
        f"SELECT RAISE(IGNORE) WHERE {_hidden('OLD', refs)}; END",
    ]


IN_PERSON = "IN (SELECT person_id FROM temp.perim_person)"
IN_TEAM = "IN (SELECT team_id FROM temp.perim_team)"


def _guards_person(t: str) -> list[str]:
    col = "id" if t == "person" else "person_id"
    out = []
    if t == "person":  # nasce del director che la crea ed entra nel perimetro (trigger AFTER INSERT)
        out.append(f"CREATE TEMP TRIGGER _p_person_ins BEFORE INSERT ON main.person BEGIN "
                   f"SELECT RAISE(ABORT, 'fuori perimetro: person') WHERE NEW.owner_user_id IS NOT teamer_owner(); END")
    else:
        extra = f" OR NEW.team_id NOT {IN_TEAM}" if t == "person_assignment" else ""
        out.append(f"CREATE TEMP TRIGGER _p_{t}_ins BEFORE INSERT ON main.{t} BEGIN "
                   f"SELECT RAISE(ABORT, 'fuori perimetro: {t}') WHERE NEW.{col} NOT {IN_PERSON}{extra}; END")
    # un'assegnazione vecchia verso un team altrui (storia) si può correggere, non spostare altrove
    moved = (f" OR (NEW.team_id IS NOT OLD.team_id AND NEW.team_id NOT {IN_TEAM})"
             if t == "person_assignment" else "")
    out += [
        f"CREATE TEMP TRIGGER _p_{t}_upd BEFORE UPDATE ON main.{t} BEGIN "
        f"SELECT RAISE(IGNORE) WHERE OLD.{col} NOT {IN_PERSON}; "
        f"SELECT RAISE(ABORT, 'fuori perimetro: {t}') WHERE NEW.{col} NOT {IN_PERSON}{moved}; END",
        f"CREATE TEMP TRIGGER _p_{t}_del BEFORE DELETE ON main.{t} BEGIN "
        f"SELECT RAISE(IGNORE) WHERE OLD.{col} NOT {IN_PERSON}; END",
    ]
    return out


def _guards_authored(conn, t: str, uid: int, in_person: str | None = IN_PERSON) -> list[str]:
    """Note e azioni: solo le proprie, e nuove solo su persone del perimetro. Per una persona uscita
    dal perimetro la nota è in sola lettura, l'azione cambia solo di stato (`AUTHORED[t]`).
    HR (`in_person=None`) non ha perimetro di persone: contano solo le regole sull'autore."""
    mine = f"NEW.author_user_id IS NOT {uid}"
    ins = mine
    upd_abort = mine
    outside = ""
    if in_person:
        ins += f" OR NEW.person_id NOT {in_person}"
        upd_abort += f" OR (NEW.person_id IS NOT OLD.person_id AND NEW.person_id NOT {in_person})"
        cols = [c for c in _cols(conn, t) if c not in ("id", "author_user_id", *AUTHORED[t])]
        changed = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in cols)
        outside = f"SELECT RAISE(IGNORE) WHERE OLD.person_id NOT {in_person} AND ({changed}); "
    return [
        f"CREATE TEMP TRIGGER _p_{t}_ins BEFORE INSERT ON main.{t} BEGIN "
        f"SELECT RAISE(ABORT, 'fuori perimetro: {t}') WHERE {ins}; END",
        f"CREATE TEMP TRIGGER _p_{t}_upd BEFORE UPDATE ON main.{t} BEGIN "
        f"SELECT RAISE(IGNORE) WHERE OLD.author_user_id IS NOT {uid}; {outside}"
        f"SELECT RAISE(ABORT, 'fuori perimetro: {t}') WHERE {upd_abort}; END",
        f"CREATE TEMP TRIGGER _p_{t}_del BEFORE DELETE ON main.{t} BEGIN "
        f"SELECT RAISE(IGNORE) WHERE OLD.author_user_id IS NOT {uid}"
        f"{f' OR OLD.person_id NOT {in_person}' if in_person else ''}; END",
    ]


def _authored_views(conn, uid: int, in_person: str | None) -> list[str]:
    """Viste di note e azioni (solo le proprie) e `perim_note_person`: id e nome delle persone
    fuori perimetro su cui l'utente ha note o azioni, perché la vista `person` non le mostra."""
    stmts = [f"CREATE TEMP VIEW {t} AS SELECT {', '.join(_cols(conn, t))} FROM main.{t} "
             f"WHERE author_user_id = {uid}" for t in AUTHORED]
    mine = " UNION ".join(f"SELECT person_id FROM main.{t} WHERE author_user_id = {uid}" for t in AUTHORED)
    where = f"id NOT {in_person} AND id IN ({mine})" if in_person else "0"
    stmts.append(f"CREATE TEMP VIEW perim_note_person AS SELECT id, full_name FROM main.person WHERE {where}")
    return stmts


def _guards_team(uid: int) -> list[str]:
    bad_parent = f"(NEW.parent_team_id IS NOT NULL AND NEW.parent_team_id NOT {IN_TEAM})"
    bad_lead = f"(NEW.lead_person_id IS NOT NULL AND NEW.lead_person_id NOT {IN_PERSON})"
    return [
        f"CREATE TEMP TRIGGER _p_team_ins BEFORE INSERT ON main.team BEGIN "
        f"SELECT RAISE(ABORT, 'fuori perimetro: team') "
        f"WHERE NEW.owner_user_id IS NOT {uid} OR {bad_parent} OR {bad_lead}; END",
        # padre e responsabile fuori dal perimetro si possono solo lasciare come sono
        f"CREATE TEMP TRIGGER _p_team_upd BEFORE UPDATE ON main.team BEGIN "
        f"SELECT RAISE(IGNORE) WHERE OLD.id NOT {IN_TEAM}; "
        f"SELECT RAISE(ABORT, 'fuori perimetro: team') WHERE NEW.owner_user_id IS NOT {uid} "
        f"OR (NEW.parent_team_id IS NOT OLD.parent_team_id AND {bad_parent}) "
        f"OR (NEW.lead_person_id IS NOT OLD.lead_person_id AND {bad_lead}); END",
        f"CREATE TEMP TRIGGER _p_team_del BEFORE DELETE ON main.team BEGIN "
        f"SELECT RAISE(IGNORE) WHERE OLD.id NOT {IN_TEAM}; END",
        # quello che il director crea entra subito nel suo perimetro
        "CREATE TEMP TRIGGER _p_team_ai AFTER INSERT ON main.team BEGIN "
        "INSERT OR IGNORE INTO perim_team VALUES (NEW.id); END",
        "CREATE TEMP TRIGGER _p_person_ai AFTER INSERT ON main.person BEGIN "
        "INSERT OR IGNORE INTO perim_person VALUES (NEW.id); END",
    ]


def refresh(conn, uid: int, role: str = "director") -> None:
    """Ricalcola il perimetro: i team del director, e le persone la cui ultima assegnazione
    valida (conclusa o no) sta in uno di quei team. HR vede tutto: niente da ricalcolare."""
    if role == "hr":
        return
    conn.execute("DELETE FROM temp.perim_team")
    conn.execute("DELETE FROM temp.perim_person")
    conn.execute("INSERT INTO temp.perim_team SELECT id FROM main.team WHERE owner_user_id = ?", (int(uid),))
    conn.execute(f"""INSERT INTO temp.perim_person
        SELECT p.id FROM main.person p
         WHERE (SELECT pa.team_id FROM main.person_assignment pa
                 WHERE pa.person_id = p.id AND pa.voided = 0
                 ORDER BY pa.start_date DESC, pa.id DESC LIMIT 1) {IN_TEAM}
            OR (p.owner_user_id = ? AND NOT EXISTS (
                    SELECT 1 FROM main.person_assignment pa WHERE pa.person_id = p.id AND pa.voided = 0))""",
                 (int(uid),))
    conn.commit()  # niente transazione implicita aperta: terrebbe una vecchia istantanea del file (WAL)


# ---- authorizer: niente letture dirette delle tabelle schermate ----

def _fk_columns(conn) -> set:
    """Le colonne che il motore legge per controllare le chiavi esterne (anche nelle cancellazioni
    a cascata): le chiavi dei padri e le colonne dei figli. Solo id e riferimenti, mai dati."""
    out = set()
    tables = [r[0] for r in conn.execute("SELECT name FROM main.sqlite_master WHERE type='table'")]
    for child in tables:
        for fk in conn.execute(f"PRAGMA main.foreign_key_list({child})"):
            out.add((fk[2], fk[4] or "id"))
            out.add((child, fk[3]))
    return out


def authorizer(h, conn):
    """Sulla connessione di un director una colonna di una tabella schermata si legge solo dalle
    nostre viste e guardie, o dalla tabella che il db sta scrivendo (UPDATE … WHERE id=?) e dalle
    colonne che il motore controlla per le sue chiavi esterne. Utenti e audit sono della
    connessione di sistema; ATTACH, VACUUM e PRAGMA sono negati. Su quella di HR le scritture
    passano solo per le colonne in `HR_WRITABLE`."""
    import sqlcipher3 as s

    shielded = {*OWNED, *CHILD, *TEAM, *PERSON, *AUTHORED}
    ours = shielded | {"perim_note_person"} | {
        r[0] for r in conn.execute("SELECT name FROM temp.sqlite_master WHERE type='trigger'")}
    fk = _fk_columns(conn)
    denied = {"app_user", "audit_event"}
    company = set(COMPANY)  # la legge il director, la scrive solo la gestione aziendale
    writable = HR_WRITABLE if h.role == "hr" else None  # None = tutto (dentro le guardie)
    OK, DENY = s.SQLITE_OK, s.SQLITE_DENY

    def check(action, a1, a2, dbname, source):
        if h.system:  # ricarica del perimetro: lettura di sistema
            return OK
        if action == s.SQLITE_READ and dbname == "main":
            if h.write_target and (a1, a2) in fk:  # controllo delle chiavi esterne durante una scrittura
                return OK
            if a1 in denied:
                return DENY
            if a1 in shielded and a2:
                return OK if source in ours or a1 == h.write_target else DENY
            return OK
        if action in (s.SQLITE_INSERT, s.SQLITE_UPDATE, s.SQLITE_DELETE) and dbname == "main":
            if a1 in denied or a1 in company:
                return DENY
            if writable is not None:
                cols = writable.get(a1, ())
                return OK if "*" in cols or (action == s.SQLITE_UPDATE and a2 in cols) else DENY
        if action in (s.SQLITE_ATTACH, s.SQLITE_DETACH, s.SQLITE_PRAGMA):
            return DENY
        return OK

    return check


def install(conn, uid: int, role: str = "director") -> None:
    """Perimetro, guardie e viste del director `uid` sulla sua connessione (prima le guardie, poi le viste)."""
    uid = int(uid)
    if role == "hr":
        return _install_hr(conn, uid)
    conn.execute("CREATE TEMP TABLE perim_team (team_id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TEMP TABLE perim_person (person_id INTEGER PRIMARY KEY)")
    refresh(conn, uid)
    stmts = _guards_team(uid)
    for t in PERSON:
        stmts += _guards_person(t)
    for t in AUTHORED:
        stmts += _guards_authored(conn, t, uid)
    for t, refs in OWNED.items():
        stmts += _guards_owned(t, uid, refs)
    for t, refs in CHILD.items():
        stmts += _guards_child(t, refs)
        if "person_id" in _cols(conn, t):
            stmts.append(f"CREATE TEMP TRIGGER _p_{t}_pins BEFORE INSERT ON main.{t} BEGIN "
                         f"SELECT RAISE(ABORT, 'fuori perimetro: {t}') WHERE NEW.person_id NOT {IN_PERSON}; END")
            # in un contenitore condiviso (premio di ruolo) le righe delle persone altrui non si toccano
            stmts.append(f"CREATE TEMP TRIGGER _p_{t}_pupd BEFORE UPDATE ON main.{t} BEGIN "
                         f"SELECT RAISE(IGNORE) WHERE OLD.person_id NOT {IN_PERSON}; END")
            stmts.append(f"CREATE TEMP TRIGGER _p_{t}_pdel BEFORE DELETE ON main.{t} BEGIN "
                         f"SELECT RAISE(IGNORE) WHERE OLD.person_id NOT {IN_PERSON}; END")
    stmts.append(f"CREATE TEMP VIEW team AS SELECT {', '.join(_cols(conn, 'team'))} FROM main.team WHERE id {IN_TEAM}")
    for t in PERSON:
        col = "id" if t == "person" else "person_id"
        stmts.append(f"CREATE TEMP VIEW {t} AS SELECT {', '.join(_cols(conn, t))} FROM main.{t} WHERE {col} {IN_PERSON}")
    for t, refs in OWNED.items():
        hidden = _hidden("x", refs)
        mine = f"x.owner_user_id = {uid}" + (f" OR {OWNED_SHARED[t]}" if t in OWNED_SHARED else "")
        stmts.append(f"CREATE TEMP VIEW {t} AS SELECT {', '.join('x.' + c for c in _cols(conn, t))} FROM main.{t} x "
                     f"WHERE ({mine}) AND NOT ({hidden})")
    for t, refs in CHILD.items():
        visible = " AND ".join(f"({col} IS NULL OR {col} IN (SELECT id FROM {parent}))" for col, parent in refs)
        if "person_id" in _cols(conn, t):
            visible += f" AND person_id {IN_PERSON}"
        stmts.append(f"CREATE TEMP VIEW {t} AS SELECT {', '.join(_cols(conn, t))} FROM main.{t} WHERE {visible}")
    stmts += _authored_views(conn, uid, IN_PERSON)
    for sql in stmts:
        conn.execute(sql)


def _install_hr(conn, uid: int) -> None:
    """Viste di HR: tutto senza filtro, tranne la configurazione propria e le note e azioni (le sue,
    con le guardie sull'autore). Il resto delle scritture lo decide l'authorizer (`HR_WRITABLE`)."""
    stmts = []
    for t in AUTHORED:
        stmts += _guards_authored(conn, t, uid, None)
    for t in [*TEAM, *PERSON, *OWNED, *CHILD]:
        where = f" WHERE owner_user_id = {uid}" if t in HR_OWN else ""
        stmts.append(f"CREATE TEMP VIEW {t} AS SELECT {', '.join(_cols(conn, t))} FROM main.{t}{where}")
    stmts += _authored_views(conn, uid, None)
    for sql in stmts:
        conn.execute(sql)


# ---- configurazione di default ----

_factory: dict | None = None


def factory_config() -> dict:
    """La configurazione di un'installazione nuova: migrazioni su un DB vuoto in memoria + modello 9-box.
    Sempre esatta, a prescindere da come è stata modificata quella esistente."""
    global _factory
    if _factory is None:
        import json

        from app.services.ninebox_defaults import DEFAULT_NINEBOX_CONFIG

        conn = db.sqlcipher.connect(":memory:")
        conn.create_function("teamer_owner", 0, lambda: None)
        db._migrate(conn)
        conn.execute("INSERT INTO evaluation_model (name, type, config) VALUES (?,?,?)",
                     ("9-Box Talent Matrix", "nine_box", json.dumps(DEFAULT_NINEBOX_CONFIG, ensure_ascii=False)))
        out = {}
        for t in CONFIG:
            cols = [c for c in _cols(conn, t) if c not in ("id", "owner_user_id")]
            out[t] = (cols, conn.execute(f"SELECT {', '.join(cols)} FROM {t}").fetchall())
        conn.close()
        _factory = out
    return _factory


def has_config(uid: int) -> bool:
    return db.sys.one("SELECT 1 FROM ninebox_weight WHERE owner_user_id=? LIMIT 1", (uid,)) is not None


def ensure_config(uid: int) -> bool:
    """Un director (o HR) senza configurazione riceve quella di default. Idempotente."""
    if has_config(uid):
        return False
    with db.sys.transaction() as c:
        for t, (cols, rows) in factory_config().items():
            c.executemany(f"INSERT INTO {t} ({', '.join(cols)}, owner_user_id) "
                          f"VALUES ({', '.join('?' * (len(cols) + 1))})",
                          [(*r, uid) for r in rows])
    return True


# ---- dati da assegnare ----

UNASSIGNED_GROUPS = [
    ("team", "team", "team"),
    ("review_cycle", "cicli di review", "cicli"),
    ("ral_budget", "budget aumenti", "budget aumenti"),
    ("hiring_budget", "budget assunzioni", "budget assunzioni"),
    ("bonus_pool", "montepremi", "montepremi"),
    ("reorg_scenario", "simulazioni", "simulazioni"),
    ("meeting_note", "note 1:1", "note"),
    ("action_item", "azioni", "azioni"),
]


def unassigned() -> dict:
    """Conteggi dei dati senza proprietario (mai nomi: l'admin non vede dati del personale)."""
    groups = [{"table": t, "label": label,
               "n": db.sys.one(f"SELECT COUNT(*) AS n FROM {t} WHERE {OWNER_COL[t]} IS NULL")["n"]}
              for t, label, _ in UNASSIGNED_GROUPS]
    config = sum(db.sys.one(f"SELECT COUNT(*) AS n FROM {t} WHERE owner_user_id IS NULL")["n"] for t in CONFIG)
    data = sum(g["n"] for g in groups)
    return {"groups": groups, "config": config, "data": data, "any": bool(data)}


def assign_unassigned(uid: int) -> dict:
    """Assegna a `uid` tutto ciò che non ha proprietario. La configurazione esistente prende il
    posto di quella del director dove coincide (stessa voce); i riferimenti ai suoi cataloghi
    vengono ripuntati sulla voce che arriva."""
    counts = {}
    with db.sys.transaction() as c:
        for t, key in NATURAL_KEYS.items():
            join = " AND ".join(f"mine.{k} = inc.{k}" for k in key)
            # voci doppie fra quelle senza proprietario (installazione nuova + dati vecchi): vince la prima
            dups = c.execute(f"SELECT mine.id AS mine, MIN(inc.id) AS inc FROM {t} mine JOIN {t} inc ON {join} "
                             f"WHERE mine.owner_user_id IS NULL AND inc.owner_user_id IS NULL AND inc.id < mine.id "
                             f"GROUP BY mine.id").fetchall()
            for dup, keep in dups:
                for ref_table, col in CATALOG_REFS.get(t, []):
                    c.execute(f"UPDATE {ref_table} SET {col}=? WHERE {col}=?", (keep, dup))
                c.execute(f"DELETE FROM {t} WHERE id=?", (dup,))
            pairs = c.execute(f"SELECT mine.id AS mine, MIN(inc.id) AS inc FROM {t} mine JOIN {t} inc ON {join} "
                              f"WHERE mine.owner_user_id = ? AND inc.owner_user_id IS NULL GROUP BY mine.id",
                              (uid,)).fetchall()
            for mine, inc in pairs:
                for ref_table, col in CATALOG_REFS.get(t, []):
                    c.execute(f"UPDATE {ref_table} SET {col}=? WHERE {col}=?", (inc, mine))
                c.execute(f"DELETE FROM {t} WHERE id=?", (mine,))
        for t, col in OWNER_COL.items():
            counts[t] = c.execute(f"UPDATE {t} SET {col}=? WHERE {col} IS NULL", (uid,)).rowcount
    bump()
    return counts


def disown_all() -> None:
    """Ripristino da un'altra istanza: i proprietari del file non esistono qui, tutto torna da assegnare."""
    with db.sys.transaction() as c:
        for t, col in OWNER_COL.items():
            c.execute(f"UPDATE {t} SET {col}=NULL")
    bump()


# ---- trasferimento di un team (admin) ----

class TransferError(Exception):
    """Trasferimento rifiutato: il messaggio è per l'admin."""


def team_tree() -> list[dict]:
    """Albero dei team con il titolare, per la console dell'admin: solo nomi, nessuna persona."""
    from app.services import org_tree

    teams = [dict(r) for r in db.sys.query(
        "SELECT t.id, t.name, t.parent_team_id, t.sort_order, t.archived_at, t.owner_user_id, u.username AS owner "
        "FROM team t LEFT JOIN app_user u ON u.id = t.owner_user_id")]
    out = []

    def walk(nodes):
        for n in nodes:
            out.append({**n["team"], "depth": n["depth"]})
            walk(n["children"])

    walk(org_tree.build_team_tree(teams, []))
    return out


HOLDING_TEAM = "Da collocare"


def ensure_holding_team(c, uid: int) -> int:
    """Il team tecnico «Da collocare» del director `uid` (uno per director, creato al volo, riaperto
    se archiviato): ci arrivano le persone spostate da HR, finché il director non le assegna."""
    row = c.execute("SELECT id, archived_at FROM team WHERE owner_user_id=? AND holding=1 ORDER BY id LIMIT 1",
                    (uid,)).fetchone()
    if row is None:
        return c.execute("INSERT INTO team (name, holding, sort_order, owner_user_id) VALUES (?, 1, 999, ?)",
                         (HOLDING_TEAM, uid)).lastrowid
    if row["archived_at"]:
        c.execute("UPDATE team SET archived_at=NULL WHERE id=?", (row["id"],))
    return row["id"]


def director_of(c, pid: int):
    """Il director titolare della persona: quello del team dell'ultima assegnazione valida, altrimenti
    chi l'ha creata (`person.owner_user_id`)."""
    row = c.execute(
        """SELECT COALESCE((SELECT t.owner_user_id FROM person_assignment pa JOIN team t ON t.id = pa.team_id
                             WHERE pa.person_id = p.id AND pa.voided = 0
                             ORDER BY pa.start_date DESC, pa.id DESC LIMIT 1), p.owner_user_id) AS uid
           FROM person p WHERE p.id = ?""", (pid,)).fetchone()
    return row["uid"] if row else None


def transfer_person(pid: int, to_uid: int, on_date: str) -> dict:
    """HR sposta una persona a un altro director (0.40): l'assegnazione corrente si chiude il giorno
    prima e ne nasce una nuova, storicizzata, nel team «Da collocare» del destinatario (stesso ruolo,
    senza riporto: lo calcola il director quando la colloca). Tutto lo storico segue la persona. A chi
    cede non resta nulla di lei, salvo le sue note e azioni (classe `authored`, in sola lettura):
    le righe nei suoi cicli passano a un ciclo del nuovo director con lo stesso nome e anno; quelle
    nei suoi budget e montepremi si staccano (le proposte pendenti si annullano); le sue simulazioni
    la dimenticano; se era responsabile di un suo team, il team resta senza responsabile. Nessuna
    quota o tetto si sposta. I team non si muovono mai."""
    n = {"righe nei cicli": 0, "righe staccate": 0, "annullate": 0}
    with db.sys.transaction() as c:
        p = c.execute("SELECT id, status, full_name FROM person WHERE id=?", (pid,)).fetchone()
        if p is None:
            raise TransferError("Persona inesistente.")
        if p["status"] != "attivo":
            raise TransferError("La persona è cessata: non si sposta.")
        src = director_of(c, pid)
        if src == to_uid:
            raise TransferError("La persona è già di quel director.")
        cur = c.execute(
            "SELECT * FROM person_assignment WHERE person_id=? AND voided=0 AND end_date IS NULL "
            "ORDER BY start_date DESC, id DESC LIMIT 1", (pid,)).fetchone()
        if cur and str(cur["start_date"]) >= on_date:
            raise TransferError("La data deve essere successiva all'inizio dell'assegnazione corrente.")
        from datetime import date, timedelta

        prev_end = (date.fromisoformat(on_date) - timedelta(days=1)).isoformat()
        c.execute("UPDATE person_assignment SET end_date=? WHERE person_id=? AND voided=0 AND end_date IS NULL",
                  (prev_end, pid))
        holding = ensure_holding_team(c, to_uid)
        c.execute("INSERT INTO person_assignment (person_id, team_id, role_type, start_date, listino_profile_id) "
                  "VALUES (?,?,?,?,?)", (pid, holding, cur["role_type"] if cur else "ic", on_date,
                                        cur["listino_profile_id"] if cur else None))   # il codice è aziendale (0.41)
        c.execute("UPDATE person SET owner_user_id=? WHERE id=?", (to_uid, pid))
        if src is None:
            bump()
            return n

        # cicli di review: le righe passano a un ciclo del nuovo director con lo stesso nome e anno
        cycles = c.execute(
            """SELECT DISTINCT rc.id, rc.name, rc.year, rc.status, rc.note FROM review_cycle rc
                 WHERE rc.owner_user_id = ? AND rc.id IN (
                     SELECT cycle_id FROM goal WHERE person_id = ?
                     UNION SELECT cycle_id FROM performance_review WHERE person_id = ?)""", (src, pid, pid)).fetchall()
        for cyc in cycles:
            twin = c.execute("SELECT id FROM review_cycle WHERE owner_user_id=? AND name=? AND year=?",
                             (to_uid, cyc["name"], cyc["year"])).fetchone()
            target = twin["id"] if twin else c.execute(
                "INSERT INTO review_cycle (name, year, status, note, owner_user_id) VALUES (?,?,?,?,?)",
                (cyc["name"], cyc["year"], cyc["status"], cyc["note"], to_uid)).lastrowid
            for t in ("goal", "performance_review"):
                n["righe nei cicli"] += c.execute(
                    f"UPDATE {t} SET cycle_id=? WHERE cycle_id=? AND person_id=?", (target, cyc["id"], pid)).rowcount

        # budget e montepremi di chi cede: le righe si staccano, i fatti restano alla persona
        budgets = f"SELECT id FROM ral_budget WHERE owner_user_id = {int(src)}"
        n["annullate"] += c.execute(
            f"UPDATE ral_proposal SET voided=1, void_reason='persona spostata' WHERE person_id=? "
            f"AND budget_id IN ({budgets}) AND voided=0 AND status IN ('bozza','proposta','approvata')", (pid,)).rowcount
        for t in ("ral_proposal", "ral_event"):
            n["righe staccate"] += c.execute(
                f"UPDATE {t} SET budget_id=NULL WHERE person_id=? AND budget_id IN ({budgets})", (pid,)).rowcount
        n["righe staccate"] += c.execute(
            f"DELETE FROM ral_budget_member WHERE person_id=? AND budget_id IN ({budgets})", (pid,)).rowcount
        n["righe staccate"] += c.execute(
            f"UPDATE bonus_allocation SET pool_id=NULL WHERE person_id=? "
            f"AND pool_id IN (SELECT id FROM bonus_pool WHERE owner_user_id = {int(src)})", (pid,)).rowcount
        # simulazioni e team di chi cede la dimenticano
        c.execute("DELETE FROM reorg_move WHERE owner_user_id=? AND person_id=?", (src, pid))
        c.execute("UPDATE reorg_team SET lead_person_id=NULL WHERE owner_user_id=? AND lead_person_id=?", (src, pid))
        c.execute("UPDATE team SET lead_person_id=NULL WHERE owner_user_id=? AND lead_person_id=?", (src, pid))
    bump()
    return n
