"""Utente director ↔ persona (0.47.3): IT collega l'utente alla persona Director+ non ancora collegata;
una persona collegata non si sposta né si cessa; badge in lista e scheda."""
import pytest

from app import db, users
from tests.conftest import PASSWORD, as_user
from tests.test_viste_hr import _seed


def _sr(client, name, team):
    client.post("/people", data={"full_name": name, "team_id": team, "role_type": "sr"})
    return db.sys.one("SELECT id FROM person WHERE full_name=?", (name,))["id"]


def test_collegabili_e_creazione_dal_pannello(client, client2, hr_client, admin_client):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    dario = _sr(client, "Dario Director", t1)
    elena = _sr(client2, "Elena Director", t2)
    assert {p["full_name"] for p in users.linkable_people()} == {"Dario Director", "Elena Director"}   # solo sr liberi
    html = admin_client.get("/admin?tab=users").text
    assert 'name="person_id"' in html and "Dario Director" in html and "Anna Alfa" not in html
    assert html.count("da collegare") == 2                                                  # coo e dir2 senza persona
    # director senza persona → errore; persona non sr → errore; hr ignora la persona
    r = admin_client.post("/admin/users", data={"username": "dir3", "role": "director"}, follow_redirects=False)
    assert "scegline" in r.headers["location"] and users.by_username("dir3") is None
    r = admin_client.post("/admin/users", data={"username": "dir3", "role": "director", "person_id": ids["Anna Alfa"]}, follow_redirects=False)
    assert "collegabile" in r.headers["location"]
    r = admin_client.post("/admin/users", data={"username": "dir3", "role": "director", "person_id": dario}, follow_redirects=False)
    assert "saved=creato" in r.headers["location"]
    assert users.by_username("dir3")["person_id"] == dario
    assert users.linked_user(dario)["username"] == "dir3"
    assert {p["full_name"] for p in users.linkable_people()} == {"Elena Director"}             # Dario non più libero
    assert "Dario Director" in admin_client.get("/admin?tab=users").text
    r = admin_client.post("/admin/users", data={"username": "hr2", "role": "hr", "person_id": elena}, follow_redirects=False)
    assert "saved=creato" in r.headers["location"] and users.by_username("hr2")["person_id"] is None
    assert db.sys.one("SELECT detail FROM audit_event WHERE event='user_create' AND detail LIKE '%dir3%'")["detail"].endswith("persona Dario Director")


def test_gestisci_collega_scollega_e_cambio_ruolo(client, client2, admin_client):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    dario = _sr(client, "Dario Director", t1)
    r = admin_client.post(f"/admin/users/{coo}/person", data={"person_id": dario}, follow_redirects=False)
    assert "saved=1" in r.headers["location"] and users.get(coo)["person_id"] == dario
    # dir2 non può prendere la stessa persona; keep la mostra ancora a coo
    r = admin_client.post(f"/admin/users/{dir2}/person", data={"person_id": dario}, follow_redirects=False)
    assert "collegabile" in r.headers["location"] and users.get(dir2)["person_id"] is None
    assert [p["id"] for p in users.linkable_people(keep=dario)] == [dario] and users.linkable_people() == []
    # un utente hr non si collega
    users.create("hr9", "hr", PASSWORD)
    with pytest.raises(users.UserError):
        users.link_person(users.by_username("hr9")["id"], dario)
    # scollega; ricollega; il cambio di ruolo scollega da solo
    admin_client.post(f"/admin/users/{coo}/person", data={"person_id": ""})
    assert users.get(coo)["person_id"] is None and db.sys.one("SELECT 1 FROM audit_event WHERE event='user_unlink'")
    admin_client.post(f"/admin/users/{dir2}/person", data={"person_id": dario})
    users.update(dir2, None, "hr")
    assert users.get(dir2)["person_id"] is None


def test_hr_non_sposta_ne_cessa_una_persona_collegata(client, client2, hr_client, admin_client):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    dario = _sr(client, "Dario Director", t1)
    admin_client.post(f"/admin/users/{coo}/person", data={"person_id": dario})
    html = hr_client.get("/people").text
    assert "utente director · coo" in html
    assert 'disabled title="È l\'utente director coo' in html or "disabled title=\"È l'utente director coo" in html
    r = hr_client.post(f"/people/{dario}/director", data={"director_id": dir2, "on_date": "2026-12-01"}, follow_redirects=False)
    assert "utente%20director" in r.headers["location"] and "coo" in r.headers["location"]
    r = hr_client.post(f"/people/{dario}/cessation", data={"end_date": "2026-12-31"}, follow_redirects=False)
    assert r.headers["location"] == f"/people/{dario}?err=utente&u=coo"
    assert db.sys.one("SELECT status FROM person WHERE id=?", (dario,))["status"] == "attivo"
    assert "utente director · coo" in client.get(f"/people/{dario}").text
    assert "prima IT la scollega" in hr_client.get(f"/people/{dario}?err=utente&u=coo").text
    # scollegata: lo spostamento passa
    admin_client.post(f"/admin/users/{coo}/person", data={"person_id": ""})
    r = hr_client.post(f"/people/{dario}/director", data={"director_id": dir2, "on_date": "2026-12-01"}, follow_redirects=False)
    assert "moved=" in r.headers["location"]


def test_cli(client, client2, capsys):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    _sr(client, "Dario Director", t1)
    from app import admin_cli, session

    session.reset()
    db.close_db()
    assert admin_cli.main(["create-user", "dir3", "--role", "director"]) == 1          # senza persona
    assert admin_cli.main(["create-user", "dir3", "--role", "director", "--person", "Nessuno"]) == 1
    assert admin_cli.main(["create-user", "dir3", "--role", "director", "--person", "dario director"]) == 0
    assert admin_cli.main(["list-users"]) == 0
    out = capsys.readouterr().out
    assert "persona: Dario Director" in out and "persona: da collegare" in out
    assert admin_cli.main(["unlink-person", "dir3"]) == 0
    assert admin_cli.main(["link-person", "coo", "Dario Director"]) == 0
    db.startup()
    assert users.by_username("dir3")["person_id"] is None
    assert users.by_username("coo")["person_id"] == db.sys.one("SELECT id FROM person WHERE full_name='Dario Director'")["id"]
