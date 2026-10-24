"""Modalità pubblica: pagine riservate chiuse, cifre oscurate, nessuna fuga nell'HTML."""
import pytest

BLOCKED_GET = ["/reports", "/comp/salary", "/comp/plan", "/comp/plan/report.xlsx", "/comp/budget",
               "/comp/bonus", "/notes", "/notes/report", "/actions", "/ninebox", "/cycles", "/settings",
               "/attachments/1"]


def _setup(client):
    """Persona con RAL e benefit riconoscibili, posizione con RAL prevista, codice di listino con tariffa."""
    from app import db

    client.post("/org/team", data={"name": "Factory", "parent_team_id": "", "lead_person_id": ""})
    tid = db.one("SELECT id FROM team WHERE name='Factory'")["id"]
    lp = db.sys.execute("INSERT INTO listino_profile (code, description, day_rate) VALUES ('GE040', 'Consultant PM', 457)")
    client.post("/people", data={"full_name": "Rita Riservata", "team_id": tid, "role_type": "ic",
                                 "ral": "38123.45", "listino_profile_id": lp})
    pid = db.one("SELECT id FROM person WHERE full_name='Rita Riservata'")["id"]
    bid = db.execute("INSERT INTO hiring_budget (period, year, total_cap) VALUES ('Assunzioni 2026', 2026, 91234)")
    db.execute("INSERT INTO hiring_position (budget_id, title, team_id, role_type, expected_ral) "
               "VALUES (?, 'Backend dev', ?, 'ic', 41777)", (bid, tid))
    db.execute("INSERT INTO meeting_note (person_id, note_date, body) VALUES (?, '2026-01-10', 'Nota segretissima')",
               (pid,))
    sid = db.execute("INSERT INTO reorg_scenario (name) VALUES ('Prova')")
    return tid, pid, sid


def _flag(username="coo") -> bool:
    """Il flag è dell'utente: accenderlo non oscura le pagine degli altri."""
    from app import db

    return bool(db.sys.one("SELECT public_mode FROM app_user WHERE username=?", (username,))["public_mode"])


def _on(client):
    client.post("/public-mode", data={"next": "/org"})
    assert _flag()


def test_switch_accende_e_spegne(client):
    from app import db

    html = client.get("/org").text
    assert 'action="/public-mode"' in html and 'class="public-switch"' in html
    r = client.post("/public-mode", data={"next": "/comp/salary"}, follow_redirects=False)
    assert r.headers["location"] == "/org"                       # da una pagina riservata si va all'organigramma
    assert _flag() and not _flag("it")
    html = client.get("/org").text
    assert "public-switch on" in html and "Modalità pubblica: pagine riservate chiuse" in html
    r = client.post("/public-mode", data={"next": "/comp/salary"}, follow_redirects=False)
    assert r.headers["location"] == "/comp/salary" and not _flag()
    assert client.get("/comp/salary").status_code == 200


@pytest.mark.parametrize("path", BLOCKED_GET)
def test_pagine_riservate_bloccate(client, path):
    _on(client)
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 403 and "modalità pubblica" in r.text


def test_dashboard_porta_all_organigramma_e_post_bloccati(client):
    tid, pid, sid = _setup(client)
    _on(client)
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/org"
    for path in [f"/people/{pid}/ral", f"/people/{pid}/benefit", f"/people/{pid}/incentive",
                 f"/people/{pid}/attachment", "/people/import", "/notes", "/comp/salary/simulate"]:
        assert client.post(path, data={}).status_code == 403, path
    assert client.get(f"/people/{pid}/replacement", follow_redirects=False).status_code == 403
    assert client.get("/comp/salary", headers={"HX-Request": "true"}).status_code == 403


def test_nessuna_cifra_nelle_pagine_condivisibili(client):
    from app import db

    tid, pid, sid = _setup(client)
    _on(client)
    pages = ["/people", f"/people/{pid}", "/org", "/org/chart", f"/org/team/{tid}", "/comp/hiring",
             "/comp/listino", "/org/sim", f"/org/sim/{sid}", f"/org/sim/compare?a=0&b={sid}"]
    for path in pages:
        r = client.get(path)
        assert r.status_code == 200, path
        for leak in ("38123", "38.123", "41777", "41.777", "91234", "91.234", "Nota segretissima"):
            assert leak not in r.text, (path, leak)
    card = client.get(f"/people/{pid}").text
    for title in ("RAL — timeline", "Benefit &amp; incentivi", "Valutazioni 9-box", "Obiettivi &amp; review",
                  "Note &amp; azioni", "Allegati", "RAL corrente"):
        assert title not in card, title
    assert "Rita Riservata" in card and "Assegnazione &amp; contratto" in card
    assert "•••" in client.get("/people").text
    listino = client.get("/comp/listino").text
    assert "€ 457" in listino                                    # la tariffa di vendita resta
    per_codice = listino.split("Listino per codice")[1].split("</table>")[0]
    assert "•••" not in per_codice                              # listino per codice in chiaro
    assert "Per team" not in listino and "Dettaglio per persona" not in listino
    nav = client.get("/org").text.split('class="sidebar"')[1].split("</nav>")[0]
    for href in ('href="/"', 'href="/reports"', 'href="/comp/salary"', 'href="/comp/plan"', 'href="/comp/budget"',
                 'href="/comp/bonus"', 'href="/notes"', 'href="/actions"', 'href="/ninebox"', 'href="/cycles"',
                 'href="/settings"'):
        assert href not in nav, href
    assert 'href="/comp/hiring"' in nav and 'href="/comp/listino"' in nav

    # spenta: torna tutto
    client.post("/public-mode", data={"next": "/org"})
    assert not _flag()
    assert "38.123" in client.get(f"/people/{pid}").text
    assert "41.777" in client.get("/comp/hiring").text
    listino = client.get("/comp/listino").text
    assert "Per team" in listino and "Dettaglio per persona" in listino
