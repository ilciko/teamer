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
