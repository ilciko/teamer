"""Ogni entità ha la strada della correzione, non solo quella del cambiamento reale."""
from app import db


def _persona(nome="Correzione Test"):
    return db.execute("INSERT INTO person (full_name, status) VALUES (?, 'attivo')", (nome,))


def _ciclo(nome="Ciclo 2026", anno=2026):
    return db.execute("INSERT INTO review_cycle (name, year) VALUES (?,?)", (nome, anno))


# ---- 9-box ----

def test_ninebox_void_toglie_dalla_griglia(client):
    """La colonna voided esisteva ma nessuna route la scriveva."""
    pid = _persona()
    aid = db.execute(
        """INSERT INTO ninebox_assessment (person_id, eval_date, role_type, seniority,
           raw_perf, raw_pot, adj_perf, adj_pot, perf_level, pot_level, box_number,
           weights_snapshot, answers)
           VALUES (?, '2026-01-01', 'ic', 'senior', 3, 3, 3, 3, 'high', 'high', 9, '{}', '[]')""",
        (pid,))

    assert str(pid) in client.get("/ninebox").text
    client.post(f"/ninebox/{aid}/void", data={"reason": "persona sbagliata"})

    riga = db.one("SELECT voided, void_reason FROM ninebox_assessment WHERE id=?", (aid,))
    assert riga["voided"] == 1 and riga["void_reason"] == "persona sbagliata"
    # sparita dalla griglia: la home 9-box filtra voided=0
    assert db.query(
        "SELECT id FROM ninebox_assessment WHERE person_id=? AND voided=0", (pid,)) == []


# ---- obiettivi ----

def test_obiettivo_si_corregge_senza_riscriverlo(client):
    pid, cid = _persona(), _ciclo()
    gid = db.execute(
        "INSERT INTO goal (person_id, cycle_id, category, description, weight_pct) "
        "VALUES (?,?,'professionale','Migliorra la documentazione',5)", (pid, cid))

    client.post(f"/cycles/{cid}/person/{pid}/goal/{gid}/update", data={
        "description": "Migliorare la documentazione", "category": "professionale",
        "weight_pct": 50})

    g = db.one("SELECT * FROM goal WHERE id=?", (gid,))
    assert g["description"] == "Migliorare la documentazione"
    assert g["weight_pct"] == 50 and g["voided"] == 0


def test_void_obiettivo_non_lascia_punteggi_orfani(client):
    pid, cid = _persona(), _ciclo()
    gid = db.execute(
        "INSERT INTO goal (person_id, cycle_id, category, description, weight_pct) "
        "VALUES (?,?,'professionale','Da annullare',50)", (pid, cid))
    rid = db.execute(
        "INSERT INTO performance_review (person_id, cycle_id) VALUES (?,?)", (pid, cid))
    db.execute("INSERT INTO goal_review (goal_id, review_id, tl_score) VALUES (?,?,4)", (gid, rid))

    client.post(f"/cycles/{cid}/person/{pid}/goal/{gid}/void", data={"reason": "duplicato"})

    assert db.one("SELECT void_reason FROM goal WHERE id=?", (gid,))["void_reason"] == "duplicato"
    assert db.query("SELECT id FROM goal_review WHERE goal_id=?", (gid,)) == []


def test_void_obiettivo_non_tocca_altre_persone(client):
    """Le guardie person_id/cycle_id: WHERE id=? da solo non basta."""
    altro_pid, cid = _persona("Altro"), _ciclo()
    gid = db.execute(
        "INSERT INTO goal (person_id, cycle_id, category, description, weight_pct) "
        "VALUES (?,?,'professionale','Non toccare',50)", (altro_pid, cid))

    client.post(f"/cycles/{cid}/person/{_persona('Estraneo')}/goal/{gid}/void")

    assert db.one("SELECT voided FROM goal WHERE id=?", (gid,))["voided"] == 0


# ---- review ----

def test_review_annullata_e_ricominciabile(client):
    """Il void era impossibile: UNIQUE(person_id, cycle_id) bloccava il reinserimento."""
    pid, cid = _persona(), _ciclo()
    client.post(f"/cycles/{cid}/person/{pid}/review", data={"overall_rating": "3"})
    rid = db.one("SELECT id FROM performance_review WHERE person_id=?", (pid,))["id"]

    client.post(f"/cycles/{cid}/person/{pid}/review/void", data={"reason": "persona sbagliata"})
    assert db.one("SELECT voided FROM performance_review WHERE id=?", (rid,))["voided"] == 1

    # ricominciare da capo non deve dare IntegrityError
    client.post(f"/cycles/{cid}/person/{pid}/review", data={"overall_rating": "4"})
    vive = db.query(
        "SELECT id, overall_rating FROM performance_review WHERE person_id=? AND voided=0", (pid,))
    assert len(vive) == 1 and vive[0]["overall_rating"] == 4


