"""E2E del listino: codici, platea, parametri, calcolo via HTTP. Dalla 0.41 codici e parametri sono
aziendali (Azienda → Listino, di HR): i director li leggono e assegnano codice e produttività."""
import re

from app import db


def _profilo(client, code, description="Profilo", sort_order=0, day_rate=None):
    """Codice di listino aziendale (come lo crea HR in Azienda → Listino)."""
    db.sys.execute("INSERT INTO listino_profile (code, description, sort_order, day_rate) VALUES (?,?,?,?) "
                   "ON CONFLICT(code) DO UPDATE SET description=excluded.description",
                   (code.upper(), description, sort_order, day_rate))
    return db.sys.one("SELECT id FROM listino_profile WHERE code=?", (code.upper(),))["id"]


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
    r = client.get("/comp/listino")
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
    """RAL 50.000 con i default (anno convenzionale): 250 lavorabili, 190,8 fatturabili, 379,98 €/gg."""
    tid, lp = _team(), _profilo(client, "GE040", "Consultant PM")
    _persona(client, "Anna Rossi", tid, 50000, lp)
    html = client.get("/comp/listino").text
    assert "379,98" in html and "190,8" in html and "250,0 lavorabili" in html


def test_codice_inline_aggiorna_solo_la_corrente(client):
    tid, lp = _team(), _profilo(client, "PS010", "Professional Service")
    pid = _persona(client, "Bruno Verdi", tid, 60000)
    client.post(f"/people/{pid}/assignment", data={"team_id": str(tid), "role_type": "tl", "start_date": "2026-01-01"})
    r = client.post(f"/comp/listino/person/{pid}/code", data={"listino_profile_id": str(lp)})
    assert r.status_code == 200 and "PS010" in r.text and "Bruno Verdi" in r.text
    rows = db.query("SELECT listino_profile_id FROM person_assignment WHERE person_id=? ORDER BY start_date", (pid,))
    assert [x["listino_profile_id"] for x in rows] == [None, lp]
    client.post(f"/comp/listino/person/{pid}/code", data={"listino_profile_id": ""})
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


def test_parametri_aziendali(client, hr_client):
    ok = {"oneri_mult": "1.41", "premi_pct": "0", "altri_costi": "2000", "festivita_gg": "10",
          "festivita_extra_gg": "1", "ferie_gg": "31", "malattia_gg": "5", "formazione_pct": "5",
          "interne_pct": "5", "saturazione_pct": "100"}
    r = hr_client.post("/azienda/listino/parametri", data=ok, follow_redirects=False)
    assert r.headers["location"] == "/azienda?tab=listino&saved=1"
    assert db.get_meta("listino_ferie_gg") == "31"
    assert "ferie e permessi 31 gg" in client.get("/comp/listino").text           # il director legge i nuovi
    r = hr_client.post("/azienda/listino/parametri", data={**ok, "oneri_mult": "abc", "ferie_gg": "30"}, follow_redirects=False)
    assert r.headers["location"].endswith("saved=err") and db.get_meta("listino_ferie_gg") == "31"
    assert client.post("/azienda/listino/parametri", data=ok).status_code == 403   # il director no
    assert 'name="oneri_mult"' not in client.get("/comp/listino").text            # e non ha il form


def test_filtri_cumulabili(client):
    tid, lp = _team(), _profilo(client, "GE040")
    lp2 = _profilo(client, "PS010", "Professional")
    t2 = _team("Sales")
    _persona(client, "Anna Alfa", tid, 50000, lp)
    _persona(client, "Bice Beta", t2, 60000, lp2, role_type="tl")
    html = client.get("/comp/listino").text
    assert "Anna Alfa" in html and "Bice Beta" in html
    html = client.get(f"/comp/listino?team={tid}").text
    assert "Anna Alfa" in html and "Bice Beta" not in html and "Azzera" in html
    html = client.get("/comp/listino?codice=PS010").text
    assert "Bice Beta" in html and "Anna Alfa" not in html
    html = client.get("/comp/listino?codice=PS010&ruolo=ic").text                  # cumulabili: nessuno
    assert "Bice Beta" not in html and "Anna Alfa" not in html
    html = client.get(f"/comp/listino?ruolo=tl&team={t2}").text
    assert "Bice Beta" in html and "Anna Alfa" not in html


