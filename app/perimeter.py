"""Perimetri per director: chi vede cosa (docs/perimetri.md).

Ogni tabella sta in esattamente una classe (`CLASSES`, verificato da tests/test_perimeter.py):

- `owned`: righe del director che le crea (`owner_user_id`, default `teamer_owner()`):
  configurazione, contenitori (cicli, budget, montepremi, simulazioni) e loro figli
  senza persona. NULL = «da assegnare»: non la vede nessuno finché l'admin non la assegna.
- `child`: righe di persona dentro un contenitore (obiettivi, review, proposte, righe di
  budget e premi): visibili se il contenitore lo è (o se staccate, contenitore NULL).
- `team`: ha il proprietario, ma il filtro per team arriva con i perimetri (0.33).
- `person`: dati di fatto della persona, filtrati per perimetro dalla 0.33.
- `instance`: utenti, audit, schema — solo connessione di sistema.

Sulla connessione di una sessione `install()` crea, in quest'ordine: le guardie (trigger
temporanei BEFORE sulle tabelle reali), poi le viste temporanee omonime con il filtro.
Le guardie vanno prima: dopo, il nome risolverebbe sulla vista.
"""
from app import db

# tabelle "del director": (colonna FK, tabella padre) che deve essere visibile
OWNED = {
    # configurazione
    "lookup": [], "ninebox_weight": [], "weight_mapping": [], "evaluation_model": [],
    "bonus_factor": [], "benefit_type": [], "listino_profile": [], "user_meta": [],
    # contenitori
    "review_cycle": [],
    "ral_budget": [("cycle_id", "review_cycle")],
    "bonus_pool": [("cycle_id", "review_cycle")],
    "hiring_budget": [],
    "hiring_transfer": [("from_budget_id", "hiring_budget"), ("to_budget_id", "hiring_budget")],
    "hiring_position": [("budget_id", "hiring_budget"), ("transfer_id", "hiring_transfer")],
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
}
TEAM = ["team"]
PERSON = ["person", "person_assignment", "employment", "ral_event", "benefit_assignment", "incentive",
          "ninebox_assessment", "attachment", "listino_person_param", "meeting_note", "action_item"]
INSTANCE = ["app_meta", "app_user", "audit_event"]

CLASSES = {"owned": list(OWNED), "child": list(CHILD), "team": TEAM, "person": PERSON, "instance": INSTANCE}

# configurazione: si copia dai default di fabbrica a ogni director nuovo
CONFIG = ["lookup", "ninebox_weight", "weight_mapping", "evaluation_model", "bonus_factor",
          "benefit_type", "listino_profile", "user_meta"]
# chiave naturale delle voci di configurazione (per fondere quella esistente in quella del director)
NATURAL_KEYS = {"lookup": ("category", "code"), "ninebox_weight": ("role_type", "seniority"),
                "weight_mapping": ("box_number",), "bonus_factor": ("kind", "code"), "user_meta": ("key",),
                "listino_profile": ("code",), "benefit_type": ("name",), "evaluation_model": ("type", "name")}
# chi punta alle voci dei cataloghi per id
CATALOG_REFS = {"benefit_type": [("benefit_assignment", "benefit_type_id")],
                "listino_profile": [("person_assignment", "listino_profile_id")]}
# configurazione che stava in app_meta: dalla 0028 è per director (tabella user_meta)
SCOPED_META = {"default_ccnl", "ral_stale_amber_years", "ral_stale_red_years"}


def scoped_meta(key: str) -> bool:
    return key in SCOPED_META or key.startswith("listino_")


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


def install(conn, uid: int) -> None:
    """Viste e guardie del director `uid` sulla sua connessione (prima le guardie, poi le viste)."""
    uid = int(uid)
    stmts = []
    for t, refs in OWNED.items():
        stmts += _guards_owned(t, uid, refs)
    for t, refs in CHILD.items():
        stmts += _guards_child(t, refs)
    for t in OWNED:
        stmts.append(f"CREATE TEMP VIEW {t} AS SELECT {', '.join(_cols(conn, t))} FROM main.{t} "
                     f"WHERE owner_user_id = {uid}")
    for t, refs in CHILD.items():
        visible = " AND ".join(f"({col} IS NULL OR {col} IN (SELECT id FROM {parent}))" for col, parent in refs)
        stmts.append(f"CREATE TEMP VIEW {t} AS SELECT {', '.join(_cols(conn, t))} FROM main.{t} WHERE {visible}")
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
    return db.sys.one("SELECT 1 FROM lookup WHERE owner_user_id=? LIMIT 1", (uid,)) is not None


def ensure_config(uid: int) -> bool:
    """Un director senza configurazione riceve quella di default. Idempotente."""
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
]


def unassigned() -> dict:
    """Conteggi dei dati senza proprietario (mai nomi: l'admin non vede dati del personale)."""
    groups = [{"table": t, "label": label,
               "n": db.sys.one(f"SELECT COUNT(*) AS n FROM {t} WHERE owner_user_id IS NULL")["n"]}
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
        for t in [*OWNED, *TEAM]:
            counts[t] = c.execute(f"UPDATE {t} SET owner_user_id=? WHERE owner_user_id IS NULL", (uid,)).rowcount
    return counts


def disown_all() -> None:
    """Ripristino da un'altra istanza: i proprietari del file non esistono qui, tutto torna da assegnare."""
    with db.sys.transaction() as c:
        for t in [*OWNED, *TEAM]:
            c.execute(f"UPDATE {t} SET owner_user_id=NULL")
