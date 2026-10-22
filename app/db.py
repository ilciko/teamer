"""Accesso al database SQLCipher e migrazioni.

Il DB è cifrato con una chiave di sistema letta da file (`config.DB_KEY_FILE`): la
conosce solo l'IT, gli utenti entrano con la propria password (`app.users`) e non
la vedono mai. Si apre all'avvio del servizio e resta aperto finché il servizio
gira: il blocco è per sessione (`app.session`), non del DB.

Una sola connessione globale, serializzata con un lock.
"""
import re
import secrets
import threading
from pathlib import Path

try:
    import sqlcipher3 as sqlcipher
except ImportError:  # wheel linux
    from sqlcipher3 import dbapi2 as sqlcipher  # pragma: no cover

from app import config

MIGRATIONS_DIR = config.BASE_DIR / "migrations"

_conn = None
_lock = threading.RLock()
# pronto | chiave_mancante | legacy (DB cifrato con la vecchia password) | chiuso
_state = "chiuso"


class WrongPassword(Exception):
    """La chiave (o la vecchia password, nella migrazione) non apre il file."""


class KeyMissing(Exception):
    """Il file della chiave di sistema manca o non è leggibile."""


class DatabaseLocked(Exception):
    """Il DB non è aperto: chiave mancante, migrazione da fare o spegnimento in corso."""


def _require():
    if _conn is None:
        raise DatabaseLocked()
    return _conn


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
        raise KeyMissing(f"chiave del database non leggibile in {path}: {exc.strerror or exc}")
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
    conn.execute(f"PRAGMA key = {key_sql}")
    conn.execute("PRAGMA kdf_iter = 256000")  # solo per le passphrase (legacy); ignorato con la chiave grezza
    try:
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlcipher.DatabaseError:
        conn.close()
        raise WrongPassword()
    return conn


def _raw(key: str) -> str:
    return f"\"x'{key}'\""


def _install(conn) -> None:
    global _conn, _state
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")  # convive con teamer-admin, che scrive da un altro processo
    conn.row_factory = sqlcipher.Row
    with _lock:
        _conn = conn
        _state = "pronto"
    migrate()


def open_db(key: str, db_path: Path | None = None):
    """Apre (o crea) il DB con la chiave di sistema. Solleva WrongPassword se non è quella."""
    close_db()  # niente connessioni cifrate orfane in memoria
    conn = _connect(Path(db_path or config.DB_PATH), _raw(key))
    _install(conn)
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
    conn = _connect(Path(db_path or config.DB_PATH), f"'{_quote_key(old_password)}'")
    conn.execute(f"PRAGMA rekey = {_raw(key)}")
    _install(conn)


def state() -> str:
    return _state


def close_db() -> None:
    global _conn, _state
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
            _state = "chiuso"


def is_open() -> bool:
    return _conn is not None


def db_exists(db_path: Path | None = None) -> bool:
    return Path(db_path or config.DB_PATH).exists()


def backup_to(dest: Path) -> None:
    """Copia consistente e ancora cifrata del DB aperto."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        _require().execute("VACUUM INTO ?", (str(dest),))


def query(sql: str, params=()) -> list:
    with _lock:
        return _require().execute(sql, params).fetchall()


def one(sql: str, params=()):
    with _lock:
        return _require().execute(sql, params).fetchone()


def execute(sql: str, params=()) -> int:
    """Esegue e committa; ritorna lastrowid."""
    with _lock:
        conn = _require()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid


def executemany(sql: str, seq) -> None:
    with _lock:
        conn = _require()
        conn.executemany(sql, seq)
        conn.commit()


def transaction():
    """Context manager: blocco di statement committati insieme."""
    class _Tx:
        def __enter__(self):
            _lock.acquire()
            try:
                self.conn = _require()
            except DatabaseLocked:
                _lock.release()
                raise
            return self.conn

        def __exit__(self, exc_type, exc, tb):
            try:
                if exc_type is None:
                    self.conn.commit()
                else:
                    self.conn.rollback()
            finally:
                _lock.release()
            return False

    return _Tx()


def schema_version() -> int:
    row = one("SELECT value FROM app_meta WHERE key = 'schema_version'")
    return int(row["value"]) if row else 0


def migrate() -> None:
    """Applica le migrazioni SQL mancanti, in ordine numerico."""
    with _lock:
        has_meta = _conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_meta'"
        ).fetchone()
        current = 0
        if has_meta:
            row = _conn.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()
            current = int(row[0]) if row else 0
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            num = int(re.match(r"(\d+)", path.name).group(1))
            if num <= current:
                continue
            _conn.executescript(path.read_text())
            _conn.execute(
                "INSERT INTO app_meta(key,value) VALUES('schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(num),),
            )
            _conn.commit()


def get_meta(key: str, default: str = "") -> str:
    row = one("SELECT value FROM app_meta WHERE key=?", (key,))
    return row["value"] if row else default


def set_meta(key: str, value: str) -> None:
    execute(
        "INSERT INTO app_meta (key, value) VALUES (?,?) "
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
