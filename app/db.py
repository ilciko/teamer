"""Accesso al database SQLCipher e migrazioni.

Il DB è cifrato con una chiave di sistema letta da file (`config.DB_KEY_FILE`): la
conosce solo l'IT, gli utenti entrano con la propria password (`app.users`) e non
la vedono mai. Si apre all'avvio del servizio e resta aperto finché il servizio
gira: il blocco è per sessione (`app.session`), non del DB.

Connessioni:
- **di sistema** (`_sys`, API `db.sys.*`): avvio, migrazioni, utenti e audit, admin,
  CLI, backup e ripristino. È quella che usano anche gli helper senza una sessione
  di director (login, test, script);
- **di sessione**: ogni sessione di un director o di HR ha la sua, aperta al primo uso e
  chiusa al blocco o all'uscita. È qui che i perimetri (`app.perimeter`) installano
  viste e guardie: la stessa query vede righe diverse a seconda di chi la esegue.

Ogni connessione ha il proprio lock; il file è in WAL e le transazioni partono con
`BEGIN IMMEDIATE`. Le scritture passano da `qualify()`, che le indirizza a `main.<t>`
(sotto una vista omonima, scrivere senza schema fallirebbe).
"""
import functools
import os
import re
import secrets
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:
    import sqlcipher3 as sqlcipher
except ImportError:  # wheel linux
    from sqlcipher3 import dbapi2 as sqlcipher  # pragma: no cover

from app import config, session

MIGRATIONS_DIR = config.BASE_DIR / "migrations"


@dataclass
class _Handle:
    conn: object
    lock: threading.RLock = field(default_factory=threading.RLock)
    user_id: int | None = None
    role: str = "director"
    rev: int = 0  # revisione del perimetro installato (perimeter.REV)
    write_target: str | None = None  # tabella che si sta scrivendo (per l'authorizer)
    system: bool = False             # ricarica del perimetro in corso: letture di sistema


_sys: _Handle | None = None
_key: str | None = None   # chiave della connessione di sistema, per aprire quelle di sessione
# apertura/chiusura delle connessioni di sessione e ripristino. Ordine dei lock: _gate → sessione → sistema
_gate = threading.RLock()
_session_handles: dict[str, "session.Session"] = {}
# pronto | chiave_mancante | legacy (DB cifrato con la vecchia password) | chiuso
_state = "chiuso"


class WrongPassword(Exception):
    """La chiave (o la vecchia password, nella migrazione) non apre il file."""


class KeyMissing(Exception):
    """Il file della chiave di sistema manca o non è leggibile."""


class DatabaseLocked(Exception):
    """Il DB non è aperto: chiave mancante, migrazione da fare o spegnimento in corso."""


def _require() -> _Handle:
    if _sys is None:
        raise DatabaseLocked()
    return _sys


def _handle() -> _Handle:
    """La connessione della richiesta: quella della sessione del director (o di HR), altrimenti di sistema."""
    from app import perimeter

    s = session.current()
    if s is None or s.role not in perimeter.SESSION_ROLES:
        return _require()
    h = s.db
    if h is None:
        with _gate:
            if s.closed:
                raise DatabaseLocked()
            if s.db is None:
                s.db = _open_session(s)
                _session_handles[s.id] = s
            h = s.db
    if h.rev != perimeter.REV:  # l'admin ha cambiato le titolarità: perimetro da ricaricare
        with h.lock:
            if h.rev != perimeter.REV and not h.conn.in_transaction:
                rev = perimeter.REV
                h.system = True
                try:
                    perimeter.refresh(h.conn, h.user_id, h.role)
                finally:
                    h.system = False
                h.rev = rev
    return h


def _open_session(s) -> _Handle:
    if _sys is None or _key is None:
        raise DatabaseLocked()
    from app import perimeter

    conn = _connect(Path(config.DB_PATH), _raw(_key))
    _configure(conn)
    # proprietario delle righe nuove nelle tabelle "del director" (DEFAULT (teamer_owner()))
    conn.create_function("teamer_owner", 0, lambda uid=s.user_id: uid)
    rev = perimeter.REV
    perimeter.install(conn, s.user_id, s.role)
    h = _Handle(conn, user_id=s.user_id, role=s.role, rev=rev)
    conn.set_authorizer(perimeter.authorizer(h, conn))
    return h


