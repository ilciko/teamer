"""Viste trasversali di HR (0.38): director per riga, filtro Director a scelta multipla, totali;
densità e Situazione del 9-box per tutti."""
import re

from app import db, users
from tests.conftest import as_user


def _seed(client, client2):
    """Un team e due persone per director (coo: Alfa, dir2: Beta)."""
    client.post("/org/team", data={"name": "Alfa", "parent_team_id": "", "lead_person_id": ""})
    client2.post("/org/team", data={"name": "Beta", "parent_team_id": "", "lead_person_id": ""})
    t1 = db.sys.one("SELECT id FROM team WHERE name='Alfa'")["id"]
    t2 = db.sys.one("SELECT id FROM team WHERE name='Beta'")["id"]
    for n in ("Anna Alfa", "Aldo Alfa"):
        client.post("/people", data={"full_name": n, "team_id": t1, "role_type": "ic", "ral": "30000"})
    for n in ("Bruno Beta", "Bice Beta"):
        client2.post("/people", data={"full_name": n, "team_id": t2, "role_type": "ic", "ral": "40000"})
    ids = {r["full_name"]: r["id"] for r in db.sys.query("SELECT id, full_name FROM person")}
    coo, dir2 = users.by_username("coo")["id"], users.by_username("dir2")["id"]
    return t1, t2, ids, coo, dir2


def test_persone_senza_ral_e_director_prima_del_team(client, client2, hr_client):
    _seed(client, client2)
    html = hr_client.get("/people").text
    head = html.split("<thead>")[1].split("</thead>")[0]
    assert "RAL" not in head and head.index("Director") < head.index("Team")
    assert "€ 30.000" not in html and "€ 40.000" not in html
    # il director tiene la RAL e non ha la colonna Director
    html = client.get("/people").text
    assert "€ 30.000" in html and "<th>Director</th>" not in html


def test_assunzioni_director_totali_filtro_e_trimestre(client, client2, hr_client):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    client.post("/comp/hiring", data={"period": "Assunzioni coo", "year": "2026", "total_cap": "100000"})
    client2.post("/comp/hiring", data={"period": "Assunzioni dir2", "year": "2026", "total_cap": "50000"})
    b1 = db.sys.one("SELECT id FROM hiring_budget WHERE period='Assunzioni coo'")["id"]
    client.post(f"/comp/hiring/{b1}/position", data={"title": "Dev", "team_id": t1, "role_type": "ic",
                                                     "expected_ral": "35000", "expected_start": "2027-02-15"})
    html = hr_client.get("/comp/hiring").text
    assert "Assunzioni coo" in html and "Assunzioni dir2" in html
    assert 'class="badge purple"' in html and ">coo<" in html and ">dir2<" in html
    assert "Totale dei budget aperti" in html and "2 budget, 1 posizioni aperte" in html
    assert "tetto € 150.000" in html and "impegnato € 35.000" in html and "residuo € 115.000" in html
    assert "Q1 2027" in html
    assert "Nuovo budget assunzioni" not in html and "/position/" not in html   # niente form per HR
    html = hr_client.get(f"/comp/hiring?director={dir2}").text
    assert "Assunzioni dir2" in html and "Assunzioni coo" not in html and "1 budget, 0 posizioni" in html
    html = hr_client.get(f"/comp/hiring?director={dir2}&director={coo}").text
    assert "2 budget" in html and "Director (2)" in html
    # il director: pagina come prima, con il trimestre, senza totali né filtro
    html = client.get("/comp/hiring").text
    assert "Q1 2027" in html and "Totale dei budget" not in html and 'name="director"' not in html
    assert "Nuovo budget assunzioni" in html and "Assunzioni dir2" not in html


def test_budget_aumenti_director_totali_filtro(client, client2, hr_client):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    client.post("/comp/budget", data={"period": "Aumenti coo", "year": "2026", "total_cap": "10000"})
    client2.post("/comp/budget", data={"period": "Aumenti dir2", "year": "2026", "total_cap": "5000"})
    b1 = db.sys.one("SELECT id FROM ral_budget WHERE period='Aumenti coo'")["id"]
    with as_user("coo"):
        db.execute("INSERT INTO ral_proposal (person_id, budget_id, amount, effective_date, status) "
                   "VALUES (?,?, 1500, '2026-07-01', 'proposta')", (ids["Anna Alfa"], b1))
    html = hr_client.get("/comp/budget").text
    assert "Aumenti coo" in html and "Aumenti dir2" in html and ">coo<" in html and ">dir2<" in html
    assert "2 budget, 1 richieste non applicate" in html
    assert "tetto € 15.000" in html and "impegnato € 1.500" in html and "residuo € 13.500" in html
    assert "Nuovo budget" not in html and "/member/" not in html and "refresh-ral" not in html
    html = hr_client.get(f"/comp/budget?director={coo}").text
    assert "Aumenti coo" in html and "Aumenti dir2" not in html
    html = client.get("/comp/budget").text
    assert "Nuovo budget" in html and "Totale dei budget" not in html


