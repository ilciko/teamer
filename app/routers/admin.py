"""Pannello del site admin (IT): utenti, audit, sistema (backup, aggiornamenti).

Nessun dato del personale passa da qui: il middleware tiene l'admin dentro `/admin`
e `/account`, il director fuori da `/admin`.
"""
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from app import config, db, perimeter, session, users
from app.services import updater

router = APIRouter()

AUDIT_PAGE = 100


def _back(tab: str = "users", **params) -> RedirectResponse:
    q = urlencode({"tab": tab, **{k: v for k, v in params.items() if v not in (None, "")}})
    return RedirectResponse(f"/admin?{q}", status_code=302)


def _audit_rows(user: str, event: str, date_from: str, date_to: str, page: int):
    where, params = [], []
    if user:
        where.append("username = ? COLLATE NOCASE")
        params.append(user)
    if event:
        where.append("event = ?")
        params.append(event)
    if date_from:
        where.append("at >= ?")
        params.append(date_from)
    if date_to:
        where.append("at < date(?, '+1 day')")
        params.append(date_to)
    sql_where = f"WHERE {' AND '.join(where)}" if where else ""
    total = db.sys.one(f"SELECT COUNT(*) AS n FROM audit_event {sql_where}", params)["n"]
    rows = db.sys.query(f"SELECT * FROM audit_event {sql_where} ORDER BY id DESC LIMIT ? OFFSET ?",
                    (*params, AUDIT_PAGE, (page - 1) * AUDIT_PAGE))
    return rows, total


