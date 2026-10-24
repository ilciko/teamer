"""Caratterizzazione di SQLite/SQLCipher per i perimetri per director.

Non testano codice dell'app: fissano i comportamenti del motore su cui poggiano
i perimetri (app/perimeter.py). Se un aggiornamento di
SQLCipher cambia uno di questi fatti, deve fallire qui, non in produzione.

L'impianto verificato: TEMP VIEW omonime che schermano le righe, TEMP TRIGGER
BEFORE sulle tabelle reali che bloccano le scritture fuori perimetro, un
authorizer per connessione che nega le letture dirette di `main.` e ATTACH.
Le strade scartate (INSTEAD OF, FTS5 schermata) sono documentate dai test
che ne mostrano il difetto.
"""
import contextvars
import threading

import pytest

try:
    import sqlcipher3 as sqlcipher
except ImportError:  # wheel linux
    from sqlcipher3 import dbapi2 as sqlcipher  # pragma: no cover

CHIAVE = "chiave-di-sistema"
SCHERMATE = {"person", "ral_event"}


def _apri(path):
    c = sqlcipher.connect(str(path), check_same_thread=False)
    c.execute(f"PRAGMA key='{CHIAVE}'")
    c.execute("PRAGMA kdf_iter=256000")
    return c


@pytest.fixture()
def conn(tmp_path):
    """Tre persone e tre eventi RAL; il perimetro copre le prime due."""
    c = _apri(tmp_path / "t.db")
    c.executescript("""
        CREATE TABLE person(id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE ral_event(id INTEGER PRIMARY KEY,
                               person_id INTEGER NOT NULL REFERENCES person(id), amount REAL);
        INSERT INTO person VALUES (1,'dentro'),(2,'dentro-bis'),(3,'fuori');
        INSERT INTO ral_event VALUES (1,1,100),(2,2,200),(3,3,300);
    """)
    c.commit()
    yield c
    c.close()


def _perimetro(c, persone=(1, 2)):
    """L'ordine è vincolante: le guardie PRIMA delle viste omonime."""
    c.execute("CREATE TEMP TABLE perim_person(person_id INTEGER PRIMARY KEY)")
    c.executemany("INSERT INTO perim_person VALUES (?)", [(p,) for p in persone])
    c.executescript("""
        CREATE TEMP TRIGGER _perim_ral_event_ins BEFORE INSERT ON ral_event BEGIN
          SELECT RAISE(ABORT,'fuori perimetro: ral_event')
           WHERE NEW.person_id NOT IN (SELECT person_id FROM temp.perim_person);
        END;
        CREATE TEMP TRIGGER _perim_ral_event_upd BEFORE UPDATE ON ral_event BEGIN
          SELECT RAISE(ABORT,'fuori perimetro: ral_event')
           WHERE OLD.person_id NOT IN (SELECT person_id FROM temp.perim_person)
              OR NEW.person_id NOT IN (SELECT person_id FROM temp.perim_person);
        END;
        CREATE TEMP TRIGGER _perim_ral_event_del BEFORE DELETE ON ral_event BEGIN
          SELECT RAISE(ABORT,'fuori perimetro: ral_event')
           WHERE OLD.person_id NOT IN (SELECT person_id FROM temp.perim_person);
        END;
        CREATE TEMP VIEW ral_event AS SELECT id, person_id, amount FROM main.ral_event
         WHERE person_id IN (SELECT person_id FROM temp.perim_person);
        CREATE TEMP VIEW person AS SELECT id, name FROM main.person
         WHERE id IN (SELECT person_id FROM temp.perim_person);
    """)


def _authorizer(c):
    """Letture di colonne su tabelle schermate solo dall'interno di viste/guardie."""
    lecite = SCHERMATE | {"_perim_ral_event_ins", "_perim_ral_event_upd", "_perim_ral_event_del"}

    def auth(action, a1, a2, dbname, source):
        if action == sqlcipher.SQLITE_READ and dbname == "main" and a1 in SCHERMATE and a2 != "":
            return sqlcipher.SQLITE_OK if source in lecite else sqlcipher.SQLITE_DENY
        if action == sqlcipher.SQLITE_ATTACH:
            return sqlcipher.SQLITE_DENY
        return sqlcipher.SQLITE_OK

    c.set_authorizer(auth)


