"""Modalità pubblica: Teamer mostrabile su uno schermo condiviso.

In pubblica le pagine riservate non si aprono (né in lettura né in scrittura, export
compresi) e le cifre (RAL, costi, budget) delle pagine condivisibili sono oscurate dal
filtro `|eur`. Il flag è dell'utente (`app_user.public_mode`): sopravvive a riavvio e
blocco, così non si torna in chiaro per sbaglio a metà di una condivisione, e non oscura
le pagine degli altri utenti. Il middleware lo legge una volta per richiesta e lo mette
in una ContextVar, letta da filtri e template.
"""
import re
from contextvars import ContextVar

from fastapi import APIRouter, Form
from fastapi.responses import RedirectResponse

from app import session, users

# pagine riservate: bloccate in pubblica, qualunque metodo (anche export e download)
BLOCKED_PREFIXES = ("/reports", "/comp/salary", "/comp/plan", "/comp/budget", "/comp/bonus",
                    "/notes", "/actions", "/ninebox", "/cycles", "/settings", "/attachments")
# sotto-route della scheda persona con RAL, benefit, incentivi, allegati, sostituzione (RAL prevista)
BLOCKED_PERSON = re.compile(r"^/people/\d+/(ral|benefit|incentive|attachment|replacement)(/|$)")
HOME = "/org"

_public: ContextVar[bool] = ContextVar("teamer_public", default=False)


def load(user) -> bool:
    """Fissa per la richiesta corrente il flag dell'utente (riga di `app_user`)."""
    on = bool(user["public_mode"])
    _public.set(on)
    return on


def active() -> bool:
    """Modalità pubblica attiva nella richiesta corrente (global Jinja `public()`)."""
    return _public.get()


def is_blocked(path: str) -> bool:
    if path == "/":
        return True  # dashboard
    return path.startswith(BLOCKED_PREFIXES) or bool(BLOCKED_PERSON.match(path))


router = APIRouter()


@router.post("/public-mode")
def toggle(next: str = Form("/")):
    """Switch della barra laterale: accende o spegne la modalità pubblica."""
    uid = session.current().user_id
    on = not users.get(uid)["public_mode"]
    users.set_public_mode(uid, on)
    dest = next if next.startswith("/") and not next.startswith("//") else "/"
    if on and is_blocked(dest.split("?")[0]):
        dest = HOME
    return RedirectResponse(dest, status_code=302)