def close_session(s, *, final: bool = False) -> None:
    """Chiude la connessione di una sessione (blocco: si riapre allo sblocco; final: sessione finita)."""
    with _gate:
        if final:
            s.closed = True
        h = s.db
        if h is not None:
            with h.lock:
                h.conn.close()
            s.db = None
        _session_handles.pop(s.id, None)


def _close_all_sessions() -> None:
    with _gate:
        for s in list(_session_handles.values()):
            close_session(s)


session.on_close = close_session


_WRITE = re.compile(r"^(\s*(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE(?:\s+OR\s+\w+)?|DELETE\s+FROM)\s+)"
                    r"(?!main\.|temp\.)([A-Za-z_]\w*)", re.IGNORECASE)


@functools.lru_cache(maxsize=2048)
def qualify(sql: str) -> str:
    """Le scritture vanno alla tabella vera: `INSERT INTO x` → `INSERT INTO main.x`. Le letture restano."""
    return _WRITE.sub(r"\1main.\2", sql, count=1)


def write_target(sql: str) -> str | None:
    m = _WRITE.match(sql)
    return m.group(2) if m else None


def _quote_key(password: str) -> str:
    return password.replace("'", "''")


def generate_key() -> str:
    """32 byte casuali in esadecimale: chiave grezza SQLCipher, niente KDF."""
    return secrets.token_hex(32)


def load_key(path: Path | None = None) -> str:
    path = Path(path or config.DB_KEY_FILE)
    try:
        key = path.read_text().strip().lower()
    except OSError as exc:
        raise KeyMissing(f"chiave del database non leggibile in {path}: {exc.strerror or exc}") from exc
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise KeyMissing(f"chiave del database non valida in {path} (attesi 64 caratteri esadecimali)")
    return key


