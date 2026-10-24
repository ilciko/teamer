"""Tappa 3 del profilo HR (0.39): contratti solo HR, RAL dirette, director «in veste di», budget
intestati al director, macchina a stati del piano, cessazione «da decidere»."""
import pytest

from app import db, users
from tests.conftest import PASSWORD, as_user, login
from tests.test_viste_hr import _seed


def _acting(hr_client, director: str):
    uid = users.by_username(director)["id"]
    r = hr_client.post("/hr/acting", data={"director_id": uid, "next": "/comp/plan"}, follow_redirects=False)
    assert r.status_code == 302
    return uid


def test_contratti_solo_hr(client, client2, hr_client):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    anna = ids["Anna Alfa"]
    # il director legge e basta: 403 su RAL, benefit, incentivi, contratto, cessazione
    for path, data in [(f"/people/{anna}/ral", {"amount": "31000", "effective_date": "2026-07-01", "change_type": "aumento"}),
                       (f"/people/{anna}/incentive", {"amount": "500", "inc_date": "2026-07-01"}),
                       (f"/people/{anna}/employment", {"livello": "l3", "start_date": "2026-07-01"}),
                       (f"/people/{anna}/cessation", {"end_date": "2026-12-31"})]:
        assert client.post(path, data=data).status_code == 403, path
    html = client.get(f"/people/{anna}").text
    assert "Nuovo evento RAL" not in html and "Assegna benefit" not in html and "li registra HR" in html
    assert "Nuova assegnazione" in html and "Elimina definitivamente" in html
    # HR scrive: nuovo evento, correzione (void), contratto, incentivo
    r = hr_client.post(f"/people/{anna}/ral", data={"amount": "31500", "effective_date": "2027-01-01", "change_type": "ccnl",
                                                   "reason": "rinnovo CCNL"}, follow_redirects=False)
    assert r.status_code == 302
    ev = db.sys.one("SELECT * FROM ral_event WHERE person_id=? ORDER BY id DESC LIMIT 1", (anna,))
    assert ev["amount"] == 31500 and ev["change_type"] == "ccnl" and ev["delta"] == 1500
    assert hr_client.post(f"/people/{anna}/employment", data={"livello": "l3", "start_date": "2026-07-01"},
                          follow_redirects=False).status_code == 302
    assert hr_client.post(f"/people/{anna}/incentive", data={"amount": "500", "inc_date": "2026-07-01"},
                          follow_redirects=False).status_code == 302
    assert hr_client.post(f"/people/{anna}/ral/{ev['id']}/void", data={}, follow_redirects=False).status_code == 302
    assert db.sys.one("SELECT voided FROM ral_event WHERE id=?", (ev["id"],))["voided"] == 1
    html = hr_client.get(f"/people/{anna}").text
    assert "Nuovo evento RAL" in html and "Assegna benefit" in html and "Nuova situazione contrattuale" in html
    assert "Nuova assegnazione" not in html and "Elimina definitivamente" not in html and "Nuova valutazione 9-box" not in html
    # il director vede l'incentivo, senza il form
    html = client.get(f"/people/{anna}").text
    assert "€ 500" in html and "Incentivo one-shot" not in html


def test_censimento_director_senza_contratto_e_hr_con_director(client, client2, hr_client):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    html = client.get("/people").text
    assert 'name="ral"' not in html and 'name="livello"' not in html and 'name="director_id"' not in html
    assert "le censisce HR" in html
    # HR: senza director → 403; con director e team di un altro director → 403; giusto → persona sua
    assert hr_client.post("/people", data={"full_name": "X"}).status_code == 403
    assert hr_client.post("/people", data={"full_name": "X", "director_id": dir2, "team_id": t1}).status_code == 403
    r = hr_client.post("/people", data={"full_name": "Yuri Ypsilon", "director_id": dir2, "team_id": t2, "role_type": "ic",
                                        "ral": "28000", "livello": "l2", "tipo_contratto": "ti"}, follow_redirects=False)
    assert r.status_code == 302
    yuri = db.sys.one("SELECT * FROM person WHERE full_name='Yuri Ypsilon'")
    assert yuri["owner_user_id"] == dir2
    assert db.sys.one("SELECT amount FROM ral_event WHERE person_id=?", (yuri["id"],))["amount"] == 28000
    assert "Yuri Ypsilon" in client2.get("/people").text and "Yuri Ypsilon" not in client.get("/people").text
    # senza team: resta di dir2 (owner_user_id), invisibile a coo
    hr_client.post("/people", data={"full_name": "Walter W", "director_id": dir2})
    assert "Walter W" in client2.get("/people").text and "Walter W" not in client.get("/people").text
    html = hr_client.get("/people").text
    assert 'name="director_id"' in html and 'data-director="' in html