# ---- viste ----

def test_vista_temporanea_scherma_anche_la_riga_chiesta_per_id(conn):
    _perimetro(conn)
    assert conn.execute("SELECT count(*) FROM ral_event").fetchone()[0] == 2
    assert conn.execute("SELECT * FROM ral_event WHERE id=3").fetchall() == []
    assert conn.execute(
        "SELECT count(*) FROM ral_event r JOIN person p ON p.id=r.person_id").fetchone()[0] == 2


def test_il_perimetro_si_aggiorna_a_caldo_senza_ricreare_le_viste(conn):
    _perimetro(conn, persone=(1,))
    assert conn.execute("SELECT count(*) FROM ral_event").fetchone()[0] == 1
    conn.execute("INSERT INTO perim_person VALUES (2)")
    assert conn.execute("SELECT count(*) FROM ral_event").fetchone()[0] == 2


# ---- scritture ----

def test_scrittura_qualificata_passa_e_mantiene_lastrowid(conn):
    """È la ragione per cui non si usano gli INSTEAD OF (vedi sotto)."""
    _perimetro(conn)
    cur = conn.execute("INSERT INTO main.ral_event(person_id, amount) VALUES (1, 5)")
    assert cur.lastrowid == 4
    assert conn.execute("SELECT amount FROM ral_event WHERE id=4").fetchone()[0] == 5


def test_scrittura_non_qualificata_esplode_sulla_vista(conn):
    """Chi dimentica `main.` non passa in silenzio: fallisce rumorosamente."""
    _perimetro(conn)
    with pytest.raises(sqlcipher.OperationalError, match="it is a view"):
        conn.execute("INSERT INTO ral_event(person_id, amount) VALUES (1, 5)")


def test_guardia_before_blocca_le_scritture_fuori_perimetro(conn):
    _perimetro(conn)
    with pytest.raises(sqlcipher.IntegrityError, match="fuori perimetro"):
        conn.execute("INSERT INTO main.ral_event(person_id, amount) VALUES (3, 5)")
    with pytest.raises(sqlcipher.IntegrityError, match="fuori perimetro"):
        conn.execute("UPDATE main.ral_event SET amount=0 WHERE id=3")
    with pytest.raises(sqlcipher.IntegrityError, match="fuori perimetro"):
        conn.execute("UPDATE main.ral_event SET person_id=3 WHERE id=1")  # spostamento
    with pytest.raises(sqlcipher.IntegrityError, match="fuori perimetro"):
        conn.execute("DELETE FROM main.ral_event WHERE id=3")
    conn.execute("UPDATE main.ral_event SET amount=1 WHERE id=1")  # dentro: passa
    assert conn.execute("SELECT count(*) FROM main.ral_event").fetchone()[0] == 3


def test_la_guardia_deve_precedere_la_vista_omonima(conn):
    """Creata dopo, il nome risolve sulla vista e BEFORE non è ammesso."""
    conn.execute("CREATE TEMP VIEW ral_event AS SELECT * FROM main.ral_event")
    with pytest.raises(sqlcipher.OperationalError, match="cannot create BEFORE trigger on view"):
        conn.execute("CREATE TEMP TRIGGER g BEFORE INSERT ON ral_event BEGIN SELECT 1; END")


def test_instead_of_non_puo_scrivere_sulla_tabella_qualificata(conn):
    """Strada scartata (appendice A4): il trigger non può nominare `main.tabella`."""
    conn.execute("CREATE TEMP VIEW ral_event AS SELECT * FROM main.ral_event")
    with pytest.raises(sqlcipher.OperationalError, match="qualified table names are not allowed"):
        conn.execute("""CREATE TEMP TRIGGER io INSTEAD OF INSERT ON ral_event BEGIN
            INSERT INTO main.ral_event(person_id, amount) VALUES (NEW.person_id, NEW.amount); END""")


# ---- authorizer ----

