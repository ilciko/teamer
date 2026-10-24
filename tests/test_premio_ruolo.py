"""Montepremi per ruolo di HR (0.43): moltiplicatori aziendali, platea per team con esclusioni,
ruolo prevalente nell'anno di competenza, ruolo e finale modificabili per allocazione."""
import pytest

from app import db
from app.services import budget
from tests.conftest import as_user
from tests.test_viste_hr import _seed


def test_ruolo_prevalente():
    hist = [{"role_type": "ic", "start_date": "2024-01-01", "end_date": "2025-08-31"},
            {"role_type": "tl", "start_date": "2025-09-01", "end_date": None}]
    assert budget.role_prevalente(hist, 2025) == "ic"      # 8 mesi contro 4
    assert budget.role_prevalente(hist, 2026) == "tl"
    assert budget.role_prevalente(hist, 2023) is None
    pari = [{"role_type": "ic", "start_date": "2025-01-01", "end_date": "2025-07-01"},
            {"role_type": "tl", "start_date": "2025-07-02", "end_date": "2025-12-31"}]
    assert budget.role_prevalente(pari, 2025) == "tl"       # 182 giorni contro 183: contano i giorni
    assert budget.role_prevalente([{"role_type": "mgr", "start_date": "2025-12-31", "end_date": None}], 2025) == "mgr"


def _pool(hr_client, **extra):
    data = {"period": "Premio HR 2026", "competence_year": "2025", "ref_date": "2025-12-31", "total_cap": "10000", **extra}
    r = hr_client.post("/comp/bonus", data=data, follow_redirects=False)
    assert r.status_code == 302, r.text
    return int(r.headers["location"].rsplit("/", 1)[1])


def test_moltiplicatori_aziendali_e_platea_per_team(client, client2, hr_client):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    # moltiplicatori: default ic 1, tl 2, mgr 3; HR li cambia in Azienda → Premi, il director no
    html = hr_client.get("/azienda?tab=premi").text
    assert 'name="f_tl"' in html and 'value="2"' in html
    assert client.post("/azienda/premi", data={"f_ic": "1"}).status_code == 403
    r = hr_client.post("/azienda/premi", data={"f_ic": "1", "f_tl": "2.5", "f_mgr": "3", "f_sr": "4"}, follow_redirects=False)
    assert r.headers["location"].endswith("saved=1")
    assert db.sys.one("SELECT factor FROM bonus_role_factor WHERE role_type='tl'")["factor"] == 2.5
    # Bruno è TL da sempre (seed: role tl? no: ic). Lo rendo TL dal 2024 con una nuova assegnazione storica
    with as_user("dir2"):
        db.execute("UPDATE person_assignment SET role_type='tl' WHERE person_id=?", (ids["Bruno Beta"],))
    pid = _pool(hr_client)
    pool = db.sys.one("SELECT * FROM bonus_pool WHERE id=?", (pid,))
    assert pool["kind"] == "ruolo" and pool["competence_year"] == 2025 and pool["total_cap"] == 10000
    allocs = {a["person_id"]: a for a in db.sys.query("SELECT * FROM bonus_allocation WHERE pool_id=?", (pid,))}
    assert len(allocs) == 4 and allocs[ids["Bruno Beta"]]["role_proposed"] == "tl" and allocs[ids["Bruno Beta"]]["weight"] == 2.5
    # 10.000 su pesi 1+1+2,5+1 = 5,5 → ic ≈ 1.820, tl ≈ 4.550 (arrotondati a 10)
    assert allocs[ids["Anna Alfa"]]["proposed_amount"] == 1820 and allocs[ids["Bruno Beta"]]["proposed_amount"] == 4550
    html = hr_client.get(f"/comp/bonus/{pid}").text
    assert "per ruolo · competenza 2025" in html and ">coo<" in html.replace("COO", "coo") or "coo" in html
    assert "(proposto)" in html and f'action="/comp/bonus/{pid}/alloc/' in html
    # platea solo team Beta + ruolo tl escluso → resta Bice
    pid2 = _pool(hr_client, period="Solo Beta", team=str(t2), excluded_role="tl")
    inc = [a["person_id"] for a in db.sys.query("SELECT person_id FROM bonus_allocation WHERE pool_id=? AND included=1", (pid2,))]
    assert inc == [ids["Bice Beta"]]
    # in organico al: chi è assunto dopo la data resta fuori
    with as_user("coo"):
        db.execute("UPDATE person SET hire_date='2026-03-01' WHERE id=?", (ids["Aldo Alfa"],))
    pid3 = _pool(hr_client, period="Organico", ref_date="2025-12-31")
    inc = {a["person_id"] for a in db.sys.query("SELECT person_id FROM bonus_allocation WHERE pool_id=? AND included=1", (pid3,))}
    assert ids["Aldo Alfa"] not in inc and ids["Anna Alfa"] in inc
    # il director non vede i pool di HR nella sua lista, e non crea pool per ruolo
    assert "Premio HR 2026" not in client2.get("/comp/bonus").text and "per ruolo" not in client2.get("/comp/bonus").text
    client.post("/comp/bonus", data={"period": "Del coo", "total_cap": "100"})
    assert db.sys.one("SELECT kind FROM bonus_pool WHERE period='Del coo'")["kind"] == "composito"
    assert "Del coo" not in hr_client.get("/comp/bonus").text