def write_key(path: Path | None = None) -> str:
    """Crea il file della chiave (mai sovrascritto: perderla = perdere i dati)."""
    path = Path(path or config.DB_KEY_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = generate_key()
    with open(path, "x") as f:
        f.write(key + "\n")
    path.chmod(0o640)
    return key


def _connect(path: Path, key_sql: str):
    """Connessione aperta e verificata; WrongPassword se la chiave non decifra il file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlcipher.connect(str(path), check_same_thread=False)
    # proprietario delle righe nuove nelle tabelle "del director": nessuno, finché una
    # sessione non registra il suo (vedi _open_session). Serve anche alle migrazioni.
    conn.create_function("teamer_owner", 0, lambda: None)
    conn.execute(f"PRAGMA key = {key_sql}")
    conn.execute("PRAGMA kdf_iter = 256000")  # solo per le passphrase (legacy); ignorato con la chiave grezza
    try:
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlcipher.DatabaseError:
        conn.close()
        raise WrongPassword() from None
    return conn


def _raw(key: str) -> str:
    """Chiave grezza come letterale di PRAGMA key/rekey, che non accettano parametri: per questo
    solo 64 cifre esadecimali, verificate qui anche se chi chiama le ha già controllate."""
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise ValueError("chiave grezza non valida")
    return f"\"x'{key}'\""


def _configure(conn) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    # più connessioni sullo stesso file (sessioni, teamer-admin da un altro processo)
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.row_factory = sqlcipher.Row


def _install(conn, key: str) -> None:
    global _sys, _state, _key
    _configure(conn)
    conn.execute("PRAGMA journal_mode = WAL")
    with _gate:
        _sys = _Handle(conn)
        _key = key
        _state = "pronto"
    migrate()
    if not sys.one("SELECT 1 FROM app_meta WHERE key='instance_id'"):  # riconosce i backup di questa istanza
        sys.execute("INSERT INTO app_meta (key, value) VALUES ('instance_id', ?)", (secrets.token_hex(8),))


def open_db(key: str, db_path: Path | None = None):
    """Apre (o crea) il DB con la chiave di sistema. Solleva WrongPassword se non è quella."""
    close_db()  # niente connessioni cifrate orfane in memoria
    if db_path is not None:
        config.DB_PATH = Path(db_path)  # le connessioni di sessione aprono lo stesso file
    conn = _connect(Path(config.DB_PATH), _raw(key))
    _install(conn, key)
    return conn


def startup(db_path: Path | None = None) -> str:
    """All'avvio del servizio: apre il DB con la chiave su file, se può. Ritorna lo stato."""
    global _state
    try:
        key = load_key()
    except KeyMissing:
        close_db()
        _state = "chiave_mancante"
        return _state
    try:
        open_db(key, db_path)
    except WrongPassword:
        _state = "legacy"
    return _state


def migrate_legacy(old_password: str, db_path: Path | None = None) -> None:
    """DB delle versioni mono-utente (cifrato con la password del COO): passa alla chiave di sistema.

    WrongPassword se la vecchia password non lo apre. Il rekey ricifra il file in place.
    """
    key = load_key()
    close_db()
    if db_path is not None:
        config.DB_PATH = Path(db_path)
    conn = _connect(Path(config.DB_PATH), f"'{_quote_key(old_password)}'")
    conn.execute(f"PRAGMA rekey = {_raw(key)}")
    _install(conn, key)


def state() -> str:
    return _state


def close_db() -> None:
    global _sys, _state
    with _gate:
        _close_all_sessions()
        if _sys is not None:
            with _sys.lock:
                _sys.conn.close()
            _sys = None
            _state = "chiuso"


def is_open() -> bool:
    return _sys is not None


def db_exists(db_path: Path | None = None) -> bool:
    return Path(db_path or config.DB_PATH).exists()


def backup_to(dest: Path) -> None:
    """Copia consistente e ancora cifrata del DB aperto (dalla connessione di sistema: senza filtri)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    h = _require()
    with h.lock:
        h.conn.execute("VACUUM INTO ?", (str(dest),))


# ---- helper: stessa API per la connessione della richiesta e per quella di sistema ----

def _run(h: _Handle, sql: str, params=(), many: bool = False):
    """Esegue con la tabella bersaglio dichiarata all'authorizer (le letture non ne hanno)."""
    h.write_target = write_target(sql)
    try:
        if many:
            return h.conn.executemany(qualify(sql), params)
        return h.conn.execute(qualify(sql), params)
    finally:
        h.write_target = None


def _query(h: _Handle, sql: str, params=()) -> list:
    with h.lock:
        return _run(h, sql, params).fetchall()


def _one(h: _Handle, sql: str, params=()):
    with h.lock:
        return _run(h, sql, params).fetchone()


def _execute(h: _Handle, sql: str, params=()) -> int:
    with h.lock:
        try:
            cur = _run(h, sql, params)
        except Exception:
            # una scrittura fermata (vincolo, guardia del perimetro) non lascia aperta la
            # transazione implicita: terrebbe il lock di scrittura su tutto il file
            h.conn.rollback()
            raise
        h.conn.commit()
        return cur.lastrowid


def _executemany(h: _Handle, sql: str, seq) -> None:
    with h.lock:
        try:
            _run(h, sql, seq, many=True)
        except Exception:
            h.conn.rollback()
            raise
        h.conn.commit()


class _TxConn:
    """Quello che `transaction()` mette in mano al codice: execute/executemany qualificati,
    cursore vero (lastrowid, fetchone)."""

    def __init__(self, h):
        self._h = h

    def execute(self, sql: str, params=()):
        return _run(self._h, sql, params)

    def executemany(self, sql: str, seq):
        return _run(self._h, sql, seq, many=True)


class _Tx:
    def __init__(self, h_getter):
        self._h_getter = h_getter

    def __enter__(self):
        self.h = self._h_getter()
        self.h.lock.acquire()
        try:
            if not self.h.conn.in_transaction:
                self.h.conn.execute("BEGIN IMMEDIATE")  # il lock di scrittura subito: niente stalli a metà
        except BaseException:
            self.h.lock.release()
            raise
        return _TxConn(self.h)

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.h.conn.commit()
            else:
                self.h.conn.rollback()
        finally:
            self.h.lock.release()
        return False


def query(sql: str, params=()) -> list:
    return _query(_handle(), sql, params)


def one(sql: str, params=()):
    return _one(_handle(), sql, params)


def execute(sql: str, params=()) -> int:
    """Esegue e committa; ritorna lastrowid."""
    return _execute(_handle(), sql, params)


def executemany(sql: str, seq) -> None:
    _executemany(_handle(), sql, seq)


def transaction():
    """Context manager: blocco di statement committati insieme."""
    return _Tx(_handle)


class _System:
    """`db.sys`: la connessione di sistema, qualunque sia la sessione della richiesta.
    Per utenti, audit e perimetri; mai dentro una transazione di sessione."""

    query = staticmethod(lambda sql, params=(): _query(_require(), sql, params))
    one = staticmethod(lambda sql, params=(): _one(_require(), sql, params))
    execute = staticmethod(lambda sql, params=(): _execute(_require(), sql, params))
    executemany = staticmethod(lambda sql, seq: _executemany(_require(), sql, seq))
    transaction = staticmethod(lambda: _Tx(_require))


sys = _System()


def schema_version() -> int:
    row = sys.one("SELECT value FROM app_meta WHERE key = 'schema_version'")
    return int(row["value"]) if row else 0


def _schema_version_of(conn) -> int | None:
    """None se il file non ha `app_meta`: non è un DB di Teamer."""
    has_meta = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_meta'"
    ).fetchone()
    if not has_meta:
        return None
    row = conn.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()
    return int(row[0]) if row else 0