def test_authorizer_nega_la_lettura_diretta_ma_non_dalla_vista(conn):
    _perimetro(conn)
    _authorizer(conn)
    assert conn.execute("SELECT count(*) FROM ral_event").fetchone()[0] == 2
    assert conn.execute(
        "SELECT count(*) FROM ral_event r JOIN person p ON p.id=r.person_id").fetchone()[0] == 2
    for q in ("SELECT * FROM main.ral_event", "SELECT amount FROM main.ral_event",
              "SELECT count(*) FROM main.ral_event WHERE person_id=3"):
        with pytest.raises(sqlcipher.DatabaseError, match="prohibited|not authorized"):
            conn.execute(q).fetchall()
    # le guardie leggono NEW/OLD e temp.perim_person: continuano a scattare
    with pytest.raises(sqlcipher.IntegrityError, match="fuori perimetro"):
        conn.execute("INSERT INTO main.ral_event(person_id, amount) VALUES (3, 5)")


def test_authorizer_limite_dichiarato_il_conteggio_senza_colonne_passa(conn):
    """SQLITE_READ con colonna vuota = riferimento alla tabella, non lettura di dati.

    Negarlo romperebbe le join fra viste (il flattener lo emette anche lì).
    Resta esposto il numero di righe totale, mai una riga. Va detto in §9.
    """
    _perimetro(conn)
    _authorizer(conn)
    assert conn.execute("SELECT count(*) FROM main.ral_event").fetchone()[0] == 3


def test_authorizer_nega_attach_e_vacuum_into(conn, tmp_path):
    _perimetro(conn)
    _authorizer(conn)
    with pytest.raises(sqlcipher.DatabaseError, match="not authorized"):
        conn.execute("ATTACH DATABASE ':memory:' AS x")
    with pytest.raises(sqlcipher.DatabaseError, match="authorization denied"):
        conn.execute(f"VACUUM INTO '{tmp_path / 'copia.db'}'")


# ---- backup, WAL ----

def test_vacuum_into_produce_una_copia_cifrata_e_completa(conn, tmp_path):
    """Il backup di HR: cifrato con la stessa chiave, senza viste né oggetti temp."""
    _perimetro(conn)
    dest = tmp_path / "copia.db"
    conn.execute(f"VACUUM INTO '{dest}'")
    assert dest.read_bytes()[:16] != b"SQLite format 3\x00"
    k = _apri(dest)
    assert k.execute("SELECT count(*) FROM ral_event").fetchone()[0] == 3
    assert k.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE '_perim%'").fetchone()[0] == 0
    k.close()


def test_wal_su_sqlcipher_resta_cifrato(conn, tmp_path):
    assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    conn.execute("INSERT INTO main.person VALUES (4, 'parola-in-chiaro-da-non-trovare')")
    conn.commit()
    wal = tmp_path / "t.db-wal"
    assert wal.exists()
    assert b"parola-in-chiaro" not in wal.read_bytes()


