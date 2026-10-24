"""Login, blocco, sessione e account.

Il DB è aperto dal servizio con la chiave di sistema; il login verifica la password
dell'utente (`app.users`) e apre una sessione (`app.session`). Il cookie firmato porta
solo l'id della sessione: il vero cancello è il registro in memoria, che il reaper
blocca quando l'ultima pagina di quella sessione si chiude.

Ruoli: l'admin (IT) vede solo il pannello `/admin` e il proprio account; il director
tutto il resto; HR tutto il resto tranne dashboard, report, simulazioni, verifica dei
riporti e configurazione, e scrive dentro `HR_WRITE_OK` (note e azioni, persone e contratti, piano e
budget; `allowed`); la parte contrattuale è solo sua (`CONTRACT_POST`: il director la legge).
"""
from urllib.parse import quote

import re

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer

from app import config, db, perimeter, session, users

router = APIRouter()

_signer = URLSafeSerializer(config.SECRET, salt="teamer-session")
COOKIE = "teamer_session"

# pagine dell'admin (oltre a quelle fuori dal guard): niente dati del personale
ADMIN_PREFIXES = ("/admin", "/account", "/lock")
HOME = {"admin": "/admin", "director": "/", "hr": "/"}
# HR (0.36): niente dashboard, report, simulazioni, verifica riporti, configurazione
HR_DENIED = ("/reports", "/org/sim", "/org/riporti", "/settings")
# le scritture di HR: il suo account, uscita, modalità pubblica, le sue note e azioni (0.37), le
# anteprime htmx (`*/simulate`), che calcolano e basta, e dalla 0.39 (tappa 3) persone e contratti,
# analisi salary, piano, budget aumenti e assunzioni (quelli dei director «in veste di») e il
# selettore del director
HR_WRITE_OK = ("/lock", "/account", "/public-mode", "/notes", "/actions", "/hr/acting",
               "/people", "/comp/salary", "/comp/plan", "/comp/budget", "/comp/hiring")
# ...ma non elimina persone né decide la sostituzione di chi cessa (è del director)
HR_WRITE_DENIED = re.compile(r"^/people/\d+/(delete|replacement)(/|$)")
# la parte contrattuale la scrive solo HR (0.39): il director la legge
CONTRACT_POST = re.compile(r"^/people/\d+/(ral|benefit|incentive|employment|cessation|director)(/|$)")


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


def request_session(request: Request) -> session.Session | None:
    """La sessione del cookie, anche se bloccata."""
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        data = _signer.loads(raw)
    except BadSignature:
        return None
    return session.get(data.get("sid") if isinstance(data, dict) else None)


def active_session(request: Request) -> session.Session | None:
    """Sessione valida: DB aperto, cookie nostro, sessione non bloccata. Nessuna scadenza."""
    if not db.is_open():
        return None
    s = request_session(request)
    return s if s is not None and not s.locked else None


def allowed(role: str, path: str, method: str = "GET") -> bool:
    from app.routers import company

    if path.startswith(company.PREFIX):  # configurazione aziendale: di chi la gestisce (oggi l'admin, poi HR)
        return role == company.MANAGED_BY
    if role == "admin":
        return path.startswith(ADMIN_PREFIXES)
    if path.startswith("/admin"):
        return False
    if role == "hr":
        if path.startswith(HR_DENIED):
            return False
        if method == "GET" or path.endswith("/simulate"):
            return True
        return path.startswith(HR_WRITE_OK) and not HR_WRITE_DENIED.match(path)
    if method != "GET" and CONTRACT_POST.match(path):
        return False
    return True


def set_cookie(response, s: session.Session) -> None:
    response.set_cookie(COOKIE, _signer.dumps({"sid": s.id}), httponly=True, samesite="lax")


def _open_session(request: Request, user) -> session.Session:
    old = request_session(request)
    if old is not None:
        session.drop(old)
    s = session.create(user["id"], user["username"], user["role"], client_ip(request))
    return s


def _landing(user) -> str:
    return "/account" if user["must_change_password"] else HOME[user["role"]]


def _login_ctx(**extra) -> dict:
    state = db.state()
    ctx = {"state": state, "error": None, "bloccato": 0, "username": ""}
    if state == "pronto" and users.count() == 0:
        ctx["state"] = "nessun_utente"
    ctx.update(extra)
    return ctx


@router.get("/login")
def login_page(request: Request, bloccato: int = 0, u: str = ""):
    from app.main import templates

    if active_session(request):
        return RedirectResponse("/", status_code=302)
    if db.state() in ("chiuso", "chiave_mancante"):  # l'IT può aver appena creato la chiave
        db.startup()
    resp = templates.TemplateResponse(request, "login.html", _login_ctx(bloccato=bloccato, username=u))
    if bloccato:
        resp.delete_cookie(COOKIE)  # cookie stantio: non serve più a niente
    return resp


@router.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form("")):
    from app.main import templates

    if db.state() != "pronto":
        return RedirectResponse("/login", status_code=302)
    user, error = users.authenticate(username, password, client_ip(request))
    if error:
        return templates.TemplateResponse(request, "login.html", _login_ctx(error=error, username=username))
    if user["role"] in perimeter.SESSION_ROLES:
        perimeter.ensure_config(user["id"])  # director di prima della 0.32: configurazione di default
    s = _open_session(request, user)
    users.audit("login_ok", user_id=user["id"], username=user["username"], ip=s.ip)
    resp = RedirectResponse(_landing(user), status_code=302)
    set_cookie(resp, s)
    return resp


