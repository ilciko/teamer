"""Ruoli, pannello del site admin, audit, migrazione dalla versione mono-utente e CLI."""
import pytest
from fastapi.testclient import TestClient

from app import config, db, session, users
from tests.conftest import PASSWORD, login, make_legacy_db


def _app():
    from app.main import app

    return app


@pytest.mark.parametrize("path", ["/people", "/org", "/comp/salary", "/notes", "/settings", "/reports"])
def test_admin_non_vede_i_dati_del_personale(admin_client, path):
    r = admin_client.get(path, follow_redirects=False)
    assert r.status_code == 403 and "non è prevista per il tuo ruolo" in r.text
    assert admin_client.post(path, data={}).status_code == 403


def test_admin_home_e_nav(admin_client):
    r = admin_client.get("/", follow_redirects=False)
    assert r.headers["location"] == "/admin"
    nav = admin_client.get("/admin").text.split('class="sidebar"')[1].split("</nav>")[0]
    assert 'href="/admin"' in nav and 'href="/people"' not in nav and "public-switch" not in nav


def test_director_fuori_dal_pannello(client):
    assert client.get("/admin", follow_redirects=False).status_code == 403
    assert client.post("/admin/users", data={"username": "x", "role": "admin"}).status_code == 403
    assert client.post("/admin/backup").status_code == 403
    assert users.by_username("x") is None
    nav = client.get("/org").text.split('class="sidebar"')[1].split("</nav>")[0]
    assert 'href="/admin"' not in nav and "coo · Director" in nav


def test_creazione_reset_e_primo_accesso(admin_client):
    r = admin_client.post("/admin/users", data={"username": "hr", "role": "director", "display_name": "HR"})
    assert r.status_code == 200
    html = r.text
    assert "Password provvisoria di hr" in html
    temp = html.split("Password provvisoria di hr:</strong> <code")[1].split(">")[1].split("<")[0]
    assert "Password provvisoria" not in admin_client.get("/admin").text   # mostrata una volta sola

    hr = TestClient(_app())
    assert login(hr, "hr", temp).url.path == "/account"
    assert hr.get("/org", follow_redirects=False).headers["location"] == "/account"   # obbligo di cambiarla
    r = hr.post("/account/password", data={"current": temp, "new": "corta", "confirm": "corta"},
                follow_redirects=False)
    assert r.headers["location"] == "/account?saved=err"
    hr.post("/account/password", data={"current": temp, "new": "la-mia-password", "confirm": "la-mia-password"})
    assert hr.get("/org").status_code == 200

    uid = users.by_username("hr")["id"]
    admin_client.post(f"/admin/users/{uid}/reset")
    assert hr.get("/org", follow_redirects=False).status_code == 302        # sessioni chiuse dal reset
    assert users.get(uid)["must_change_password"] == 1


def test_disattivazione_e_ultimo_admin(admin_client, client):
    coo = users.by_username("coo")["id"]
    admin_client.post(f"/admin/users/{coo}/active", data={"active": "0"})
    assert client.get("/org", follow_redirects=False).status_code == 302
    it = users.by_username("it")["id"]
    r = admin_client.post(f"/admin/users/{it}/active", data={"active": "0"}, follow_redirects=False)
    assert "err=" in r.headers["location"] and users.get(it)["active"] == 1


def test_audit_registra_chi_ha_fatto_cosa_senza_contenuto(client, admin_client):
    client.post("/people", data={"full_name": "Persona Audit", "ral": "45678"})
    rows = db.query("SELECT * FROM audit_event ORDER BY id")
    events = [(r["username"], r["event"]) for r in rows]
    assert ("coo", "login_ok") in events and ("it", "login_ok") in events
    azione = [r for r in rows if r["event"] == "azione" and r["username"] == "coo"][-1]
    assert azione["detail"].startswith("POST /people")
    assert not any("45678" in (r["detail"] or "") or "Persona Audit" in (r["detail"] or "") for r in rows)
    html = admin_client.get("/admin?tab=audit&user=coo").text
    assert "POST /people" in html and "login_ok" in html
    assert "login_ok" not in admin_client.get("/admin?tab=audit&user=coo&event=azione").text.split("<table")[1]


