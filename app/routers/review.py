"""Ciclo annuale: cicli, obiettivi, performance review, benessere."""
from datetime import date, datetime

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from app import db
from app.services import goal_score

router = APIRouter()


def _templates():
    from app.main import templates

    return templates


@router.get("/cycles")
def cycles_list(request: Request):
    cycles = []
    for c in db.query("SELECT * FROM review_cycle ORDER BY year DESC, id DESC"):
        stats = db.one(
            """SELECT
                 (SELECT COUNT(DISTINCT person_id) FROM goal WHERE cycle_id=? AND voided=0) AS with_goals,
                 (SELECT COUNT(*) FROM performance_review WHERE cycle_id=? AND voided=0 AND status='finalizzata') AS done,
                 (SELECT COUNT(*) FROM performance_review WHERE cycle_id=? AND voided=0) AS started""",
            (c["id"], c["id"], c["id"]))
        cycles.append({**dict(c), **dict(stats)})
    return _templates().TemplateResponse(request, "cycles.html", {"cycles": cycles})


@router.post("/cycles")
def cycle_create(name: str = Form(...), year: int = Form(...)):
    cid = db.execute("INSERT INTO review_cycle (name, year) VALUES (?,?)", (name, year))
    return RedirectResponse(f"/cycles/{cid}", status_code=302)


@router.post("/cycles/{cid}/close")
def cycle_close(cid: int):
    db.execute("UPDATE review_cycle SET status='chiuso' WHERE id=?", (cid,))
    return RedirectResponse(f"/cycles/{cid}", status_code=302)


@router.post("/cycles/{cid}/riapri")
def cycle_reopen(cid: int):
    """Un ciclo chiuso per sbaglio non deve essere un vicolo cieco."""
    db.execute("UPDATE review_cycle SET status='aperto' WHERE id=?", (cid,))
    return RedirectResponse(f"/cycles/{cid}", status_code=302)


@router.post("/cycles/{cid}/update")
def cycle_update(cid: int, name: str = Form(...), year: int = Form(...)):
    """Correzione di nome/anno: errore di inserimento, non cambiamento reale."""
    db.execute("UPDATE review_cycle SET name=?, year=? WHERE id=?", (name.strip(), year, cid))
    return RedirectResponse(f"/cycles/{cid}", status_code=302)


@router.get("/cycles/{cid}")
def cycle_detail(request: Request, cid: int):
    c = db.one("SELECT * FROM review_cycle WHERE id=?", (cid,))
    if not c:
        return RedirectResponse("/cycles", status_code=302)
    rows = db.query(
        """SELECT p.id, p.full_name,
             (SELECT COUNT(*) FROM goal g WHERE g.person_id=p.id AND g.cycle_id=? AND g.voided=0) AS n_goals,
             (SELECT status FROM performance_review pr WHERE pr.person_id=p.id AND pr.cycle_id=? AND pr.voided=0) AS review_status,
             (SELECT overall_rating FROM performance_review pr WHERE pr.person_id=p.id AND pr.cycle_id=? AND pr.voided=0) AS rating
           FROM person p WHERE p.status='attivo' ORDER BY p.full_name""",
        (cid, cid, cid))
    people = []
    for r in rows:
        active = [dict(g) for g in db.query(
            "SELECT category, weight_pct FROM goal "
            "WHERE person_id=? AND cycle_id=? AND voided=0 AND status='attivo'", (r["id"], cid))]
        people.append({**dict(r),
                       "weight_sums": goal_score.weights_by_category(active),
                       "weight_ok": goal_score.weights_complete(active) if active else False})
    return _templates().TemplateResponse(request, "cycle_detail.html", {"c": c, "people": people})


