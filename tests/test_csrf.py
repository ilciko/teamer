"""0.47.5: le richieste non-GET da un'altra origine si rifiutano (CSRF), login e battito compresi."""
from app import db


def _title(client):
    return db.one("SELECT name FROM team WHERE name='Da fuori'")


def test_post_da_altra_origine_rifiutata(client):
    data = {"name": "Da fuori", "parent_team_id": "", "lead_person_id": ""}
    r = client.post("/org/team", data=data, headers={"Origin": "http://evil.example"}, follow_redirects=False)
    assert r.status_code == 403 and "altra origine" in r.text
    assert _title(client) is None
    r = client.post("/org/team", data=data, headers={"Sec-Fetch-Site": "same-site"}, follow_redirects=False)
    assert r.status_code == 403
    r = client.post("/org/team", data=data, headers={"Sec-Fetch-Site": "cross-site", "Origin": "http://testserver"},
                    follow_redirects=False)
    assert r.status_code == 403   # in HTTPS vale Sec-Fetch-Site, anche se l'Origin torna
    assert _title(client) is None


def test_post_stessa_origine_passa(client):
    data = {"name": "Da fuori", "parent_team_id": "", "lead_person_id": ""}
    r = client.post("/org/team", data=data, headers={"Origin": "http://testserver"}, follow_redirects=False)
    assert r.status_code in (200, 302) and _title(client) is not None
    r = client.post("/heartbeat", headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code != 403   # passa il controllo d'origine (poi il battito vuole il suo corpo)


def test_proxy_con_host_inoltrato(client):
    """Dietro un reverse proxy in HTTP l'host pubblico arriva in X-Forwarded-Host."""
    r = client.post("/org/team", data={"name": "Da fuori", "parent_team_id": "", "lead_person_id": ""},
                    headers={"Origin": "https://teamer.example", "X-Forwarded-Host": "teamer.example"},
                    follow_redirects=False)
    assert r.status_code in (200, 302) and _title(client) is not None


def test_login_e_battito_coperti(fresh_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        r = c.post("/login", data={"username": "x", "password": "y"}, headers={"Origin": "http://evil.example"})
        assert r.status_code == 403
        assert c.post("/heartbeat", headers={"Origin": "null"}).status_code == 403
        assert c.get("/login", headers={"Origin": "http://evil.example"}).status_code == 200   # GET passa
