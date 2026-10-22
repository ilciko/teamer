"""E2E su assunzioni a budget: panel del team e correzione delle posizioni."""


def _budget(client, period, year, cap=200000):
    from app import db

    client.post("/comp/hiring", data={"period": period, "year": year, "total_cap": cap})
    return db.one("SELECT id FROM hiring_budget WHERE period=?", (period,))["id"]


def _position(client, bid, title, team_id, ral=45000, start="2026-03-01"):
    from app import db

    client.post(f"/comp/hiring/{bid}/position", data={
        "title": title, "team_id": team_id, "role_type": "ic",
        "expected_ral": ral, "expected_start": start})
    return db.one("SELECT id FROM hiring_position WHERE title=?", (title,))["id"]


def _teams(client):
    from app import db

    client.post("/org/team", data={"name": "Alfa"})
    client.post("/org/team", data={"name": "Beta"})
    return (db.one("SELECT id FROM team WHERE name='Alfa'")["id"],
            db.one("SELECT id FROM team WHERE name='Beta'")["id"])


def test_navigazione_fra_team(client):
    """Le schede team si scorrono in ordine alfabetico, senza wrap-around."""
    alfa, beta = _teams(client)

    html_alfa = client.get(f"/org/team/{alfa}").text
    assert f'href="/org/team/{beta}"' in html_alfa   # Beta è il successivo
    assert "title=\"Precedente\"" not in html_alfa   # Alfa è il primo

    html_beta = client.get(f"/org/team/{beta}").text
    assert f'href="/org/team/{alfa}"' in html_beta
    assert "title=\"Prossimo\"" not in html_beta     # Beta è l'ultimo


def test_panel_assunzioni_del_team(client):
    """Il panel mostra solo le posizioni aperte del team, e il loro impegnato."""
    from app import db

    alfa, beta = _teams(client)
    bid = _budget(client, "Assunzioni 2026", 2026)
    hp = _position(client, bid, "Sviluppatore senior", alfa)

    html = client.get(f"/org/team/{alfa}").text
    assert "Sviluppatore senior" in html and "€ 45.000" in html
    assert "Sviluppatore senior" not in client.get(f"/org/team/{beta}").text

    # una posizione chiusa esce dal panel: non impegna più headcount
    pid = db.execute("INSERT INTO person (full_name) VALUES ('Assunta Uno')")
    client.post(f"/comp/hiring/position/{hp}/status",
                data={"status": "assunta", "person_id": pid})
    assert "Sviluppatore senior" not in client.get(f"/org/team/{alfa}").text
    assert "Nessuna posizione aperta a budget" in client.get(f"/org/team/{alfa}").text


def test_correzione_posizione_ruolo_team_budget(client):
    """La correzione tocca anche ruolo, team e budget di imputazione."""
    from app import db

    alfa, beta = _teams(client)
    b26 = _budget(client, "Assunzioni 2026", 2026)
    b27 = _budget(client, "Assunzioni 2027", 2027)
    hp = _position(client, b26, "Team lead", alfa)

    client.post(f"/comp/hiring/position/{hp}/update", data={
        "title": "Team lead platform", "team_id": beta, "role_type": "tl",
        "budget_id": b27, "expected_ral": 52000, "expected_start": "2027-01-15"})
    row = db.one("SELECT * FROM hiring_position WHERE id=?", (hp,))
    assert row["title"] == "Team lead platform"
    assert row["team_id"] == beta and row["role_type"] == "tl"
    assert row["budget_id"] == b27 and row["expected_ral"] == 52000

    # la posizione si è spostata di team: segue il panel
    assert "Team lead platform" in client.get(f"/org/team/{beta}").text
    assert "Team lead platform" not in client.get(f"/org/team/{alfa}").text


