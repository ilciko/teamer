"""E2E sulle route: i filtri "tutti" inviano il parametro vuoto, non assente."""
import pytest


@pytest.mark.parametrize("url", [
    "/comp/plan?budget_id=",
    "/comp/salary?budget_id=",
    "/comp/plan/report?budget_id=&status=proposta",
    "/comp/plan/report.xlsx?budget_id=&status=proposta",
    "/notes?person_id=",
    "/reports?team_id=",
    "/comp/listino?anno=",
    "/settings?tab=listino",
])
def test_filtro_vuoto_non_e_errore(client, url):
    """Un query param intero vuoto vale "nessun filtro": mai 422."""
    assert client.get(url).status_code == 200


def _ral(client, pid, amount, effective_date, change_type):
    return client.post(f"/people/{pid}/ral", data={
        "amount": amount, "effective_date": effective_date, "change_type": change_type})


def test_timeline_dopo_reinserimento(client, hr_client):
    """Annullare e reinserire una RAL non deve sfasare le variazioni mostrate (gli eventi li scrive HR, 0.39)."""
    from app import db

    pid = db.execute("INSERT INTO person (full_name) VALUES ('Timeline Test')")
    _ral(hr_client, pid, 39500, "2005-02-23", "assunzione")
    _ral(hr_client, pid, 44000, "2021-01-01", "promozione")
    _ral(hr_client, pid, 47500, "2022-01-01", "aumento")
    _ral(hr_client, pid, 48100, "2022-07-01", "adeguamento")

    eid = db.one("SELECT id FROM ral_event WHERE person_id=? AND effective_date='2022-01-01'",
                 (pid,))["id"]
    hr_client.post(f"/people/{pid}/ral/{eid}/void")
    _ral(hr_client, pid, 47500, "2022-01-01", "aumento")

    html = client.get(f"/people/{pid}").text
    assert "€ 3.500" in html and "€ -600" not in html
    # il delta salvato è ora corretto anche in DB (conta per il budget)
    rientro = db.one("SELECT delta FROM ral_event WHERE person_id=? AND voided=0 "
                     "AND effective_date='2022-01-01'", (pid,))
    assert rientro["delta"] == 3500


def test_piano_conferma_nuova_ral(client, hr_client):
    """Nel piano si digita la nuova RAL: la proposta salva la variazione."""
    from app import db

    pid = db.execute("INSERT INTO person (full_name) VALUES ('Proposta Test')")
    _ral(hr_client, pid, 40000, "2024-01-01", "assunzione")
    prop = db.execute(
        "INSERT INTO ral_proposal (person_id, amount, effective_date, status) "
        "VALUES (?, 1500, '2026-01-01', 'bozza')", (pid,))

    assert 'value="41500"' in client.get("/comp/plan").text
    client.post(f"/comp/plan/{prop}/update",
                data={"new_ral": 41800, "effective_date": "2026-01-01"})
    assert db.one("SELECT amount FROM ral_proposal WHERE id=?", (prop,))["amount"] == 1800


def test_censimento_neoassunto_parte_dall_assunzione(client):
    """Chi è assunto dopo la data di censimento non eredita la data di riferimento."""
    from app import db

    client.post("/people", data={
        "full_name": "Neo Assunta", "hire_date": "2026-06-01",
        "ref_date": "2025-01-01", "ral": "32000"})
    pid = db.one("SELECT id FROM person WHERE full_name='Neo Assunta'")["id"]
    ev = db.one("SELECT * FROM ral_event WHERE person_id=?", (pid,))
    assert ev["effective_date"] == "2026-06-01"

    # chi è assunto prima resta alla data di censimento: è la RAL vigente allora
    client.post("/people", data={
        "full_name": "Veterano", "hire_date": "2010-03-01",
        "ref_date": "2025-01-01", "ral": "45000"})
    vid = db.one("SELECT id FROM person WHERE full_name='Veterano'")["id"]
    assert db.one("SELECT * FROM ral_event WHERE person_id=?", (vid,))["effective_date"] == "2025-01-01"

    assert "01/06/2026" in client.get("/comp/salary").text


def test_soglie_anzianita_ral(client):
    """Le soglie arancio/rosso si configurano da Generale e colorano l'analisi salary."""
    from app import db

    pid = db.execute("INSERT INTO person (full_name) VALUES ('Ferma Da Anni')")
    db.execute("INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type) "
               "VALUES (?, '2015-01-01', 40000, 0, 'censimento')", (pid,))
    assert "txt-red" in client.get("/comp/salary").text

    # soglie assurde: nessuna evidenziazione
    r = client.post("/settings/general", data={
        "default_ccnl": "Metalmeccanici Confapi",
        "ral_stale_amber_years": "50", "ral_stale_red_years": "60"})
    assert r.status_code == 200 and db.get_meta("ral_stale_amber_years") == "50"
    html = client.get("/comp/salary").text
    assert "txt-red" not in html and "txt-amber" not in html

    # rosso non oltre l'arancio: nulla viene salvato
    client.post("/settings/general", data={
        "default_ccnl": "Altro CCNL",
        "ral_stale_amber_years": "4", "ral_stale_red_years": "2"})
    assert db.get_meta("ral_stale_amber_years") == "50"
    assert db.get_meta("default_ccnl") == "Metalmeccanici Confapi"


def test_report_include_chi_non_ha_data_di_assunzione(client):
    """Senza hire_date la persona spariva dal report: il monte RAL non tornava."""
    from app import db

    pid = db.execute("INSERT INTO person (full_name, hire_date) VALUES ('Con Data', '2026-01-01')")
    db.execute("INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type) "
               "VALUES (?, '2026-01-01', 40000, 0, 'assunzione')", (pid,))
    senza = db.execute("INSERT INTO person (full_name) VALUES ('Senza Data')")
    db.execute("INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type) "
               "VALUES (?, '2026-01-01', 35000, 0, 'censimento')", (senza,))

    html = client.get("/reports").text
    # il monte RAL corrente comprende entrambe: 40.000 + 35.000
    assert "75000" in html


def test_report_parte_dal_dato_e_le_esclusioni_lo_allargano(client):
    """L'analisi comincia dove il monte RAL è leggibile; escludere allarga indietro."""
    from app import db

    vecchia = db.execute(
        "INSERT INTO person (full_name, hire_date) VALUES ('Storica', '2020-01-01')")
    db.execute("INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type) "
               "VALUES (?, '2020-01-01', 40000, 0, 'assunzione')", (vecchia,))
    tardiva = db.execute(
        "INSERT INTO person (full_name, hire_date) VALUES ('Censita Tardi', '2021-01-01')")
    db.execute("INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type) "
               "VALUES (?, '2026-03-01', 45000, 0, 'censimento')", (tardiva,))

    html = client.get("/reports").text
    assert "L'analisi parte dal 01/03/2026, non ho dati precedenti." in html
    # gli addetti invece tengono tutta la storia: si ricostruiscono dalle assunzioni
    assert "01/2020" in html
    assert "prima RAL 01/03/2026" in html   # nel pannello esclusioni, per decidere

    # esclusa lei, il monte RAL è ricostruibile da quando c'è la prima
    client.post("/reports/exclusions", data={"include": [str(vecchia)]})
    assert db.one("SELECT report_excluded FROM person WHERE id=?", (tardiva,))["report_excluded"] == 1
    html = client.get("/reports").text
    assert "L'analisi parte dal 01/01/2020, non ho dati precedenti." in html
    assert "1 incluse, 1 escluse" in html
