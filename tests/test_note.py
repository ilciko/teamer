"""Le note 1:1 si riaprono, si correggono e si eliminano."""
from app import db


def _persona(nome="Nota Test"):
    return db.execute("INSERT INTO person (full_name) VALUES (?)", (nome,))


def _crea_nota(client, pid, titolo, testo, azione=None):
    data = {"person_id": pid, "note_date": "2026-09-08", "type": "1:1",
            "title": titolo, "body": testo}
    if azione:
        data |= {"action_desc": azione, "action_due": "2026-10-01"}
    client.post("/notes", data=data)
    return db.one("SELECT id FROM meeting_note WHERE person_id=? ORDER BY id DESC", (pid,))["id"]


def test_form_di_modifica_precompilato(client):
    """Riaprire una nota mostra il testo che c'è già, pronto da completare."""
    pid = _persona()
    nid = _crea_nota(client, pid, "Primo giro", "appunti presi di corsa")
    html = client.get(f"/notes/{nid}/modifica").text
    assert "appunti presi di corsa" in html and "Primo giro" in html


def test_modifica_riallinea_la_ricerca(client):
    """Il trigger FTS meeting_note_au deve seguire la correzione."""
    pid = _persona()
    nid = _crea_nota(client, pid, "Giro", "parlato di rubiera")
    client.post(f"/notes/{nid}", data={
        "person_id": pid, "note_date": "2026-09-08", "type": "1:1",
        "title": "Giro", "body": "parlato di sassuolo"})

    assert db.one("SELECT updated_at FROM meeting_note WHERE id=?", (nid,))["updated_at"]
    assert "sassuolo" in client.get("/notes?q=sassuolo").text
    trovate = db.query("SELECT rowid FROM meeting_note_fts WHERE meeting_note_fts MATCH 'rubiera'")
    assert trovate == []


def test_eliminazione_lascia_vivere_gli_impegni(client):
    """La nota sparisce; l'impegno preso resta, scollegato."""
    pid = _persona()
    nid = _crea_nota(client, pid, "Con azione", "testo", azione="richiamare HR")

    aid = db.one("SELECT id FROM action_item WHERE meeting_note_id=?", (nid,))["id"]
    r = client.post(f"/notes/{nid}/delete")
    assert r.status_code == 200

    assert db.one("SELECT id FROM meeting_note WHERE id=?", (nid,)) is None
    assert db.query("SELECT rowid FROM meeting_note_fts WHERE meeting_note_fts MATCH 'testo'") == []
    azione = db.one("SELECT * FROM action_item WHERE id=?", (aid,))
    assert azione is not None and azione["meeting_note_id"] is None


def test_annulla_torna_alla_riga(client):
    """Il pulsante Annulla ricarica la riga in sola lettura, senza toccare i dati."""
    pid = _persona()
    nid = _crea_nota(client, pid, "Titolo", "corpo")
    html = client.get(f"/notes/{nid}/riga").text
    assert "corpo" in html and "<form" not in html


def test_nota_inesistente_non_e_un_500(client):
    assert client.get("/notes/9999/modifica").status_code == 404


def _crea_nota_il(client, pid, data, titolo):
    client.post("/notes", data={"person_id": pid, "note_date": data, "type": "1:1",
                                "title": titolo, "body": f"corpo {titolo}"})
    return db.one("SELECT id FROM meeting_note WHERE person_id=? ORDER BY id DESC", (pid,))["id"]


