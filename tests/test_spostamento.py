"""Tappa 4 (0.40): il cambio director dalla pagina Persone di HR."""
from app import db, users
from tests.test_viste_hr import _seed


def test_lista_persone_con_select_e_conferma(client, client2, hr_client):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    html = hr_client.get("/people").text
    assert html.count('class="mv-director"') == 4 and 'id="mv-dialog"' in html and "Sposta →" in html
    assert f'data-current="{coo}"' in html and f'data-current="{dir2}"' in html
    # i director non hanno il select
    assert 'class="mv-director"' not in client.get("/people").text
    r = hr_client.post(f"/people/{ids['Anna Alfa']}/director", data={"director_id": dir2, "on_date": "2026-11-01"},
                       follow_redirects=False)
    assert r.status_code == 302
    html = hr_client.get(r.headers["location"]).text
    assert "Anna Alfa" in html and "Da collocare" in html and "dir2" in html.split('class="flash"')[1][:300]
    assert "Anna Alfa" in client2.get("/people").text and "Anna Alfa" not in client.get("/people").text
    # la persona cessata non si sposta e non ha il select
    hr_client.post(f"/people/{ids['Aldo Alfa']}/cessation", data={"end_date": "2026-10-31"})
    r = hr_client.post(f"/people/{ids['Aldo Alfa']}/director", data={"director_id": dir2, "on_date": "2026-11-01"},
                       follow_redirects=False)
    assert "cessata" in r.headers["location"]
    assert hr_client.get("/people?show=tutti").text.count('class="mv-director"') == 3
    # persona senza assegnazione (solo owner): si sposta lo stesso, e nasce nel team tecnico
    hr_client.post("/people", data={"full_name": "Nina Nuova", "director_id": coo})
    nina = db.sys.one("SELECT id FROM person WHERE full_name='Nina Nuova'")["id"]
    assert hr_client.post(f"/people/{nina}/director", data={"director_id": dir2, "on_date": "2026-11-02"},
                          follow_redirects=False).status_code == 302
    assert db.sys.one("SELECT owner_user_id FROM person WHERE id=?", (nina,))["owner_user_id"] == dir2
    assert "Nina Nuova" in client2.get("/").text   # da collocare


def test_correggi_uno_spostamento_sbagliato(client, client2, hr_client):
    """0.47.2: spostata per errore oggi, «Correggi» verso il director di prima la rimette nel suo team;
    «Sposta» con la stessa data è rifiutato."""
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    anna = ids["Anna Alfa"]
    from datetime import date

    oggi = "2026-12-01"   # dopo l'inizio dell'assegnazione del seed (oggi)
    r = hr_client.post(f"/people/{anna}/director", data={"director_id": dir2, "on_date": oggi}, follow_redirects=False)
    assert "moved=" in r.headers["location"]
    r = hr_client.post(f"/people/{anna}/director", data={"director_id": coo, "on_date": oggi}, follow_redirects=False)
    assert "Correggi" in r.headers["location"] or "successiva" in r.headers["location"]   # il controllo resta
    assert "Correggi" in hr_client.get("/people").text
    r = hr_client.post(f"/people/{anna}/director", data={"director_id": coo, "on_date": oggi, "correct": "1"}, follow_redirects=False)
    assert "moved=" in r.headers["location"]
    cur = db.sys.one("SELECT pa.*, t.holding FROM person_assignment pa JOIN team t ON t.id=pa.team_id "
                     "WHERE pa.person_id=? AND pa.voided=0 AND pa.end_date IS NULL", (anna,))
    assert cur["team_id"] == t1 and cur["holding"] == 0                           # tornata nel suo team
    assert db.sys.one("SELECT COUNT(*) AS n FROM person_assignment WHERE person_id=? AND voided=1", (anna,))["n"] == 1
    assert db.sys.one("SELECT owner_user_id FROM person WHERE id=?", (anna,))["owner_user_id"] == coo
    assert "Anna Alfa" in client.get("/people").text and "Anna Alfa" not in client2.get("/people").text
    assert "(correzione)" in db.sys.one("SELECT detail FROM audit_event WHERE event='person_transfer' ORDER BY id DESC LIMIT 1")["detail"]
    # correggi verso un terzo director: via l'assegnazione sbagliata, nuova «Da collocare» da lui
    users.create("dir3", "director", "password-di-prova")
    dir3 = users.by_username("dir3")["id"]
    hr_client.post(f"/people/{anna}/director", data={"director_id": dir2, "on_date": "2026-12-02"})
    r = hr_client.post(f"/people/{anna}/director", data={"director_id": dir3, "on_date": "2026-12-02", "correct": "1"}, follow_redirects=False)
    assert "moved=" in r.headers["location"]
    cur = db.sys.one("SELECT t.holding, t.owner_user_id FROM person_assignment pa JOIN team t ON t.id=pa.team_id "
                     "WHERE pa.person_id=? AND pa.voided=0 AND pa.end_date IS NULL", (anna,))
    assert cur["holding"] == 1 and cur["owner_user_id"] == dir3
    assert db.sys.one("SELECT COUNT(*) AS n FROM person_assignment WHERE person_id=? AND voided=1", (anna,))["n"] == 2
    # «Correggi» su chi non viene da uno spostamento: rifiutato
    r = hr_client.post(f"/people/{ids['Bruno Beta']}/director", data={"director_id": coo, "on_date": oggi, "correct": "1"}, follow_redirects=False)
    assert "Da%20collocare" in r.headers["location"]