def test_simulazioni_non_finiscono_nell_audit(client):
    client.post("/comp/salary/simulate", data={})
    assert db.one("SELECT COUNT(*) AS n FROM audit_event WHERE detail LIKE '%simulate%'")["n"] == 0


def test_login_sbagliato_e_tab_sistema(admin_client):
    c = TestClient(_app())
    r = c.post("/login", data={"username": "coo", "password": "no"})
    assert "Nome utente o password errati" in r.text
    html = admin_client.get("/admin?tab=system").text
    assert str(config.DB_KEY_FILE) in html and db.load_key() not in html


def test_backup_dal_pannello(admin_client):
    r = admin_client.post("/admin/backup")
    assert r.status_code == 200 and r.content[:16] != b"SQLite format 3\x00"


# ---- stati del servizio ----

def test_chiave_mancante(app_db, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_KEY_FILE", tmp_path / "manca.key")
    db.close_db()
    r = TestClient(_app()).get("/org")
    assert r.url.path == "/login" and "teamer-admin init" in r.text


def test_nessun_utente(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "vuoto.db")
    session.reset()
    db.startup()
    try:
        assert "create-admin" in TestClient(_app()).get("/login").text
    finally:
        db.close_db()


def test_migrazione_dalla_versione_mono_utente(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    session.reset()
    db.close_db()
    make_legacy_db(path)
    assert db.startup() == "legacy"
    c = TestClient(_app())
    assert "Aggiornamento della cifratura" in c.get("/login").text
    r = c.post("/login/migrazione", data={"old_password": "sbagliata", "username": "direttore"})
    assert "Password del database errata" in r.text and db.state() == "legacy"
    r = c.post("/login/migrazione", data={"old_password": "demo1234", "username": "direttore"})
    assert r.url.path == "/account"                       # 8 caratteri: va cambiata
    u = users.by_username("direttore")
    assert u["role"] == "director" and u["must_change_password"] == 1
    assert u["public_mode"] == 1 and db.get_meta("public_mode", "assente") == "assente"   # il flag passa all'utente
    assert db.one("SELECT COUNT(*) AS n FROM audit_event WHERE event='migrazione_chiave'")["n"] == 1
    db.close_db()
    assert db.startup() == "pronto"                       # ora si apre con la chiave
    db.close_db()


# ---- CLI ----

def test_cli_init_e_reset(tmp_path, monkeypatch, capsys):
    from app import admin_cli

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "cli.db")
    monkeypatch.setattr(config, "DB_KEY_FILE", tmp_path / "cli.key")
    session.reset()
    db.close_db()
    assert admin_cli.main(["init"]) == 0
    out = capsys.readouterr().out
    assert "Chiave di sistema creata" in out and "Utente: admin" in out
    assert admin_cli.main(["init"]) == 0 and "già un site admin" in capsys.readouterr().out
    assert admin_cli.main(["create-user", "coo", "--role", "director"]) == 0
    temp = capsys.readouterr().out.split("Password provvisoria: ")[1].split()[0]
    assert admin_cli.main(["reset-password", "coo"]) == 0
    nuova = capsys.readouterr().out.split("Password provvisoria: ")[1].split()[0]
    assert nuova != temp
    assert admin_cli.main(["list-users"]) == 0 and "Director" in capsys.readouterr().out
    assert admin_cli.main(["disable", "admin"]) == 1          # ultimo admin
    db.startup()
    try:
        assert users.authenticate("coo", nuova)[1] is None
        assert db.one("SELECT username FROM audit_event WHERE event='password_reset'")["username"] == "cli"
    finally:
        db.close_db()