@router.get("/cycles/{cid}/person/{pid}")
def cycle_person(request: Request, cid: int, pid: int):
    c = db.one("SELECT * FROM review_cycle WHERE id=?", (cid,))
    p = db.one("SELECT * FROM person WHERE id=?", (pid,))
    if not c or not p:
        return RedirectResponse("/cycles", status_code=302)
    # obiettivi definiti IN questo ciclo (per l'anno successivo)
    goals_defined = db.query(
        "SELECT * FROM goal WHERE person_id=? AND cycle_id=? AND voided=0 ORDER BY category, id",
        (pid, cid))
    # obiettivi da valutare: definiti nel ciclo dell'anno precedente
    prev = db.one(
        "SELECT * FROM review_cycle WHERE year < ? ORDER BY year DESC LIMIT 1", (c["year"],))
    review = db.one(
        "SELECT * FROM performance_review WHERE person_id=? AND cycle_id=? AND voided=0", (pid, cid))
    goals_to_review, reviews_map = [], {}
    if prev:
        goals_to_review = db.query(
            "SELECT * FROM goal WHERE person_id=? AND cycle_id=? AND voided=0 AND status='attivo' "
            "ORDER BY category, id", (pid, prev["id"]))
        if review:
            for gr in db.query(
                    "SELECT * FROM goal_review WHERE review_id=?", (review["id"],)):
                reviews_map[gr["goal_id"]] = gr
    wellbeing = None
    if review:
        wellbeing = db.one("SELECT * FROM wellbeing_entry WHERE review_id=?", (review["id"],))
    tl_totals, self_totals = _totali(pid, cid)
    active_defined = [dict(g) for g in goals_defined if g["status"] == "attivo"]
    weight_sums = goal_score.weights_by_category(active_defined)
    weight_ok = goal_score.weights_complete(active_defined) if active_defined else False
    attachments = []
    if review:
        attachments = db.query(
            "SELECT id, filename, note FROM attachment WHERE review_id=?", (review["id"],))
    return _templates().TemplateResponse(request, "cycle_person.html", {
        "c": c, "p": p, "prev": prev,
        "goals_defined": goals_defined, "weight_ok": weight_ok,
        "weight_sums": weight_sums,
        "goals_to_review": goals_to_review, "reviews_map": reviews_map,
        "review": review, "wellbeing": wellbeing,
        "tl_totals": tl_totals, "self_totals": self_totals,
        "attachments": attachments,
    })


@router.post("/cycles/{cid}/person/{pid}/goal")
def goal_create(cid: int, pid: int, description: str = Form(...), category: str = Form(...),
                weight_pct: float = Form(...), note: str = Form(None)):
    db.execute(
        "INSERT INTO goal (person_id, cycle_id, category, description, weight_pct, note) "
        "VALUES (?,?,?,?,?,?)",
        (pid, cid, category, description.strip(), weight_pct, note or None))
    return RedirectResponse(f"/cycles/{cid}/person/{pid}", status_code=302)


@router.post("/cycles/{cid}/person/{pid}/goal/{gid}/update")
def goal_update(cid: int, pid: int, gid: int, description: str = Form(...),
                category: str = Form(...), weight_pct: float = Form(...),
                note: str = Form(None)):
    """Correzione in place: un peso sbagliato o un refuso non valgono un void.

    Il cambiamento reale (obiettivo diverso) è "Aggiungi obiettivo".
    """
    db.execute(
        "UPDATE goal SET category=?, description=?, weight_pct=?, note=? "
        "WHERE id=? AND person_id=? AND cycle_id=?",
        (category, description.strip(), weight_pct, note or None, gid, pid, cid))
    return RedirectResponse(f"/cycles/{cid}/person/{pid}", status_code=302)


@router.post("/cycles/{cid}/person/{pid}/goal/{gid}/void")
def goal_void(cid: int, pid: int, gid: int, reason: str = Form("")):
    with db.transaction() as conn:
        conn.execute(
            "UPDATE goal SET voided=1, void_reason=? WHERE id=? AND person_id=? AND cycle_id=?",
            (reason.strip() or "annullato da UI", gid, pid, cid))
        # i punteggi seguono l'obiettivo: senza questo resterebbero orfani e
        # tornerebbero a galla se l'obiettivo venisse ripristinato
        conn.execute("DELETE FROM goal_review WHERE goal_id=?", (gid,))
    return RedirectResponse(f"/cycles/{cid}/person/{pid}", status_code=302)


def _totali(pid: int, cid: int) -> tuple[dict, dict]:
    """Punteggi complessivi per categoria (professionale ≠ personale, mai sommati)."""
    prev = db.one("SELECT * FROM review_cycle WHERE year < (SELECT year FROM review_cycle "
                  "WHERE id=?) ORDER BY year DESC LIMIT 1", (cid,))
    review = db.one(
        "SELECT id FROM performance_review WHERE person_id=? AND cycle_id=? AND voided=0",
        (pid, cid))
    if not prev:
        return {}, {}
    scores = {}
    if review:
        scores = {gr["goal_id"]: gr for gr in db.query(
            "SELECT * FROM goal_review WHERE review_id=?", (review["id"],))}
    items_by_cat: dict = {}
    for g in db.query(
            "SELECT * FROM goal WHERE person_id=? AND cycle_id=? AND voided=0 AND status='attivo' "
            "ORDER BY category, id", (pid, prev["id"])):
        gr = scores.get(g["id"])
        items_by_cat.setdefault(g["category"], []).append({
            "weight_pct": g["weight_pct"],
            "tl_score": gr["tl_score"] if gr else None,
            "self_score": gr["self_score"] if gr else None,
        })
    return (
        {cat: goal_score.weighted_score(i, "tl_score") for cat, i in items_by_cat.items()},
        {cat: goal_score.weighted_score(i, "self_score") for cat, i in items_by_cat.items()},
    )


