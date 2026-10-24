"""Ruolo HR, tappa 1 (0.36): vede le persone di tutti i director; le sue scritture sono in
tests/test_note_autore.py (tappa 2) e tests/test_tappa3_hr.py (contratti, budget, piano)."""
import pytest

from app import db, perimeter, users
from tests.conftest import PASSWORD, as_user, login

# pagine che HR legge (tutte quelle dei director tranne dashboard, report, simulazioni, riporti, configurazione)
HR_PAGES = ["/people", "/people?show=tutti", "/org", "/org/chart", "/comp/hiring", "/comp/salary",
            "/comp/plan", "/comp/plan/report", "/comp/budget", "/comp/bonus", "/comp/listino",
            "/ninebox", "/cycles", "/notes", "/notes/report", "/actions", "/account", "/azienda", "/azienda?tab=listino"]
HR_DENIED = ["/", "/reports", "/org/sim", "/org/riporti", "/settings", "/admin"]


def _seed(client, client2):
    """Una persona per director, in un team ciascuno."""
    client.post("/org/team", data={"name": "Alfa", "parent_team_id": "", "lead_person_id": ""})
    client2.post("/org/team", data={"name": "Beta", "parent_team_id": "", "lead_person_id": ""})
    t1 = db.sys.one("SELECT id FROM team WHERE name='Alfa'")["id"]
    t2 = db.sys.one("SELECT id FROM team WHERE name='Beta'")["id"]
    client.post("/people", data={"full_name": "Anna Alfa", "team_id": t1, "role_type": "ic", "ral": "30000"})
    client2.post("/people", data={"full_name": "Bruno Beta", "team_id": t2, "role_type": "tl", "ral": "40000"})
    p1 = db.sys.one("SELECT id FROM person WHERE full_name='Anna Alfa'")["id"]
    p2 = db.sys.one("SELECT id FROM person WHERE full_name='Bruno Beta'")["id"]
    return t1, t2, p1, p2


def test_hr_vede_le_persone_di_tutti_i_director(client, client2, hr_client):
    t1, t2, p1, p2 = _seed(client, client2)
    html = hr_client.get("/people").text
    assert "Anna Alfa" in html and "Bruno Beta" in html
    assert "<th>Director</th>" in html and "Tutti i director" in html
    coo = users.by_username("coo")["id"]
    html = hr_client.get(f"/people?director={coo}").text
    assert "Anna Alfa" in html and "Bruno Beta" not in html
    # i director, invece, non vedono la colonna e restano nel loro perimetro
    html = client.get("/people").text
    assert "Bruno Beta" not in html and "<th>Director</th>" not in html
    # le schede e l'organigramma di entrambi
    assert "Bruno Beta" in hr_client.get(f"/people/{p2}").text
    assert "€ 40.000" in hr_client.get(f"/people/{p2}").text
    org = hr_client.get("/org").text
    assert "Alfa" in org and "Beta" in org
    with as_user("hr1"):
        assert {r["name"] for r in db.query("SELECT name FROM team")} == {"Alfa", "Beta"}
        assert len(db.query("SELECT id FROM person")) == 2


@pytest.mark.parametrize("path", HR_PAGES)
def test_pagine_di_lettura_aperte(client, client2, hr_client, path):
    _seed(client, client2)
    assert hr_client.get(path).status_code == 200, path


def test_scheda_persona_e_team_senza_errori(client, client2, hr_client):
    t1, t2, p1, p2 = _seed(client, client2)
    for path in [f"/people/{p1}", f"/people/{p2}", f"/org/team/{t1}", f"/org/team/{t2}",
                 f"/people/{p1}/replacement"]:
        assert hr_client.get(path).status_code == 200, path


@pytest.mark.parametrize("path", HR_DENIED)
def test_pagine_fuori_dal_ruolo(hr_client, path):
    r = hr_client.get(path, follow_redirects=False)
    if path == "/":
        assert r.status_code == 302 and r.headers["location"] == "/org"   # niente dashboard: casa è l'organigramma
    else:
        assert r.status_code == 403, path


def test_post_rifiutati_salvo_account_e_anteprime(client, client2, hr_client):
    t1, t2, p1, p2 = _seed(client, client2)
    for path, data in [("/org/team", {"name": "X"}), (f"/people/{p1}/delete", {"confirm_name": "Anna Alfa"}),
                       (f"/people/{p1}/replacement", {"title": "X", "expected_start": "2026-01-01"}),
                       ("/comp/bonus", {}), ("/ninebox/save", {}), ("/cycles", {}),
                       ("/settings/general", {}), ("/admin/users", {}), ("/comp/listino/person/1/code", {})]:
        assert hr_client.post(path, data=data).status_code == 403, path
    assert db.sys.one("SELECT COUNT(*) AS n FROM person")["n"] == 2
    assert db.sys.one("SELECT COUNT(*) AS n FROM team")["n"] == 2
    # anteprime htmx e account restano suoi
    assert hr_client.post("/comp/salary/simulate", data={}).status_code == 200
    r = hr_client.post("/account/password", data={"current": PASSWORD, "new": "nuova-password-hr",
                                                  "confirm": "nuova-password-hr"}, follow_redirects=False)
    assert r.headers["location"] == "/account?saved=1"
    r = hr_client.post("/public-mode", data={"next": "/org"}, follow_redirects=False)
    assert r.status_code == 302
    assert hr_client.get("/comp/salary", follow_redirects=False).status_code == 403   # in pubblica
    hr_client.post("/public-mode", data={"next": "/org"})
    assert hr_client.get("/comp/salary").status_code == 200


