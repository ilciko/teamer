"""Note e azioni con autore (0.37, classe `authored`): ognuno vede e scrive solo le proprie; quando
la persona passa a un altro director restano a chi le ha scritte, in sola lettura."""
import pytest

from app import db, perimeter, users
from tests.conftest import as_user


def _team(client, name):
    client.post("/org/team", data={"name": name, "parent_team_id": "", "lead_person_id": ""})
    return db.sys.one("SELECT id FROM team WHERE name=?", (name,))["id"]


def _person(client, name, team):
    client.post("/people", data={"full_name": name, "team_id": team, "role_type": "ic", "ral": "30000"})
    return db.sys.one("SELECT id FROM person WHERE full_name=?", (name,))["id"]


def _note(c, pid, title, body="testo", action=None):
    data = {"person_id": pid, "note_date": "2026-03-01", "type": "1:1", "title": title, "body": body}
    if action:
        data |= {"action_desc": action, "action_due": "2026-04-01"}
    r = c.post("/notes", data=data, follow_redirects=False)
    assert r.status_code == 302, r.text[-300:]
    return db.sys.one("SELECT id FROM meeting_note WHERE title=?", (title,))["id"]


@pytest.fixture()
def luca(client, client2, hr_client):
    """Luca, di coo (team Logistica); dir2 ha Vendite, vuoto."""
    log = _team(client, "Logistica")
    _team(client2, "Vendite")
    return {"log": log, "luca": _person(client, "Luca Logistica", log)}


def _transfer(hr_client, pid):
    """HR sposta la persona a dir2 (0.40): arriva nel suo team «Da collocare»."""
    r = hr_client.post(f"/people/{pid}/director", data={"director_id": users.by_username("dir2")["id"],
                                                        "on_date": "2027-01-01"}, follow_redirects=False)
    assert r.status_code == 302 and "moved=" in r.headers["location"], r.headers.get("location")


# ---- ognuno le sue ----

def test_autore_di_default_e_ognuno_vede_solo_le_sue(client, hr_client, luca):
    mia = _note(client, luca["luca"], "Nota di coo", action="richiamare")
    sua = _note(hr_client, luca["luca"], "Nota di HR", action="contratto")
    coo, hr = users.by_username("coo")["id"], users.by_username("hr1")["id"]
    assert db.sys.one("SELECT author_user_id FROM meeting_note WHERE id=?", (mia,))["author_user_id"] == coo
    assert db.sys.one("SELECT author_user_id FROM meeting_note WHERE id=?", (sua,))["author_user_id"] == hr
    assert {r["author_user_id"] for r in db.sys.query("SELECT author_user_id FROM action_item")} == {coo, hr}
    for c, mine, other in ((client, "Nota di coo", "Nota di HR"), (hr_client, "Nota di HR", "Nota di coo")):
        for path in ("/notes", f"/notes?person_id={luca['luca']}", "/notes/report", f"/people/{luca['luca']}"):
            html = c.get(path).text
            assert mine in html and other not in html, path
        html = c.get("/actions").text
        assert ("richiamare" in html) == (c is client) and ("contratto" in html) == (c is hr_client)
    # la ricerca per parole non scavalca l'autore
    assert "Nota di HR" not in client.get("/notes?q=testo").text
    with as_user("coo"):
        assert db.one("SELECT COUNT(*) AS n FROM meeting_note")["n"] == 1
    with as_user("hr1"):
        assert db.one("SELECT COUNT(*) AS n FROM action_item")["n"] == 1


def test_hr_gestisce_le_sue_note_e_azioni(client, hr_client, luca):
    pid = luca["luca"]
    nid = _note(hr_client, pid, "Colloquio HR", "prima stesura", action="inviare lettera")
    html = hr_client.get("/notes").text
    assert 'class="hr-ok"' in html and "Colloquio HR" in html
    assert "<form" in hr_client.get(f"/notes/{nid}/modifica").text
    r = hr_client.post(f"/notes/{nid}", data={"person_id": pid, "note_date": "2026-03-02", "type": "1:1",
                                              "title": "Colloquio HR", "body": "riscritta"}, follow_redirects=False)
    assert r.status_code == 302
    assert db.sys.one("SELECT body FROM meeting_note WHERE id=?", (nid,))["body"] == "riscritta"
    aid = db.sys.one("SELECT id FROM action_item WHERE meeting_note_id=?", (nid,))["id"]
    assert hr_client.post(f"/actions/{aid}/status", data={"status": "chiuso"}, follow_redirects=False).status_code == 302
    assert db.sys.one("SELECT status FROM action_item WHERE id=?", (aid,))["status"] == "chiuso"
    assert hr_client.post("/notes/archivia", data={"ids": [nid]}, follow_redirects=False).status_code == 302
    assert db.sys.one("SELECT archived_at FROM meeting_note WHERE id=?", (nid,))["archived_at"]
    assert hr_client.post(f"/notes/{nid}/delete", data={}, follow_redirects=False).status_code == 302
    assert db.sys.one("SELECT 1 FROM meeting_note WHERE id=?", (nid,)) is None
    assert db.sys.one("SELECT meeting_note_id FROM action_item WHERE id=?", (aid,))["meeting_note_id"] is None
    assert hr_client.post("/actions", data={"person_id": pid, "description": "nuova azione"},
                          follow_redirects=False).status_code == 302
    # fuori dalle sue route HR resta in sola lettura
    assert hr_client.post("/org/team", data={"name": "X"}).status_code == 403


