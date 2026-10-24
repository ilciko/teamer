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
    """0.47.4: «Correggi» si fa sempre e porta nel «Da collocare» del director scelto, con la stessa
    data d'inizio dell'assegnazione corretta (annullata); «Sposta» con la stessa data è rifiutato."""
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    anna = ids["Anna Alfa"]

    def corrente(pid):
        return db.sys.one("SELECT pa.*, t.holding, t.owner_user_id FROM person_assignment pa JOIN team t ON t.id=pa.team_id "
                          "WHERE pa.person_id=? AND pa.voided=0 AND pa.end_date IS NULL", (pid,))

    def annullate(pid):
        return db.sys.one("SELECT COUNT(*) AS n FROM person_assignment WHERE person_id=? AND voided=1", (pid,))["n"]

    oggi = "2026-12-01"   # dopo l'inizio dell'assegnazione del seed (oggi)
    r = hr_client.post(f"/people/{anna}/director", data={"director_id": dir2, "on_date": oggi}, follow_redirects=False)
    assert "moved=" in r.headers["location"]
    r = hr_client.post(f"/people/{anna}/director", data={"director_id": coo, "on_date": oggi}, follow_redirects=False)
    assert "Correggi" in r.headers["location"]   # il controllo sulla data resta per «Sposta»
    assert "Correggi" in hr_client.get("/people").text
    # verso il director di prima: anche lui la ritrova in «Da collocare», dalla stessa data
    r = hr_client.post(f"/people/{anna}/director", data={"director_id": coo, "on_date": "2030-01-01", "correct": "1"},
                       follow_redirects=False)
    assert "moved=" in r.headers["location"]
    cur = corrente(anna)
    assert cur["holding"] == 1 and cur["owner_user_id"] == coo and str(cur["start_date"])[:10] == oggi
    assert annullate(anna) == 1
    assert db.sys.one("SELECT owner_user_id FROM person WHERE id=?", (anna,))["owner_user_id"] == coo
    assert "Anna Alfa" in client.get("/people").text and "Anna Alfa" not in client2.get("/people").text
    assert "(correzione)" in db.sys.one("SELECT detail FROM audit_event WHERE event='person_transfer' ORDER BY id DESC LIMIT 1")["detail"]
    # verso un terzo director
    users.create("dir3", "director", "password-di-prova")
    dir3 = users.by_username("dir3")["id"]
    r = hr_client.post(f"/people/{anna}/director", data={"director_id": dir3, "on_date": oggi, "correct": "1"}, follow_redirects=False)
    assert "moved=" in r.headers["location"]
    cur = corrente(anna)
    assert cur["holding"] == 1 and cur["owner_user_id"] == dir3 and str(cur["start_date"])[:10] == oggi
    assert annullate(anna) == 2
    # chi non viene da uno spostamento (director sbagliato al censimento): si corregge lo stesso
    bruno = ids["Bruno Beta"]
    inizio = str(corrente(bruno)["start_date"])[:10]
    r = hr_client.post(f"/people/{bruno}/director", data={"director_id": coo, "on_date": oggi, "correct": "1"}, follow_redirects=False)
    assert "moved=" in r.headers["location"]
    cur = corrente(bruno)
    assert cur["holding"] == 1 and cur["owner_user_id"] == coo and str(cur["start_date"])[:10] == inizio
    assert annullate(bruno) == 1
    assert "Bruno Beta" in client.get("/people").text and "Bruno Beta" not in client2.get("/people").text