def test_una_connessione_regge_piu_thread_con_un_lock(conn):
    """FastAPI esegue le route sync in un threadpool: la connessione è condivisa."""
    lock = threading.RLock()
    errori = []

    def scrivi(n):
        try:
            for _ in range(50):
                with lock:
                    conn.execute("INSERT INTO main.ral_event(person_id, amount) VALUES (1, ?)", (n,))
                    conn.commit()
        except Exception as e:  # pragma: no cover
            errori.append(e)

    ts = [threading.Thread(target=scrivi, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errori
    assert conn.execute("SELECT count(*) FROM main.ral_event").fetchone()[0] == 203


# ---- FTS5 ----

def test_fts5_non_e_schermabile_dalla_vista(conn):
    """Strada scartata (appendice A5): l'indice legge il content table come `main.`.

    La vista omonima su meeting_note non lo tocca: chi interroga l'indice
    direttamente legge tutte le note. Per questo FTS5 viene eliminato.
    """
    conn.executescript("""
        CREATE TABLE meeting_note(id INTEGER PRIMARY KEY, person_id INTEGER NOT NULL, body TEXT);
        CREATE VIRTUAL TABLE meeting_note_fts USING fts5(body, content='meeting_note', content_rowid='id');
        INSERT INTO meeting_note VALUES (1, 1, 'colloquio sereno'), (2, 3, 'colloquio teso');
        INSERT INTO meeting_note_fts(rowid, body) SELECT id, body FROM meeting_note;
        CREATE TEMP TABLE perim_person(person_id INTEGER PRIMARY KEY);
        INSERT INTO perim_person VALUES (1);
        CREATE TEMP VIEW meeting_note AS SELECT id, person_id, body FROM main.meeting_note
         WHERE person_id IN (SELECT person_id FROM temp.perim_person);
    """)
    with pytest.raises(sqlcipher.OperationalError):  # MATCH non lavora su una vista
        conn.execute("CREATE TEMP VIEW meeting_note_fts AS SELECT * FROM main.meeting_note_fts")
        conn.execute("SELECT rowid FROM meeting_note_fts WHERE meeting_note_fts MATCH 'colloquio'").fetchall()
    conn.execute("DROP VIEW meeting_note_fts")
    diretta = conn.execute(
        "SELECT body FROM meeting_note_fts WHERE meeting_note_fts MATCH 'colloquio'").fetchall()
    assert len(diretta) == 2  # il buco: entrambe, anche quella fuori perimetro
    con_join = conn.execute(
        "SELECT mn.body FROM meeting_note_fts f JOIN meeting_note mn ON mn.id=f.rowid "
        "WHERE meeting_note_fts MATCH 'colloquio'").fetchall()
    assert len(con_join) == 1  # salva solo per disciplina del join


# ---- contesto di richiesta ----

def test_contextvar_del_middleware_arriva_nella_route_sync_del_threadpool():
    """Il contesto di richiesta si propaga al worker thread: anyio copia il contesto."""
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient

    var: contextvars.ContextVar = contextvars.ContextVar("sessione", default=None)
    app = FastAPI()

    @app.middleware("http")
    async def lega(request: Request, call_next):
        tok = var.set("sessione-di-prova")
        try:
            return await call_next(request)
        finally:
            var.reset(tok)

    @app.get("/")
    def route():  # sync: gira nel threadpool
        return {"sessione": var.get(), "thread": threading.current_thread().name}

    r = TestClient(app).get("/").json()
    assert r["sessione"] == "sessione-di-prova"
    assert r["thread"] != threading.main_thread().name


# ---- fatti aggiunti per i perimetri per director (app/perimeter.py) ----

def _owned(tmp_path, uid=7, name="o.db"):
    """Connessione con la funzione teamer_owner() e una tabella col proprietario di default."""
    c = _apri(tmp_path / name)
    c.create_function("teamer_owner", 0, lambda: uid)
    return c


def test_proprietario_dal_default_per_connessione(tmp_path):
    """La riga nuova prende il proprietario dalla connessione, senza toccare le INSERT."""
    a = _owned(tmp_path, 7)
    a.execute("CREATE TABLE lookup(id INTEGER PRIMARY KEY, code TEXT, "
              "owner_user_id INTEGER NOT NULL DEFAULT (teamer_owner()), UNIQUE(owner_user_id, code))")
    a.execute("INSERT INTO lookup(code) VALUES ('x')")
    a.commit()
    b = _owned(tmp_path, 9)
    b.execute("INSERT INTO lookup(code) VALUES ('x')")           # stesso codice, altro proprietario
    b.commit()
    assert a.execute("SELECT owner_user_id FROM lookup ORDER BY id").fetchall() == [(7,), (9,)]
    # ON CONFLICT col proprietario nel bersaglio
    a.execute("INSERT INTO main.lookup(code) VALUES ('x') ON CONFLICT(owner_user_id, code) DO UPDATE SET code='x'")
    with pytest.raises(sqlcipher.OperationalError, match="ON CONFLICT clause does not match"):
        a.execute("INSERT INTO lookup(code) VALUES ('x') ON CONFLICT(code) DO NOTHING")


def test_senza_funzione_o_senza_utente_la_insert_fallisce(tmp_path):
    """Fail-closed: una connessione che non sa chi è non può creare righe con proprietario."""
    a = _owned(tmp_path, 7)
    a.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, owner_user_id INTEGER NOT NULL DEFAULT (teamer_owner()))")
    a.commit()
    nuda = _apri(tmp_path / "o.db")
    with pytest.raises(sqlcipher.OperationalError, match="teamer_owner"):
        nuda.execute("INSERT INTO t DEFAULT VALUES")
    nuda.execute("INSERT INTO t(owner_user_id) VALUES (3)")      # esplicito: passa (adozione da sistema)
    nuda.commit()
    anonima = _apri(tmp_path / "o.db")
    anonima.create_function("teamer_owner", 0, lambda: None)
    with pytest.raises(sqlcipher.IntegrityError, match="NOT NULL"):
        anonima.execute("INSERT INTO t DEFAULT VALUES")


def test_default_con_funzione_non_si_aggiunge_con_alter(tmp_path):
    """Le tabelle che prendono il proprietario vanno ricostruite."""
    a = _owned(tmp_path)
    a.execute("CREATE TABLE t(id INTEGER PRIMARY KEY)")
    a.execute("INSERT INTO t DEFAULT VALUES")                    # su una tabella vuota SQLite lo accetta
    with pytest.raises(sqlcipher.OperationalError, match="non-constant default"):
        a.execute("ALTER TABLE t ADD COLUMN owner_user_id INTEGER DEFAULT (teamer_owner())")


def test_guardia_ignore_salta_le_righe_altrui_in_silenzio(conn):
    """UPDATE/DELETE di massa toccano solo il perimetro; per id una riga altrui 'non esiste'."""
    _perimetro(conn)
    conn.executescript("""
        DROP TRIGGER _perim_ral_event_upd; DROP TRIGGER _perim_ral_event_del;
        DROP VIEW ral_event;
        CREATE TEMP TRIGGER g_upd BEFORE UPDATE ON main.ral_event BEGIN
          SELECT RAISE(IGNORE) WHERE OLD.person_id NOT IN (SELECT person_id FROM temp.perim_person);
          SELECT RAISE(ABORT,'fuori perimetro') WHERE NEW.person_id NOT IN (SELECT person_id FROM temp.perim_person);
        END;
        CREATE TEMP TRIGGER g_del BEFORE DELETE ON main.ral_event BEGIN
          SELECT RAISE(IGNORE) WHERE OLD.person_id NOT IN (SELECT person_id FROM temp.perim_person);
        END;
        CREATE TEMP VIEW ral_event AS SELECT id, person_id, amount FROM main.ral_event
         WHERE person_id IN (SELECT person_id FROM temp.perim_person);
    """)
    assert conn.execute("UPDATE main.ral_event SET amount=0").rowcount == 2
    assert conn.execute("DELETE FROM main.ral_event WHERE id=3").rowcount == 0
    with pytest.raises(sqlcipher.IntegrityError, match="fuori perimetro"):
        conn.execute("UPDATE main.ral_event SET person_id=3 WHERE id=1")
    assert conn.execute("SELECT amount FROM main.ral_event WHERE id=3").fetchone()[0] == 300


def test_trigger_after_insert_allarga_il_perimetro(conn):
    """Un team creato nella transazione entra subito nel perimetro; lastrowid resta giusto."""
    conn.executescript("""
        CREATE TABLE team(id INTEGER PRIMARY KEY, name TEXT);
        CREATE TEMP TABLE perim_team(team_id INTEGER PRIMARY KEY);
        CREATE TEMP TRIGGER t_ai AFTER INSERT ON main.team BEGIN
          INSERT OR IGNORE INTO perim_team VALUES (NEW.id);
        END;
    """)
    cur = conn.execute("INSERT INTO main.team(name) VALUES ('nuovo')")
    assert cur.lastrowid == 1
    assert conn.execute("SELECT team_id FROM perim_team").fetchall() == [(1,)]


def test_guardia_nel_trigger_legge_la_vista_omonima(conn):
    """Un nome non qualificato nel corpo di un trigger temp risolve sulla vista filtrata."""
    _perimetro(conn)
    conn.execute("CREATE TEMP TRIGGER g_padre BEFORE INSERT ON main.ral_event BEGIN "
                 "SELECT RAISE(ABORT,'persona non visibile') WHERE NEW.person_id NOT IN (SELECT id FROM person); END")
    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute("INSERT INTO main.ral_event(person_id, amount) VALUES (3, 1)")


def test_cascata_con_proprietario_sul_figlio(tmp_path):
    """Con ON DELETE CASCADE la guardia del figlio deve guardare il figlio, non il padre già sparito."""
    c = _owned(tmp_path, 7)
    c.execute("PRAGMA foreign_keys=ON")
    c.executescript("""
        CREATE TABLE scen(id INTEGER PRIMARY KEY, owner_user_id INTEGER NOT NULL DEFAULT (teamer_owner()));
        CREATE TABLE mossa(id INTEGER PRIMARY KEY, scen_id INTEGER REFERENCES scen(id) ON DELETE CASCADE,
                           owner_user_id INTEGER NOT NULL DEFAULT (teamer_owner()));
        INSERT INTO scen DEFAULT VALUES; INSERT INTO mossa(scen_id) VALUES (1);
        CREATE TEMP TRIGGER g BEFORE DELETE ON main.mossa BEGIN
          SELECT RAISE(IGNORE) WHERE OLD.owner_user_id <> teamer_owner();
        END;
    """)
    c.execute("DELETE FROM main.scen WHERE id=1")
    assert c.execute("SELECT count(*) FROM main.mossa").fetchone()[0] == 0


def test_authorizer_ammette_la_tabella_bersaglio_della_scrittura(conn):
    """UPDATE/DELETE ... WHERE id=? leggono colonne di main.x: vanno ammesse solo mentre si scrive su x."""
    _perimetro(conn)
    bersaglio = {"t": None}
    lecite = SCHERMATE | {"_perim_ral_event_ins", "_perim_ral_event_upd", "_perim_ral_event_del"}

    def auth(action, a1, a2, dbname, source):
        if action == sqlcipher.SQLITE_READ and dbname == "main" and a1 in SCHERMATE and a2 != "":
            ok = source in lecite or (source is None and a1 == bersaglio["t"])
            return sqlcipher.SQLITE_OK if ok else sqlcipher.SQLITE_DENY
        return sqlcipher.SQLITE_OK

    conn.set_authorizer(auth)
    with pytest.raises(sqlcipher.DatabaseError):
        conn.execute("UPDATE main.ral_event SET amount=1 WHERE id=1")          # senza bersaglio dichiarato
    bersaglio["t"] = "ral_event"
    conn.execute("UPDATE main.ral_event SET amount=1 WHERE id=1")
    with pytest.raises(sqlcipher.DatabaseError):                               # sottoquery su un'altra tabella
        conn.execute("UPDATE main.ral_event SET amount=1 WHERE person_id IN (SELECT id FROM main.person)")
    bersaglio["t"] = None


def test_wal_due_connessioni_su_file_con_begin_immediate(tmp_path):
    """Due sessioni sullo stesso file: la seconda aspetta busy_timeout e poi scrive."""
    a = _apri(tmp_path / "w.db")
    a.execute("PRAGMA journal_mode=WAL")
    a.execute("CREATE TABLE t(v)")
    a.commit()
    b = _apri(tmp_path / "w.db")
    b.execute("PRAGMA busy_timeout=3000")
    a.execute("BEGIN IMMEDIATE")
    a.execute("INSERT INTO t VALUES (1)")
    esito = {}

    def scrivi():
        b.execute("BEGIN IMMEDIATE")
        b.execute("INSERT INTO t VALUES (2)")
        b.commit()
        esito["ok"] = True

    th = threading.Thread(target=scrivi)
    th.start()
    th.join(0.3)
    assert "ok" not in esito          # bloccata finché A non chiude
    a.commit()
    th.join(3)
    assert esito.get("ok") and a.execute("SELECT count(*) FROM t").fetchone()[0] == 2