def test_ruolo_per_allocazione_finale_ed_esclusione(client, client2, hr_client):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    pid = _pool(hr_client, per_head="500", total_cap="")
    a = {x["person_id"]: x for x in db.sys.query("SELECT * FROM bonus_allocation WHERE pool_id=?", (pid,))}
    assert db.sys.one("SELECT total_cap FROM bonus_pool WHERE id=?", (pid,))["total_cap"] == 2000   # 500 × 4
    anna = a[ids["Anna Alfa"]]
    # ruolo cambiato solo per il premio: peso 3 (mgr), proposta ricalcolata, l'assegnazione non si tocca
    hr_client.post(f"/comp/bonus/{pid}/alloc/{anna['id']}/role", data={"role_type": "mgr"})
    row = db.sys.one("SELECT * FROM bonus_allocation WHERE id=?", (anna["id"],))
    assert row["role_type"] == "mgr" and row["role_proposed"] == "ic" and row["weight"] == 3.0 and row["proposed_amount"] == 1000
    assert db.sys.one("SELECT role_type FROM person_assignment WHERE person_id=? AND end_date IS NULL", (ids["Anna Alfa"],))["role_type"] == "ic"
    # finale ritoccato a mano sopravvive alla rigenerazione; l'esclusione toglie dal tetto a testa
    hr_client.post(f"/comp/bonus/{pid}/alloc/{anna['id']}", data={"final_amount": "1234"})
    hr_client.post(f"/comp/bonus/{pid}/generate", data={})
    assert db.sys.one("SELECT final_amount FROM bonus_allocation WHERE id=?", (anna["id"],))["final_amount"] == 1234
    bice = a[ids["Bice Beta"]]
    hr_client.post(f"/comp/bonus/{pid}/alloc/{bice['id']}/toggle", data={})
    assert db.sys.one("SELECT total_cap FROM bonus_pool WHERE id=?", (pid,))["total_cap"] == 1500
    assert db.sys.one("SELECT included, proposed_amount FROM bonus_allocation WHERE id=?", (bice["id"],))["included"] == 0
    # vuoto = torna al ruolo proposto; chiusura
    hr_client.post(f"/comp/bonus/{pid}/alloc/{anna['id']}/role", data={"role_type": ""})
    assert db.sys.one("SELECT role_type, weight FROM bonus_allocation WHERE id=?", (anna["id"],))["role_type"] == "ic"
    hr_client.post(f"/comp/bonus/{pid}/close", data={})
    assert "Riapri" in hr_client.get(f"/comp/bonus/{pid}").text
    assert client.get(f"/comp/bonus/{pid}", follow_redirects=False).status_code == 302   # non suo: la vista non lo mostra