def test_la_nota_altrui_non_si_tocca_nemmeno_per_id(client, hr_client, luca):
    pid = luca["luca"]
    mia = _note(client, pid, "Di coo", "segreta")
    sua = _note(hr_client, pid, "Di HR", "riservata")
    aid = db.sys.execute("INSERT INTO action_item (person_id, description, author_user_id) VALUES (?, 'di coo', ?)",
                         (pid, users.by_username("coo")["id"]))
    for user, nid, other_aid in (("hr1", mia, aid), ("coo", sua, None)):
        with as_user(user):
            assert db.one("SELECT 1 FROM meeting_note WHERE id=?", (nid,)) is None
            db.execute("UPDATE meeting_note SET body='forzato' WHERE id=?", (nid,))
            db.execute("UPDATE meeting_note SET archived_at='2026-01-01' WHERE id=?", (nid,))
            db.execute("DELETE FROM meeting_note WHERE id=?", (nid,))
            with pytest.raises(db.sqlcipher.DatabaseError, match="fuori perimetro"):
                db.execute("INSERT INTO meeting_note (person_id, note_date, author_user_id) VALUES (?, '2026-01-01', ?)",
                           (pid, users.by_username("coo" if user == "hr1" else "hr1")["id"]))
            if other_aid:
                db.execute("UPDATE action_item SET status='chiuso' WHERE id=?", (other_aid,))
    assert hr_client.get(f"/notes/{mia}/modifica").status_code == 404
    assert hr_client.post(f"/notes/{mia}", data={"person_id": pid, "note_date": "2026-01-01", "body": "x"},
                          follow_redirects=False).status_code == 302
    for nid, body in ((mia, "segreta"), (sua, "riservata")):
        row = db.sys.one("SELECT body, archived_at FROM meeting_note WHERE id=?", (nid,))
        assert row["body"] == body and row["archived_at"] is None
    assert db.sys.one("SELECT status FROM action_item WHERE id=?", (aid,))["status"] == "aperto"


# ---- la persona passa a un altro director ----

def test_dopo_il_trasferimento_le_note_restano_a_chi_le_ha_scritte(client, client2, hr_client, admin_client, luca):
    pid = luca["luca"]
    nid = _note(client, pid, "Prima del passaggio", "da ricordare", action="verificare obiettivi")
    aid = db.sys.one("SELECT id FROM action_item WHERE meeting_note_id=?", (nid,))["id"]
    _note(hr_client, pid, "Nota HR", "resta a HR")
    _transfer(hr_client, luca["luca"])
    # chi cede le legge nella sezione apposita, senza link alla scheda né modifica
    html = client.get("/notes").text
    assert "Persone non più nel tuo perimetro" in html and "Prima del passaggio" in html
    assert f'href="/people/{pid}"' not in html and f"/notes/{nid}/modifica" not in html
    assert "da ricordare" in client.get("/notes?q=ricordare").text
    report = client.get(f"/notes/report?person_id={pid}").text
    assert "Luca Logistica" in report and "Prima del passaggio" in report
    html = client.get("/actions").text
    assert "verificare obiettivi" in html and "(altro director)" in html and f'href="/people/{pid}"' not in html
    # chi riceve non le vede; HR tiene la sua
    for c in (client2,):
        assert "Prima del passaggio" not in c.get("/notes").text
        assert "verificare obiettivi" not in c.get("/actions").text
        assert "Prima del passaggio" not in c.get(f"/people/{pid}").text
    assert "Nota HR" in hr_client.get(f"/people/{pid}").text
    with as_user("dir2"):
        assert db.one("SELECT COUNT(*) AS n FROM meeting_note")["n"] == 0
    # in sola lettura: modifica, archiviazione e cancellazione non fanno niente; l'azione si chiude
    assert client.get(f"/notes/{nid}/modifica").status_code == 404
    client.post(f"/notes/{nid}", data={"person_id": pid, "note_date": "2026-03-01", "body": "cambiata"})
    client.post("/notes/archivia", data={"ids": [nid]})
    client.post(f"/notes/{nid}/delete", data={})
    row = db.sys.one("SELECT body, archived_at FROM meeting_note WHERE id=?", (nid,))
    assert row["body"] == "da ricordare" and row["archived_at"] is None
    with as_user("coo"):
        db.execute("UPDATE action_item SET description='altro' WHERE id=?", (aid,))
        assert db.one("SELECT description FROM action_item WHERE id=?", (aid,))["description"] == "verificare obiettivi"
    client.post(f"/actions/{aid}/status", data={"status": "chiuso"})
    assert db.sys.one("SELECT status FROM action_item WHERE id=?", (aid,))["status"] == "chiuso"
    # niente note nuove su chi non è più nel perimetro
    assert client.post("/notes", data={"person_id": pid, "note_date": "2026-03-05", "body": "x"}).status_code == 403
    assert client.post("/actions", data={"person_id": pid, "description": "x"}).status_code == 403
    assert db.sys.one("SELECT COUNT(*) AS n FROM meeting_note")["n"] == 2
    # la vista col nome mostra solo le persone fuori perimetro su cui ho note
    with as_user("coo"):
        assert [r["full_name"] for r in db.query("SELECT full_name FROM perim_note_person")] == ["Luca Logistica"]
    with as_user("dir2"):
        assert db.query("SELECT * FROM perim_note_person") == []


