"""Registro delle pagine aperte e blocco automatico del database.

Niente timeout di inattività: finché almeno una pagina Teamer manda il suo
battito la sessione resta valida, anche per mezz'ora di scrittura senza un
click. Quando l'ultima pagina se ne va — addio esplicito alla chiusura del tab
o silenzio oltre la grazia — il reaper chiude *davvero* la connessione
SQLCipher, che è ciò che "Blocca" ha sempre promesso e mai fatto.
"""
import asyncio
import threading
import time

from app import config, db

# Dopo l'addio dell'ultima pagina non si blocca all'istante: un `pageshow` di
# ritorno (bfcache, "riapri scheda chiusa") fa in tempo a ripresentarsi.
BYE_GRACE_SECONDS = 5

_lock = threading.Lock()
_tabs: dict[str, float] = {}  # id scheda -> ultimo battito
_last_seen = 0.0              # battito, richiesta autenticata o login
_inflight = 0                 # richieste autenticate in corso
_bye = False                  # l'ultima scheda ha detto addio: grazia corta


def _now() -> float:
    return time.monotonic()


def touch_tab(tab_id: str) -> None:
    global _last_seen, _bye
    with _lock:
        _tabs[tab_id] = _now()
        _last_seen = _now()
        _bye = False


def drop_tab(tab_id: str) -> None:
    """Una scheda si è chiusa. Se ne restano altre non cambia nulla."""
    global _bye
    with _lock:
        _tabs.pop(tab_id, None)
        if not _tabs:
            _bye = True


def touch_request() -> None:
    """Una richiesta autenticata prova che una pagina è viva quanto un battito."""
    global _last_seen, _bye
    with _lock:
        _last_seen = _now()
        _bye = False


def enter() -> None:
    global _inflight
    with _lock:
        _inflight += 1


def leave() -> None:
    global _inflight
    with _lock:
        _inflight -= 1


def reset() -> None:
    """Login, lock manuale, sblocco: il registro riparte da zero."""
    global _last_seen, _bye
    with _lock:
        _tabs.clear()
        _last_seen = _now()
        _bye = False


def is_deserted() -> bool:
    """Vero se non c'è più nessuna pagina aperta là fuori."""
    now = _now()
    with _lock:
        if _inflight:  # non si chiude il DB sotto i piedi di una richiesta
            return False
        if any(now - ts <= config.LOCK_GRACE_SECONDS for ts in _tabs.values()):
            return False
        grace = BYE_GRACE_SECONDS if _bye else config.LOCK_GRACE_SECONDS
        return now - _last_seen > grace


def maybe_lock() -> bool:
    """Chiude il DB se nessuno lo sta più guardando. Sincrona: testabile."""
    if not db.is_open() or not is_deserted():
        return False
    db.close_db()
    reset()
    return True


async def reaper() -> None:
    """Task di background del lifespan."""
    while True:
        await asyncio.sleep(config.REAPER_TICK_SECONDS)
        try:
            # close_db() attende il lock del DB: in un thread, non nell'event loop.
            await asyncio.to_thread(maybe_lock)
        except Exception:  # il reaper non deve mai morire
            pass