def _salvato(request: Request, cid: int, pid: int, template: str):
    """Risposta a un salvataggio htmx: nessun redirect, così il testo digitato
    negli altri form della pagina non viene buttato via."""
    tl_totals, self_totals = _totali(pid, cid)
    return _templates().TemplateResponse(request, template, {
        "ora": datetime.now().strftime("%H:%M"),
        "tl_totals": tl_totals, "self_totals": self_totals,
    })


def _ensure_review(pid: int, cid: int) -> int:
    r = db.one(
        "SELECT id FROM performance_review WHERE person_id=? AND cycle_id=? AND voided=0",
        (pid, cid))
    if r:
        return r["id"]
    return db.execute(
        "INSERT INTO performance_review (person_id, cycle_id, review_date) VALUES (?,?,?)",
        (pid, cid, date.today().isoformat()))


@router.post("/cycles/{cid}/person/{pid}/goal-scores")
async def goal_scores_save(request: Request, cid: int, pid: int):
    form = await request.form()
    rid = _ensure_review(pid, cid)
    with db.transaction() as conn:
        for key, val in form.items():
            if not key.startswith(("self_", "tl_", "note_")):
                continue
            field, _, gid = key.partition("_")
            gid = int(gid)
            conn.execute(
                "INSERT INTO goal_review (goal_id, review_id) VALUES (?,?) "
                "ON CONFLICT(goal_id, review_id) DO NOTHING", (gid, rid))
            col = {"self": "self_score", "tl": "tl_score", "note": "note"}[field]
            if field in ("self", "tl"):
                val = float(val) if val else None
            conn.execute(
                f"UPDATE goal_review SET {col}=? WHERE goal_id=? AND review_id=?",
                (val or None, gid, rid))
    if request.headers.get("HX-Request"):
        return _salvato(request, cid, pid, "_totali_obiettivi.html")
    return RedirectResponse(f"/cycles/{cid}/person/{pid}", status_code=302)


@router.post("/cycles/{cid}/person/{pid}/review")
def review_save(request: Request, cid: int, pid: int, review_date: str = Form(None),
                overall_rating: str = Form(None),
                overall_employee_comment: str = Form(None), overall_tl_comment: str = Form(None),
                growth_self_comment: str = Form(None), growth_tl_comment: str = Form(None),
                synthesis_employee_comment: str = Form(None), synthesis_tl_comment: str = Form(None),
                finalize: str = Form(None)):
    rid = _ensure_review(pid, cid)
    db.execute(
        """UPDATE performance_review SET review_date=?, overall_rating=?,
           overall_employee_comment=?, overall_tl_comment=?,
           growth_self_comment=?, growth_tl_comment=?,
           synthesis_employee_comment=?, synthesis_tl_comment=?, status=?
           WHERE id=?""",
        (review_date or date.today().isoformat(),
         int(overall_rating) if overall_rating else None,
         overall_employee_comment or None, overall_tl_comment or None,
         growth_self_comment or None, growth_tl_comment or None,
         synthesis_employee_comment or None, synthesis_tl_comment or None,
         "finalizzata" if finalize else "bozza", rid))
    if request.headers.get("HX-Request") and not finalize:
        # Solo "Salva bozza" passa da htmx. La finalizzazione è un submit
        # classico apposta: htmx non manda il valore del bottone, quindi con un
        # hx-post sul form "Finalizza" arriverebbe senza finalize=1 e la review
        # resterebbe bozza, sparendo dal montepremi in silenzio.
        return _salvato(request, cid, pid, "_stato_salvataggio.html")
    return RedirectResponse(f"/cycles/{cid}/person/{pid}", status_code=302)


