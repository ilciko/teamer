"""Login, blocco e sessione.

Il login apre il DB cifrato con la passphrase: nessuna tabella utenti, la
password giusta è quella che decifra il file. La sessione non ha timeout di
inattività: il cookie firmato dice solo "questo browser ha fatto il login", e
il vero cancello è `db.is_open()`. Chi decide quando chiudere il DB è
`app.session` (battito delle pagine aperte + reaper).
"""
import time

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer

from app import config, db, session
from app.services.ninebox_defaults import ensure_default_model

router = APIRouter()

_signer = URLSafeSerializer(config.SECRET, salt="teamer-session")
COOKIE = "teamer_session"


def _make_cookie() -> str:
    return _signer.dumps({"ts": time.time()})


def session_valid(request: Request) -> bool:
    """Valida finché il DB è aperto e il cookie è nostro. Nessuna scadenza."""
    if not db.is_open():
        return False
    raw = request.cookies.get(COOKIE)
    if not raw:
        return False
    try:
        _signer.loads(raw)
    except BadSignature:
        return False
    return True


def refresh_cookie(response) -> None:
    response.set_cookie(COOKIE, _make_cookie(), httponly=True, samesite="lax")


@router.get("/login")
def login_page(request: Request, bloccato: int = 0):
    from app.main import templates

    if session_valid(request):
        return RedirectResponse("/", status_code=302)
    resp = templates.TemplateResponse(
        request, "login.html",
        {"first_run": not db.db_exists(), "error": None, "bloccato": bloccato},
    )
    if bloccato:
        resp.delete_cookie(COOKIE)  # cookie stantio: non serve più a niente
    return resp


@router.post("/login")
def login(request: Request, password: str = Form(...), password_confirm: str = Form(None)):
    from app.main import templates

    first_run = not db.db_exists()
    error = None
    if first_run:
        if not password or password != password_confirm:
            error = "Le password non coincidono."
        elif len(password) < 8:
            error = "Minimo 8 caratteri."
    if error is None:
        try:
            db.open_db(password)
            ensure_default_model()
        except db.WrongPassword:
            error = "Password errata."
    if error:
        return templates.TemplateResponse(
            request, "login.html", {"first_run": first_run, "error": error, "bloccato": 0}
        )
    session.reset()
    resp = RedirectResponse("/", status_code=302)
    refresh_cookie(resp)
    return resp


@router.post("/lock")
def lock():
    session.reset()
    db.close_db()
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE)
    return resp


# ---- battito delle pagine aperte ----
#
# Queste route stanno fuori dal guard di `main` di proposito: devono rispondere
# sempre 200/JSON, anche a DB bloccato. Con un redirect a /login la fetch del JS
# riceverebbe l'HTML del login (status 200) e non saprebbe distinguere "bloccato"
# da "tutto a posto" — e soprattutto una pagina con una nota a metà non deve mai
# essere trascinata via. L'autenticazione la fanno da sé con session_valid().


@router.post("/heartbeat")
def heartbeat(request: Request, tab: str = Form(...)):
    # la versione serve alla pagina che aspetta la fine di un aggiornamento (cambia al riavvio)
    if not session_valid(request):
        return JSONResponse({"stato": "bloccato", "version": config.APP_VERSION})
    session.touch_tab(tab)
    return JSONResponse({"stato": "aperto", "version": config.APP_VERSION})


@router.post("/heartbeat/chiusa")
def heartbeat_bye(request: Request, tab: str = Form(...)):
    """Addio via sendBeacon: se era l'ultima scheda il blocco arriva subito."""
    if session_valid(request):
        session.drop_tab(tab)
    return Response(status_code=204)


@router.post("/unlock")
def unlock(password: str = Form(...)):
    """Riapre il DB senza ricaricare la pagina: il testo non salvato resta dov'è."""
    if db.is_open():
        return JSONResponse({"ok": True})
    try:
        db.open_db(password)
        ensure_default_model()
    except db.WrongPassword:
        return JSONResponse({"ok": False, "errore": "Password errata."})
    session.reset()
    resp = JSONResponse({"ok": True})
    refresh_cookie(resp)
    return resp
