"""Perimetri, parte 0.33: ogni director vede solo i suoi team e le loro persone; spostamento di una
persona a un altro director (0.40, fatto da HR: `perimeter.transfer_person`)."""
import pytest

from app import db, perimeter, users
from tests.conftest import PASSWORD, as_user, login

PERSON_TABLES = [*perimeter.PERSON, *[t for t in perimeter.CHILD if t not in ("goal_review", "wellbeing_entry")]]


def _team(client, name, parent=None, lead=None):
    client.post("/org/team", data={"name": name, "parent_team_id": parent or "", "lead_person_id": lead or ""})
    return db.one("SELECT id FROM team WHERE name=?", (name,))["id"]


def _person(client, name, team, role="ic"):
    pid = db.execute("INSERT INTO person (full_name, hire_date) VALUES (?, '2024-01-01')", (name,))
    client.post(f"/people/{pid}/assignment", data={"team_id": team, "role_type": role, "start_date": "2024-01-01"})
    return pid


@pytest.fixture()
def org(client, client2):
    """coo: Direzione (Rita, director) → Logistica (Lea, mgr; Luca) → Magazzino (Mario). E Vendite (Vera).

    Su Luca un po' di tutto: RAL, nota, obiettivo e review in un ciclo, 9-box, benefit, codice di
    listino, proposta pendente in un budget, premio in un montepremi, posizione aperta, simulazione."""
    d = _team(client, "Direzione")
    log = _team(client, "Logistica", parent=d)
    mag = _team(client, "Magazzino", parent=log)
    ven = _team(client, "Vendite", parent=d)
    ids = {"d": d, "log": log, "mag": mag, "ven": ven,
           "rita": _person(client, "Rita Direzione", d, "sr"), "lea": _person(client, "Lea Logistica", log, "mgr"),
           "luca": _person(client, "Luca Logistica", log), "mario": _person(client, "Mario Magazzino", mag),
           "vera": _person(client, "Vera Vendite", ven)}
    luca = ids["luca"]
    db.execute("INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type) "
               "VALUES (?, '2024-01-01', 31234, 0, 'censimento')", (luca,))
    db.execute("INSERT INTO meeting_note (person_id, note_date, title, body) VALUES (?, '2026-01-10', 'Colloquio Luca', 'magazzino')", (luca,))
    ids["cycle"] = db.execute("INSERT INTO review_cycle (name, year) VALUES ('Review 2026', 2026)")
    db.execute("INSERT INTO goal (person_id, cycle_id, category, description, weight_pct) "
               "VALUES (?,?, 'professionale', 'Obiettivo di Luca', 100)", (luca, ids["cycle"]))
    db.execute("INSERT INTO performance_review (person_id, cycle_id) VALUES (?,?)", (luca, ids["cycle"]))
    db.execute("INSERT INTO ninebox_assessment (person_id, eval_date, role_type, seniority, raw_perf, raw_pot, "
               "adj_perf, adj_pot, perf_level, pot_level, box_number, weights_snapshot, answers) "
               "VALUES (?, '2026-01-01', 'ic', 'mid', 2, 2, 2, 2, 'med', 'med', 5, '{}', '{}')", (luca,))
    bt = db.sys.execute("INSERT INTO benefit_type (name) VALUES ('Auto aziendale')")   # catalogo aziendale
    db.execute("INSERT INTO benefit_assignment (person_id, benefit_type_id, value, effective_date) "
               "VALUES (?,?,'1','2025-01-01')", (luca, bt))
    lp = db.sys.execute("INSERT INTO listino_profile (code, description, day_rate) VALUES ('GE040', 'Consultant', 450)")
    db.execute("UPDATE person_assignment SET listino_profile_id=? WHERE person_id=?", (lp, luca))
    ids["budget"] = db.execute("INSERT INTO ral_budget (period, total_cap) VALUES ('Aumenti 2026', 10000)")
    db.execute("INSERT INTO ral_proposal (person_id, budget_id, amount, effective_date, status) "
               "VALUES (?,?, 1500, '2026-07-01', 'proposta')", (luca, ids["budget"]))
    ids["pool"] = db.execute("INSERT INTO bonus_pool (period, total_cap) VALUES ('Premi 2026', 5000)")
    db.execute("INSERT INTO bonus_allocation (pool_id, person_id, weight, final_amount) VALUES (?,?,1,800)",
               (ids["pool"], luca))
    hb = db.execute("INSERT INTO hiring_budget (period, year, total_cap) VALUES ('Assunzioni 2026', 2026, 50000)")
    ids["pos"] = db.execute("INSERT INTO hiring_position (budget_id, title, team_id) VALUES (?, 'Mulettista', ?)",
                            (hb, log))
    sc = db.execute("INSERT INTO reorg_scenario (name) VALUES ('Sim coo')")
    db.execute("INSERT INTO reorg_move (scenario_id, person_id, team_ref, role_type) VALUES (?,?,?, 'ic')",
               (sc, luca, ven))
    return ids


