"""E2E del listino: codici, platea, parametri, calcolo via HTTP."""
import re

from app import db


def _profilo(client, code, description="Profilo", sort_order=0):
    client.post("/settings/listino", data={"code": code, "description": description, "sort_order": sort_order})
    return db.one("SELECT id FROM listino_profile WHERE code=?", (code.upper(),))["id"]


def _persona(client, name, team_id=None, ral=None, listino_profile_id=None, role_type="ic"):
    data = {"full_name": name, "role_type": role_type, "ref_date": "2025-01-01"}
    if team_id:
        data["team_id"] = str(team_id)
    if ral is not None:
        data["ral"] = str(ral)
    if listino_profile_id:
        data["listino_profile_id"] = str(listino_profile_id)
    client.post("/people", data=data)
    return db.one("SELECT id FROM person WHERE full_name=?", (name,))["id"]


def _team(name="Tech"):
    return db.execute("INSERT INTO team (name) VALUES (?)", (name,))


def _codice_corrente(pid):
    return db.one("SELECT listino_profile_id FROM person_assignment WHERE person_id=? "
                  "AND end_date IS NULL AND voided=0", (pid,))["listino_profile_id"]


def _costi(html):
    return re.findall(r"€ ([\d.]+,\d\d)", html)


def test_pagina_senza_codici(client):
    tid = _team()
    _persona(client, "Senza Codice", tid, 40000)
    _persona(client, "Senza Team")
    r = client.get("/comp/listino?anno=2026")
    assert r.status_code == 200
    assert "Senza codice (1)" in r.text and "Senza Codice" in r.text
    assert "Nessuna assegnazione corrente ha un codice" in r.text
    assert "Senza team, quindi senza codice" in r.text and "Senza Team" in r.text


def test_censimento_con_codice_e_senza(client):
    tid, lp = _team(), _profilo(client, "ge040", "Consultant PM")
    con = _persona(client, "Con Codice", tid, 50000, lp)
    senza = _persona(client, "Senza Codice", tid, 50000)
    assert _codice_corrente(con) == lp
    assert _codice_corrente(senza) is None


def test_esempio_di_riferimento(client):
    """RAL 50.000 nel 2026 con i default: 253 lavorabili, 193,5 fatturabili, 374,68 €/gg."""
    tid, lp = _team(), _profilo(client, "GE040", "Consultant PM")
    _persona(client, "Anna Rossi", tid, 50000, lp)
    html = client.get("/comp/listino?anno=2026").text
    assert "374,68" in html and "193,5" in html and "253,0 lavorabili" in html


def test_codice_inline_aggiorna_solo_la_corrente(client):
    tid, lp = _team(), _profilo(client, "PS010", "Professional Service")
    pid = _persona(client, "Bruno Verdi", tid, 60000)
    client.post(f"/people/{pid}/assignment", data={"team_id": str(tid), "role_type": "tl", "start_date": "2026-01-01"})
    r = client.post(f"/comp/listino/person/{pid}/code", data={"listino_profile_id": str(lp), "anno": "2026"})
    assert r.status_code == 200 and "PS010" in r.text and "Bruno Verdi" in r.text
    rows = db.query("SELECT listino_profile_id FROM person_assignment WHERE person_id=? ORDER BY start_date", (pid,))
    assert [x["listino_profile_id"] for x in rows] == [None, lp]
    client.post(f"/comp/listino/person/{pid}/code", data={"listino_profile_id": "", "anno": "2026"})
    assert _codice_corrente(pid) is None
    orfano = _persona(client, "Senza Team")
    assert client.post(f"/comp/listino/person/{orfano}/code", data={"listino_profile_id": str(lp)}).status_code == 400
    assert client.post(f"/comp/listino/person/{pid}/code", data={"listino_profile_id": "9999"}).status_code == 400


def test_nuova_assegnazione_porta_il_codice_e_correzione(client):
    tid = _team()
    a, b = _profilo(client, "A1", "Uno"), _profilo(client, "B2", "Due")
    pid = _persona(client, "Anna Rossi", tid, 50000, a)
    client.post(f"/people/{pid}/assignment", data={"team_id": str(tid), "role_type": "tl",
                                                   "start_date": "2026-01-01", "listino_profile_id": str(b)})
    rows = db.query("SELECT id, listino_profile_id, end_date FROM person_assignment WHERE person_id=? ORDER BY start_date", (pid,))
    assert [x["listino_profile_id"] for x in rows] == [a, b] and rows[0]["end_date"] is not None
    client.post(f"/people/{pid}/assignment/{rows[1]['id']}/update",
                data={"team_id": str(tid), "role_type": "tl", "start_date": "2026-01-01", "listino_profile_id": str(a)})
    assert _codice_corrente(pid) == a
    card = client.get(f"/people/{pid}").text
    assert "listino A1" in card and "Codice listino" in card