def test_connessione_di_hr_fuori_dalla_whitelist(client, client2, hr_client):
    t1, t2, p1, p2 = _seed(client, client2)
    with as_user("hr1"):
        with pytest.raises(db.sqlcipher.DatabaseError):
            db.query("SELECT * FROM app_user")
        with pytest.raises(db.sqlcipher.DatabaseError):
            db.execute("INSERT INTO team (name) VALUES ('Gamma')")
        with pytest.raises(db.sqlcipher.DatabaseError):
            db.execute("UPDATE team SET name='X' WHERE id=?", (t1,))
        with pytest.raises(db.sqlcipher.DatabaseError):
            db.execute("DELETE FROM ninebox_assessment")
        with pytest.raises(db.sqlcipher.DatabaseError):
            db.execute("INSERT INTO bonus_pool (period, total_cap) VALUES ('x', 1)")
        with pytest.raises(db.sqlcipher.DatabaseError):
            db.execute("INSERT INTO lookup (category, code, label) VALUES ('x', 'y', 'z')")
        # la configurazione è la sua, di default (una voce sola per chiave)
        assert db.get_meta("ral_stale_amber_years", "2") == "2"
        assert len(db.query("SELECT * FROM weight_mapping")) == 9
        assert db.one("SELECT 1 FROM evaluation_model WHERE type='nine_box'")
    assert db.sys.one("SELECT full_name FROM person WHERE id=?", (p1,))["full_name"] == "Anna Alfa"
    assert db.sys.one("SELECT COUNT(*) AS n FROM team")["n"] == 2


def test_whitelist_e_ruolo_nel_db(app_db):
    # 0.39: note e azioni, contratti, persone, budget e piano; mai team, configurazione, cicli, 9-box, montepremi
    assert set(perimeter.AUTHORED) | set(perimeter.HR_CONTRACT) <= set(perimeter.HR_WRITABLE)
    assert not {"team", "user_meta", "review_cycle", "ninebox_assessment", "bonus_pool", "lookup"} & set(perimeter.HR_WRITABLE)
    assert "hr" in users.ROLES and "hr" in perimeter.SESSION_ROLES
    with pytest.raises(db.sqlcipher.IntegrityError):
        db.sys.execute("INSERT INTO app_user (username, role, password_hash) VALUES ('x', 'boh', 'h')")


def test_barra_laterale_e_avviso(hr_client):
    html = hr_client.get("/org").text
    nav = html.split('class="sidebar"')[1].split("</nav>")[0]
    assert 'href="/people"' in nav and 'href="/comp/plan"' in nav and 'href="/notes"' in nav
    for href in ('href="/"', 'href="/reports"', 'href="/settings"', 'href="/admin"'):
        assert href not in nav, href
    assert 'href="/azienda"' in nav                                             # Azienda è di HR (0.41)
    assert "hr1 · HR" in nav and "public-switch" in nav
    assert "hr-readonly" in html and "Profilo HR" in html
    for page in (html, hr_client.get("/org/chart").text):
        assert 'href="/org/sim"' not in page and 'href="/org/riporti' not in page


def test_admin_e_cli_creano_utenti_hr(admin_client, app_db, capsys):
    r = admin_client.post("/admin/users", data={"username": "hr2", "role": "hr", "display_name": "Risorse umane"})
    assert r.status_code == 200 and "Password provvisoria di hr2" in r.text
    u = users.by_username("hr2")
    assert u["role"] == "hr" and perimeter.has_config(u["id"])
    from app import admin_cli, session

    session.reset()
    db.close_db()
    assert admin_cli.main(["create-user", "hr3", "--role", "hr"]) == 0
    assert "Password provvisoria" in capsys.readouterr().out
    assert db.startup() == "pronto"
    assert users.by_username("hr3")["role"] == "hr"


def test_cambio_di_ruolo_a_hr(client, client2, hr_client):
    """Un director che diventa HR perde la sessione e rientra vedendo tutti."""
    _seed(client, client2)
    dir2 = users.by_username("dir2")
    users.update(dir2["id"], None, "hr")
    assert client2.get("/org", follow_redirects=False).status_code == 302
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    assert login(c, "dir2").url.path == "/org"
    html = c.get("/people").text
    assert "Anna Alfa" in html and "Bruno Beta" in html