def test_correzione_non_azzera_budget_e_ruolo(client):
    """budget_id e role_type sono NOT NULL/def.: un valore vuoto lascia il dato attuale."""
    from app import db

    alfa, _ = _teams(client)
    bid = _budget(client, "Assunzioni 2026", 2026)
    hp = _position(client, bid, "Data engineer", alfa)

    client.post(f"/comp/hiring/position/{hp}/update", data={
        "title": "Data engineer", "team_id": alfa, "role_type": "",
        "budget_id": "", "expected_ral": 45000, "expected_start": "2026-03-01"})
    row = db.one("SELECT budget_id, role_type FROM hiring_position WHERE id=?", (hp,))
    assert row["budget_id"] == bid and row["role_type"] == "ic"


def test_correzione_su_posizione_assunta(client):
    """Anche una posizione già assunta si corregge; il budget segue la RAL reale."""
    from app import db

    alfa, _ = _teams(client)
    bid = _budget(client, "Assunzioni 2026", 2026)
    hp = _position(client, bid, "QA engineer", alfa)
    pid = db.execute("INSERT INTO person (full_name) VALUES ('Assunta Due')")
    client.post(f"/people/{pid}/ral", data={
        "amount": 41000, "effective_date": "2026-03-01", "change_type": "assunzione"})
    client.post(f"/comp/hiring/position/{hp}/status",
                data={"status": "assunta", "person_id": pid})

    assert "modifica «QA engineer»" in client.get("/comp/hiring").text
    client.post(f"/comp/hiring/position/{hp}/update", data={
        "title": "QA engineer senior", "team_id": alfa, "role_type": "sr",
        "budget_id": bid, "expected_ral": 99000, "expected_start": "2026-03-01"})
    assert db.one("SELECT title FROM hiring_position WHERE id=?", (hp,))["title"] \
        == "QA engineer senior"
    # applicato = RAL reale della persona, non la expected_ral ritoccata
    assert "€ 41.000" in client.get("/comp/hiring").text


def _open_ids(bid):
    from app import db

    return [r["id"] for r in db.query(
        "SELECT id FROM hiring_position WHERE budget_id=? AND voided=0 "
        "AND status IN ('pianificata','in_selezione')", (bid,))]


def test_trasferimento_su_budget_esistente(client):
    """Modalità 1: le posizioni scelte passano al budget aperto, il residuo lo segue."""
    from app import db

    alfa, _ = _teams(client)
    b26 = _budget(client, "Assunzioni 2026", 2026, cap=200000)
    b27 = _budget(client, "Assunzioni 2027", 2027, cap=100000)
    p1 = _position(client, b26, "Dev senior", alfa, ral=50000)
    p2 = _position(client, b26, "Dev junior", alfa, ral=30000)

    client.post(f"/comp/hiring/{b26}/transfer", data={
        "mode": "esistente", "to_budget_id": b27, "amount": 120000,
        "note": "residuo non speso", f"pos_{p1}": "trasferisci", f"pos_{p2}": "chiudi"})

    assert db.one("SELECT budget_id FROM hiring_position WHERE id=?", (p1,))["budget_id"] == b27
    assert db.one("SELECT status FROM hiring_position WHERE id=?", (p2,))["status"] == "annullata"
    assert db.one("SELECT status FROM hiring_budget WHERE id=?", (b26,))["status"] == "chiuso"

    tr = db.one("SELECT * FROM hiring_transfer WHERE from_budget_id=?", (b26,))
    assert tr["to_budget_id"] == b27 and tr["amount"] == 120000 and tr["voided"] == 0

    html = client.get("/comp/hiring").text
    # il riporto è dentro il tetto (100.000 propri + 120.000) ma resta esposto a parte
    assert "tetto € 220.000" in html and "riporto AP € 120.000" in html
    # il budget chiuso è finito nello storico
    assert "budget chiusi" in html


