"""Il blocco del DB segue le pagine aperte, non l'orologio."""
import pytest

from app import auth, config, db, session


@pytest.fixture(autouse=True)
def registro_pulito():
    session.reset()
    yield
    session.reset()


@pytest.fixture()
def senza_grazia(monkeypatch):
    """Grazia a zero: quello che resta è solo la presenza delle schede."""
    monkeypatch.setattr(config, "LOCK_GRACE_SECONDS", 0)
    monkeypatch.setattr(session, "BYE_GRACE_SECONDS", 0)


def test_multi_tab_non_blocca():
    """Chiudere una scheda con un'altra aperta non deve bloccare niente."""
    session.touch_tab("a")
    session.touch_tab("b")
    session.drop_tab("a")
    assert not session.is_deserted()


def test_ultima_scheda_chiusa_blocca_davvero(fresh_db, senza_grazia):
    """Il lock chiude la connessione cifrata, non solo il cookie."""
    session.touch_tab("a")
    session.drop_tab("a")
    assert session.maybe_lock() is True
    assert db.is_open() is False


def test_richiesta_in_corso_ferma_il_reaper(senza_grazia):
    """Il DB non si chiude sotto i piedi di una richiesta."""
    session.touch_tab("a")
    session.drop_tab("a")
    session.enter()
    try:
        assert not session.is_deserted()
    finally:
        session.leave()
    assert session.is_deserted()


def test_battito_recente_tiene_aperto():
    """Mezz'ora a scrivere senza click: la scheda batte, la sessione resta."""
    session.touch_tab("a")
    assert not session.is_deserted()


def test_query_dopo_il_lock_non_e_un_500(fresh_db):
    """Chi trova il DB chiuso a metà richiesta riceve DatabaseLocked, non AttributeError."""
    db.close_db()
    with pytest.raises(db.DatabaseLocked):
        db.query("SELECT 1")
    with pytest.raises(db.DatabaseLocked):
        with db.transaction():
            pass


def test_open_db_non_lascia_connessioni_orfane(tmp_path):
    """Due open di fila: la prima connessione cifrata va chiusa, non abbandonata."""
    path = tmp_path / "doppio.db"
    db.close_db()
    db.open_db("password-test", db_path=path)
    prima = db._conn
    db.open_db("password-test", db_path=path)
    assert db._conn is not prima
    assert db.one("SELECT 1 AS n")["n"] == 1
    db.close_db()


def test_nessun_idle_timeout(client):
    """Un cookie vecchio di anni resta valido: la scadenza per inattività non c'è più."""
    client.cookies.set(auth.COOKIE, auth._signer.dumps({"ts": 0}))
    assert client.get("/notes").status_code == 200


def test_heartbeat_non_redirige_mai(client):
    """A DB bloccato il battito risponde JSON: la pagina non viene trascinata via."""
    j = client.post("/heartbeat", data={"tab": "t1"}).json()
    assert j["stato"] == "aperto" and j["version"]
    client.post("/lock")
    r = client.post("/heartbeat", data={"tab": "t1"})
    assert r.status_code == 200 and r.json()["stato"] == "bloccato"


def test_unlock_riapre_senza_ricaricare(client):
    """Si sblocca in place: la password giusta riapre il DB, quella sbagliata no."""
    client.post("/lock")
    assert client.post("/unlock", data={"password": "sbagliata"}).json()["ok"] is False
    assert db.is_open() is False
    assert client.post("/unlock", data={"password": "password-test"}).json()["ok"] is True
    assert client.get("/notes").status_code == 200


def test_htmx_a_db_chiuso_sa_dove_mandare(client):
    """Le richieste htmx normali continuano a ricevere HX-Redirect."""
    client.post("/lock")
    r = client.get("/notes", headers={"HX-Request": "true"}, follow_redirects=False)
    assert r.headers.get("HX-Redirect") == "/login"