def test_riapertura_review_e_esplicita(client):
    """La de-finalizzazione cambia il montepremi: deve essere una scelta."""
    pid, cid = _persona(), _ciclo()
    client.post(f"/cycles/{cid}/person/{pid}/review", data={"overall_rating": "3", "finalize": "1"})
    assert db.one("SELECT status FROM performance_review WHERE person_id=?",
                  (pid,))["status"] == "finalizzata"

    client.post(f"/cycles/{cid}/person/{pid}/review/riapri")
    assert db.one("SELECT status FROM performance_review WHERE person_id=?",
                  (pid,))["status"] == "bozza"


# ---- benessere ----

def test_benessere_si_azzera(client):
    pid, cid = _persona(), _ciclo()
    client.post(f"/cycles/{cid}/person/{pid}/wellbeing", data={"tl_comment": "compilato per errore"})
    assert db.query("SELECT id FROM wellbeing_entry") != []

    client.post(f"/cycles/{cid}/person/{pid}/wellbeing/azzera")
    assert db.query("SELECT id FROM wellbeing_entry") == []


# ---- ciclo ----

def test_ciclo_si_riapre_e_si_rinomina(client):
    cid = _ciclo("Cilco 2026", 2026)
    client.post(f"/cycles/{cid}/close")
    assert db.one("SELECT status FROM review_cycle WHERE id=?", (cid,))["status"] == "chiuso"

    client.post(f"/cycles/{cid}/riapri")
    client.post(f"/cycles/{cid}/update", data={"name": "Ciclo 2026", "year": 2027})
    c = db.one("SELECT * FROM review_cycle WHERE id=?", (cid,))
    assert c["status"] == "aperto" and c["name"] == "Ciclo 2026" and c["year"] == 2027


# ---- allegati ----

def test_allegato_si_elimina(client):
    pid = _persona()
    aid = db.execute(
        "INSERT INTO attachment (person_id, filename, content) VALUES (?, 'sbagliato.pdf', X'00')",
        (pid,))
    client.post(f"/people/{pid}/attachment/{aid}/delete")
    assert db.one("SELECT id FROM attachment WHERE id=?", (aid,)) is None


# ---- salvataggi non distruttivi (quattro form nella stessa pagina) ----

def test_salvataggio_htmx_non_ricarica_la_pagina(client):
    """Salvare la review non deve restituire un redirect: gli altri form della
    pagina hanno testo digitato che il ricaricamento butterebbe via."""
    pid, cid = _persona(), _ciclo()
    r = client.post(f"/cycles/{cid}/person/{pid}/review",
                    data={"overall_tl_comment": "un commento lungo"},
                    headers={"HX-Request": "true"}, follow_redirects=False)

    assert r.status_code == 200 and "Salvato alle" in r.text
    assert db.one("SELECT overall_tl_comment FROM performance_review WHERE person_id=?",
                  (pid,))["overall_tl_comment"] == "un commento lungo"


def test_finalizza_via_htmx_ricarica_comunque(client):
    """La finalizzazione cambia badge e pulsanti: lì il redirect serve."""
    pid, cid = _persona(), _ciclo()
    r = client.post(f"/cycles/{cid}/person/{pid}/review",
                    data={"overall_rating": "4", "finalize": "1"},
                    headers={"HX-Request": "true"}, follow_redirects=False)

    assert r.status_code == 302
    assert db.one("SELECT status FROM performance_review WHERE person_id=?",
                  (pid,))["status"] == "finalizzata"


def test_bozza_via_htmx_non_finalizza(client):
    """La finalizzazione non passa da htmx: htmx non manda il valore del bottone.

    Verificato nel browser: con hx-post sul form, finalize non arriva affatto.
    """
    pid, cid = _persona(), _ciclo()
    # "Salva bozza" invia finalize=""
    client.post(f"/cycles/{cid}/person/{pid}/review", data={"overall_rating": "3", "finalize": ""},
                headers={"HX-Request": "true"})
    assert db.one("SELECT status FROM performance_review WHERE person_id=?",
                  (pid,))["status"] == "bozza"


def test_punteggi_htmx_restituisce_i_totali_aggiornati(client):
    """Il frammento porta i totali ricalcolati, senza il bottone di submit."""
    pid = _persona()
    prev, cur = _ciclo("2025", 2025), _ciclo("2026", 2026)
    gid = db.execute(
        "INSERT INTO goal (person_id, cycle_id, category, description, weight_pct) "
        "VALUES (?,?,'professionale','Obiettivo',100)", (pid, prev))

    r = client.post(f"/cycles/{cur}/person/{pid}/goal-scores",
                    data={f"tl_{gid}": "5"}, headers={"HX-Request": "true"},
                    follow_redirects=False)

    assert r.status_code == 200
    assert "Salvato alle" in r.text and "TL professionale: 5" in r.text
    assert "<button" not in r.text  # il submit resta fuori dallo swap