def _visible(username, pids):
    """Righe di persona visibili all'utente per quelle persone, tabella per tabella."""
    with as_user(username):
        q = ",".join(str(p) for p in pids)
        return {t: db.one(f"SELECT COUNT(*) AS n FROM {t} WHERE {'id' if t == 'person' else 'person_id'} IN ({q})")["n"]
                for t in PERSON_TABLES}


def _transfer(hr_client, pid, to="dir2", on_date="2026-06-01"):
    r = hr_client.post(f"/people/{pid}/director", data={"director_id": users.by_username(to)["id"], "on_date": on_date},
                       follow_redirects=False)
    assert r.status_code == 302 and "moved=" in r.headers["location"], r.headers.get("location")


# ---- un director vede solo i suoi ----

def test_altro_director_non_vede_niente(org, client2):
    for url in ("/people", "/org", "/org/chart", "/notes?q=magazzino", "/cycles", "/comp/salary", "/comp/hiring"):
        html = client2.get(url).text
        assert "Luca Logistica" not in html and "Logistica" not in html and "Mulettista" not in html, url
    assert all(n == 0 for n in _visible("dir2", [org["luca"], org["rita"]]).values())
    r = client2.get(f"/people/{org['luca']}", follow_redirects=False)
    assert r.status_code in (302, 404) or "Luca Logistica" not in r.text


def test_forzare_le_scritture_non_cambia_niente(org, client2):
    # assegnare una propria persona a un team altrui
    with as_user("dir2"):
        mia = db.execute("INSERT INTO person (full_name) VALUES ('Persona dir2')")
    r = client2.post(f"/people/{mia}/assignment", data={"team_id": org["log"], "role_type": "ic",
                                                        "start_date": "2026-01-01"})
    assert r.status_code == 403
    assert not db.sys.query("SELECT 1 FROM person_assignment WHERE person_id=?", (mia,))
    # correggere o cancellare dati altrui per id
    client2.post(f"/people/{org['luca']}/update", data={"full_name": "Hackerato"})
    client2.post(f"/org/team/{org['log']}", data={"name": "Rinominato"})
    assert db.sys.one("SELECT full_name FROM person WHERE id=?", (org["luca"],))["full_name"] == "Luca Logistica"
    assert db.sys.one("SELECT name FROM team WHERE id=?", (org["log"],))["name"] == "Logistica"
    # un team proprio sotto un team altrui
    r = client2.post("/org/team", data={"name": "Intruso", "parent_team_id": org["log"], "lead_person_id": ""})
    assert r.status_code == 403 and not db.sys.one("SELECT 1 FROM team WHERE name='Intruso'")


def test_persona_senza_team_resta_di_chi_la_crea(client, client2):
    client2.post("/people", data={"full_name": "Senza Team Ancora"})
    assert "Senza Team Ancora" in client2.get("/people").text
    assert "Senza Team Ancora" not in client.get("/people").text
    perimeter.bump()                                                 # ricarica: resta sua
    assert "Senza Team Ancora" in client2.get("/people").text


# ---- trasferimento ----