def test_salva_predefiniti(client):
    ok = {"anno": "2026", "oneri_mult": "1.41", "premi_pct": "0", "altri_costi": "2000", "festivita_gg": "",
          "festivita_extra_gg": "1", "ferie_gg": "30", "malattia_gg": "5", "formazione_pct": "5",
          "interne_pct": "5", "saturazione_pct": "100"}
    r = client.post("/comp/listino/defaults", data=ok)
    assert r.status_code == 200 and "Parametri salvati" in r.text
    assert db.get_meta("listino_ferie_gg") == "30" and db.get_meta("listino_festivita_gg") == ""
    assert 'name="ferie_gg" value="30"' in r.text
    r = client.post("/comp/listino/defaults", data={**ok, "oneri_mult": "abc", "ferie_gg": "31"})
    assert "Dati non validi" in r.text and db.get_meta("listino_ferie_gg") == "30"


def test_simulate_rispetta_i_parametri(client):
    tid, lp = _team(), _profilo(client, "GE040")
    _persona(client, "Anna Rossi", tid, 50000, lp)
    pieno = client.post("/comp/listino/simulate", data={"anno": "2026", "saturazione_pct": "100"}).text
    mezzo = client.post("/comp/listino/simulate", data={"anno": "2026", "saturazione_pct": "50"}).text
    assert "374,68" in pieno and "749,35" in mezzo
    assert "<button" not in pieno and "<select" not in pieno  # il frammento non ha controlli


def test_settings_listino(client):
    lp = _profilo(client, "ge040", "Consultant PM")
    html = client.get("/settings?tab=listino").text
    assert "GE040" in html and "Consultant PM" in html
    client.post(f"/settings/listino/{lp}/update", data={"description": "Consultant Project Manager", "sort_order": 5})
    row = db.one("SELECT * FROM listino_profile WHERE id=?", (lp,))
    assert row["code"] == "GE040" and row["description"] == "Consultant Project Manager" and row["sort_order"] == 5
    tid = _team()
    pid = _persona(client, "Anna Rossi", tid, 50000, lp)
    client.post(f"/settings/listino/{lp}/toggle")
    assert db.one("SELECT active FROM listino_profile WHERE id=?", (lp,))["active"] == 0
    page = client.get("/comp/listino?anno=2026").text
    assert "(disattivato)" in page and "374,68" in page  # resta sulla persona e nel listino
    assert _codice_corrente(pid) == lp
    r = client.post("/settings/listino", data={"code": "", "description": "x"})
    assert "Dati non validi" in r.text


def test_senza_ral_elencata_ma_esclusa(client):
    tid, lp = _team(), _profilo(client, "GE040")
    _persona(client, "Con Ral", tid, 50000, lp)
    _persona(client, "Senza Ral", tid, None, lp)
    html = client.get("/comp/listino?anno=2026").text
    assert "RAL mancante" in html and "Senza Ral" in html
    assert "1 persona con codice ma senza RAL" in html
    assert "1 escl." in html
    assert "374,68" in html


def test_part_time_da_employment(client):
    tid, lp = _team(), _profilo(client, "GE040")
    from app import db

    pid = _persona(client, "Anna Rossi", tid, 50000, lp)
    db.execute("INSERT INTO employment (person_id, livello, part_time_pct, start_date) "   # il contratto lo scrive HR (0.39)
               "VALUES (?, 'impiegato', 50, '2026-01-01')", (pid,))
    html = client.post("/comp/listino/simulate", data={"anno": "2026"}).text
    assert "96,8" in html and "749,35" in html  # metà giorni, costo/gg doppio


def test_anno_bisestile_e_override_festivita(client):
    html = client.post("/comp/listino/simulate", data={"anno": "2028", "festivita_gg": ""}).text
    assert "366 giorni − 106 weekend" in html and "dal calendario" in html
    html = client.post("/comp/listino/simulate", data={"anno": "2028", "festivita_gg": "10"}).text
    assert "− 11,0 festività (impostate)" in html