def test_codici_in_azienda(client, hr_client):
    r = hr_client.post("/azienda/listino", data={"code": "ge040", "description": "Consultant PM", "sort_order": 1},
                       follow_redirects=False)
    assert r.headers["location"] == "/azienda?tab=listino&saved=1"
    lp = db.sys.one("SELECT * FROM listino_profile WHERE code='GE040'")
    assert lp and lp["description"] == "Consultant PM"
    hr_client.post(f"/azienda/listino/{lp['id']}/update", data={"description": "Consultant Project Manager", "sort_order": 5})
    assert db.sys.one("SELECT description, sort_order FROM listino_profile WHERE id=?", (lp["id"],))["sort_order"] == 5
    assert "Consultant Project Manager" in hr_client.get("/azienda?tab=listino").text
    hr_client.post(f"/azienda/listino/{lp['id']}/toggle")
    assert db.sys.one("SELECT active FROM listino_profile WHERE id=?", (lp["id"],))["active"] == 0
    assert "Nessun codice di listino attivo" in client.get("/comp/listino").text
    r = hr_client.post("/azienda/listino", data={"code": "", "description": "x"}, follow_redirects=False)
    assert r.headers["location"].endswith("saved=err")
    # il director non scrive i codici: né dalla route né dal DB
    assert client.post("/azienda/listino", data={"code": "X", "description": "x"}).status_code == 403
    assert client.get("/settings?tab=listino").status_code == 200 and "Codici di listino" not in client.get("/settings?tab=listino").text
    import pytest
    with pytest.raises(db.sqlcipher.DatabaseError):
        db.execute("INSERT INTO listino_profile (code, description) VALUES ('X', 'x')")


def test_senza_ral_elencata_ma_esclusa(client):
    tid, lp = _team(), _profilo(client, "GE040")
    _persona(client, "Con Ral", tid, 50000, lp)
    _persona(client, "Senza Ral", tid, None, lp)
    html = client.get("/comp/listino").text
    assert "RAL mancante" in html and "Senza Ral" in html
    assert "1 persona con codice ma senza RAL" in html
    assert "1 escl." in html
    assert "379,98" in html


def test_part_time_da_employment(client):
    tid, lp = _team(), _profilo(client, "GE040")
    from app import db

    pid = _persona(client, "Anna Rossi", tid, 50000, lp)
    db.execute("INSERT INTO employment (person_id, livello, part_time_pct, start_date) "   # il contratto lo scrive HR (0.39)
               "VALUES (?, 'impiegato', 50, '2026-01-01')", (pid,))
    html = client.get("/comp/listino").text
    assert "95,4" in html and "759,96" in html  # metà giorni, costo/gg doppio


def test_giorni_fissi_nel_riepilogo(client):
    html = client.get("/comp/listino").text
    assert "365 giorni − 104 weekend − 11,0 festività = 250,0 lavorabili" in html