def latest_migration() -> int:
    return max(int(re.match(r"(\d+)", p.name).group(1)) for p in MIGRATIONS_DIR.glob("*.sql"))


def _migrate(conn) -> None:
    current = _schema_version_of(conn) or 0
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        num = int(re.match(r"(\d+)", path.name).group(1))
        if num <= current:
            continue
        conn.executescript(path.read_text())
        conn.execute(
            "INSERT INTO app_meta(key,value) VALUES('schema_version',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(num),),
        )
        conn.commit()


def migrate() -> None:
    """Applica le migrazioni SQL mancanti, in ordine numerico."""
    h = _require()
    with h.lock:
        _migrate(h.conn)


# ---- ripristino ----
#
# Il file porta i DATI; utenti e audit restano quelli dell'istanza: chi ripristina non
# resta chiuso fuori, e un DB della 0.29 (senza utenti) si importa tenendo gli account.

INSTANCE_TABLES = ("app_user", "audit_event")


class RestoreError(Exception):
    """Il file non si può ripristinare: il messaggio è per l'utente."""


def restore(src: Path, *, source_key: str | None = None, password: str | None = None) -> dict:
    """Sostituisce il DB aperto con `src` (backup di Teamer, anche di un'altra istanza o della 0.29).

    `src` si apre con la chiave di questa istanza, con `source_key` (chiave di un'altra istanza)
    o con `password` (DB ≤ 0.29). Viene ricifrato con la chiave di questa istanza e migrato;
    utenti e audit dell'istanza ci vengono copiati sopra. Prima dello scambio il DB attuale
    va in `data/backups/` (ritorna il nome). Solleva WrongPassword o RestoreError.
    """
    key = load_key()
    dest = Path(config.DB_PATH)
    work = dest.parent / "restore"
    work.mkdir(parents=True, exist_ok=True)
    tmp = work / "in-ripristino.db"
    for f in work.glob("in-ripristino.db*"):
        f.unlink()
    shutil.copyfile(src, tmp)
    if password:
        key_sql = f"'{_quote_key(password)}'"
    elif source_key:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", source_key.strip()):
            raise RestoreError("La chiave di origine deve avere 64 caratteri esadecimali.")
        key_sql = _raw(source_key.strip().lower())
    else:
        key_sql = _raw(key)
    try:
        conn = _connect(tmp, key_sql)
    except sqlcipher.DatabaseError:  # file non cifrato o non SQLite
        raise WrongPassword() from None
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RestoreError("Il file è danneggiato (integrity_check non superato).")
        version = _schema_version_of(conn)
        if version is None:
            raise RestoreError("Il file non è un database di Teamer.")
        if version > latest_migration():
            raise RestoreError("Il file viene da una versione di Teamer più recente: aggiorna prima questa istanza.")
        if key_sql != _raw(key):
            conn.execute(f"PRAGMA rekey = {_raw(key)}")
        conn.row_factory = sqlcipher.Row
        _migrate(conn)
        # nessuna sessione apre connessioni finché il file nuovo non è al suo posto
        with _gate:
            _close_all_sessions()
            sys_h = _require()
            with sys_h.lock:
                cur = sys_h.conn
                here = cur.execute("SELECT value FROM app_meta WHERE key='instance_id'").fetchone()
                there = conn.execute("SELECT value FROM app_meta WHERE key='instance_id'").fetchone()
                same_instance = bool(here and there and here[0] == there[0])
                for table in INSTANCE_TABLES:
                    cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})")]
                    rows = cur.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
                    conn.execute(f"DELETE FROM {table}")
                    conn.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                     [tuple(r) for r in rows])
                conn.execute("DELETE FROM app_meta WHERE key='public_mode'")  # ≤ 0.29: ora è per utente
                if not same_instance:
                    # gli utenti del file non sono quelli di qui: i dati tornano «da assegnare»
                    from app import perimeter

                    for table in [*perimeter.OWNED, *perimeter.TEAM, "person"]:
                        conn.execute(f"UPDATE {table} SET owner_user_id=NULL")
                    conn.execute("INSERT INTO app_meta (key, value) VALUES ('instance_id', ?) "
                                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (here[0] if here else "",))
                conn.commit()
                stats = {"from_version": version, "same_instance": same_instance,
                         "people": conn.execute("SELECT COUNT(*) FROM person").fetchone()[0],
                         "teams": conn.execute("SELECT COUNT(*) FROM team").fetchone()[0]}
                conn.close()
                conn = None
                # scambio: copia di sicurezza del DB attuale, poi il file nuovo al suo posto
                stamp = f"{datetime.now():%Y%m%d%H%M%S}"
                backup = dest.parent / "backups" / f"teamer-pre-ripristino-{stamp}.db"
                n = 1
                while backup.exists():  # due ripristini nello stesso secondo
                    n += 1
                    backup = dest.parent / "backups" / f"teamer-pre-ripristino-{stamp}-{n}.db"
                backup_to(backup)
                backup.chmod(0o600)
                close_db()
                for ext in ("-wal", "-shm", "-journal"):
                    Path(f"{dest}{ext}").unlink(missing_ok=True)
                os.replace(tmp, dest)
                open_db(key, dest)
        stats["backup"] = backup.name
        stats["summary"] = (f"{stats['people']} {'persona' if stats['people'] == 1 else 'persone'}, "
                            f"{stats['teams']} team")
        return stats
    finally:
        if conn is not None:
            conn.close()
        for f in work.glob("in-ripristino.db*"):
            f.unlink()


def get_meta(key: str, default: str = "") -> str:
    """Le chiavi di configurazione (CCNL, soglie, listino) sono del director: tabella user_meta."""
    from app import perimeter

    table = "user_meta" if perimeter.scoped_meta(key) else "app_meta"
    row = one(f"SELECT value FROM {table} WHERE key=?", (key,))
    return row["value"] if row else default


def set_meta(key: str, value: str) -> None:
    from app import perimeter

    if perimeter.scoped_meta(key):
        execute("INSERT INTO user_meta (key, value) VALUES (?,?) "
                "ON CONFLICT(owner_user_id, key) DO UPDATE SET value=excluded.value", (key, value))
    else:
        sys.execute("INSERT INTO app_meta (key, value) VALUES (?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def lookups(category: str) -> list:
    return query(
        "SELECT code, label FROM lookup WHERE category=? AND active=1 ORDER BY sort_order",
        (category,),
    )


def lookup_label(category: str, code) -> str:
    if code is None:
        return ""
    row = one("SELECT label FROM lookup WHERE category=? AND code=?", (category, str(code)))
    return row["label"] if row else str(code)