def test_piano_aumenti_solo_proposte_con_director_e_budget(client, client2, hr_client):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    client.post("/comp/budget", data={"period": "Aumenti coo", "year": "2026", "total_cap": "10000"})
    client2.post("/comp/budget", data={"period": "Aumenti dir2", "year": "2026", "total_cap": "5000"})
    b1 = db.sys.one("SELECT id FROM ral_budget WHERE period='Aumenti coo'")["id"]
    b2 = db.sys.one("SELECT id FROM ral_budget WHERE period='Aumenti dir2'")["id"]
    with as_user("coo"):
        db.execute("INSERT INTO ral_proposal (person_id, budget_id, amount, effective_date, status) "
                   "VALUES (?,?, 1500, '2026-07-01', 'proposta')", (ids["Anna Alfa"], b1))
        db.execute("INSERT INTO ral_proposal (person_id, budget_id, amount, effective_date, status) "
                   "VALUES (?,?, 900, '2026-07-01', 'bozza')", (ids["Aldo Alfa"], b1))
    with as_user("dir2"):
        db.execute("INSERT INTO ral_proposal (person_id, budget_id, amount, effective_date, status) "
                   "VALUES (?,?, 2000, '2026-09-01', 'proposta')", (ids["Bruno Beta"], b2))
    html = hr_client.get("/comp/plan").text
    assert "Anna Alfa" in html and "Bruno Beta" in html and "Aldo Alfa" not in html   # la bozza non c'è
    assert "Aumenti coo" in html and "Aumenti dir2" in html and ">coo<" in html and ">dir2<" in html
    assert "2 proposte" in html and "variazione totale +€ 3.500" in html
    assert "€ 31.500" in html and "€ 42.000" in html          # nuove RAL
    assert 'name="budget_id"' not in html and "/update" not in html and "/status" not in html
    assert "Richieste in attesa" in html
    html = hr_client.get(f"/comp/plan?director={dir2}").text
    assert "Bruno Beta" in html and "Anna Alfa" not in html and "1 proposte" in html
    # il director: selettore dei budget, bozze e azioni come prima
    html = client.get("/comp/plan").text
    assert 'name="budget_id"' in html and "Aldo Alfa" in html and "Invia a HR" in html
    assert "Bruno Beta" not in html and "Richieste in attesa" not in html


def _assess(uid_name, pid, box):
    with as_user(uid_name):
        db.execute("INSERT INTO ninebox_assessment (person_id, eval_date, role_type, seniority, raw_perf, raw_pot, "
                   "adj_perf, adj_pot, perf_level, pot_level, box_number, weights_snapshot, answers) "
                   "VALUES (?, '2026-01-01', 'ic', 'mid', 2, 2, 2, 2, 'med', 'med', ?, '{}', '{}')", (pid, box))


def test_ninebox_filtri_e_avvio_solo_per_i_director(client, client2, hr_client):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    _assess("coo", ids["Anna Alfa"], 9)
    _assess("dir2", ids["Bruno Beta"], 5)
    html = hr_client.get("/ninebox").text
    assert "Anna" in html and "Bruno" in html and 'name="director"' in html and 'name="team"' in html
    assert "Avvia" not in html and "/ninebox/start/" not in html
    assert "Alfa · coo" in html and "Beta · dir2" in html          # team con il director nel filtro
    html = hr_client.get(f"/ninebox?director={dir2}").text
    assert "Bruno" in html and "Anna" not in html and "filtro attivo: 1 valutate, 1 mai valutate" in html
    html = hr_client.get(f"/ninebox?team={t1}").text
    assert "Anna" in html and "Bruno" not in html
    html = hr_client.get(f"/ninebox?team={t1}&director={dir2}").text   # cumulabili: nessuno
    assert "Anna" not in html and "Bruno" not in html and "0 valutate, 0 mai valutate" in html
    # il director: filtro team, niente director, avvio presente
    html = client.get("/ninebox").text
    assert 'name="team"' in html and 'name="director"' not in html and "Avvia" in html
    assert "Bruno" not in html and "Alfa · coo" not in html and ">Alfa<" in html.replace("> Alfa<", ">Alfa<")


def test_ninebox_densita_e_situazione(client, client2):
    t1, t2, ids, coo, dir2 = _seed(client, client2)
    for n in ("P1 Uno", "P2 Due", "P3 Tre"):
        client.post("/people", data={"full_name": n, "team_id": t1, "role_type": "ic"})
    pids = [r["id"] for r in db.sys.query("SELECT id FROM person WHERE full_name LIKE 'P_ %' OR full_name LIKE '% Alfa'")]
    assert len(pids) == 5
    for pid in pids[:4]:
        _assess("coo", pid, 5)
    html = client.get("/ninebox").text
    box5 = re.search(r'<div class="c9 pick"[^>]*data-box="5".*?</div>\s*</div>', html, re.S).group(0)
    assert box5.count("chip-person") == 4 and "persone</div>" not in box5     # fino a 4 nomi
    _assess("coo", pids[4], 5)
    html = client.get("/ninebox").text
    box5 = re.search(r'<div class="c9 pick"[^>]*data-box="5".*?</div>\s*</div>', html, re.S).group(0)
    assert "chip-person" not in box5 and "<strong>5</strong> persone" in box5   # oltre: solo il totale
    # Situazione: vuota di default, le righe ci sono ma nascoste, pulsante con il totale
    assert 'id="sit-table" hidden' in html and html.count('class="sit-row" data-box="5" hidden') == 5
    assert "Mostra tutte (5)" in html and "Seleziona una casella" in html