def test_salary_diretta_di_hr_e_in_veste_di(client, client2, hr_client):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    html = hr_client.get("/comp/salary").text
    assert "scrittura diretta" in html and 'name="budget_id"' not in html and "9-box" not in html
    assert "Bruno Beta" in html and ">coo<" in html and ">dir2<" in html
    anna, bruno = ids["Anna Alfa"], ids["Bruno Beta"]
    r = hr_client.post("/comp/salary/apply", data={"effective_date": "2026-09-01", "change_type": "ccnl", "reason": "CCNL",
                                                  f"ral_{anna}": "30600", f"lvl_{bruno}": "l4", f"date_{bruno}": "2026-10-01"},
                       follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("saved=2")
    ev = db.sys.one("SELECT * FROM ral_event WHERE person_id=? ORDER BY id DESC LIMIT 1", (anna,))
    assert ev["amount"] == 30600 and ev["delta"] == 600 and ev["change_type"] == "ccnl" and str(ev["effective_date"]) == "2026-09-01"
    emp = db.sys.one("SELECT * FROM employment WHERE person_id=? AND end_date IS NULL", (bruno,))
    assert emp["livello"] == "l4" and str(emp["start_date"]) == "2026-10-01"
    assert db.sys.one("SELECT COUNT(*) AS n FROM ral_proposal")["n"] == 0        # niente piano
    assert client.post("/comp/salary/apply", data={}).status_code == 403          # il director no
    # «in veste di» dir2: il piano di dir2, solo le sue persone, proposte in bozza sue
    _acting(hr_client, "dir2")
    html = hr_client.get("/comp/salary").text
    assert "scrittura diretta" not in html and "Salva nel piano" in html
    assert "Bruno Beta" in html and "Anna Alfa" not in html and "in veste di <strong>dir2</strong>" in html
    assert hr_client.post("/comp/salary/apply", data={}).status_code == 403     # la scrittura diretta non è «in veste di»
    client2.post("/comp/budget", data={"period": "Aumenti dir2", "year": "2026", "total_cap": "5000"})
    b2 = db.sys.one("SELECT id FROM ral_budget WHERE period='Aumenti dir2'")["id"]
    r = hr_client.post("/comp/salary/plan", data={"budget_id": b2, "effective_date": "2027-01-01", f"inc_{bruno}": "1000"},
                       follow_redirects=False)
    assert r.status_code == 302
    pr = db.sys.one("SELECT * FROM ral_proposal WHERE person_id=?", (bruno,))
    assert pr["status"] == "bozza" and pr["budget_id"] == b2
    assert "Bruno Beta" in client2.get("/comp/plan").text


def test_budget_creati_da_hr_intestati_al_director(client, client2, hr_client):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    # senza «in veste di»: niente form e 403
    html = hr_client.get("/comp/budget").text
    assert "Nuovo budget" not in html
    assert hr_client.post("/comp/budget", data={"period": "X", "year": "2026", "total_cap": "1"}).status_code == 403
    assert hr_client.post("/comp/hiring", data={"period": "X", "year": "2026", "total_cap": "1"}).status_code == 403
    _acting(hr_client, "dir2")
    html = hr_client.get("/comp/budget").text
    assert "Nuovo budget" in html and 'badge purple">dir2' in html
    r = hr_client.post("/comp/budget", data={"period": "Aumenti HR", "year": "2026", "pct": "2"}, follow_redirects=False)
    assert r.status_code == 302
    b = db.sys.one("SELECT * FROM ral_budget WHERE period='Aumenti HR'")
    assert b["owner_user_id"] == dir2
    members = db.sys.query("SELECT person_id FROM ral_budget_member WHERE budget_id=?", (b["id"],))
    assert {m["person_id"] for m in members} == {ids["Bruno Beta"], ids["Bice Beta"]}   # platea: solo le persone di dir2
    r = hr_client.post("/comp/hiring", data={"period": "Assunzioni HR", "year": "2026", "total_cap": "40000"}, follow_redirects=False)
    assert r.status_code == 302
    hb = db.sys.one("SELECT * FROM hiring_budget WHERE period='Assunzioni HR'")
    assert hb["owner_user_id"] == dir2
    # dir2 li vede come suoi, coo no
    assert "Aumenti HR" in client2.get("/comp/budget").text and "Assunzioni HR" in client2.get("/comp/hiring").text
    assert "Aumenti HR" not in client.get("/comp/budget").text and "Assunzioni HR" not in client.get("/comp/hiring").text
    # una posizione «sostituisce» / «+1» e la RAL prevista corretta da HR in consultazione
    hr_client.post(f"/comp/hiring/{hb['id']}/position", data={"title": "Dev", "team_id": t2, "role_type": "ic", "expected_ral": "30000",
                                                              "replaces_person_id": ids["Bice Beta"]})
    hr_client.post(f"/comp/hiring/{hb['id']}/position", data={"title": "Analista", "team_id": t2, "role_type": "ic", "expected_ral": "30000"})
    html = hr_client.get("/comp/hiring").text
    assert "sostituisce</span> <a" in html and "+1 al team" in html
    hr_client.post("/hr/acting", data={"director_id": "", "next": "/comp/hiring"})
    pos = db.sys.one("SELECT id FROM hiring_position WHERE title='Analista'")["id"]
    html = hr_client.get("/comp/hiring").text
    assert f'action="/comp/hiring/position/{pos}/ral"' in html and "Nuovo budget assunzioni" not in html
    assert hr_client.post(f"/comp/hiring/position/{pos}/ral", data={"expected_ral": "33000"}, follow_redirects=False).status_code == 302
    assert db.sys.one("SELECT expected_ral FROM hiring_position WHERE id=?", (pos,))["expected_ral"] == 33000
    assert client.post(f"/comp/hiring/position/{pos}/ral", data={"expected_ral": "1"}).status_code == 403


def test_piano_macchina_a_stati_e_validazione_di_hr(client, client2, hr_client):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    client.post("/comp/budget", data={"period": "Aumenti coo", "year": "2026", "total_cap": "10000"})
    b1 = db.sys.one("SELECT id FROM ral_budget WHERE period='Aumenti coo'")["id"]
    anna = ids["Anna Alfa"]
    with as_user("coo"):
        pid = db.execute("INSERT INTO ral_proposal (person_id, budget_id, amount, effective_date, status) "
                         "VALUES (?,?, 1000, '2027-02-01', 'bozza')", (anna, b1))
    st = lambda: db.sys.one("SELECT status, amount FROM ral_proposal WHERE id=?", (pid,))
    # bozza → approvata non esiste; bozza → proposta sì
    client.post(f"/comp/plan/{pid}/status", data={"status": "approvata"})
    assert st()["status"] == "bozza"
    client.post(f"/comp/plan/{pid}/status", data={"status": "proposta"})
    assert st()["status"] == "proposta"
    # il director non cambia più l'importo di una proposta inviata; HR sì (validazione), senza blocco sul tetto
    client.post(f"/comp/plan/{pid}/update", data={"new_ral": "32000", "effective_date": "2027-02-01"})
    assert st()["amount"] == 1000
    html = client.get("/comp/plan").text
    assert f'action="/comp/plan/{pid}/update"' not in html and "↩ bozza" in html
    hr_client.post(f"/comp/plan/{pid}/update", data={"new_ral": "45000", "effective_date": "2027-02-01"})
    assert st()["amount"] == 15000          # oltre il tetto di 10.000: HR non è bloccata
    # il director la riporta in bozza, la corregge, la rimanda; HR la approva e la applica «in veste di» coo
    client.post(f"/comp/plan/{pid}/status", data={"status": "bozza"})
    client.post(f"/comp/plan/{pid}/update", data={"new_ral": "31000", "effective_date": "2027-02-01"})
    assert st() == {"status": "bozza", "amount": 1000} or (st()["status"] == "bozza" and st()["amount"] == 1000)
    client.post(f"/comp/plan/{pid}/status", data={"status": "proposta"})
    _acting(hr_client, "coo")
    html = hr_client.get("/comp/plan").text
    assert "Approva" in html and 'name="budget_id"' in html and "Aumenti coo" in html
    hr_client.post(f"/comp/plan/{pid}/status", data={"status": "approvata"})
    assert st()["status"] == "approvata"
    hr_client.post(f"/comp/plan/{pid}/apply", data={})
    assert st()["status"] == "applicata"
    ev = db.sys.one("SELECT amount FROM ral_event WHERE person_id=? ORDER BY id DESC LIMIT 1", (anna,))
    assert ev["amount"] == 31000


def test_cessazione_da_hr_e_decisione_del_director(client, client2, hr_client):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    anna = ids["Anna Alfa"]
    r = hr_client.post(f"/people/{anna}/cessation", data={"end_date": "2026-10-31"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"/people/{anna}"   # niente flusso di sostituzione per HR
    assert db.sys.one("SELECT status FROM person WHERE id=?", (anna,))["status"] == "cessato"
    assert "da decidere" in hr_client.get(f"/people/{anna}").text
    # il director la trova in dashboard e in scheda, e decide di non sostituire
    html = client.get("/").text
    assert "Cessazioni da decidere" in html and "Anna Alfa" in html
    html = client.get(f"/people/{anna}").text
    assert "Pianifica sostituzione" in html and f'action="/people/{anna}/replacement/none"' in html
    assert hr_client.post(f"/people/{anna}/replacement/none", data={}).status_code == 403
    client.post(f"/people/{anna}/replacement/none", data={"note": "ruolo assorbito"})
    d = db.sys.one("SELECT * FROM replacement_decision WHERE person_id=? AND voided=0", (anna,))
    assert d["decided_by"] == coo and d["note"] == "ruolo assorbito"
    assert "Cessazioni da decidere" not in client.get("/").text
    html = client.get(f"/people/{anna}").text
    assert "non sostituire" in html and "ruolo assorbito" in html and "Annulla la decisione" in html
    # annullata: torna da decidere; poi la sostituzione chiude la questione
    client.post(f"/people/{anna}/replacement/none/{d['id']}/void", data={})
    assert "Cessazioni da decidere" in client.get("/").text
    client.post(f"/people/{anna}/replacement", data={"title": "Sost. Anna", "team_id": t1, "role_type": "ic",
                                                     "expected_ral": "30000", "expected_start": "2026-11-01"})
    assert "Cessazioni da decidere" not in client.get("/").text
    assert db.sys.one("SELECT replaces_person_id FROM hiring_position WHERE title='Sost. Anna'")["replaces_person_id"] == anna
    # il director registra ancora da sé la cessazione? No: è di HR (403); dir2 non vede nulla di Anna
    assert client.post(f"/people/{ids['Aldo Alfa']}/cessation", data={"end_date": "2026-12-31"}).status_code == 403
    assert "Anna Alfa" not in client2.get("/").text


def test_selettore_in_veste_di(client, client2, hr_client):
    _seed(client, client2)
    assert client.post("/hr/acting", data={"director_id": "1"}).status_code == 403
    html = hr_client.get("/comp/hiring").text
    assert 'action="/hr/acting"' in html and "solo consultazione" in html and "consultazione: per creare" in html
    uid = _acting(hr_client, "coo")
    html = hr_client.get("/comp/hiring").text
    assert f'<option value="{uid}" selected' in html and "in veste di <strong>coo</strong>" in html
    assert 'name="director"' not in html            # niente filtro: è la pagina di coo
    hr_client.post("/hr/acting", data={"director_id": "999", "next": "/comp/hiring"})
    assert "solo consultazione" in hr_client.get("/comp/hiring").text and "in veste di <strong>" not in hr_client.get("/comp/hiring").text
    # un director nuovo creato dall'admin compare nel selettore
    users.create("dir3", "director", PASSWORD)
    assert ">dir3<" in hr_client.get("/comp/budget").text
