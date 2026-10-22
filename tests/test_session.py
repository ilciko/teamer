"""Il blocco segue le pagine aperte di ogni sessione, non l'orologio, e non tocca gli altri utenti."""
import pytest

from app import auth, config, db, session
from tests.conftest import PASSWORD, login


@pytest.fixture()
def senza_grazia(monkeypatch):
    """Grazia a zero: quello che resta è solo la presenza delle schede."""
    monkeypatch.setattr(config, "LOCK_GRACE_SECONDS", 0)
    monkeypatch.setattr(session, "BYE_GRACE_SECONDS", 0)


@pytest.fixture()
def s():
    session.reset()
    yield session.create(1, "coo", "director")
    session.reset()


def test_multi_tab_non_blocca(s):
    """Chiudere una scheda con un'altra aperta non deve bloccare niente."""
    session.touch_tab(s, "a")
    session.touch_tab(s, "b")
    session.drop_tab(s, "a")
    assert not session.is_deserted(s)


def test_ultima_scheda_chiusa_blocca_la_sessione_non_il_db(fresh_db, s, monkeypatch):
    """Il lock è della sessione: il DB resta aperto e l'altro utente non se ne accorge."""
    monkeypatch.setattr(session, "BYE_GRACE_SECONDS", 0)   # l'addio blocca subito
    altra = session.create(2, "hr", "director")
    session.touch_tab(altra, "x")                           # batte da un istante: entro la grazia
    session.touch_tab(s, "a")
    session.drop_tab(s, "a")
    assert session.maybe_lock() == [s]
    assert s.locked and not altra.locked
    assert db.is_open()


def test_richiesta_in_corso_ferma_il_reaper(s, senza_grazia):
    """La sessione non si blocca sotto i piedi di una richiesta."""
    session.touch_tab(s, "a")
    session.drop_tab(s, "a")
    session.enter(s)
    try:
        assert not session.is_deserted(s)
    finally:
        session.leave(s)
    assert session.is_deserted(s)


def test_battito_recente_tiene_aperto(s):
    """Mezz'ora a scrivere senza click: la scheda batte, la sessione resta."""
    session.touch_tab(s, "a")
    assert not session.is_deserted(s)


def test_sessioni_bloccate_da_ore_si_dimenticano(s, monkeypatch):
    session.lock(s)
    assert session.maybe_lock() == [] and session.get(s.id) is s
    monkeypatch.setattr(config, "LOCKED_SESSION_HOURS", 0)
    s.locked_at -= 1
    session.maybe_lock()
    assert session.get(s.id) is None


def test_query_a_db_chiuso_non_e_un_500(fresh_db):
    """Chi trova il DB chiuso riceve DatabaseLocked, non AttributeError."""
    db.close_db()
    with pytest.raises(db.DatabaseLocked):
        db.query("SELECT 1")
    with pytest.raises(db.DatabaseLocked):
        with db.transaction():
            pass


def test_open_db_non_lascia_connessioni_orfane(tmp_path):
    """Due open di fila: la prima connessione cifrata va chiusa, non abbandonata."""
    from tests.conftest import TEST_KEY

    path = tmp_path / "doppio.db"
    db.close_db()
    db.open_db(TEST_KEY, db_path=path)
    prima = db._sys.conn
    db.open_db(TEST_KEY, db_path=path)
    assert db._sys.conn is not prima
    assert db.one("SELECT 1 AS n")["n"] == 1
    db.close_db()


def test_cookie_falso_o_vecchio_formato_non_entra(client):
    client.cookies.set(auth.COOKIE, auth._signer.dumps({"ts": 0}))          # cookie della versione mono-utente
    assert client.get("/notes", follow_redirects=False).status_code == 302
    client.cookies.set(auth.COOKIE, auth._signer.dumps({"sid": "inventata"}))
    assert client.get("/notes", follow_redirects=False).status_code == 302


def test_nessun_idle_timeout(client):
    """Nessuna scadenza per inattività: la sessione vale finché non si blocca."""
    s = next(iter(session._sessions.values()))
    s.last_seen -= 10 ** 6
    assert client.get("/notes").status_code == 200


def test_heartbeat_non_redirige_mai(client):
    """A sessione bloccata il battito risponde JSON: la pagina non viene trascinata via."""
    j = client.post("/heartbeat", data={"tab": "t1"}).json()
    assert j["stato"] == "aperto" and j["version"]
    session.lock(next(iter(session._sessions.values())))
    r = client.post("/heartbeat", data={"tab": "t1"})
    assert r.status_code == 200 and r.json()["stato"] == "bloccato"


