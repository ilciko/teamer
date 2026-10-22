"""Perimetri, parte 0.33: ogni director vede solo i suoi team e le loro persone; trasferimenti."""
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
    bt = db.execute("INSERT INTO benefit_type (name) VALUES ('Auto aziendale')")
    db.execute("INSERT INTO benefit_assignment (person_id, benefit_type_id, value, effective_date) "
               "VALUES (?,?,'1','2025-01-01')", (luca, bt))
    lp = db.execute("INSERT INTO listino_profile (code, description, day_rate) VALUES ('GE040', 'Consultant', 450)")
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


def _transfer(admin_client, team, to="dir2"):
    r = admin_client.post(f"/admin/teams/{team}/transfer",
                          data={"user_id": users.by_username(to)["id"], "confirm": "TRASFERISCI"})
    assert r.status_code == 200 and "trasferito a" in r.text, r.text[-500:]


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

def test_trasferimento_passa_persone_e_storico(org, client, client2, admin_client):
    _transfer(admin_client, org["log"])
    moved = [org["lea"], org["luca"], org["mario"]]
    # a chi cede non resta niente delle persone trasferite, in nessuna tabella
    assert all(n == 0 for n in _visible("coo", moved).values()), _visible("coo", moved)
    with as_user("coo"):
        assert not db.query("SELECT 1 FROM team WHERE id IN (?,?)", (org["log"], org["mag"]))
        assert not db.query("SELECT 1 FROM reorg_move WHERE person_id=?", (org["luca"],))
        assert db.one("SELECT 1 FROM team WHERE id=?", (org["ven"],))           # Vendite resta sua
    html = client.get("/org").text
    assert "Logistica" not in html and "Magazzino" not in html and "Vendite" in html
    # chi riceve vede tutto
    seen = _visible("dir2", [org["luca"]])
    for t in ("person", "person_assignment", "ral_event", "meeting_note", "goal", "performance_review",
              "ninebox_assessment", "benefit_assignment", "bonus_allocation"):
        assert seen[t] >= 1, t
    html = client2.get(f"/people/{org['luca']}").text
    assert "Luca Logistica" in html and "Review 2026" in html
    assert "Colloquio Luca" in client2.get("/notes?q=magazzino").text
    with as_user("dir2"):
        cyc = db.one("SELECT c.name, c.owner_user_id FROM goal g JOIN review_cycle c ON c.id=g.cycle_id "
                     "WHERE g.person_id=?", (org["luca"],))
        assert cyc["name"] == "Review 2026" and cyc["owner_user_id"] == users.by_username("dir2")["id"]
        bt = db.one("SELECT bt.name FROM benefit_assignment ba JOIN benefit_type bt ON bt.id=ba.benefit_type_id "
                    "WHERE ba.person_id=?", (org["luca"],))
        assert bt["name"] == "Auto aziendale"                                    # catalogo ricollegato
        lp = db.one("SELECT lp.code FROM person_assignment pa JOIN listino_profile lp ON lp.id=pa.listino_profile_id "
                    "WHERE pa.person_id=? AND pa.end_date IS NULL", (org["luca"],))
        assert lp["code"] == "GE040"
    # contenitori economici di chi cede: righe staccate, pendenti annullate, nessuna quota spostata
    prop = db.sys.one("SELECT * FROM ral_proposal WHERE person_id=?", (org["luca"],))
    assert prop["voided"] == 1 and prop["budget_id"] is None
    assert db.sys.one("SELECT pool_id FROM bonus_allocation WHERE person_id=?", (org["luca"],))["pool_id"] is None
    assert db.sys.one("SELECT total_cap FROM ral_budget WHERE id=?", (org["budget"],))["total_cap"] == 10000
    pos = db.sys.one("SELECT voided, void_reason FROM hiring_position WHERE id=?", (org["pos"],))
    assert pos["voided"] == 1 and pos["void_reason"] == "team trasferito"
    assert db.sys.one("SELECT 1 FROM audit_event WHERE event='team_transfer'")