def test_riapertura_crea_il_budget_nuovo(client):
    """Modalità 2: il budget di destinazione nasce col trasferimento."""
    from app import db

    alfa, _ = _teams(client)
    b26 = _budget(client, "Assunzioni 2026", 2026, cap=200000)
    hp = _position(client, b26, "Dev senior", alfa, ral=50000)

    client.post(f"/comp/hiring/{b26}/transfer", data={
        "mode": "nuovo", "period": "Assunzioni 2027", "year": 2027,
        "total_cap": 80000, "amount": 150000, f"pos_{hp}": "trasferisci"})

    nuovo = db.one("SELECT * FROM hiring_budget WHERE period='Assunzioni 2027'")
    assert nuovo["total_cap"] == 80000 and nuovo["status"] == "aperto"
    assert db.one("SELECT budget_id FROM hiring_position WHERE id=?", (hp,))["budget_id"] == nuovo["id"]
    assert db.one("SELECT status FROM hiring_budget WHERE id=?", (b26,))["status"] == "chiuso"
    assert "tetto € 230.000" in client.get("/comp/hiring").text


def test_posizione_lasciata_tiene_aperto_il_budget(client):
    """Un budget con posizioni vive dentro non va archiviato."""
    from app import db

    alfa, _ = _teams(client)
    b26 = _budget(client, "Assunzioni 2026", 2026)
    b27 = _budget(client, "Assunzioni 2027", 2027)
    resta = _position(client, b26, "Dev senior", alfa)

    client.post(f"/comp/hiring/{b26}/transfer", data={
        "mode": "esistente", "to_budget_id": b27, "amount": 50000,
        f"pos_{resta}": "resta"})

    assert db.one("SELECT status FROM hiring_budget WHERE id=?", (b26,))["status"] == "aperto"
    assert _open_ids(b26) == [resta]
    # il riporto è comunque partito: è una scelta esplicita
    assert db.one("SELECT amount FROM hiring_transfer WHERE from_budget_id=?", (b26,))["amount"] == 50000


def test_annulla_trasferimento_riporta_indietro(client):
    """L'errore si annulla: tornano il riporto, le posizioni aperte e il budget."""
    from app import db

    alfa, _ = _teams(client)
    b26 = _budget(client, "Assunzioni 2026", 2026, cap=200000)
    b27 = _budget(client, "Assunzioni 2027", 2027, cap=100000)
    aperta = _position(client, b26, "Dev senior", alfa, ral=50000)
    assunta = _position(client, b26, "Dev junior", alfa, ral=30000)

    client.post(f"/comp/hiring/{b26}/transfer", data={
        "mode": "esistente", "to_budget_id": b27, "amount": 120000,
        f"pos_{aperta}": "trasferisci", f"pos_{assunta}": "trasferisci"})
    pid = db.execute("INSERT INTO person (full_name) VALUES ('Neo Collega')")
    client.post(f"/comp/hiring/position/{assunta}/status",
                data={"status": "assunta", "person_id": pid})

    tid = db.one("SELECT id FROM hiring_transfer WHERE from_budget_id=?", (b26,))["id"]
    client.post(f"/comp/hiring/transfer/{tid}/void")

    assert db.one("SELECT voided FROM hiring_transfer WHERE id=?", (tid,))["voided"] == 1
    assert db.one("SELECT status FROM hiring_budget WHERE id=?", (b26,))["status"] == "aperto"
    # l'aperta torna indietro, chi è già stato assunto resta dov'è: lì il denaro è speso
    assert db.one("SELECT budget_id FROM hiring_position WHERE id=?", (aperta,))["budget_id"] == b26
    assert db.one("SELECT budget_id FROM hiring_position WHERE id=?", (assunta,))["budget_id"] == b27
    assert "riporto AP €" not in client.get("/comp/hiring").text


def test_chiusura_semplice_e_riapertura(client):
    """Un budget senza posizioni aperte si chiude e si riapre senza trasferimenti."""
    from app import db

    b26 = _budget(client, "Assunzioni 2026", 2026)
    client.post(f"/comp/hiring/{b26}/close")
    assert db.one("SELECT status FROM hiring_budget WHERE id=?", (b26,))["status"] == "chiuso"
    html = client.get("/comp/hiring").text
    assert "Nessun budget assunzioni aperto" in html and "1 budget chiusi" in html
    client.post(f"/comp/hiring/{b26}/reopen")
    assert db.one("SELECT status FROM hiring_budget WHERE id=?", (b26,))["status"] == "aperto"
