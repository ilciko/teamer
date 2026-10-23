"""Note 1:1 (con ricerca per parole) e azioni.

Sono di chi le scrive (classe `authored`, docs/perimetri.md): la vista mostra solo le proprie.
Quando la persona esce dal perimetro la vista `person` non la mostra più: il nome arriva da
`perim_note_person` e la nota resta in sola lettura (`outside`); un'azione si può ancora chiudere.
"""
from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import RedirectResponse

from app import db
from app.params import OptInt

router = APIRouter()


def _templates():
    from app.main import templates

    return templates


def _notes_url(q: str = "", person_id=None, anchor: int | None = None,
               archived: str = "") -> str:
    """Torna alla lista da cui si era partiti, sulla nota giusta."""
    params = {"q": q or "", "person_id": person_id or ""}
    if archived:
        params["archived"] = "1"
    return f"/notes?{urlencode(params)}" + (f"#nota-{anchor}" if anchor else "")


# nome della persona anche se è uscita dal perimetro (`outside` = 1), per note e azioni
_PERSON_NAME = ("COALESCE(p.full_name, np.full_name) AS full_name, p.id IS NULL AS outside")
_PERSON_JOIN = ("LEFT JOIN person p ON p.id = {a}.person_id "
                "LEFT JOIN perim_note_person np ON np.id = {a}.person_id")


def _note(nid: int):
    """Una nota propria di una persona ancora nel perimetro (le altre non si modificano)."""
    return db.one(
        f"""SELECT mn.*, {_PERSON_NAME} FROM meeting_note mn {_PERSON_JOIN.format(a='mn')}
            WHERE mn.id=? AND p.id IS NOT NULL""", (nid,))


@router.get("/notes")
def notes_list(request: Request, q: str = "", person_id: OptInt = None, archived: str = ""):
    """Le archiviate restano fuori (anche dalla ricerca) finché il toggle è spento."""
    params: list = []
    sql = f"""SELECT mn.*, {_PERSON_NAME} FROM meeting_note mn {_PERSON_JOIN.format(a='mn')} WHERE 1=1"""
    # ricerca per parole: ognuna deve comparire nel titolo o nel testo (niente sintassi da imparare)
    for word in q.split():
        like = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        sql += " AND (mn.title LIKE ? ESCAPE '\\' OR mn.body LIKE ? ESCAPE '\\')"
        params += [like, like]
    if person_id:
        sql += " AND mn.person_id=?"
        params.append(person_id)
    if not archived:
        sql += " AND mn.archived_at IS NULL"
    sql += " ORDER BY mn.note_date DESC, mn.id DESC LIMIT 100"
    rows = db.query(sql, tuple(params))
    notes = [n for n in rows if not n["outside"]]
    people = db.query("SELECT id, full_name FROM person ORDER BY full_name")
    return _templates().TemplateResponse(request, "notes.html", {
        "notes": notes, "outside_notes": [n for n in rows if n["outside"]],
        "q": q, "person_id": person_id, "people": people,
        "archived": "1" if archived else "",
        "person_name": next((pp["full_name"] for pp in people if pp["id"] == person_id), None),
    })


@router.get("/notes/report")
def notes_report(request: Request, person_id: OptInt = None, archived: str = ""):
    """Report stampabile (→ PDF dal browser): globale o del singolo dipendente,
    dal più recente. Stessi filtri della lista, esclusa la ricerca full-text."""
    sql = f"""SELECT mn.*, {_PERSON_NAME} FROM meeting_note mn {_PERSON_JOIN.format(a='mn')} WHERE 1=1"""
    params: list = []
    if person_id:
        sql += " AND mn.person_id=?"
        params.append(person_id)
    if not archived:
        sql += " AND mn.archived_at IS NULL"
    sql += " ORDER BY mn.note_date DESC, mn.id DESC"
    person = db.one("SELECT id, full_name FROM person WHERE id=? UNION ALL "
                    "SELECT id, full_name FROM perim_note_person WHERE id=?", (person_id, person_id)) \
        if person_id else None
    return _templates().TemplateResponse(request, "notes_report.html", {
        "notes": db.query(sql, tuple(params)), "person": person,
        "person_id": person_id, "archived": "1" if archived else "",
        "today": date.today(),
    })


async def _note_ids(request: Request) -> tuple[list[int], str]:
    form = await request.form()
    ids = [int(v) for v in form.getlist("ids") if str(v).isdigit()]
    back = _notes_url(form.get("f_q", ""), form.get("f_person_id", ""),
                      archived=form.get("f_archived", ""))
    return ids, back


@router.post("/notes/archivia")
async def notes_archive(request: Request):
    """Archivia le note selezionate. Chi era già archiviata tiene la sua data."""
    ids, back = await _note_ids(request)
    if ids:
        marks = ",".join("?" * len(ids))
        db.execute(
            f"UPDATE meeting_note SET archived_at=datetime('now','localtime') "
            f"WHERE archived_at IS NULL AND id IN ({marks})", tuple(ids))
    return RedirectResponse(back, status_code=302)