def test_archiviazione_per_selezione(client):
    """Le archiviate spariscono da lista e ricerca, il toggle le riporta, il ripristino le riattiva."""
    pid = _persona()
    vecchia = _crea_nota_il(client, pid, "2024-01-10", "Vecchiume")
    altra = _crea_nota_il(client, pid, "2024-02-10", "Altrovecchio")
    tenuta = _crea_nota_il(client, pid, "2026-09-01", "Attuale")

    r = client.post("/notes/archivia", data={"ids": [vecchia, altra], "f_person_id": str(pid)})
    assert r.status_code == 200

    lista = client.get(f"/notes?person_id={pid}").text
    assert "Attuale" in lista and "Vecchiume" not in lista and "Altrovecchio" not in lista
    assert "corpo Vecchiume" not in client.get("/notes?q=Vecchiume").text
    assert "corpo Vecchiume" in client.get("/notes?q=Vecchiume&archived=1").text

    con_archivio = client.get(f"/notes?person_id={pid}&archived=1").text
    assert "Vecchiume" in con_archivio and "archiviata il" in con_archivio
    assert "Ripristina selezionate" in con_archivio

    # archiviare non è correggere: updated_at resta com'era
    assert db.one("SELECT updated_at FROM meeting_note WHERE id=?", (vecchia,))["updated_at"] is None

    client.post("/notes/ripristina", data={"ids": [vecchia], "f_archived": "1"})
    assert "Vecchiume" in client.get(f"/notes?person_id={pid}").text
    assert db.one("SELECT archived_at FROM meeting_note WHERE id=?", (tenuta,))["archived_at"] is None


def test_archiviare_due_volte_non_sposta_la_data(client):
    pid = _persona()
    nid = _crea_nota_il(client, pid, "2025-05-05", "Una")
    client.post("/notes/archivia", data={"ids": [nid]})
    db.execute("UPDATE meeting_note SET archived_at='2025-06-01 10:00:00' WHERE id=?", (nid,))
    client.post("/notes/archivia", data={"ids": [nid]})
    assert db.one("SELECT archived_at FROM meeting_note WHERE id=?", (nid,))["archived_at"] \
        == "2025-06-01 10:00:00"


def test_selezione_vuota_non_fa_nulla(client):
    pid = _persona()
    _crea_nota_il(client, pid, "2025-05-05", "Intatta")
    assert client.post("/notes/archivia", data={}).status_code == 200
    assert db.one("SELECT COUNT(*) AS n FROM meeting_note WHERE archived_at IS NOT NULL")["n"] == 0


def test_report_globale_e_per_persona(client):
    """Globale senza persona, del singolo con persona; dal più recente; archiviate a richiesta."""
    anna = _persona("Anna Report")
    bruno = _persona("Bruno Report")
    _crea_nota_il(client, anna, "2025-03-01", "AnnaMarzo")
    _crea_nota_il(client, anna, "2026-03-01", "AnnaRecente")
    archiviata = _crea_nota_il(client, anna, "2024-03-01", "AnnaArchiviata")
    _crea_nota_il(client, bruno, "2025-06-01", "BrunoGiugno")
    client.post("/notes/archivia", data={"ids": [archiviata]})

    globale = client.get("/notes/report").text
    assert "tutto il team" in globale and "Bruno Report" in globale
    assert globale.index("AnnaRecente") < globale.index("BrunoGiugno") < globale.index("AnnaMarzo")
    assert "AnnaArchiviata" not in globale

    di_anna = client.get(f"/notes/report?person_id={anna}").text
    assert "Anna Report" in di_anna and "BrunoGiugno" not in di_anna

    con_archivio = client.get(f"/notes/report?person_id={anna}&archived=1").text
    assert "AnnaArchiviata" in con_archivio and "archiviata il" in con_archivio

    assert "Report di Anna Report" in client.get(f"/notes?person_id={anna}").text
    assert "Report globale" in client.get("/notes").text


def test_archiviate_fuori_da_dashboard_e_scheda(client):
    pid = _persona("Carla Archivio")
    nid = _crea_nota_il(client, pid, "2026-09-10", "DaNascondere")
    assert "DaNascondere" in client.get(f"/people/{pid}").text
    client.post("/notes/archivia", data={"ids": [nid]})
    assert "DaNascondere" not in client.get(f"/people/{pid}").text
    assert "DaNascondere" not in client.get("/").text