def test_spostamento_passa_la_persona_e_lo_storico(org, client, client2, hr_client):
    _transfer(hr_client, org["luca"])
    # a chi cede non resta niente di Luca, in nessuna tabella; i team restano suoi
    assert all(n == 0 for n in _visible("coo", [org["luca"]]).values()), _visible("coo", [org["luca"]])
    with as_user("coo"):
        assert db.one("SELECT 1 FROM team WHERE id=?", (org["log"],))
        assert not db.query("SELECT 1 FROM reorg_move WHERE person_id=?", (org["luca"],))
    html = client.get("/org").text
    assert "Logistica" in html and "Luca" not in html and "Lea Logistica" in client.get("/people").text
    # chi riceve vede tutto, nel team «Da collocare»
    seen = _visible("dir2", [org["luca"]])
    for t in ("person", "person_assignment", "ral_event", "goal", "performance_review",
              "ninebox_assessment", "benefit_assignment", "bonus_allocation"):
        assert seen[t] >= 1, t
    html = client2.get(f"/people/{org['luca']}").text
    assert "Luca Logistica" in html and "Review 2026" in html and "Da collocare" in html
    cur = db.sys.one("SELECT pa.*, t.name, t.holding FROM person_assignment pa JOIN team t ON t.id=pa.team_id "
                     "WHERE pa.person_id=? AND pa.end_date IS NULL", (org["luca"],))
    assert cur["holding"] == 1 and str(cur["start_date"]) == "2026-06-01" and cur["role_type"] == "ic" \
        and cur["manager_person_id"] is None
    old = db.sys.one("SELECT end_date FROM person_assignment WHERE person_id=? AND team_id=?", (org["luca"], org["log"]))
    assert str(old["end_date"]) == "2026-05-31"                                 # storicizzata, non riscritta
    # la nota resta a chi l'ha scritta (in sola lettura), non passa a chi riceve
    assert "Colloquio Luca" not in client2.get("/notes?q=magazzino").text
    assert "Colloquio Luca" in client.get("/notes?q=magazzino").text
    with as_user("dir2"):
        cyc = db.one("SELECT c.name, c.owner_user_id FROM goal g JOIN review_cycle c ON c.id=g.cycle_id "
                     "WHERE g.person_id=?", (org["luca"],))
        assert cyc["name"] == "Review 2026" and cyc["owner_user_id"] == users.by_username("dir2")["id"]
        lp = db.one("SELECT lp.code FROM person_assignment pa JOIN listino_profile lp ON lp.id=pa.listino_profile_id "
                    "WHERE pa.person_id=? AND pa.end_date IS NULL", (org["luca"],))
        assert lp["code"] == "GE040"                                             # il codice è aziendale: resta
    # contenitori economici di chi cede: righe staccate, pendenti annullate, nessuna quota spostata
    prop = db.sys.one("SELECT * FROM ral_proposal WHERE person_id=?", (org["luca"],))
    assert prop["voided"] == 1 and prop["budget_id"] is None
    assert db.sys.one("SELECT pool_id FROM bonus_allocation WHERE person_id=?", (org["luca"],))["pool_id"] is None
    assert db.sys.one("SELECT total_cap FROM ral_budget WHERE id=?", (org["budget"],))["total_cap"] == 10000
    assert db.sys.one("SELECT voided FROM hiring_position WHERE id=?", (org["pos"],))["voided"] == 0   # il team resta
    assert db.sys.one("SELECT 1 FROM audit_event WHERE event='person_transfer'")


def test_da_collocare_avviso_grafico_e_collocazione(org, client, client2, hr_client):
    _transfer(hr_client, org["lea"])   # responsabile di Logistica
    # il team resta senza responsabile; Luca e Mario riportavano a Lea: il director lo vede in verifica
    assert db.sys.one("SELECT lead_person_id FROM team WHERE id=?", (org["log"],))["lead_person_id"] is None
    assert "Lea Logistica" not in client.get("/org/chart").text
    # dir2: avviso in dashboard, team «Da collocare» nell'organigramma e nel grafico (ha una persona)
    html = client2.get("/").text
    assert "Persone da collocare" in html and "Lea Logistica" in html
    assert "da collocare" in client2.get("/org").text and "Lea Logistica" in client2.get("/org/chart").text
    assert "Lea Logistica" not in client.get("/org/riporti").text
    # dir2 la colloca in un suo team: la dashboard si pulisce e il team tecnico vuoto sparisce dal grafico
    client2.post("/org/team", data={"name": "Beta", "parent_team_id": "", "lead_person_id": ""})
    beta = db.sys.one("SELECT id FROM team WHERE name='Beta'")["id"]
    client2.post(f"/people/{org['lea']}/assignment", data={"team_id": beta, "role_type": "mgr", "start_date": "2026-07-01"})
    assert "Persone da collocare" not in client2.get("/").text
    assert "Da collocare" not in client2.get("/org/chart").text and "Da collocare" in client2.get("/org").text
    # un secondo spostamento riusa lo stesso team tecnico
    _transfer(hr_client, org["mario"])
    assert db.sys.one("SELECT COUNT(*) AS n FROM team WHERE holding=1")["n"] == 1


def test_eliminare_una_persona_ancora_indicata_altrove(org, client, hr_client):
    _transfer(hr_client, org["lea"])   # il riporto di Lea verso Rita resta scritto nella sua storia
    r = client.post(f"/people/{org['rita']}/delete", data={"confirm_name": "Rita Direzione"}, follow_redirects=False)
    assert "err=linked" in r.headers["location"]
    assert db.sys.one("SELECT 1 FROM person WHERE id=?", (org["rita"],))