@router.post("/notes/ripristina")
async def notes_restore(request: Request):
    ids, back = await _note_ids(request)
    if ids:
        marks = ",".join("?" * len(ids))
        db.execute(f"UPDATE meeting_note SET archived_at=NULL WHERE id IN ({marks})", tuple(ids))
    return RedirectResponse(back, status_code=302)


@router.post("/notes")
def note_create(person_id: int = Form(...), note_date: str = Form(...),
                type: str = Form("1:1"), title: str = Form(None), body: str = Form(None),
                action_desc: str = Form(None), action_due: str = Form(None)):
    with db.transaction() as conn:
        cur = conn.execute(
            "INSERT INTO meeting_note (person_id, note_date, type, title, body) VALUES (?,?,?,?,?)",
            (person_id, note_date, type, title or None, body or None))
        if action_desc:
            conn.execute(
                "INSERT INTO action_item (meeting_note_id, person_id, description, due_date) "
                "VALUES (?,?,?,?)",
                (cur.lastrowid, person_id, action_desc, action_due or None))
    return RedirectResponse(f"/notes?person_id={person_id}", status_code=302)


@router.get("/notes/{nid}/modifica")
def note_edit_form(request: Request, nid: int, f_q: str = "", f_person_id: OptInt = None,
                   f_archived: str = ""):
    """Frammento htmx: la riga della nota diventa un form di correzione."""
    n = _note(nid)
    if not n:
        return Response(status_code=404)
    return _templates().TemplateResponse(request, "_note_edit.html", {
        "n": n,
        "people": db.query("SELECT id, full_name FROM person ORDER BY full_name"),
        "linked": db.query(
            "SELECT * FROM action_item WHERE meeting_note_id=? ORDER BY due_date", (nid,)),
        "f_q": f_q, "f_person_id": f_person_id, "f_archived": f_archived,
    })


@router.get("/notes/{nid}/riga")
def note_row(request: Request, nid: int, f_q: str = "", f_person_id: OptInt = None,
             f_archived: str = ""):
    """Annulla la modifica: torna la riga in sola lettura."""
    n = _note(nid)
    if not n:
        return Response(status_code=404)
    return _templates().TemplateResponse(request, "_note_row.html", {
        "n": n, "f_q": f_q, "f_person_id": f_person_id, "f_archived": f_archived})


@router.post("/notes/{nid}")
def note_update(nid: int, person_id: int = Form(...), note_date: str = Form(...),
                type: str = Form("1:1"), title: str = Form(None), body: str = Form(None),
                f_q: str = Form(""), f_person_id: str = Form(""), f_archived: str = Form("")):
    """Correzione in place. Il trigger FTS meeting_note_au riallinea la ricerca."""
    db.execute(
        "UPDATE meeting_note SET person_id=?, note_date=?, type=?, title=?, body=?, "
        "updated_at=datetime('now','localtime') WHERE id=?",
        (person_id, note_date, type, title or None, body or None, nid))
    return RedirectResponse(_notes_url(f_q, f_person_id, nid, f_archived), status_code=302)


@router.post("/notes/{nid}/delete")
def note_delete(nid: int, f_q: str = Form(""), f_person_id: str = Form(""),
                f_archived: str = Form("")):
    """Cancellazione definitiva (nota inserita per errore o duplicata).

    Gli impegni collegati non muoiono con la nota: si scollegano. Senza questo
    PRAGMA foreign_keys=ON farebbe fallire la DELETE, perché action_item.
    meeting_note_id non ha ON DELETE.
    """
    with db.transaction() as conn:
        conn.execute("UPDATE action_item SET meeting_note_id=NULL WHERE meeting_note_id=?", (nid,))
        conn.execute("DELETE FROM meeting_note WHERE id=?", (nid,))
    return RedirectResponse(_notes_url(f_q, f_person_id, archived=f_archived), status_code=302)


@router.get("/actions")
def actions_list(request: Request, show: str = "aperte"):
    where = "WHERE a.status != 'chiuso'" if show == "aperte" else ""
    actions = db.query(
        f"""SELECT a.*, {_PERSON_NAME} FROM action_item a {_PERSON_JOIN.format(a='a')} {where}
            ORDER BY CASE WHEN a.due_date IS NULL THEN 1 ELSE 0 END, a.due_date""")
    people = db.query("SELECT id, full_name FROM person WHERE status='attivo' ORDER BY full_name")
    return _templates().TemplateResponse(request, "actions.html", {
        "actions": actions, "show": show, "people": people, "today": date.today().isoformat(),
    })


@router.post("/actions")
def action_create(person_id: int = Form(...), description: str = Form(...),
                  due_date: str = Form(None)):
    db.execute(
        "INSERT INTO action_item (person_id, description, due_date) VALUES (?,?,?)",
        (person_id, description.strip(), due_date or None))
    return RedirectResponse("/actions", status_code=302)


@router.post("/actions/{aid}/status")
def action_status(aid: int, status: str = Form(...)):
    closed = date.today().isoformat() if status == "chiuso" else None
    db.execute("UPDATE action_item SET status=?, closed_date=? WHERE id=?", (status, closed, aid))
    return RedirectResponse("/actions", status_code=302)