@router.post("/cycles/{cid}/person/{pid}/review/void")
def review_void(cid: int, pid: int, reason: str = Form("")):
    """Annulla la review (avviata per errore, o sulla persona sbagliata).

    Serve perché _ensure_review la crea come effetto collaterale anche solo
    salvando il benessere o un punteggio: senza questa strada quella riga
    marcherebbe per sempre la persona come "review avviata".
    """
    db.execute(
        "UPDATE performance_review SET voided=1, void_reason=? "
        "WHERE person_id=? AND cycle_id=? AND voided=0",
        (reason.strip() or "annullata da UI", pid, cid))
    return RedirectResponse(f"/cycles/{cid}/person/{pid}", status_code=302)


@router.post("/cycles/{cid}/person/{pid}/review/riapri")
def review_reopen(cid: int, pid: int):
    """Riporta in bozza una review finalizzata, per correggerla.

    Esplicito di proposito: la de-finalizzazione cambia il montepremi, che pesca
    solo le review finalizzate. Non deve mai essere un effetto collaterale.
    """
    db.execute(
        "UPDATE performance_review SET status='bozza' "
        "WHERE person_id=? AND cycle_id=? AND voided=0", (pid, cid))
    return RedirectResponse(f"/cycles/{cid}/person/{pid}", status_code=302)


@router.post("/cycles/{cid}/person/{pid}/wellbeing")
def wellbeing_save(request: Request, cid: int, pid: int,
                   workload_rating: str = Form(None), workload_employee_comment: str = Form(None),
                   workload_tl_comment: str = Form(None),
                   satisfaction_rating: str = Form(None), satisfaction_employee_comment: str = Form(None),
                   satisfaction_tl_comment: str = Form(None),
                   wlb_resources: str = Form(None), wlb_resources_note: str = Form(None),
                   wlb_time_difficulty: str = Form(None), wlb_time_note: str = Form(None),
                   wlb_balance: str = Form(None), wlb_balance_note: str = Form(None),
                   tl_comment: str = Form(None)):
    rid = _ensure_review(pid, cid)

    def flag(v):
        return None if v in (None, "") else int(v)

    with db.transaction() as conn:
        conn.execute("INSERT OR IGNORE INTO wellbeing_entry (review_id) VALUES (?)", (rid,))
        conn.execute(
            """UPDATE wellbeing_entry SET workload_rating=?, workload_employee_comment=?,
               workload_tl_comment=?, satisfaction_rating=?, satisfaction_employee_comment=?,
               satisfaction_tl_comment=?, wlb_resources=?, wlb_resources_note=?,
               wlb_time_difficulty=?, wlb_time_note=?, wlb_balance=?, wlb_balance_note=?,
               tl_comment=? WHERE review_id=?""",
            (workload_rating or None, workload_employee_comment or None, workload_tl_comment or None,
             satisfaction_rating or None, satisfaction_employee_comment or None,
             satisfaction_tl_comment or None,
             flag(wlb_resources), wlb_resources_note or None,
             flag(wlb_time_difficulty), wlb_time_note or None,
             flag(wlb_balance), wlb_balance_note or None,
             tl_comment or None, rid))
    if request.headers.get("HX-Request"):
        return _salvato(request, cid, pid, "_stato_salvataggio.html")
    return RedirectResponse(f"/cycles/{cid}/person/{pid}", status_code=302)


@router.post("/cycles/{cid}/person/{pid}/wellbeing/azzera")
def wellbeing_reset(cid: int, pid: int):
    """Cancella il questionario compilato per errore (tabella senza `voided`)."""
    db.execute(
        """DELETE FROM wellbeing_entry WHERE review_id IN
           (SELECT id FROM performance_review WHERE person_id=? AND cycle_id=? AND voided=0)""",
        (pid, cid))
    return RedirectResponse(f"/cycles/{cid}/person/{pid}", status_code=302)


@router.post("/cycles/{cid}/person/{pid}/attachment/{att_id}/delete")
def review_attachment_delete(cid: int, pid: int, att_id: int):
    """Un allegato caricato sulla persona sbagliata va tolto, non tenuto per sempre."""
    db.execute("DELETE FROM attachment WHERE id=? AND person_id=?", (att_id, pid))
    return RedirectResponse(f"/cycles/{cid}/person/{pid}", status_code=302)


@router.post("/cycles/{cid}/person/{pid}/attachment")
async def review_attachment(cid: int, pid: int, file: UploadFile, note: str = Form(None)):
    rid = _ensure_review(pid, cid)
    data = await file.read()
    if data:
        db.execute(
            "INSERT INTO attachment (person_id, review_id, filename, mime, content, note) "
            "VALUES (?,?,?,?,?,?)",
            (pid, rid, file.filename, file.content_type, data, note or None))
    return RedirectResponse(f"/cycles/{cid}/person/{pid}", status_code=302)