def test_dopo_il_trasferimento_niente_riferimenti_esterni(org, client2, admin_client):
    _transfer(admin_client, org["log"])
    # Logistica per dir2 è una radice: il padre (Direzione, di coo) non compare e non si perde salvando
    html = client2.get("/org").text
    assert "Direzione" not in html and "Logistica" in html
    client2.post(f"/org/team/{org['log']}", data={"name": "Logistica Nord", "parent_team_id": "", "lead_person_id": ""})
    t = db.sys.one("SELECT name, parent_team_id FROM team WHERE id=?", (org["log"],))
    assert t["name"] == "Logistica Nord" and t["parent_team_id"] == org["d"]
    # il riporto di Lea (manager) verso Rita (director di coo) resta, non è un'anomalia, non si vede
    rita = db.sys.one("SELECT manager_person_id FROM person_assignment WHERE person_id=? AND end_date IS NULL",
                      (org["lea"],))["manager_person_id"]
    assert rita == org["rita"]
    chart = client2.get("/org/chart").text
    assert "Rita" not in chart and "non attivo" not in chart
    assert "Rita" not in client2.get(f"/people/{org['lea']}").text
    r = client2.get("/org/riporti")
    assert "Lea Logistica" not in r.text
    # una nuova assegnazione di Lea nel perimetro di dir2 non azzera il riporto che sta sopra
    client2.post(f"/people/{org['lea']}/assignment", data={"team_id": org["mag"], "role_type": "mgr",
                                                           "start_date": "2026-03-01"})
    assert db.sys.one("SELECT manager_person_id FROM person_assignment WHERE person_id=? AND end_date IS NULL",
                      (org["lea"],))["manager_person_id"] is not None


def test_eliminare_una_persona_ancora_indicata_altrove(org, client, admin_client):
    _transfer(admin_client, org["log"])
    r = client.post(f"/people/{org['rita']}/delete", data={"confirm_name": "Rita Direzione"}, follow_redirects=False)
    assert "err=linked" in r.headers["location"]
    assert db.sys.one("SELECT 1 FROM person WHERE id=?", (org["rita"],))


def test_trasferimento_rifiutato(org, admin_client):
    r = admin_client.post(f"/admin/teams/{org['log']}/transfer",
                          data={"user_id": users.by_username("coo")["id"], "confirm": "TRASFERISCI"})
    assert "già di quel director" in r.text
    r = admin_client.post(f"/admin/teams/{org['log']}/transfer",
                          data={"user_id": users.by_username("dir2")["id"], "confirm": "no"})
    assert "TRASFERISCI" in r.text
    html = admin_client.get("/admin?tab=teams").text
    assert "Logistica" in html and "Luca" not in html                          # nomi dei team, mai persone


def test_cli_trasferisce(org, capsys):
    from app import admin_cli, session

    session.reset()
    db.close_db()
    assert admin_cli.main(["list-teams"]) == 0
    out = capsys.readouterr().out
    assert "Logistica" in out and "coo" in out
    assert admin_cli.main(["transfer-team", "logistica", "--to", "dir2"]) == 0
    assert "trasferito a dir2" in capsys.readouterr().out
    db.startup()
    assert db.sys.one("SELECT owner_user_id FROM team WHERE id=?", (org["mag"],))["owner_user_id"] == \
        users.by_username("dir2")["id"]


PAGES = ["/", "/people", "/org", "/org/chart", "/org/riporti", "/comp/hiring", "/comp/salary", "/comp/plan",
         "/comp/budget", "/comp/bonus", "/comp/listino", "/ninebox", "/cycles", "/notes", "/actions",
         "/reports", "/org/sim", "/settings", "/account"]


def test_tutte_le_pagine_si_aprono_per_entrambi_dopo_un_trasferimento(org, client, client2, admin_client):
    _transfer(admin_client, org["log"])
    for c, name in ((client, "coo"), (client2, "dir2")):
        for url in PAGES:
            assert c.get(url).status_code == 200, (name, url)
    for pid in (org["lea"], org["luca"], org["mario"]):
        assert client2.get(f"/people/{pid}").status_code == 200
    assert client.get(f"/people/{org['vera']}").status_code == 200
    for t in (org["log"], org["mag"]):
        assert client2.get(f"/org/team/{t}").status_code == 200
    assert client.get(f"/org/team/{org['ven']}").status_code == 200
