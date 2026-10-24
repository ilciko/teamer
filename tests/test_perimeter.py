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
    client.post("/settings/ninebox-weights", data={"p|ic|new": "0.5", "q|ic|new": "-0.5"})
    client.post("/settings/general", data={"ral_stale_amber_years": "3", "ral_stale_red_years": "5"})
    with as_user("coo"):
        assert db.get_meta("ral_stale_amber_years") == "3"
        assert db.one("SELECT perf_adj FROM ninebox_weight WHERE role_type='ic' AND seniority='new'")["perf_adj"] == 0.5
    with as_user("dir2"):
        assert db.get_meta("ral_stale_amber_years", "2") == "2"               # default, non la copia di coo
        assert db.one("SELECT perf_adj FROM ninebox_weight WHERE role_type='ic' AND seniority='new'")["perf_adj"] != 0.5
        assert len(db.query("SELECT * FROM weight_mapping")) == 9
        assert db.one("SELECT 1 FROM evaluation_model WHERE type='nine_box'")


def test_liste_valori_e_benefit_sono_aziendali(client, client2, admin_client, hr_client):
    """Una lista sola per tutti: la gestisce HR (0.41), i director la leggono e non la scrivono."""
    hr_client.post("/azienda/liste", data={"category": "livello", "code": "Q9", "label": "Quadro super"})
    hr_client.post("/azienda/benefit", data={"name": "Buoni pasto", "value_kind": "amount", "is_cost": "1"})
    hr_client.post("/azienda/default", data={"default_ccnl": "Commercio"})
    for u in ("coo", "dir2"):
        with as_user(u):
            assert db.one("SELECT label FROM lookup WHERE code='Q9'")["label"] == "Quadro super"
            assert db.one("SELECT 1 FROM benefit_type WHERE name='Buoni pasto'")
            assert db.get_meta("default_ccnl") == "Commercio"
    with as_user("dir2"):
        with pytest.raises(db.sqlcipher.DatabaseError):
            db.execute("UPDATE lookup SET label='Forzata' WHERE code='Q9'")
        with pytest.raises(db.sqlcipher.DatabaseError):
            db.execute("INSERT INTO benefit_type (name) VALUES ('Mio')")
    assert client.get("/azienda", follow_redirects=False).status_code == 403
    assert client.post("/azienda/liste", data={"category": "x", "code": "y", "label": "z"}).status_code == 403
    assert admin_client.get("/azienda?tab=liste").status_code == 403           # Azienda è di HR (0.41)
    assert hr_client.get("/azienda?tab=liste").status_code == 200


def test_configurazione_isolata_in_scrittura(client, client2):
    client2.post("/settings/general", data={"ral_stale_amber_years": "3", "ral_stale_red_years": "6"})
    with as_user("coo"):
        assert db.get_meta("ral_stale_amber_years", "2") == "2"
    with as_user("dir2"):
        assert db.get_meta("ral_stale_amber_years", "2") == "3"
    # dir2 cambia un peso di coo per id: la guardia salta la riga altrui
    coo_w = db.sys.one("SELECT id, weight FROM weight_mapping WHERE owner_user_id=? AND box_number=9",
                       (users.by_username("coo")["id"],))
    with as_user("dir2"):
        db.execute("UPDATE weight_mapping SET weight=99 WHERE id=?", (coo_w["id"],))
    assert db.sys.one("SELECT weight FROM weight_mapping WHERE id=?", (coo_w["id"],))["weight"] == coo_w["weight"]


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
    db.sys.execute("UPDATE user_meta SET value='7' WHERE key='ral_stale_amber_years' AND owner_user_id IS NULL")
    if not db.sys.one("SELECT 1 FROM user_meta WHERE key='ral_stale_amber_years' AND owner_user_id IS NULL"):
        db.sys.execute("INSERT INTO user_meta (key, value) VALUES ('ral_stale_amber_years', '7')")


