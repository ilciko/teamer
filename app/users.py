"""Utenti, password e audit.

La password di un utente non apre il DB (lo apre la chiave di sistema, vedi `db`):
qui ne sta solo l'hash scrypt. Ruoli:

- `admin`: site admin (IT). Utenti, audit, backup, aggiornamenti; nessun dato del personale.
- `director`: il COO. Tutto il resto, come nella versione mono-utente.

Gli utenti si correggono in place e si disattivano, non si cancellano: l'audit punta a
loro. `audit_event` è append-only.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from app import db, session

ROLES = {"admin": "Site admin", "director": "Director"}
MIN_PASSWORD = 12
MAX_FAILED = 5            # errori consecutivi prima del blocco temporaneo
MAX_LOCK_MINUTES = 60
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1
GENERIC_ERROR = "Nome utente o password errati."


class UserError(Exception):
    """Operazione rifiutata: il messaggio è per l'utente."""


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _ts(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S")


# ---- password ----

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, h = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calc.hex(), h)


def password_error(password: str, confirm: str | None = None) -> str | None:
    if confirm is not None and password != confirm:
        return "Le password non coincidono."
    if len(password or "") < MIN_PASSWORD:
        return f"La password deve avere almeno {MIN_PASSWORD} caratteri."
    return None


def temporary_password() -> str:
    return secrets.token_urlsafe(12)  # 16 caratteri


# ---- lettura ----

def get(uid: int):
    return db.one("SELECT * FROM app_user WHERE id=?", (uid,))


def by_username(username: str):
    return db.one("SELECT * FROM app_user WHERE username=?", ((username or "").strip(),))


def all_users() -> list:
    return db.query("SELECT * FROM app_user ORDER BY active DESC, role, username")


def count() -> int:
    return db.one("SELECT COUNT(*) AS n FROM app_user")["n"]


def active_admins() -> int:
    return db.one("SELECT COUNT(*) AS n FROM app_user WHERE role='admin' AND active=1")["n"]


# ---- audit ----

def audit(event: str, detail: str | None = None, *, user_id=None, username=None, ip=None) -> None:
    """Registra un evento. Senza utente esplicito usa la sessione della richiesta corrente."""
    s = session.current()
    if user_id is None and username is None and s is not None:
        user_id, username = s.user_id, s.username
    if ip is None and s is not None:
        ip = s.ip
    db.execute("INSERT INTO audit_event (user_id, username, event, detail, ip) VALUES (?,?,?,?,?)",
               (user_id, username, event, detail, ip))


def _target(u) -> str:
    return f"utente {u['username']}"


# ---- login ----

def authenticate(username: str, password: str, ip: str | None = None):
    """Ritorna (utente, None) o (None, messaggio). Applica e registra il backoff."""
    u = by_username(username)
    if u is None:
        audit("login_ko", "utente inesistente", username=(username or "").strip()[:64], ip=ip)
        return None, GENERIC_ERROR
    if u["locked_until"] and u["locked_until"] > _ts(_now()):
        audit("login_ko", "utente bloccato per troppi tentativi", user_id=u["id"], username=u["username"], ip=ip)
        return None, f"Troppi tentativi errati: riprova dopo le {u['locked_until'][11:16]} o chiedi lo sblocco all'IT."
    if not verify_password(password, u["password_hash"]):
        failed = u["failed_logins"] + 1
        locked_until = None
        if failed >= MAX_FAILED:
            minutes = min(2 ** (failed - MAX_FAILED), MAX_LOCK_MINUTES)
            locked_until = _ts(_now() + timedelta(minutes=minutes))
        db.execute("UPDATE app_user SET failed_logins=?, locked_until=? WHERE id=?", (failed, locked_until, u["id"]))
        audit("login_ko", f"password errata ({failed})", user_id=u["id"], username=u["username"], ip=ip)
        return None, GENERIC_ERROR
    if not u["active"]:
        audit("login_ko", "utente disattivato", user_id=u["id"], username=u["username"], ip=ip)
        return None, "Utente disattivato: rivolgiti all'IT."
    db.execute("UPDATE app_user SET failed_logins=0, locked_until=NULL, last_login_at=? WHERE id=?",
               (_ts(_now()), u["id"]))
    return get(u["id"]), None


# ---- gestione ----

def create(username: str, role: str, password: str, display_name: str | None = None,
           must_change: bool = False) -> int:
    username = (username or "").strip()
    if not username or len(username) > 64 or any(c.isspace() for c in username):
        raise UserError("Nome utente non valido (niente spazi, massimo 64 caratteri).")
    if role not in ROLES:
        raise UserError("Ruolo non valido.")
    if by_username(username):
        raise UserError(f"Il nome utente {username} esiste già.")
    uid = db.execute(
        "INSERT INTO app_user (username, display_name, role, password_hash, must_change_password, "
        "password_changed_at) VALUES (?,?,?,?,?,?)",
        (username, (display_name or "").strip() or None, role, hash_password(password),
         1 if must_change else 0, _ts(_now())))
    audit("user_create", f"utente {username} ({ROLES[role]})")
    return uid


def update(uid: int, display_name: str | None, role: str) -> None:
    u = get(uid)
    if role not in ROLES:
        raise UserError("Ruolo non valido.")
    if u["role"] == "admin" and role != "admin" and u["active"] and active_admins() <= 1:
        raise UserError("Deve restare almeno un site admin attivo.")
    db.execute("UPDATE app_user SET display_name=?, role=? WHERE id=?",
               ((display_name or "").strip() or None, role, uid))
    if role != u["role"]:
        session.drop_user(uid)  # il ruolo decide le pagine: si rientra
    audit("user_update", f"{_target(u)}: ruolo {ROLES[role]}")


def set_password(uid: int, new: str) -> None:
    """Cambio della propria password: toglie l'obbligo di cambiarla."""
    db.execute("UPDATE app_user SET password_hash=?, must_change_password=0, password_changed_at=? WHERE id=?",
               (hash_password(new), _ts(_now()), uid))
    audit("password_change", _target(get(uid)))


def reset_password(uid: int) -> str:
    """Reset dall'IT: password provvisoria da cambiare al primo accesso. Le sessioni aperte finiscono."""
    temp = temporary_password()
    db.execute("UPDATE app_user SET password_hash=?, must_change_password=1, failed_logins=0, "
               "locked_until=NULL, password_changed_at=? WHERE id=?",
               (hash_password(temp), _ts(_now()), uid))
    session.drop_user(uid)
    audit("password_reset", _target(get(uid)))
    return temp


def set_active(uid: int, active: bool) -> None:
    u = get(uid)
    if not active and u["role"] == "admin" and u["active"] and active_admins() <= 1:
        raise UserError("Deve restare almeno un site admin attivo.")
    db.execute("UPDATE app_user SET active=? WHERE id=?", (1 if active else 0, uid))
    if not active:
        session.drop_user(uid)
    audit("user_enable" if active else "user_disable", _target(u))


def unlock(uid: int) -> None:
    """Toglie il blocco per troppi tentativi."""
    db.execute("UPDATE app_user SET failed_logins=0, locked_until=NULL WHERE id=?", (uid,))
    audit("user_unlock", _target(get(uid)))


def set_public_mode(uid: int, on: bool) -> None:
    db.execute("UPDATE app_user SET public_mode=? WHERE id=?", (1 if on else 0, uid))