def test_unlock_riprende_la_stessa_sessione(client):
    """Si sblocca in place: la password giusta riprende la sessione, quella sbagliata no."""
    s = next(iter(session._sessions.values()))
    session.lock(s)
    assert client.get("/notes", follow_redirects=False).status_code == 302
    assert client.post("/unlock", data={"username": "coo", "password": "sbagliata"}).json()["ok"] is False
    assert s.locked
    assert client.post("/unlock", data={"password": PASSWORD}).json()["ok"] is True  # utente dalla sessione
    assert not s.locked and session.get(s.id) is s
    assert client.get("/notes").status_code == 200


def test_unlock_dopo_un_riavvio_crea_una_sessione(client):
    session.reset()  # servizio riavviato: il registro in memoria è vuoto
    assert client.post("/heartbeat", data={"tab": "t"}).json()["stato"] == "bloccato"
    assert client.post("/unlock", data={"username": "coo", "password": PASSWORD}).json()["ok"] is True
    assert client.get("/notes").status_code == 200


def test_due_utenti_il_blocco_di_uno_non_tocca_l_altro(client, app_db):
    from fastapi.testclient import TestClient

    from app import users
    from app.main import app

    users.create("hr", "director", PASSWORD)
    altro = TestClient(app)
    login(altro, "hr")
    client.post("/lock")
    assert client.get("/notes", follow_redirects=False).status_code == 302
    assert altro.get("/notes").status_code == 200
    assert db.is_open()


def test_htmx_a_sessione_chiusa_sa_dove_mandare(client):
    """Le richieste htmx normali continuano a ricevere HX-Redirect."""
    client.post("/lock")
    r = client.get("/notes", headers={"HX-Request": "true"}, follow_redirects=False)
    assert r.headers.get("HX-Redirect") == "/login"


# ---- una connessione per sessione ----

def _sessione_di(username):
    return next(s for s in session._sessions.values() if s.username == username)


def test_ogni_director_ha_la_sua_connessione(client, admin_client, app_db):
    from fastapi.testclient import TestClient

    from app import users
    from app.main import app

    users.create("hr", "director", PASSWORD)
    altro = TestClient(app)
    login(altro, "hr")
    client.post("/people", data={"full_name": "Scritta Da Coo"})
    altro.post("/people", data={"full_name": "Scritta Da Hr"})
    assert "Scritta Da Hr" in altro.get("/people").text and "Scritta Da Coo" not in altro.get("/people").text
    assert "Scritta Da Coo" in client.get("/people").text and "Scritta Da Hr" not in client.get("/people").text
    assert db.sys.one("SELECT COUNT(*) AS n FROM person")["n"] == 2   # stesso file, viste diverse
    coo, hr = _sessione_di("coo"), _sessione_di("hr")
    assert coo.db is not None and hr.db is not None and coo.db.conn is not hr.db.conn
    assert coo.db.conn is not db._sys.conn
    admin_client.get("/admin")
    assert _sessione_di("it").db is None                       # l'admin usa la connessione di sistema


def test_blocco_e_uscita_chiudono_la_connessione(client):
    client.get("/people")
    s = _sessione_di("coo")
    session.lock(s)
    assert s.db is None and not s.closed
    assert client.post("/unlock", data={"password": PASSWORD}).json()["ok"]
    assert client.get("/people").status_code == 200 and s.db is not None   # riaperta allo sblocco
    client.post("/lock")
    assert s.db is None and s.closed


def test_ripristino_con_sessioni_aperte(client, admin_client, tmp_path):
    client.post("/people", data={"full_name": "Prima Del Backup"})
    bk = tmp_path / "bk.db"
    db.backup_to(bk)
    client.post("/people", data={"full_name": "Dopo Il Backup"})
    s = _sessione_di("coo")
    assert s.db is not None
    db.restore(bk)
    assert s.db is None                                         # chiusa: si riapre sul file nuovo
    html = client.get("/people").text
    assert "Prima Del Backup" in html and "Dopo Il Backup" not in html


def test_transazione_parte_con_lock_di_scrittura(client):
    """BEGIN IMMEDIATE: due sessioni non si bloccano a metà transazione (SQLITE_BUSY_SNAPSHOT)."""
    client.get("/people")
    s = _sessione_di("coo")
    tok = session.bind(s)
    try:
        with db.transaction() as conn:
            assert s.db.conn.in_transaction
            conn.execute("INSERT INTO person (full_name) VALUES ('In Transazione')")
    finally:
        session.unbind(tok)
    assert db.sys.one("SELECT 1 FROM person WHERE full_name='In Transazione'")