def test_eliminare_una_persona_con_note_altrui(client, hr_client, luca):
    """La cancellazione definitiva si ferma se un altro utente ha note su di lei (si usa la cessazione)."""
    pid = luca["luca"]
    _note(hr_client, pid, "Di HR")
    r = client.post(f"/people/{pid}/delete", data={"confirm_name": "Luca Logistica"}, follow_redirects=False)
    assert r.headers["location"].endswith("err=linked")
    assert db.sys.one("SELECT 1 FROM person WHERE id=?", (pid,))


# ---- migrazione e dati da assegnare ----

def test_migrazione_assegna_le_note_al_titolare_della_persona(tmp_path):
    """Le note di prima della 0.37 vanno al director del team dell'ultima assegnazione valida,
    altrimenti a chi ha creato la persona; senza nessuno dei due restano da assegnare."""
    conn = db.sqlcipher.connect(":memory:")
    conn.create_function("teamer_owner", 0, lambda: None)
    for path in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        if int(path.name[:4]) <= 31:
            conn.executescript(path.read_text())
    conn.execute("INSERT INTO app_user (id, username, role, password_hash) VALUES (7, 'd7', 'director', 'h'), "
                 "(8, 'd8', 'director', 'h')")
    conn.execute("INSERT INTO team (id, name, owner_user_id) VALUES (1, 'A', 7), (2, 'B', 8)")
    conn.execute("INSERT INTO person (id, full_name, owner_user_id) VALUES (1, 'In team', NULL), "
                 "(2, 'Solo creata', 8), (3, 'Di nessuno', NULL)")
    conn.execute("INSERT INTO person_assignment (person_id, team_id, role_type, start_date, end_date, voided) VALUES "
                 "(1, 2, 'ic', '2020-01-01', '2021-01-01', 0), (1, 1, 'ic', '2021-01-02', NULL, 0), "
                 "(1, 2, 'ic', '2025-01-01', NULL, 1)")   # l'ultima valida è nel team A (di 7)
    for pid in (1, 2, 3):
        conn.execute("INSERT INTO meeting_note (person_id, note_date, title) VALUES (?, '2025-01-01', 'n')", (pid,))
        conn.execute("INSERT INTO action_item (person_id, description) VALUES (?, 'a')", (pid,))
    conn.executescript((db.MIGRATIONS_DIR / "0032_note_con_autore.sql").read_text())
    for t in ("meeting_note", "action_item"):
        assert [r[0] for r in conn.execute(f"SELECT author_user_id FROM {t} ORDER BY person_id")] == [7, 8, None]
        assert conn.execute(f"SELECT sql FROM sqlite_master WHERE name='{t}'").fetchone()[0].count("teamer_owner()") == 1
    assert conn.execute("SELECT COUNT(*) FROM meeting_note WHERE person_id=1").fetchone()[0] == 1


def test_note_senza_autore_sono_dati_da_assegnare(client, admin_client, luca):
    pid = luca["luca"]
    db.sys.execute("INSERT INTO meeting_note (person_id, note_date, title) VALUES (?, '2025-01-01', 'Orfana')", (pid,))
    db.sys.execute("INSERT INTO action_item (person_id, description) VALUES (?, 'orfana')", (pid,))
    u = perimeter.unassigned()
    assert {g["label"]: g["n"] for g in u["groups"] if g["n"]} == {"note 1:1": 1, "azioni": 1}
    assert "Orfana" not in client.get("/notes").text
    counts = perimeter.assign_unassigned(users.by_username("coo")["id"])
    assert counts["meeting_note"] == 1 and counts["action_item"] == 1
    assert "Orfana" in client.get("/notes").text and "orfana" in client.get("/actions").text
    perimeter.disown_all()
    assert db.sys.one("SELECT author_user_id FROM meeting_note WHERE title='Orfana'")["author_user_id"] is None