@router.post("/login/migrazione")
def login_migration(request: Request, old_password: str = Form(...), username: str = Form(...),
                    display_name: str = Form("")):
    """DB delle versioni mono-utente: la password attuale lo ricifra sulla chiave di sistema.

    Chi la conosce diventa il primo director, con la stessa password (da cambiare se corta).
    """
    from app.main import templates

    if db.state() != "legacy":
        return RedirectResponse("/login", status_code=302)
    try:
        db.migrate_legacy(old_password)
    except db.WrongPassword:
        return templates.TemplateResponse(request, "login.html",
                                          _login_ctx(error="Password del database errata.", username=username))
    public_on = db.get_meta("public_mode", "0") == "1"
    db.sys.execute("DELETE FROM app_meta WHERE key='public_mode'")  # ora è per utente
    try:
        uid = users.create(username, "director", old_password, display_name,
                           must_change=users.password_error(old_password) is not None)
    except users.UserError as exc:
        return templates.TemplateResponse(request, "login.html", _login_ctx(error=str(exc), username=username))
    users.set_public_mode(uid, public_on)
    user = users.get(uid)
    s = _open_session(request, user)
    users.audit("migrazione_chiave", "DB ricifrato con la chiave di sistema", user_id=uid,
                username=user["username"], ip=s.ip)
    resp = RedirectResponse(_landing(user), status_code=302)
    set_cookie(resp, s)
    return resp


@router.post("/lock")
def lock(request: Request):
    """Blocca (chiude) la propria sessione; le altre non se ne accorgono."""
    s = request_session(request)
    dest = "/login"
    if s is not None:
        users.audit("logout", user_id=s.user_id, username=s.username, ip=s.ip)
        session.drop(s)
        dest = f"/login?u={quote(s.username)}"
    resp = RedirectResponse(dest, status_code=302)
    resp.delete_cookie(COOKIE)
    return resp


# ---- battito delle pagine aperte ----
#
# Queste route stanno fuori dal guard di `main` di proposito: devono rispondere
# sempre 200/JSON, anche a sessione bloccata. Con un redirect a /login la fetch del
# JS riceverebbe l'HTML del login (status 200) e non saprebbe distinguere "bloccato"
# da "tutto a posto" — e soprattutto una pagina con una nota a metà non deve mai
# essere trascinata via. L'autenticazione la fanno da sé con active_session().


@router.post("/heartbeat")
def heartbeat(request: Request, tab: str = Form(...)):
    # la versione serve alla pagina che aspetta la fine di un aggiornamento (cambia al riavvio)
    s = active_session(request)
    if s is None:
        return JSONResponse({"stato": "bloccato", "version": config.APP_VERSION})
    session.touch_tab(s, tab)
    return JSONResponse({"stato": "aperto", "version": config.APP_VERSION})


@router.post("/heartbeat/chiusa")
def heartbeat_bye(request: Request, tab: str = Form(...)):
    """Addio via sendBeacon: se era l'ultima scheda il blocco arriva subito."""
    s = active_session(request)
    if s is not None:
        session.drop_tab(s, tab)
    return Response(status_code=204)


@router.post("/unlock")
def unlock(request: Request, username: str = Form(""), password: str = Form(...)):
    """Sblocca senza ricaricare la pagina: il testo non salvato resta dov'è."""
    if active_session(request):
        return JSONResponse({"ok": True})
    if db.state() != "pronto":
        return JSONResponse({"ok": False, "errore": "Teamer non è pronto: ricarica la pagina."})
    old = request_session(request)
    if not username and old is not None:
        username = old.username
    user, error = users.authenticate(username, password, client_ip(request))
    if error:
        return JSONResponse({"ok": False, "errore": error})
    if old is not None and old.user_id == user["id"]:
        session.unlock(old)
        s = old
    else:  # servizio riavviato o un altro utente: sessione nuova
        s = _open_session(request, user)
    users.audit("unlock", user_id=user["id"], username=user["username"], ip=s.ip)
    resp = JSONResponse({"ok": True})
    set_cookie(resp, s)
    return resp


# ---- account (tutti i ruoli) ----


@router.get("/account")
def account_page(request: Request, saved: str = ""):
    from app.main import templates

    s = session.current()
    return templates.TemplateResponse(request, "account.html", {
        "u": users.get(s.user_id), "saved": saved, "min_len": users.MIN_PASSWORD,
        "roles": users.ROLES})


@router.post("/account/password")
def account_password(current: str = Form(...), new: str = Form(...), confirm: str = Form(...)):
    s = session.current()
    u = users.get(s.user_id)
    if not users.verify_password(current, u["password_hash"]):
        users.audit("password_change_ko", "password attuale errata")
        return RedirectResponse("/account?saved=wrongpw", status_code=302)
    if users.password_error(new, confirm):
        return RedirectResponse("/account?saved=err", status_code=302)
    if new == current:
        return RedirectResponse("/account?saved=same", status_code=302)
    users.set_password(u["id"], new)
    return RedirectResponse("/account?saved=1", status_code=302)