def test_tariffa_e_scostamento(client):
    tid = _team()
    client.post("/settings/listino", data={"code": "GE040", "description": "Consultant PM", "day_rate": "450"})
    lp = db.one("SELECT * FROM listino_profile WHERE code='GE040'")
    assert lp["day_rate"] == 450
    senza = _profilo(client, "PS010", "Professional Service")
    _persona(client, "Anna Rossi", tid, 50000, lp["id"])
    _persona(client, "Bruno Verdi", tid, 50000, senza)
    html = client.get("/comp/listino?anno=2026").text
    assert "€ 450" in html and "+€ 75,32" in html and "(+16,7%)" in html
    assert "Per i codici senza tariffa non c'è confronto" in html
    assert "sopra listino" not in html
    # tariffa sotto il costo: delta negativo e badge sul max
    client.post(f"/settings/listino/{lp['id']}/update", data={"description": "Consultant PM", "day_rate": "300"})
    html = client.get("/comp/listino?anno=2026").text
    assert "−€ 74,68" in html and "(−24,9%)" in html and "sopra listino" in html
    # tariffa vuota la toglie; non numerica → errore
    client.post(f"/settings/listino/{lp['id']}/update", data={"description": "Consultant PM", "day_rate": ""})
    assert db.one("SELECT day_rate FROM listino_profile WHERE id=?", (lp["id"],))["day_rate"] is None
    r = client.post(f"/settings/listino/{lp['id']}/update", data={"description": "Consultant PM", "day_rate": "abc"})
    assert "Dati non validi" in r.text


def test_produttivita_per_persona(client):
    tid, lp = _team(), _profilo(client, "GE040")
    pid = _persona(client, "Anna Rossi", tid, 50000, lp)
    altro = _persona(client, "Bruno Verdi", tid, 50000, lp)
    # saturazione 50 solo per Anna: i suoi giorni si dimezzano, Bruno resta al predefinito
    r = client.post(f"/comp/listino/person/{pid}/prod", data={"pp_saturazione_pct": "50", "anno": "2026"})
    assert r.status_code == 200 and "749,35" in r.text and "374,68" in r.text and "pers." in r.text
    row = db.one("SELECT * FROM listino_person_param WHERE person_id=?", (pid,))
    assert row["saturazione_pct"] == 50 and row["formazione_pct"] is None
    # blended ora diverso dalla media: stessi costi, giorni diversi
    assert "€ 562,02" in r.text  # media semplice (374,68 + 749,35) / 2
    assert "€ 499,57" in r.text  # blended 145.000 / 290,25
    # un campo alla volta: aggiornare la formazione non tocca la saturazione
    client.post(f"/comp/listino/person/{pid}/prod", data={"pp_formazione_pct": "10", "anno": "2026"})
    row = db.one("SELECT * FROM listino_person_param WHERE person_id=?", (pid,))
    assert row["saturazione_pct"] == 50 and row["formazione_pct"] == 10
    # saturazione oltre il 100 (MLO): ammessa fino a 200, i giorni crescono
    r = client.post(f"/comp/listino/person/{pid}/prod", data={"pp_saturazione_pct": "105", "anno": "2026"})
    assert db.one("SELECT saturazione_pct FROM listino_person_param WHERE person_id=?", (pid,))["saturazione_pct"] == 105
    assert "191,9" in r.text  # 215 × (100 − 10 − 5) × 105 / 10000
    client.post(f"/comp/listino/person/{pid}/prod", data={"pp_saturazione_pct": "50", "anno": "2026"})
    # valore non valido: ignorato con avviso, non azzera
    r = client.post(f"/comp/listino/person/{pid}/prod", data={"pp_saturazione_pct": "250", "anno": "2026"})
    assert db.one("SELECT saturazione_pct FROM listino_person_param WHERE person_id=?", (pid,))["saturazione_pct"] == 50
    assert "Valore non valido per Anna Rossi" in r.text and "saturazione" in r.text
    # vuoto = torna al globale; tutti vuoti = riga sparita
    client.post(f"/comp/listino/person/{pid}/prod", data={"pp_saturazione_pct": "", "pp_formazione_pct": "", "anno": "2026"})
    assert db.one("SELECT * FROM listino_person_param WHERE person_id=?", (pid,)) is None
    html = client.get("/comp/listino?anno=2026").text
    assert "pers." not in html and 'placeholder="5"' in html
    assert client.post("/comp/listino/person/9999/prod", data={"pp_saturazione_pct": "50"}).status_code == 404
    # la cancellazione della persona porta via anche i suoi parametri
    client.post(f"/comp/listino/person/{altro}/prod", data={"pp_interne_pct": "20"})
    client.post(f"/people/{altro}/delete", data={"confirm_name": "Bruno Verdi"})
    assert db.one("SELECT * FROM listino_person_param WHERE person_id=?", (altro,)) is None
