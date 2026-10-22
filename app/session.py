"""Sessioni degli utenti: registro delle pagine aperte e blocco automatico.

Niente timeout di inattività: finché almeno una pagina Teamer di quella sessione
manda il suo battito, la sessione resta valida, anche per mezz'ora di scrittura
senza un click. Quando l'ultima pagina se ne va — addio esplicito alla chiusura
del tab o silenzio oltre la grazia — il reaper **blocca quella sessione**: l'overlay
chiede di nuovo la password. Il DB resta aperto per gli altri utenti (la chiave è
di sistema, non dell'utente): il blocco di uno non tocca nessun altro.

Il registro vive in memoria: un riavvio del servizio blocca tutti.
"""
import asyncio
import secrets
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass, field

from app import config

# Dopo l'addio dell'ultima pagina non si blocca all'istante: un `pageshow` di
# ritorno (bfcache, "riapri scheda chiusa") fa in tempo a ripresentarsi.
BYE_GRACE_SECONDS = 5

_lock = threading.Lock()


def _now() -> float:
    return time.monotonic()


@dataclass
class Session:
    user_id: int
    username: str
    role: str
    ip: str | None = None
    id: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    tabs: dict = field(default_factory=dict)   # id scheda -> ultimo battito
    last_seen: float = field(default_factory=_now)  # battito, richiesta autenticata o login
    inflight: int = 0                           # richieste autenticate in corso
    bye: bool = False                           # l'ultima scheda ha detto addio: grazia corta
    locked: bool = False
    locked_at: float = 0.0


_sessions: dict[str, Session] = {}
_current: ContextVar[Session | None] = ContextVar("teamer_session", default=None)


# ---- registro ----

def create(user_id: int, username: str, role: str, ip: str | None = None) -> Session:
    s = Session(user_id=user_id, username=username, role=role, ip=ip)
    with _lock:
        _sessions[s.id] = s
    return s


def get(sid: str | None) -> Session | None:
    if not sid:
        return None
    with _lock:
        return _sessions.get(sid)


def drop(s: Session) -> None:
    with _lock:
        _sessions.pop(s.id, None)


def drop_user(user_id: int) -> int:
    """Utente disattivato o password resettata: le sue sessioni finiscono subito."""
    with _lock:
        ids = [sid for sid, s in _sessions.items() if s.user_id == user_id]
        for sid in ids:
            del _sessions[sid]
    return len(ids)


def of_user(user_id: int) -> list[Session]:
    with _lock:
        return [s for s in _sessions.values() if s.user_id == user_id]


def reset() -> None:
    """Tutte le sessioni via (test, spegnimento)."""
    with _lock:
        _sessions.clear()


# ---- sessione corrente (fissata dal middleware per la richiesta) ----

def bind(s: Session | None):
    return _current.set(s)


def unbind(token) -> None:
    _current.reset(token)


def current() -> Session | None:
    return _current.get()


# ---- presenza delle pagine ----

def touch_tab(s: Session, tab_id: str) -> None:
    with _lock:
        s.tabs[tab_id] = _now()
        s.last_seen = _now()
        s.bye = False


def drop_tab(s: Session, tab_id: str) -> None:
    """Una scheda si è chiusa. Se ne restano altre non cambia nulla."""
    with _lock:
        s.tabs.pop(tab_id, None)
        if not s.tabs:
            s.bye = True


def touch_request(s: Session) -> None:
    """Una richiesta autenticata prova che una pagina è viva quanto un battito."""
    with _lock:
        s.last_seen = _now()
        s.bye = False


def enter(s: Session) -> None:
    with _lock:
        s.inflight += 1


def leave(s: Session) -> None:
    with _lock:
        s.inflight -= 1


def lock(s: Session) -> None:
    with _lock:
        s.locked = True
        s.locked_at = _now()
        s.tabs.clear()


def unlock(s: Session) -> None:
    """Sblocco in place: il registro della sessione riparte da zero."""
    with _lock:
        s.locked = False
        s.tabs.clear()
        s.last_seen = _now()
        s.bye = False


def is_deserted(s: Session) -> bool:
    """Vero se non c'è più nessuna pagina di questa sessione aperta là fuori."""
    now = _now()
    with _lock:
        if s.inflight:  # non si blocca sotto i piedi di una richiesta
            return False
        if any(now - ts <= config.LOCK_GRACE_SECONDS for ts in s.tabs.values()):
            return False
        grace = BYE_GRACE_SECONDS if s.bye else config.LOCK_GRACE_SECONDS
        return now - s.last_seen > grace


def maybe_lock() -> list[Session]:
    """Blocca le sessioni che nessuno guarda più e dimentica quelle bloccate da ore. Sincrona: testabile."""
    with _lock:
        candidates = list(_sessions.values())
    locked = []
    for s in candidates:
        if s.locked:
            if _now() - s.locked_at > config.LOCKED_SESSION_HOURS * 3600:
                drop(s)
        elif is_deserted(s):
            lock(s)
            locked.append(s)
    return locked


async def reaper() -> None:
    """Task di background del lifespan."""
    from app import users

    while True:
        await asyncio.sleep(config.REAPER_TICK_SECONDS)
        try:
            for s in maybe_lock():
                await asyncio.to_thread(
                    users.audit, "lock", user_id=s.user_id, username=s.username,
                    detail="ultima pagina chiusa", ip=s.ip)
        except Exception:  # il reaper non deve mai morire
            pass