def test_spostamento_rifiutato(org, client, hr_client, admin_client):
    coo = users.by_username("coo")["id"]
    r = hr_client.post(f"/people/{org['luca']}/director", data={"director_id": coo, "on_date": "2026-06-01"}, follow_redirects=False)
    assert "gi%C3%A0%20di%20quel%20director" in r.headers["location"]
    r = hr_client.post(f"/people/{org['luca']}/director", data={"director_id": users.by_username("dir2")["id"],
                                                                "on_date": "2023-01-01"}, follow_redirects=False)
    assert "successiva" in r.headers["location"]
    assert client.post(f"/people/{org['luca']}/director", data={"director_id": "1"}).status_code == 403   # non il director
    assert admin_client.post(f"/people/{org['luca']}/director", data={"director_id": "1"}).status_code == 403
    html = admin_client.get("/admin?tab=teams").text
    assert "Logistica" not in html and "Luca" not in html and "Trasferisci" not in html   # via il tab Team dell'admin (0.42)
    assert db.sys.one("SELECT COUNT(*) AS n FROM team WHERE holding=1")["n"] == 0


def test_cli_senza_trasferimento(org, capsys):
    from app import admin_cli, session

    session.reset()
    db.close_db()
    assert admin_cli.main(["list-teams"]) == 0
    out = capsys.readouterr().out
    assert "Logistica" in out and "coo" in out
    with pytest.raises(SystemExit):
        admin_cli.main(["transfer-team", "logistica", "--to", "dir2"])
    db.startup()


PAGES = ["/", "/people", "/org", "/org/chart", "/org/riporti", "/comp/hiring", "/comp/salary", "/comp/plan",
         "/comp/budget", "/comp/bonus", "/comp/listino", "/ninebox", "/cycles", "/notes", "/actions",
         "/reports", "/org/sim", "/settings", "/account"]


def test_tutte_le_pagine_si_aprono_per_entrambi_dopo_uno_spostamento(org, client, client2, hr_client):
    for pid in (org["lea"], org["luca"], org["mario"]):
        _transfer(hr_client, pid)
    for c, name in ((client, "coo"), (client2, "dir2")):
        for url in PAGES:
            assert c.get(url).status_code == 200, (name, url)
    for pid in (org["lea"], org["luca"], org["mario"]):
        assert client2.get(f"/people/{pid}").status_code == 200
    assert client.get(f"/people/{org['vera']}").status_code == 200
    for t in (org["log"], org["mag"], org["ven"]):
        assert client.get(f"/org/team/{t}").status_code == 200
    hold = db.sys.one("SELECT id FROM team WHERE holding=1")["id"]
    assert client2.get(f"/org/team/{hold}").status_code == 200
    for url in ("/people", "/org", "/comp/salary", "/ninebox"):
        assert hr_client.get(url).status_code == 200


# ---- authorizer (0.34): niente scorciatoie verso le tabelle vere ----

@pytest.mark.parametrize("sql", [
    "SELECT * FROM main.person",
    "SELECT full_name FROM main.person WHERE id = 1",
    "SELECT p.full_name FROM person x JOIN main.person p ON p.id = x.id",
    "SELECT username FROM app_user",
    "SELECT detail FROM audit_event",
    "SELECT name FROM main.team",
    "SELECT amount FROM main.ral_event",
    "SELECT body FROM main.meeting_note",
])
def test_letture_dirette_negate(org, sql):
    with as_user("dir2"):
        with pytest.raises(db.sqlcipher.DatabaseError):
            db.query(sql)


def test_comandi_che_scavalcano_le_viste_negati(org, tmp_path):
    with as_user("dir2"):
        for sql in (f"ATTACH DATABASE '{tmp_path / 'x.db'}' AS x", "PRAGMA main.table_info(person)",
                    f"VACUUM INTO '{tmp_path / 'copia.db'}'"):
            with pytest.raises(db.sqlcipher.DatabaseError):
                db.query(sql)
        # dentro una scrittura una sottoquery su un'altra tabella vera è negata
        mia = db.execute("INSERT INTO person (full_name) VALUES ('Mia')")
        with pytest.raises(db.sqlcipher.DatabaseError):
            db.execute("UPDATE person SET notes=(SELECT name FROM main.team LIMIT 1) WHERE id=?", (mia,))
        # aggiornare per id una riga altrui: ammesso dall'authorizer, saltato dalla guardia
        db.execute("UPDATE person SET full_name='Presa' WHERE id=?", (org["luca"],))
    assert db.sys.one("SELECT full_name FROM person WHERE id=?", (org["luca"],))["full_name"] == "Luca Logistica"


def test_limite_dichiarato_conteggio_totale(org):
    """count(*) non legge colonne: passa. Si sa quante righe ha una tabella, mai quali."""
    with as_user("dir2"):
        assert db.one("SELECT COUNT(*) AS n FROM main.person")["n"] >= 5
        assert db.one("SELECT COUNT(*) AS n FROM person")["n"] == 0
