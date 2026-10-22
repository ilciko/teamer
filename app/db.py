"""Accesso al database SQLCipher e migrazioni.

Mono-utente: una sola connessione globale, serializzata con un lock.
La connessione esiste solo dopo il login (la passphrase apre il DB);
il lock dell'app chiude la connessione.
"""
import re
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


class WrongPassword(Exception):
    pass


class DatabaseLocked(Exception):
    """Il DB è stato bloccato mentre la richiesta era in corso."""


def _require():
    if _conn is None:
        raise DatabaseLocked()
    return _conn


def _quote_key(password: str) -> str:
    return password.replace("'", "''")


def open_db(password: str, db_path: Path | None = None):
    """Apre (o crea al primo avvio) il DB cifrato. Solleva WrongPassword se la chiave è errata."""
    global _conn
    close_db()  # niente connessioni cifrate orfane in memoria
    path = Path(db_path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlcipher.connect(str(path), check_same_thread=False)
    conn.execute(f"PRAGMA key = '{_quote_key(password)}'")
    conn.execute("PRAGMA kdf_iter = 256000")
    try:
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlcipher.DatabaseError:
        conn.close()
        raise WrongPassword()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlcipher.Row
    with _lock:
        _conn = conn
    migrate()
    return conn


def close_db() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def is_open() -> bool:
    return _conn is not None


def db_exists(db_path: Path | None = None) -> bool:
    return Path(db_path or config.DB_PATH).exists()


def rekey(new_password: str) -> None:
    with _lock:
        _require().execute(f"PRAGMA rekey = '{_quote_key(new_password)}'")


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