@router.get("/admin")
def admin_page(request: Request, tab: str = "users", saved: str = "", err: str = "", restored: str = "",
               user: str = "", event: str = "", date_from: str = "", date_to: str = "", page: int = 1):
    from app.main import templates

    ctx = {"tab": tab, "saved": saved, "err": err, "restored": restored, "min_len": users.MIN_PASSWORD}
    if tab == "users":
        rows = users.all_users()
        ctx["users"] = rows
        ctx["sessions"] = {u["id"]: session.of_user(u["id"]) for u in rows}
        ctx["temp"] = request.cookies.get("teamer_temp_pw")  # mostrata una volta sola
        ctx["now"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ctx["unassigned"] = perimeter.unassigned()
        ctx["directors"] = [u for u in rows if u["role"] == "director" and u["active"]]
    elif tab == "audit":
        page = max(page, 1)
        rows, total = _audit_rows(user, event, date_from, date_to, page)
        ctx.update(rows=rows, total=total, page=page, pages=max(1, -(-total // AUDIT_PAGE)),
                   f={"user": user, "event": event, "date_from": date_from, "date_to": date_to},
                   events=[r["event"] for r in db.sys.query("SELECT DISTINCT event FROM audit_event ORDER BY event")])
    elif tab == "system":
        ctx["sys"] = {"version": config.APP_VERSION, "schema": db.schema_version(),
                      "db_path": config.DB_PATH, "key_file": config.DB_KEY_FILE,
                      "users": users.count()}
    elif tab == "update":
        ctx["upd"] = {"current": config.APP_VERSION, "latest": updater.latest(), "available": updater.available(),
                      "state": updater.state(), "log": updater.log_tail(), "can_request": updater.can_request(),
                      "pending": updater.pending(), "repo": updater.REPO, "backups": updater.backups()}
    resp = templates.TemplateResponse(request, "admin.html", ctx)
    if tab == "users" and ctx.get("temp"):
        resp.delete_cookie("teamer_temp_pw", path="/admin")
    return resp


# ---- utenti ----

def _with_temp(resp: RedirectResponse, username: str, temp: str) -> RedirectResponse:
    """La password provvisoria passa in un cookie breve (mai nell'URL né nel log) e si legge una volta."""
    resp.set_cookie("teamer_temp_pw", f"{username}:{temp}", max_age=120, httponly=True,
                    samesite="strict", path="/admin")
    return resp


@router.post("/admin/users")
def user_create(username: str = Form(...), display_name: str = Form(""), role: str = Form(...)):
    temp = users.temporary_password()
    try:
        users.create(username, role, temp, display_name, must_change=True)
    except users.UserError as exc:
        return _back(err=str(exc))
    return _with_temp(_back(saved="creato"), username.strip(), temp)


@router.post("/admin/users/{uid}/update")
def user_update(uid: int, display_name: str = Form(""), role: str = Form(...)):
    try:
        users.update(uid, display_name, role)
    except users.UserError as exc:
        return _back(err=str(exc))
    return _back(saved="1")


@router.post("/admin/users/{uid}/reset")
def user_reset(uid: int):
    u = users.get(uid)
    temp = users.reset_password(uid)
    return _with_temp(_back(saved="reset"), u["username"], temp)


@router.post("/admin/users/{uid}/active")
def user_active(uid: int, active: int = Form(...)):
    if not active and uid == session.current().user_id:
        return _back(err="Non puoi disattivare il tuo stesso utente.")
    try:
        users.set_active(uid, bool(active))
    except users.UserError as exc:
        return _back(err=str(exc))
    return _back(saved="1")


@router.post("/admin/users/{uid}/unlock")
def user_unlock(uid: int):
    users.unlock(uid)
    return _back(saved="1")


@router.post("/admin/users/{uid}/sessions/close")
def user_sessions_close(uid: int):
    me = session.current()
    n = 0
    for s in session.of_user(uid):
        if s.id != me.id:  # la propria sessione si chiude con «Esci»
            session.drop(s)
            n += 1
    users.audit("sessions_close", f"utente {users.get(uid)['username']}: {n} sessioni chiuse")
    return _back(saved="1")


@router.post("/admin/assign")
def assign(user_id: int = Form(...), confirm: str = Form("")):
    """Dati esistenti senza proprietario (dopo la 0.32, o un ripristino da altrove) a un director."""
    u = users.get(user_id)
    if u is None or u["role"] != "director" or not u["active"]:
        return _back(err="Scegli un director attivo.")
    if confirm != "ASSEGNA":
        return _back(err="Per assegnare scrivi ASSEGNA nel campo di conferma.")
    counts = perimeter.assign_unassigned(user_id)
    users.audit("assign_unassigned", f"a {u['username']}: " + ", ".join(
        f"{label} {counts[t]}" for t, label, _ in perimeter.UNASSIGNED_GROUPS if counts.get(t)) or "solo configurazione")
    return _back(saved="assegnati")


# ---- sistema ----

@router.post("/admin/backup")
def backup():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = Path(config.DB_PATH).parent / "backup" / f"teamer-{stamp}.db"
    db.backup_to(dest)
    users.audit("backup", dest.name)
    return FileResponse(dest, filename=dest.name, media_type="application/octet-stream")


@router.post("/admin/restore")
async def restore(file: UploadFile, source_key: str = Form(""), password: str = Form(""),
                  confirm: str = Form("")):
    """Ripristino o import una tantum: i dati arrivano dal file, utenti e audit restano questi."""
    if confirm != "SOSTITUISCI":
        return _back("system", err="Per ripristinare scrivi SOSTITUISCI nel campo di conferma.")
    upload = Path(config.DB_PATH).parent / "restore" / "upload.db"
    upload.parent.mkdir(parents=True, exist_ok=True)
    upload.write_bytes(await file.read())
    try:
        stats = db.restore(upload, source_key=source_key or None, password=password or None)
    except db.WrongPassword:
        return _back("system", err="Il file non si apre con la chiave o la password indicate "
                                   "(o non è un database cifrato di Teamer).")
    except db.RestoreError as exc:
        return _back("system", err=str(exc))
    finally:
        upload.unlink(missing_ok=True)
    origine = "password 0.29" if password else "chiave di un'altra istanza" if source_key else "chiave di questa istanza"
    users.audit("restore", f"{file.filename} (schema {stats['from_version']}, {origine}): "
                           f"{stats['summary']}; copia precedente {stats['backup']}")
    return _back("system", restored=f"{stats['summary']}; "
                                     f"il database precedente è in data/backups/{stats['backup']}")


@router.post("/admin/update/check")
def update_check():
    updater.check()
    return _back("update")


@router.post("/admin/update/run")
def update_run():
    """Chiede l'aggiornamento all'updater di sistema (path unit, root): l'app non ha i privilegi per farlo."""
    ok = updater.request_update()
    if ok:
        users.audit("update_request", f"da {config.APP_VERSION}")
    return _back("update", saved="avviato" if ok else "err")