def test_dati_senza_proprietario_non_li_vede_nessuno(client, client2):
    _dati_senza_proprietario()
    for u in ("coo", "dir2"):
        with as_user(u):
            assert not db.query("SELECT 1 FROM review_cycle WHERE name='Ciclo Esistente'")
    u = perimeter.unassigned()
    assert u["any"] and {g["table"]: g["n"] for g in u["groups"]}["review_cycle"] == 1


def test_assegnazione_fonde_la_configurazione(client, admin_client):
    coo = users.by_username("coo")["id"]
    _dati_senza_proprietario()
    r = admin_client.post("/admin/assign", data={"user_id": coo, "confirm": "ASSEGNA"})
    assert r.status_code == 200 and "Fatto" in r.text
    with as_user("coo"):
        assert db.one("SELECT 1 FROM review_cycle WHERE name='Ciclo Esistente'")
        assert db.get_meta("ral_stale_amber_years") == "7"                          # l'esistente vince
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
    # 0030: il CCNL predefinito torna aziendale (in app_meta), passando da user_meta
    assert conn.execute("SELECT value FROM app_meta WHERE key='default_ccnl'").fetchone()[0] == "Commercio"
    assert conn.execute("SELECT 1 FROM user_meta WHERE key='default_ccnl'").fetchone() is None
    assert conn.execute("SELECT parent_team_id FROM team WHERE id=2").fetchone()[0] == 1
    conn.close()


def test_migrazione_0030_fonde_liste_e_benefit_dei_director(tmp_path):
    """Da 0.32–0.34 (configurazione per director) alla 0.35: liste, benefit e CCNL tornano aziendali."""
    conn = db._connect(tmp_path / "v034.db", db._raw(db.generate_key()))
    for f in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        if int(f.name[:4]) <= 29:
            conn.executescript(f.read_text())
    conn.execute("INSERT OR REPLACE INTO app_meta VALUES ('schema_version', '29')")
    conn.executescript("""
        INSERT INTO app_user (id, username, role, password_hash) VALUES (1, 'a', 'director', 'x'), (2, 'b', 'director', 'x');
        UPDATE lookup SET owner_user_id = 1;                                           -- la copia «originale» di a
        INSERT INTO lookup (category, code, label, owner_user_id)
            SELECT category, code, label || ' (b)', 2 FROM lookup WHERE owner_user_id = 1;  -- la copia di b
        INSERT INTO benefit_type (id, name, owner_user_id) VALUES (10, 'Auto', 1), (20, 'Auto', 2), (30, 'Solo b', 2);
        INSERT INTO person (id, full_name) VALUES (1, 'P');
        INSERT INTO benefit_assignment (person_id, benefit_type_id, value, effective_date) VALUES (1, 20, '1', '2026-01-01');
        UPDATE user_meta SET owner_user_id = 1, value = 'CCNL di a' WHERE key = 'default_ccnl';
        INSERT INTO user_meta (key, value, owner_user_id) VALUES ('default_ccnl', 'CCNL di b', 2);
    """)
    conn.commit()
    n_codes = conn.execute("SELECT COUNT(*) FROM lookup WHERE owner_user_id = 1").fetchone()[0]
    db._migrate(conn)
    assert conn.execute("SELECT COUNT(*) FROM lookup").fetchone()[0] == n_codes + 1      # una voce per codice (+ 'ccnl' della 0033)
    assert conn.execute("SELECT COUNT(*) FROM lookup WHERE label LIKE '%(b)'").fetchone()[0] == 0
    assert [r[0] for r in conn.execute("SELECT name FROM benefit_type ORDER BY id")] == ["Auto", "Solo b"]
    assert conn.execute("SELECT benefit_type_id FROM benefit_assignment").fetchone()[0] == 10   # ripuntato
    assert conn.execute("SELECT value FROM app_meta WHERE key='default_ccnl'").fetchone()[0] == "CCNL di a"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert "owner_user_id" not in {r[1] for r in conn.execute("PRAGMA table_info(lookup)")}
    conn.close()