def test_tariffa_e_scostamento(client, hr_client):
    tid = _team()
    _profilo(client, "GE040", "Consultant PM", day_rate=450)
    lp = db.one("SELECT * FROM listino_profile WHERE code='GE040'")
    assert lp["day_rate"] == 450
    senza = _profilo(client, "PS010", "Professional Service")
    _persona(client, "Anna Rossi", tid, 50000, lp["id"])
    _persona(client, "Bruno Verdi", tid, 50000, senza)
    html = client.get("/comp/listino").text
    assert "€ 450" in html and "+€ 70,02" in html and "(+15,6%)" in html
    assert "Per i codici senza tariffa non c'è confronto" in html
    assert "sopra listino" not in html
    # tariffa sotto il costo: delta negativo e badge sul max
    db.sys.execute("UPDATE listino_profile SET day_rate=300 WHERE id=?", (lp["id"],))
    html = client.get("/comp/listino").text
    assert "−€ 79,98" in html and "(−26,7%)" in html and "sopra listino" in html
    # tariffa vuota la toglie; non numerica → errore
    db.sys.execute("UPDATE listino_profile SET day_rate=NULL WHERE id=?", (lp["id"],))
    assert db.one("SELECT day_rate FROM listino_profile WHERE id=?", (lp["id"],))["day_rate"] is None
    r = hr_client.post(f"/azienda/listino/{lp['id']}/update", data={"description": "Consultant PM", "day_rate": "abc"}, follow_redirects=False)
    assert r.headers["location"].endswith("saved=err") and "Dati non validi" in hr_client.get(r.headers["location"]).text


def test_produttivita_per_persona(client):
    tid, lp = _team(), _profilo(client, "GE040")
    pid = _persona(client, "Anna Rossi", tid, 50000, lp)
    altro = _persona(client, "Bruno Verdi", tid, 50000, lp)
    # saturazione 50 solo per Anna: i suoi giorni si dimezzano, Bruno resta al predefinito
    r = client.post(f"/comp/listino/person/{pid}/prod", data={"pp_saturazione_pct": "50"})
    assert r.status_code == 200 and "759,96" in r.text and "379,98" in r.text and "pers." in r.text
    row = db.one("SELECT * FROM listino_person_param WHERE person_id=?", (pid,))
    assert row["saturazione_pct"] == 50 and row["formazione_pct"] is None
    # blended ora diverso dalla media: stessi costi, giorni diversi
    assert "€ 569,97" in r.text  # media semplice (379,98 + 759,96) / 2
    assert "€ 506,64" in r.text  # blended 145.000 / 286,2
    # un campo alla volta: aggiornare la formazione non tocca la saturazione
    client.post(f"/comp/listino/person/{pid}/prod", data={"pp_formazione_pct": "10"})
    row = db.one("SELECT * FROM listino_person_param WHERE person_id=?", (pid,))
    assert row["saturazione_pct"] == 50 and row["formazione_pct"] == 10
    # saturazione oltre il 100 (MLO): ammessa fino a 200, i giorni crescono
    r = client.post(f"/comp/listino/person/{pid}/prod", data={"pp_saturazione_pct": "105"})
    assert db.one("SELECT saturazione_pct FROM listino_person_param WHERE person_id=?", (pid,))["saturazione_pct"] == 105
    assert "189,2" in r.text  # 212 × (100 − 10 − 5) × 105 / 10000
    client.post(f"/comp/listino/person/{pid}/prod", data={"pp_saturazione_pct": "50"})
    # valore non valido: ignorato con avviso, non azzera
    r = client.post(f"/comp/listino/person/{pid}/prod", data={"pp_saturazione_pct": "250"})
    assert db.one("SELECT saturazione_pct FROM listino_person_param WHERE person_id=?", (pid,))["saturazione_pct"] == 50
    assert "Valore non valido per Anna Rossi" in r.text and "saturazione" in r.text
    # vuoto = torna al globale; tutti vuoti = riga sparita
    client.post(f"/comp/listino/person/{pid}/prod", data={"pp_saturazione_pct": "", "pp_formazione_pct": ""})
    assert db.one("SELECT * FROM listino_person_param WHERE person_id=?", (pid,)) is None
    html = client.get("/comp/listino").text
    assert "pers." not in html and 'placeholder="5"' in html
    assert client.post("/comp/listino/person/9999/prod", data={"pp_saturazione_pct": "50"}).status_code == 404
    # la cancellazione della persona porta via anche i suoi parametri
    client.post(f"/comp/listino/person/{altro}/prod", data={"pp_interne_pct": "20"})
    client.post(f"/people/{altro}/delete", data={"confirm_name": "Bruno Verdi"})
    assert db.one("SELECT * FROM listino_person_param WHERE person_id=?", (altro,)) is None
