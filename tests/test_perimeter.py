"""Perimetri, parte 0.32: proprietari, configurazione per director, dati da assegnare."""
import pytest

from app import db, perimeter, session, users
from tests.conftest import PASSWORD, as_user, login


def _tables():
    return {r["name"] for r in db.sys.query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


# ---- classificazione ----

def test_ogni_tabella_ha_esattamente_una_classe(app_db):
    seen = [t for ts in perimeter.CLASSES.values() for t in ts]
    assert len(seen) == len(set(seen)), "tabella in più classi"
    assert set(seen) == _tables(), "tabella nuova da classificare in app/perimeter.py"


def test_tabelle_del_director_hanno_il_proprietario_di_default(app_db):
    for t in [*perimeter.OWNED, *perimeter.TEAM]:
        col = {r["name"]: r for r in db.sys.query(f"PRAGMA table_info({t})")}.get("owner_user_id")
        assert col is not None, t
        assert col["dflt_value"] == "teamer_owner()", t


def test_le_unique_della_configurazione_includono_il_proprietario(app_db):
    for t in perimeter.CONFIG:
        for idx in db.sys.query(f"PRAGMA index_list({t})"):
            if idx["unique"] and idx["origin"] != "pk":
                cols = {r["name"] for r in db.sys.query(f"PRAGMA index_info({idx['name']})")}
                assert "owner_user_id" in cols, (t, cols)


def test_ogni_scrittura_va_su_una_tabella_classificata():
    from tests.test_sql_scritture import WRITES

    classified = {t for ts in perimeter.CLASSES.values() for t in ts}
    assert {db.write_target(sql) for _, sql in WRITES} <= classified


def test_istanza_ha_un_identificativo(app_db):
    assert len(db.get_meta("instance_id")) == 16


# ---- configurazione per director ----

def test_director_nuovo_parte_dalla_configurazione_di_default(client, client2):
    client.post("/settings/lookup/1/update", data={"label": "Rinominata da coo", "sort_order": 0})
    client.post("/settings/general", data={"default_ccnl": "Commercio", "ral_stale_amber_years": "3",
                                           "ral_stale_red_years": "5"})
    with as_user("coo"):
        assert db.get_meta("default_ccnl") == "Commercio"
    with as_user("dir2"):
        assert db.get_meta("default_ccnl") == "Metalmeccanici Confapi"     # default, non la copia di coo
        assert not db.query("SELECT 1 FROM lookup WHERE label='Rinominata da coo'")
        assert len(db.query("SELECT * FROM ninebox_weight")) == 12
        assert len(db.query("SELECT * FROM weight_mapping")) == 9
        assert db.one("SELECT 1 FROM evaluation_model WHERE type='nine_box'")
    assert "Rinominata da coo" not in client2.get("/settings?tab=lookup").text


def test_configurazione_isolata_in_scrittura(client, client2):
    client2.post("/settings/lookup", data={"category": "livello", "code": "Q9", "label": "Quadro dir2"})
    with as_user("coo"):
        assert not db.query("SELECT 1 FROM lookup WHERE code='Q9'")
        assert db.one("SELECT perf_adj FROM ninebox_weight WHERE role_type='ic' AND seniority='new'")
    with as_user("dir2"):
        assert db.one("SELECT owner_user_id FROM lookup WHERE code='Q9'")["owner_user_id"] == \
            users.by_username("dir2")["id"]
    # dir2 rinomina un id di coo: la guardia salta la riga altrui, niente cambia
    coo_lookup = db.sys.one("SELECT id, label FROM lookup WHERE owner_user_id=? LIMIT 1",
                            (users.by_username("coo")["id"],))
    client2.post(f"/settings/lookup/{coo_lookup['id']}/update", data={"label": "Forzata", "sort_order": 0})
    assert db.sys.one("SELECT label FROM lookup WHERE id=?", (coo_lookup["id"],))["label"] == coo_lookup["label"]


# ---- contenitori ----

def test_contenitori_del_director_che_li_crea(client, client2):
    client.post("/cycles", data={"name": "Review coo", "year": 2026})
    client.post("/comp/hiring", data={"period": "Assunzioni coo", "year": 2026, "total_cap": "100000"})
    cid = db.sys.one("SELECT id FROM review_cycle WHERE name='Review coo'")["id"]
    assert "Review coo" in client.get("/cycles").text
    assert "Review coo" not in client2.get("/cycles").text
    assert "Assunzioni coo" not in client2.get("/comp/hiring").text
    r = client2.get(f"/cycles/{cid}", follow_redirects=False)
    assert r.status_code in (302, 404) or "Review coo" not in r.text
    with as_user("dir2"):
        assert db.one("SELECT 1 FROM review_cycle WHERE id=?", (cid,)) is None
        # scrivere nel contenitore altrui: la guardia del motore lo impedisce
        pid = db.execute("INSERT INTO person (full_name) VALUES ('Di dir2')")
        with pytest.raises(Exception, match="fuori perimetro"):
            db.execute("INSERT INTO goal (person_id, cycle_id, category, description, weight_pct) "
                       "VALUES (?,?,?,?,100)", (pid, cid, "professionale", "x"))


# ---- dati da assegnare ----

def _dati_senza_proprietario():
    """Come dopo la 0028: righe create dalla connessione di sistema (proprietario NULL)."""
    db.sys.execute("INSERT INTO team (name) VALUES ('Team Esistente')")
    db.sys.execute("INSERT INTO review_cycle (name, year) VALUES ('Ciclo Esistente', 2025)")
    db.sys.execute("INSERT INTO lookup (category, code, label) VALUES ('livello', 'Z1', 'Livello esistente')")
    bt = db.sys.execute("INSERT INTO benefit_type (name) VALUES ('Auto aziendale')")
    db.sys.execute("UPDATE user_meta SET value='CCNL esistente' WHERE key='default_ccnl' AND owner_user_id IS NULL")
    return bt


def test_dati_senza_proprietario_non_li_vede_nessuno(client, client2):
    _dati_senza_proprietario()
    for u in ("coo", "dir2"):
        with as_user(u):
            assert not db.query("SELECT 1 FROM review_cycle WHERE name='Ciclo Esistente'")
    u = perimeter.unassigned()
    assert u["any"] and {g["table"]: g["n"] for g in u["groups"]}["review_cycle"] == 1


def test_assegnazione_fonde_la_configurazione(client, admin_client):
    coo = users.by_username("coo")["id"]
    # coo aveva già un suo catalogo benefit usato da una persona
    with as_user("coo"):
        mio = db.execute("INSERT INTO benefit_type (name) VALUES ('Auto aziendale')")
        pid = db.execute("INSERT INTO person (full_name) VALUES ('Con Auto')")
        db.execute("INSERT INTO benefit_assignment (person_id, benefit_type_id, value, effective_date) "
                   "VALUES (?,?,'1','2026-01-01')", (pid, mio))
    incoming_bt = _dati_senza_proprietario()
    r = admin_client.post("/admin/assign", data={"user_id": coo, "confirm": "ASSEGNA"})
    assert r.status_code == 200 and "Fatto" in r.text
    with as_user("coo"):
        assert db.one("SELECT 1 FROM review_cycle WHERE name='Ciclo Esistente'")
        assert db.get_meta("default_ccnl") == "CCNL esistente"                    # l'esistente vince
        assert db.one("SELECT label FROM lookup WHERE category='livello' AND code='Z1'")["label"] == "Livello esistente"
        assert len(db.query("SELECT 1 FROM lookup WHERE category='livello'")) == \
            len({r["code"] for r in db.query("SELECT code FROM lookup WHERE category='livello'")})
        assert len(db.query("SELECT * FROM benefit_type WHERE name='Auto aziendale'")) == 1
        assert db.one("SELECT benefit_type_id FROM benefit_assignment WHERE person_id=?",
                      (pid,))["benefit_type_id"] == incoming_bt                    # riferimento ripuntato
    assert not perimeter.unassigned()["any"]
    assert db.sys.one("SELECT 1 FROM audit_event WHERE event='assign_unassigned'")


def test_assegnazione_solo_a_un_director(admin_client):
    it = users.by_username("it")["id"]
    r = admin_client.post("/admin/assign", data={"user_id": it, "confirm": "ASSEGNA"})
    assert "director attivo" in r.text


# ---- ripristino ----

def test_ripristino_da_un_altra_istanza_torna_da_assegnare(client, tmp_path):
    client.post("/cycles", data={"name": "Ciclo Prima", "year": 2026})
    bk = tmp_path / "bk.db"
    db.backup_to(bk)
    db.restore(bk)                                                   # stessa istanza: restano di coo
    with as_user("coo"):
        assert db.one("SELECT 1 FROM review_cycle WHERE name='Ciclo Prima'")
    db.sys.execute("UPDATE app_meta SET value='altraistanza0000' WHERE key='instance_id'")
    bk = tmp_path / "altra.db"
    db.backup_to(bk)
    db.sys.execute("UPDATE app_meta SET value='questaistanza000' WHERE key='instance_id'")
    stats = db.restore(bk)
    assert not stats["same_instance"]
    with as_user("coo"):
        assert not db.query("SELECT 1 FROM review_cycle WHERE name='Ciclo Prima'")
    assert perimeter.unassigned()["any"] and db.get_meta("instance_id") == "questaistanza000"


def test_cli_assegna(app_db, capsys):
    from app import admin_cli

    db.sys.execute("INSERT INTO team (name) VALUES ('Da shell')")
    db.close_db()
    assert admin_cli.main(["assign-unassigned", "coo"]) == 0
    assert "team 1" in capsys.readouterr().out
    assert admin_cli.main(["assign-unassigned", "it"]) == 1
    db.startup()
    assert db.sys.one("SELECT owner_user_id FROM team WHERE name='Da shell'")["owner_user_id"] == \
        users.by_username("coo")["id"]


def test_migrazione_0028_su_un_db_popolato(tmp_path):
    """Un DB 0.31 con dati in ogni tabella ricostruita: stessi conteggi, FK integre, tutto da assegnare."""
    conn = db._connect(tmp_path / "v031.db", db._raw(db.generate_key()))
    conn.execute("PRAGMA foreign_keys=ON")
    for f in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        if int(f.name[:4]) <= 27:
            conn.executescript(f.read_text())
    conn.execute("INSERT OR REPLACE INTO app_meta VALUES ('schema_version', '27')")
    conn.executescript("""
        INSERT INTO team (id, name) VALUES (1, 'Radice'); INSERT INTO team (id, name, parent_team_id) VALUES (2, 'Figlio', 1);
        INSERT INTO person (id, full_name) VALUES (1, 'Anna');
        INSERT INTO person_assignment (person_id, team_id, role_type, start_date) VALUES (1, 2, 'ic', '2025-01-01');
        INSERT INTO review_cycle (id, name, year) VALUES (1, 'Review 2025', 2025);
        INSERT INTO goal (person_id, cycle_id, category, description, weight_pct) VALUES (1, 1, 'professionale', 'x', 100);
        INSERT INTO ral_budget (id, period, cycle_id, total_cap) VALUES (1, 'Aumenti', 1, 1000);
        INSERT INTO bonus_pool (id, period, cycle_id, total_cap) VALUES (1, 'Premi', 1, 500);
        INSERT INTO bonus_allocation (pool_id, person_id, weight) VALUES (1, 1, 1);
        INSERT INTO hiring_budget (id, period, year, total_cap) VALUES (1, 'Assunzioni', 2025, 30000);
        INSERT INTO hiring_position (id, budget_id, title, team_id) VALUES (1, 1, 'Dev', 2);
        INSERT INTO reorg_scenario (id, name) VALUES (1, 'Sim');
        INSERT INTO reorg_team (scenario_id, team_id, name) VALUES (1, 2, 'Figlio rinominato');
        INSERT INTO reorg_position_move (scenario_id, position_id, team_ref, role_type) VALUES (1, 1, 1, 'ic');
        INSERT INTO benefit_type (id, name) VALUES (1, 'Auto');
        INSERT INTO benefit_assignment (person_id, benefit_type_id, value, effective_date) VALUES (1, 1, '1', '2025-01-01');
        UPDATE app_meta SET value='Commercio' WHERE key='default_ccnl';
    """)
    conn.commit()
    tables = [*perimeter.OWNED, *perimeter.TEAM, "bonus_allocation", "goal", "benefit_assignment"]
    tables.remove("user_meta")
    before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    db._migrate(conn)
    assert db._schema_version_of(conn) >= 28
    assert {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables} == before
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    for t in [*perimeter.OWNED, *perimeter.TEAM]:
        assert conn.execute(f"SELECT COUNT(*) FROM {t} WHERE owner_user_id IS NOT NULL").fetchone()[0] == 0, t
    assert conn.execute("SELECT value FROM user_meta WHERE key='default_ccnl'").fetchone()[0] == "Commercio"
    assert conn.execute("SELECT 1 FROM app_meta WHERE key='default_ccnl'").fetchone() is None
    assert conn.execute("SELECT parent_team_id FROM team WHERE id=2").fetchone()[0] == 1
    conn.close()
