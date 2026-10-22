"""Teamer — app FastAPI."""
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import auth, config, db, public, session, users
from app.services import updater

APP_DIR = Path(__file__).resolve().parent


async def _update_checker():
    """Controllo della versione: poco dopo l'avvio e poi una volta al giorno (solo avviso)."""
    await asyncio.sleep(updater.FIRST_CHECK_DELAY_SECONDS)
    while True:
        await asyncio.to_thread(updater.check)
        await asyncio.sleep(updater.CHECK_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.startup()  # chiave di sistema su file: il DB resta aperto finché gira il servizio
    task = asyncio.create_task(session.reaper()) if config.AUTOLOCK else None
    # in sviluppo (sorgenti non installati) non c'è una versione da confrontare
    checker = asyncio.create_task(_update_checker()) if config.APP_VERSION != "dev" and config.UPDATE_CHECK else None
    try:
        yield
    finally:
        if checker:
            checker.cancel()
        if task:
            task.cancel()
        session.reset()
        db.close_db()  # spegnimento pulito: niente DB decifrato appeso


app = FastAPI(title="Teamer", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

templates = Jinja2Templates(directory=APP_DIR / "templates")


def fmt_eur(value) -> str:
    if value is None:
        return "—"
    value = float(value)
    s = f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"€ {s}"


def fmt_date(value) -> str:
    if not value:
        return "—"
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return str(value)


def fmt_eur_masked(value) -> str:
    """`|eur`: in modalità pubblica le cifre (RAL, costi, budget) non si vedono."""
    return "•••" if public.active() else fmt_eur(value)


import json as _json

templates.env.filters["eur"] = fmt_eur_masked
templates.env.filters["eur_plain"] = fmt_eur  # cifre mostrabili anche in pubblica (tariffe di listino)
templates.env.globals["public"] = public.active
templates.env.globals["current_user"] = session.current
templates.env.globals["roles"] = users.ROLES
templates.env.globals["update_available"] = updater.available
templates.env.filters["dt"] = fmt_date
templates.env.filters["from_json"] = _json.loads
templates.env.globals["lookups"] = db.lookups
templates.env.globals["lookup_label"] = db.lookup_label
templates.env.globals["meta"] = db.get_meta
templates.env.globals["today"] = lambda: date.today().isoformat()
templates.env.globals["heartbeat_seconds"] = lambda: config.HEARTBEAT_SECONDS
templates.env.globals["asset_v"] = lambda: config.APP_VERSION

# /heartbeat e /unlock si autenticano da soli e rispondono sempre JSON: passare
# dal guard li farebbe redirigere a /login, e una pagina con una nota a metà non
# deve mai essere trascinata via da una richiesta di sfondo.
PUBLIC_PATHS = ("/login", "/unlock", "/heartbeat", "/static", "/favicon.ico")
# POST che calcolano e basta (anteprime htmx): non sono azioni da mettere nell'audit
AUDIT_SKIP = ("/lock",)
AUDIT_SKIP_SUFFIX = ("/simulate",)


def _redirect(request: Request, dest: str):
    if request.headers.get("HX-Request"):
        return Response(status_code=200, headers={"HX-Redirect": dest})
    return RedirectResponse(dest, status_code=302)


def _to_login(request: Request):
    """Cookie presente ma sessione bloccata o finita; altrimenti primo accesso."""
    return _redirect(request, "/login?bloccato=1" if request.cookies.get(auth.COOKIE) else "/login")


def _forbidden(request: Request, role: str):
    """Pagina fuori dal ruolo: l'admin non vede i dati del personale, il director non il pannello IT."""
    if request.url.path == "/" and request.method == "GET" and not request.headers.get("HX-Request"):
        return RedirectResponse(auth.HOME[role], status_code=302)
    if request.method != "GET" or request.headers.get("HX-Request"):
        return Response("Non disponibile per il tuo ruolo", status_code=403)
    return templates.TemplateResponse(request, "forbidden.html", {"home": auth.HOME[role]}, status_code=403)


def _public_blocked(request: Request):
    """Pagina riservata in modalità pubblica: la dashboard rimanda all'organigramma, il resto è 403."""
    if request.url.path == "/" and request.method == "GET" and not request.headers.get("HX-Request"):
        return RedirectResponse(public.HOME, status_code=302)
    if request.method != "GET" or request.headers.get("HX-Request"):
        return Response("Non disponibile in modalità pubblica", status_code=403)
    return templates.TemplateResponse(request, "public_blocked.html", {}, status_code=403)


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    if path.startswith(PUBLIC_PATHS):
        return await call_next(request)
    s = auth.active_session(request)
    if s is None:
        return _to_login(request)
    token = session.bind(s)
    try:
        user = users.get(s.user_id)
        if user is None or not user["active"]:
            session.drop(s)
            return _to_login(request)
        if user["must_change_password"] and not path.startswith(("/account", "/lock")):
            return _redirect(request, "/account")
        if not auth.allowed(s.role, path):
            return _forbidden(request, s.role)
        if public.load(user) and public.is_blocked(path):
            return _public_blocked(request)
        session.touch_request(s)
        session.enter(s)
        try:
            response = await call_next(request)
        finally:
            session.leave(s)
        if request.method != "GET" and path not in AUDIT_SKIP and not path.endswith(AUDIT_SKIP_SUFFIX) \
                and db.is_open():
            # chi ha fatto cosa, mai il contenuto: il corpo può avere cifre riservate
            users.audit("azione", f"{request.method} {path} → {response.status_code}")
    finally:
        session.unbind(token)
    # Le pagine sono dati riservati che cambiano a ogni salvataggio: mai dalla
    # cache del browser, o un tasto Indietro mostra numeri già superati.
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(db.sqlcipher.IntegrityError)
async def _out_of_perimeter(request: Request, exc: db.sqlcipher.IntegrityError):
    """Una guardia del perimetro ha fermato una scrittura (ultima difesa: l'interfaccia non la offre)."""
    if "fuori perimetro" not in str(exc):
        raise exc
    return Response("Operazione non consentita", status_code=403)


@app.exception_handler(db.DatabaseLocked)
async def _db_locked(request: Request, exc: db.DatabaseLocked):
    """Il DB non è aperto (chiave mancante, migrazione da fare, spegnimento)."""
    return _to_login(request)


app.include_router(auth.router)
app.include_router(public.router)

from app.routers import (  # noqa: E402
    admin,
    compensation,
    interactions,
    listino,
    ninebox,
    org,
    reorg,
    reports,
    review,
    settings,
)

app.include_router(admin.router)
app.include_router(reports.router)
app.include_router(org.router)
app.include_router(reorg.router)
app.include_router(compensation.router)
app.include_router(listino.router)
app.include_router(ninebox.router)
app.include_router(review.router)
app.include_router(interactions.router)
app.include_router(settings.router)
