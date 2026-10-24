"""0.47: un budget (aumenti, assunzioni, montepremi) senza movimenti si elimina anche se chiuso;
con movimenti resta nello storico. Vale per il director e per HR «in veste di»."""
from app import db, users
from tests.conftest import as_user
from tests.test_viste_hr import _seed


def test_budget_aumenti(client, client2, hr_client):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    client.post("/comp/budget", data={"period": "Vuoto", "year": "2026", "total_cap": "1000"})
    client.post("/comp/budget", data={"period": "Con proposta", "year": "2026", "total_cap": "1000"})
    vuoto = db.sys.one("SELECT id FROM ral_budget WHERE period='Vuoto'")["id"]
    pieno = db.sys.one("SELECT id FROM ral_budget WHERE period='Con proposta'")["id"]
    with as_user("coo"):
        db.execute("INSERT INTO ral_proposal (person_id, budget_id, amount, effective_date, status) VALUES (?,?, 500, '2027-01-01', 'bozza')",
                   (ids["Anna Alfa"], pieno))
    client.post(f"/comp/budget/{vuoto}/close", data={})
    html = client.get("/comp/budget").text
    assert f'action="/comp/budget/{vuoto}/delete"' in html and f'action="/comp/budget/{pieno}/delete"' not in html
    r = client.post(f"/comp/budget/{pieno}/delete", data={}, follow_redirects=False)
    assert "err=movimenti" in r.headers["location"] and db.sys.one("SELECT 1 FROM ral_budget WHERE id=?", (pieno,))
    r = client.post(f"/comp/budget/{vuoto}/delete", data={}, follow_redirects=False)
    assert "deleted=1" in r.headers["location"]
    assert db.sys.one("SELECT 1 FROM ral_budget WHERE id=?", (vuoto,)) is None
    assert db.sys.one("SELECT COUNT(*) AS n FROM ral_budget_member WHERE budget_id=?", (vuoto,))["n"] == 0
    # HR «in veste di» dir2 elimina un budget chiuso di dir2; in consultazione non ha il pulsante
    client2.post("/comp/budget", data={"period": "Di dir2", "year": "2026", "total_cap": "1"})
    b2 = db.sys.one("SELECT id FROM ral_budget WHERE period='Di dir2'")["id"]
    client2.post(f"/comp/budget/{b2}/close", data={})
    assert "/delete" not in hr_client.get("/comp/budget").text
    hr_client.post("/hr/acting", data={"director_id": dir2, "next": "/comp/budget"})
    assert f'action="/comp/budget/{b2}/delete"' in hr_client.get("/comp/budget").text
    hr_client.post(f"/comp/budget/{b2}/delete", data={})
    assert db.sys.one("SELECT 1 FROM ral_budget WHERE id=?", (b2,)) is None


def test_budget_assunzioni_e_montepremi(client, client2, hr_client):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    client.post("/comp/hiring", data={"period": "Ass. vuoto", "year": "2026", "total_cap": "100"})
    client.post("/comp/hiring", data={"period": "Ass. con posizione", "year": "2026", "total_cap": "100"})
    vuoto = db.sys.one("SELECT id FROM hiring_budget WHERE period='Ass. vuoto'")["id"]
    pieno = db.sys.one("SELECT id FROM hiring_budget WHERE period='Ass. con posizione'")["id"]
    client.post(f"/comp/hiring/{pieno}/position", data={"title": "Dev", "team_id": t1, "role_type": "ic", "expected_ral": "1"})
    client.post(f"/comp/hiring/{vuoto}/close", data={})
    html = client.get("/comp/hiring").text
    assert f'action="/comp/hiring/{vuoto}/delete"' in html
    assert "err=movimenti" in client.post(f"/comp/hiring/{pieno}/delete", data={}, follow_redirects=False).headers["location"]
    assert "deleted=1" in client.post(f"/comp/hiring/{vuoto}/delete", data={}, follow_redirects=False).headers["location"]
    assert db.sys.one("SELECT 1 FROM hiring_budget WHERE id=?", (vuoto,)) is None
    # montepremi chiuso senza importi: eliminabile; con importi no
    client.post("/comp/bonus", data={"period": "Premi vuoti", "total_cap": "0"})
    pool = db.sys.one("SELECT id FROM bonus_pool WHERE period='Premi vuoti'")["id"]
    client.post(f"/comp/bonus/{pool}/generate", data={})
    client.post(f"/comp/bonus/{pool}/close", data={})
    assert f'action="/comp/bonus/{pool}/delete"' in client.get("/comp/bonus").text
    client.post(f"/comp/bonus/{pool}/delete", data={})
    assert db.sys.one("SELECT 1 FROM bonus_pool WHERE id=?", (pool,)) is None
    client.post("/comp/bonus", data={"period": "Premi pieni", "total_cap": "1000"})
    pool = db.sys.one("SELECT id FROM bonus_pool WHERE period='Premi pieni'")["id"]
    client.post(f"/comp/bonus/{pool}/generate", data={})
    aid = db.sys.one("SELECT id FROM bonus_allocation WHERE pool_id=? ORDER BY id LIMIT 1", (pool,))["id"]
    client.post(f"/comp/bonus/{pool}/alloc/{aid}", data={"final_amount": "100"})   # un importo assegnato
    client.post(f"/comp/bonus/{pool}/close", data={})
    assert f'action="/comp/bonus/{pool}/delete"' not in client.get("/comp/bonus").text
    client.post(f"/comp/bonus/{pool}/delete", data={})
    assert db.sys.one("SELECT 1 FROM bonus_pool WHERE id=?", (pool,))
