"""Teamer — app FastAPI."""
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import auth, config, db, public, session
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


def _to_login(request: Request):
    """Cookie presente ma DB chiuso = sessione bloccata; altrimenti primo accesso."""
    dest = "/login?bloccato=1" if request.cookies.get(auth.COOKIE) else "/login"
    if request.headers.get("HX-Request"):
        return Response(status_code=200, headers={"HX-Redirect": dest})
    return RedirectResponse(dest, status_code=302)


def _public_blocked(request: Request):
    """Pagina riservata in modalità pubblica: la dashboard rimanda all'organigramma, il resto è 403."""
    if request.url.path == "/" and request.method == "GET" and not request.headers.get("HX-Request"):
        return RedirectResponse(public.HOME, status_code=302)
    if request.method != "GET" or request.headers.get("HX-Request"):
        return Response("Non disponibile in modalità pubblica", status_code=403)
    return templates.TemplateResponse(request, "public_blocked.html", {}, status_code=403)


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    if request.url.path.startswith(PUBLIC_PATHS):
        return await call_next(request)
    if not auth.session_valid(request):
        return _to_login(request)
    if db.is_open() and public.load() and public.is_blocked(request.url.path):
        return _public_blocked(request)
    session.touch_request()
    session.enter()
    try:
        response = await call_next(request)
    finally:
        session.leave()
    if db.is_open():
        # Non si rinnova il cookie che POST /lock ha appena cancellato.
        auth.refresh_cookie(response)
    # Le pagine sono dati riservati che cambiano a ogni salvataggio: mai dalla
    # cache del browser, o un tasto Indietro mostra numeri già superati.
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(db.DatabaseLocked)
async def _db_locked(request: Request, exc: db.DatabaseLocked):
    """Il DB si è chiuso a metà richiesta (lock manuale da un'altra scheda)."""
    return _to_login(request)


app.include_router(auth.router)
app.include_router(public.router)

from app.routers import (  # noqa: E402
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

app.include_router(reports.router)
app.include_router(org.router)
app.include_router(reorg.router)
app.include_router(compensation.router)
app.include_router(listino.router)
app.include_router(ninebox.router)
app.include_router(review.router)
app.include_router(interactions.router)
app.include_router(settings.router)
