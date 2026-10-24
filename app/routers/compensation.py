"""Retribuzione: eventi RAL, budget, benefit, incentivi, analisi salary, montepremi."""
import json
from datetime import date, timedelta

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from app import db, perimeter, session, users
from app.routers import hrview
from app.params import OptInt
from app.services import budget as budget_svc
from app.services import cost, goal_score, hr_report

router = APIRouter()


def _templates():
    from app.main import templates

    return templates


# ---- eventi RAL (dalla scheda persona) ----

@router.post("/people/{pid}/ral")
def ral_create(pid: int, amount: float = Form(...), effective_date: str = Form(...),
               change_type: str = Form("aumento"), reason: str = Form(None),
               budget_id: str = Form(None)):
    prev = cost.current_ral(pid, on_date=effective_date)
    delta = round(amount - prev["amount"], 2) if prev else 0.0
    db.execute(
        "INSERT INTO ral_event (person_id, budget_id, effective_date, amount, delta, change_type, reason) "
        "VALUES (?,?,?,?,?,?,?)",
        (pid, budget_id or None, effective_date, amount, delta, change_type, reason or None))
    return RedirectResponse(f"/people/{pid}", status_code=302)


@router.post("/people/{pid}/ral/{eid}/void")
def ral_void(pid: int, eid: int):
    db.execute(
        "UPDATE ral_event SET voided=1, void_reason='annullato da UI' WHERE id=? AND person_id=?",
        (eid, pid))
    return RedirectResponse(f"/people/{pid}", status_code=302)


# ---- benefit / incentivi ----

@router.post("/people/{pid}/benefit")
def benefit_assign(pid: int, benefit_type_id: int = Form(...), value: str = Form(None),
                   effective_date: str = Form(...), reason: str = Form(None)):
    with db.transaction() as conn:
        conn.execute(
            "UPDATE benefit_assignment SET end_date=? WHERE person_id=? AND benefit_type_id=? "
            "AND end_date IS NULL AND voided=0",
            (effective_date, pid, benefit_type_id))
        conn.execute(
            "INSERT INTO benefit_assignment (person_id, benefit_type_id, value, effective_date, reason) "
            "VALUES (?,?,?,?,?)",
            (pid, benefit_type_id, value or None, effective_date, reason or None))
    return RedirectResponse(f"/people/{pid}", status_code=302)


@router.post("/people/{pid}/benefit/{bid}/end")
def benefit_end(pid: int, bid: int):
    db.execute(
        "UPDATE benefit_assignment SET end_date=? WHERE id=? AND person_id=?",
        (date.today().isoformat(), bid, pid))
    return RedirectResponse(f"/people/{pid}", status_code=302)


@router.post("/people/{pid}/incentive")
def incentive_create(pid: int, amount: float = Form(...), inc_date: str = Form(...),
                     reason: str = Form(None)):
    db.execute(
        "INSERT INTO incentive (person_id, inc_date, amount, reason) VALUES (?,?,?,?)",
        (pid, inc_date, amount, reason or None))
    return RedirectResponse(f"/people/{pid}", status_code=302)


# ---- analisi salary ----

PENDING = ("bozza", "proposta", "approvata")


def _salary_rows(budget_id=None, director_id=None):
    """Righe dell'analisi salary; `a_piano` = proposte pendenti su quel budget. Per HR
    `director_id` restringe alle persone di un director («in veste di»)."""
    flt = " AND COALESCE(t.owner_user_id, p.owner_user_id) = ?" if director_id else ""
    rows = db.query(
        f"""SELECT p.id, p.full_name, t.name AS team_name, pa.role_type,
                  COALESCE(t.owner_user_id, p.owner_user_id) AS director_id,
                  (SELECT amount FROM ral_event r WHERE r.person_id=p.id AND r.voided=0
                   ORDER BY r.effective_date DESC, r.id DESC LIMIT 1) AS ral,
                  (SELECT box_number FROM ninebox_assessment n WHERE n.person_id=p.id AND n.voided=0
                   ORDER BY n.eval_date DESC, n.id DESC LIMIT 1) AS box,
                  e.livello, e.id AS employment_id,
                  (SELECT COALESCE(SUM(amount),0) FROM ral_proposal pr
                   WHERE pr.person_id=p.id AND pr.voided=0
                     AND pr.status IN ('bozza','proposta','approvata')
                     AND (? IS NULL OR pr.budget_id = ?)) AS a_piano
        FROM person p
        LEFT JOIN person_assignment pa ON pa.person_id=p.id AND pa.voided=0 AND pa.end_date IS NULL
        LEFT JOIN team t ON t.id = pa.team_id
        LEFT JOIN employment e ON e.person_id=p.id AND e.voided=0 AND e.end_date IS NULL
        WHERE p.status='attivo'{flt} ORDER BY t.name, p.full_name""",
        (budget_id, budget_id, *([director_id] if director_id else [])))
    return [dict(r) for r in rows]


def _new_employment(conn, pid: int, new_livello: str, effective: str, reason: str | None) -> None:
    """Nuova situazione contrattuale con il livello nuovo: chiude la corrente il giorno prima e
    copia da lei il resto (CCNL, contratto, smart working, part-time)."""
    prev_end = (date.fromisoformat(effective) - timedelta(days=1)).isoformat()
    prev = conn.execute(
        "SELECT * FROM employment WHERE person_id=? AND end_date IS NULL AND voided=0 "
        "ORDER BY start_date DESC LIMIT 1", (pid,)).fetchone()
    conn.execute(
        "UPDATE employment SET end_date=? WHERE person_id=? AND end_date IS NULL AND voided=0",
        (prev_end, pid))
    conn.execute(
        "INSERT INTO employment (person_id, livello, ccnl, tipo_contratto, smartwork, "
        "timbratura_scheme, part_time_pct, weekly_hours, start_date, note) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (pid, new_livello,
         prev["ccnl"] if prev else db.get_meta("default_ccnl") or None,
         prev["tipo_contratto"] if prev else None,
         prev["smartwork"] if prev else None,
         prev["timbratura_scheme"] if prev else None,
         prev["part_time_pct"] if prev else 100,
         prev["weekly_hours"] if prev else None,
         effective, reason))


def _hr_direct(row, new_ral: float, effective: str, new_livello: str, change_type: str, reason: str | None) -> None:
    """HR (0.39): nuova RAL e/o livello scritti direttamente, senza piano (variazioni CCNL, scatti,
    adeguamenti). L'importo è la RAL nuova, assoluta: vale anche per chi non ha ancora una RAL."""
    with db.transaction() as conn:
        if new_livello:
            _new_employment(conn, row["id"], new_livello, effective, reason)
        if new_ral:
            conn.execute(
                "INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type, reason) "
                "VALUES (?,?,?,?,?,?)",
                (row["id"], effective, round(new_ral, 2), round(new_ral - (row["ral"] or 0), 2),
                 change_type, reason))


def _apply_increase(row, amount: float, effective: str, new_livello: str,
                    budget_id, reason: str) -> int | None:
    """Rende reale un aumento: evento RAL e, se il livello cambia, nuova employment.

    Ritorna l'id dell'evento RAL creato (None se c'è solo il cambio livello).
    """
    if new_livello:
        with db.transaction() as conn:
            _new_employment(conn, row["id"], new_livello, effective, reason)
    if amount and row["ral"]:
        return db.execute(
            "INSERT INTO ral_event (person_id, budget_id, effective_date, amount, delta, "
            "change_type, reason) VALUES (?,?,?,?,?,?,?)",
            (row["id"], budget_id, effective, round(row["ral"] + amount, 2), amount,
             "promozione" if new_livello else "aumento", reason))
    return None


def _num(form, key) -> float:
    try:
        return float(form.get(key) or 0)
    except ValueError:
        return 0.0


def _salary_changes(form, budget_id=None) -> list[dict]:
    """Righe con un aumento e/o un cambio livello richiesto.

    L'importo è la fonte di verità: la % è solo un modo di digitarlo (i due campi
    si sincronizzano nel browser). Qui si rilegge sempre l'importo.
    """
    default_date = form.get("effective_date") or date.today().isoformat()
    changes = []
    for r in _salary_rows(budget_id):
        inc = _num(form, f"inc_{r['id']}")
        new_lvl = (form.get(f"lvl_{r['id']}") or "").strip()
        if new_lvl == (r["livello"] or ""):
            new_lvl = ""
        if not inc and not new_lvl:
            continue
        ral = r["ral"] or 0
        changes.append({
            **r, "inc": inc,
            "new_ral": round(ral + inc, 2) if inc else ral,
            "a_regime": round(ral + (r["a_piano"] or 0) + inc, 2),
            "pct": (inc / ral * 100) if ral and inc else 0,
            "new_livello": new_lvl,
            "date": form.get(f"date_{r['id']}") or default_date,
        })
    return changes


@router.get("/comp/salary")
def salary_page(request: Request, budget_id: OptInt = None, saved: int = 0):
    """Per HR (0.39): senza director scelto è l'inserimento diretto di RAL e livello nuovi (CCNL),
    per tutte le persone con il loro director; «in veste di» un director è il suo piano aumenti."""
    ctx = hrview.context(request)
    rows = _salary_rows(budget_id, ctx["acting"])
    if ctx["hr"]:
        rows = [{**r, "director": ctx["directors"].get(r["director_id"])} for r in rows]
    budgets = db.query(
        "SELECT * FROM ral_budget WHERE status='aperto' " + ("AND owner_user_id=? " if ctx["acting"] else "") +
        "ORDER BY year IS NULL, year DESC, id DESC", (ctx["acting"],) if ctx["acting"] else ())
    budget = db.one("SELECT * FROM ral_budget WHERE id=?", (budget_id,)) if budget_id else None
    total = sum(r["ral"] or 0 for r in rows)
    amber = int(db.get_meta("ral_stale_amber_years", "2"))
    red = int(db.get_meta("ral_stale_red_years", "4"))
    last_inc = cost.last_ral_changes()
    for c in last_inc.values():
        c["flag"] = cost.ral_age_flag(c["effective_date"], amber, red)
    return _templates().TemplateResponse(request, "salary.html", {
        **ctx, "rows": rows, "budgets": budgets, "budget": budget,
        "budget_id": budget_id, "total": total, "saved": saved,
        "last_inc": last_inc,
    })


@router.post("/comp/salary/apply")
async def salary_apply(request: Request):
    """HR (0.39): le RAL e i livelli nuovi scritti qui diventano subito eventi reali, senza piano
    (variazioni CCNL comunicate dallo studio paghe). Solo HR, e non «in veste di» un director."""
    if not hrview.is_hr() or hrview.acting_id():
        raise HTTPException(403)
    form = await request.form()
    default_date = form.get("effective_date") or date.today().isoformat()
    change_type = form.get("change_type") or "ccnl"
    reason = (form.get("reason") or "").strip() or None
    saved = 0
    for r in _salary_rows():
        new_ral = _num(form, f"ral_{r['id']}")
        new_lvl = (form.get(f"lvl_{r['id']}") or "").strip()
        if new_lvl == (r["livello"] or ""):
            new_lvl = ""
        if not new_ral and not new_lvl:
            continue
        _hr_direct(r, new_ral, form.get(f"date_{r['id']}") or default_date, new_lvl, change_type, reason)
        saved += 1
    return RedirectResponse(f"/comp/salary?saved={saved}", status_code=302)


@router.post("/comp/salary/simulate")
async def salary_simulate(request: Request):
    """Frammento htmx: ricalcola i totali della simulazione aumenti."""
    form = await request.form()
    budget_id = int(form["budget_id"]) if form.get("budget_id") else None
    summary = None
    if budget_id:
        b = db.one("SELECT * FROM ral_budget WHERE id=?", (budget_id,))
        if b:
            summary = _budget_numbers(b)
    sim = _salary_changes(form, budget_id)
    tot_delta = sum(s["inc"] for s in sim)
    residual = round(summary["residuo"] - tot_delta, 2) if summary else None
    return _templates().TemplateResponse(request, "_salary_sim.html", {
        "sim": sim, "tot_delta": tot_delta, "summary": summary, "residual": residual,
    })


@router.post("/comp/salary/plan")
async def salary_plan(request: Request):
    """Salva le righe compilate come proposte in bozza: nulla diventa reale qui."""
    hrview.require_acting()   # HR propone solo «in veste di» un director
    form = await request.form()
    budget_id = int(form["budget_id"]) if form.get("budget_id") else None
    reason = form.get("reason") or None
    saved = 0
    for s in _salary_changes(form, budget_id):
        db.execute(
            "INSERT INTO ral_proposal (person_id, budget_id, amount, effective_date, "
            "new_livello, status, note) VALUES (?,?,?,?,?, 'bozza', ?)",
            (s["id"], budget_id, s["inc"], s["date"], s["new_livello"] or None, reason))
        saved += 1
    qs = f"budget_id={budget_id}&" if budget_id else ""
    return RedirectResponse(f"/comp/plan?{qs}saved={saved}", status_code=302)


# ---- piano aumenti ----

def _pending_by_person() -> dict:
    """Proposte non ancora applicate, raggruppate per persona (per le baseline del piano)."""
    out: dict = {}
    for r in db.query(
        "SELECT id, person_id, effective_date, amount FROM ral_proposal "
        "WHERE voided=0 AND status IN ('bozza','proposta','approvata')"
    ):
        out.setdefault(r["person_id"], []).append(r)
    return out


def _proposal_baseline(p, ral=None, pending=None) -> float:
    """RAL da cui parte la proposta: la corrente più le tranche pendenti che la precedono.

    Serve perché nel piano si conferma la **nuova RAL** e la variazione è la
    differenza: con più tranche ciascuna si compone su quelle applicate prima di
    lei (`plan_apply_approved` applica in ordine di decorrenza).
    """
    if ral is None:
        cur = cost.current_ral(p["person_id"])
        ral = cur["amount"] if cur else 0
    if pending is None:
        pending = db.query(
            "SELECT id, effective_date, amount FROM ral_proposal WHERE person_id=? AND voided=0 "
            "AND status IN ('bozza','proposta','approvata')", (p["person_id"],))
    key = (p["effective_date"] or "", p["id"])
    prima = sum(r["amount"] or 0 for r in pending
                if (r["effective_date"] or "", r["id"]) < key)
    return round((ral or 0) + prima, 2)


@router.get("/comp/plan")
def plan_page(request: Request, budget_id: OptInt = None, saved: int = 0):
    """Per HR (0.38): solo le proposte in stato «proposta» (quelle che la riguardano), con director
    e budget per riga, filtro Director e totale delle richieste; niente selettore dei budget."""
    ctx = hrview.context(request)
    where, params = "WHERE pr.voided=0", []
    if ctx["ro_hr"]:   # HR che consulta: solo ciò che la riguarda; «in veste di» è il piano del director
        budget_id = None
        where += " AND pr.status='proposta'"
    if ctx["sel"]:
        where += f" AND COALESCE(b.owner_user_id, t.owner_user_id, p.owner_user_id) IN ({','.join('?' * len(ctx['sel']))})"
        params += sorted(ctx["sel"])
    if budget_id:
        where += " AND pr.budget_id=?"
        params.append(budget_id)
    proposals = db.query(
        f"""SELECT pr.*, p.full_name, b.period AS budget_period,
                   COALESCE(b.owner_user_id, t.owner_user_id, p.owner_user_id) AS director_id,
                   (SELECT amount FROM ral_event r WHERE r.person_id=pr.person_id AND r.voided=0
                    ORDER BY r.effective_date DESC, r.id DESC LIMIT 1) AS ral,
                   (SELECT livello FROM employment e WHERE e.person_id=pr.person_id
                    AND e.voided=0 AND e.end_date IS NULL ORDER BY e.start_date DESC LIMIT 1) AS livello,
                   (SELECT amount FROM ral_event r2 WHERE r2.id=pr.ral_event_id) AS applied_ral
            FROM ral_proposal pr JOIN person p ON p.id=pr.person_id
            LEFT JOIN ral_budget b ON b.id=pr.budget_id
            LEFT JOIN person_assignment pa ON pa.person_id=p.id AND pa.voided=0 AND pa.end_date IS NULL
            LEFT JOIN team t ON t.id=pa.team_id
            {where}
            ORDER BY CASE pr.status WHEN 'bozza' THEN 0 WHEN 'proposta' THEN 1
                     WHEN 'approvata' THEN 2 WHEN 'applicata' THEN 3 ELSE 4 END,
                     p.full_name, pr.effective_date""", tuple(params))
    proposals = [{**dict(p), "director": ctx["directors"].get(p["director_id"])} for p in proposals]
    pending = _pending_by_person()
    for p in proposals:
        if p["status"] == "applicata":
            continue
        p["baseline"] = _proposal_baseline(p, p["ral"], pending.get(p["person_id"], []))
        new_ral = round(p["baseline"] + (p["amount"] or 0), 2)
        p["new_ral"] = int(new_ral) if new_ral == int(new_ral) else new_ral  # niente "43500.0"
    budget = db.one("SELECT * FROM ral_budget WHERE id=?", (budget_id,)) if budget_id else None
    totals = None
    if ctx["ro_hr"]:
        totals = {"n": len(proposals), "delta": sum(p["amount"] or 0 for p in proposals),
                  "new_ral": sum(p["new_ral"] for p in proposals)}
    return _templates().TemplateResponse(request, "plan.html", {
        **ctx, "totals": totals,
        "proposals": proposals, "budget": budget, "budget_id": budget_id,
        "budgets": db.query("SELECT * FROM ral_budget " + ("WHERE owner_user_id=? " if ctx["acting"] else "") +
                            "ORDER BY id DESC", (ctx["acting"],) if ctx["acting"] else ()),
        "summary": _budget_numbers(budget) if budget else None,
        "n_approvate": sum(1 for p in proposals if p["status"] == "approvata"),
        "n_bozze": sum(1 for p in proposals if p["status"] == "bozza"),
        "saved": saved,
    })


def _plan_redirect(budget_id) -> RedirectResponse:
    qs = f"?budget_id={budget_id}" if budget_id else ""
    return RedirectResponse(f"/comp/plan{qs}", status_code=302)


# macchina a stati del piano (0.39): bozza → proposta (a HR) → approvata → applicata; una proposta
# si respinge o torna in bozza (per cambiarne l'importo), un'approvata torna in attesa, una respinta si riapre
PLAN_TRANSITIONS = {"bozza": {"proposta"}, "proposta": {"approvata", "respinta", "bozza"},
                    "approvata": {"proposta"}, "respinta": {"bozza"}}


@router.post("/comp/plan/{pid}/status")
def plan_status(pid: int, status: str = Form(...)):
    p = db.one("SELECT * FROM ral_proposal WHERE id=?", (pid,))
    if not p or status not in PLAN_TRANSITIONS.get(p["status"], ()):
        return _plan_redirect(p["budget_id"] if p else None)
    today = date.today().isoformat()
    proposed_at = today if status == "proposta" else p["proposed_at"]
    decided_at = today if status in ("approvata", "respinta") else None
    db.execute("UPDATE ral_proposal SET status=?, proposed_at=?, decided_at=? WHERE id=?",
               (status, proposed_at, decided_at, pid))
    if status == "proposta":
        qs = f"budget_id={p['budget_id']}&" if p["budget_id"] else ""
        return RedirectResponse(f"/comp/plan?{qs}sent=1", status_code=302)
    return _plan_redirect(p["budget_id"])


@router.post("/comp/plan/{pid}/update")
def plan_update(pid: int, new_ral: float = Form(0), effective_date: str = Form(None),
                new_livello: str = Form(None), note: str = Form(None)):
    """Si conferma la nuova RAL (è quella che decide HR): la variazione la calcola il server.
    Il director cambia solo le bozze (una proposta inviata la riporta in bozza); HR cambia le
    proposte in attesa — è la sua validazione — e, «in veste di» un director, anche le sue bozze."""
    p = db.one("SELECT * FROM ral_proposal WHERE id=?", (pid,))
    editable = {"bozza"} if not hrview.is_hr() else ({"bozza", "proposta"} if hrview.acting_id() else {"proposta"})
    if not p or p["status"] not in editable:
        return _plan_redirect(p["budget_id"] if p else None)
    p = dict(p)
    p["effective_date"] = effective_date or None
    amount = round(new_ral - _proposal_baseline(p), 2) if new_ral else 0.0
    db.execute(
        "UPDATE ral_proposal SET amount=?, effective_date=?, new_livello=?, note=? WHERE id=?",
        (amount, effective_date or None, new_livello or None, note or None, pid))
    return _plan_redirect(p["budget_id"])


@router.post("/comp/plan/{pid}/void")
def plan_void(pid: int):
    p = db.one("SELECT * FROM ral_proposal WHERE id=?", (pid,))
    if p and p["status"] != "applicata":
        db.execute("UPDATE ral_proposal SET voided=1, void_reason='annullata da UI' WHERE id=?",
                   (pid,))
    return _plan_redirect(p["budget_id"] if p else None)


def _apply_proposal(p) -> bool:
    """Trasforma una proposta approvata in realtà. True se applicata.

    Legge la RAL vigente alla decorrenza: applicando due tranche in ordine di
    decorrenza, la seconda parte dal valore aggiornato dalla prima.
    """
    effective = p["effective_date"] or date.today().isoformat()
    ral = cost.current_ral(p["person_id"], on_date=effective)
    row = {"id": p["person_id"], "ral": ral["amount"] if ral else None}
    event_id = _apply_increase(row, p["amount"] or 0, effective, p["new_livello"] or "",
                               p["budget_id"], p["note"] or "revisione salariale")
    db.execute(
        "UPDATE ral_proposal SET status='applicata', ral_event_id=?, decided_at=? WHERE id=?",
        (event_id, date.today().isoformat(), p["id"]))
    return True


@router.post("/comp/plan/{pid}/apply")
def plan_apply(pid: int):
    p = db.one("SELECT * FROM ral_proposal WHERE id=?", (pid,))
    if p and p["status"] == "approvata" and not p["voided"]:
        _apply_proposal(p)
    return _plan_redirect(p["budget_id"] if p else None)


REPORT_STATUSES = {
    "proposta": ("proposta",),
    "approvata": ("approvata",),
    "tutte": ("bozza", "proposta", "approvata"),
}


@router.get("/comp/plan/report")
def plan_report(request: Request, budget_id: OptInt = None, status: str = "proposta"):
    statuses = REPORT_STATUSES.get(status, ("proposta",))
    rows = hr_report.report_rows(budget_id, statuses)
    budget = db.one("SELECT * FROM ral_budget WHERE id=?", (budget_id,)) if budget_id else None
    return _templates().TemplateResponse(request, "plan_report.html", {
        "rows": rows, "budget": budget, "budget_id": budget_id, "status": status,
        "summary": _budget_numbers(budget) if budget else None,
        "total": sum(r["amount"] or 0 for r in rows),
        "today": date.today(),
    })


@router.get("/comp/plan/report.xlsx")
def plan_report_xlsx(budget_id: OptInt = None, status: str = "proposta"):
    statuses = REPORT_STATUSES.get(status, ("proposta",))
    rows = hr_report.report_rows(budget_id, statuses)
    budget = db.one("SELECT * FROM ral_budget WHERE id=?", (budget_id,)) if budget_id else None
    name = f"proposte-aumenti-{budget['period'].replace(' ', '-') if budget else 'tutte'}.xlsx"
    return Response(
        content=hr_report.build_xlsx(budget, rows),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/comp/plan/apply-approved")
def plan_apply_approved(budget_id: str = Form(None)):
    bid = int(budget_id) if budget_id else None
    sql = "SELECT * FROM ral_proposal WHERE status='approvata' AND voided=0"
    params = ()
    if bid:
        sql += " AND budget_id=?"
        params = (bid,)
    for p in db.query(sql + " ORDER BY effective_date", params):
        _apply_proposal(p)
    return _plan_redirect(bid)


# ---- budget aumenti ----

def _budget_numbers(b) -> dict:
    """Tetto ripartito fra applicato (eventi reali) e impegnato (proposte pendenti)."""
    applied = [e["delta"] for e in db.query(
        "SELECT delta FROM ral_event WHERE budget_id=? AND voided=0", (b["id"],))]
    committed = [p["amount"] for p in db.query(
        "SELECT amount FROM ral_proposal WHERE budget_id=? AND voided=0 "
        "AND status IN ('bozza','proposta','approvata')", (b["id"],))]
    return budget_svc.budget_summary(b["total_cap"], applied, committed)


def _budget_recompute_cap(budget_id: int) -> None:
    """Se il budget è a percentuale, il tetto segue il monte RAL degli inclusi."""
    b = db.one("SELECT * FROM ral_budget WHERE id=?", (budget_id,))
    if not b or b["pct"] is None:
        return
    amounts = [m["ral_snapshot"] for m in db.query(
        "SELECT ral_snapshot FROM ral_budget_member WHERE budget_id=? AND included=1", (budget_id,))]
    db.execute("UPDATE ral_budget SET total_cap=? WHERE id=?",
               (budget_svc.cap_from_pct(b["pct"], amounts), budget_id))


@router.post("/comp/budget/{bid}/close")
def budget_close(bid: int):
    db.execute("UPDATE ral_budget SET status='chiuso' WHERE id=?", (bid,))
    return RedirectResponse("/comp/budget", status_code=302)


@router.post("/comp/budget/{bid}/reopen")
def budget_reopen(bid: int):
    db.execute("UPDATE ral_budget SET status='aperto' WHERE id=?", (bid,))
    return RedirectResponse("/comp/budget", status_code=302)


@router.get("/comp/budget")
def budget_page(request: Request):
    """Per HR (0.38): director su ogni budget, filtro Director, totale dei budget aperti e delle
    richieste (proposte non applicate) che il filtro mostra."""
    ctx = hrview.context(request)
    budgets = []
    for b in db.query(
            "SELECT * FROM ral_budget ORDER BY year IS NULL, year DESC, id DESC"):
        if not hrview.keep(ctx, b["owner_user_id"]):
            continue
        events = db.query(
            "SELECT r.*, p.full_name FROM ral_event r JOIN person p ON p.id=r.person_id "
            "WHERE r.budget_id=? AND r.voided=0 ORDER BY r.effective_date", (b["id"],))
        members = db.query(
            "SELECT m.*, p.full_name, p.hire_date FROM ral_budget_member m "
            "JOIN person p ON p.id=m.person_id WHERE m.budget_id=? ORDER BY p.full_name", (b["id"],))
        monte = sum(m["ral_snapshot"] for m in members if m["included"])
        pending = db.query(
            "SELECT pr.*, p.full_name FROM ral_proposal pr JOIN person p ON p.id=pr.person_id "
            "WHERE pr.budget_id=? AND pr.voided=0 AND pr.status IN ('bozza','proposta','approvata') "
            "ORDER BY pr.effective_date", (b["id"],))
        n_prop = db.one("SELECT COUNT(*) AS n FROM ral_proposal WHERE budget_id=? AND voided=0", (b["id"],))["n"]
        budgets.append({**dict(b), "events": events, "members": members, "monte": monte,
                        "pending": pending, "director": ctx["directors"].get(b["owner_user_id"]),
                        "deletable": not events and n_prop == 0,   # 0.47: senza movimenti si elimina, anche chiuso
                        **_budget_numbers(b)})
    open_budgets = [b for b in budgets if b["status"] == "aperto"]
    totals = None
    if ctx["ro_hr"]:
        totals = {k: sum(b[k] for b in open_budgets) for k in ("total_cap", "applicato", "impegnato", "residuo")}
        totals["n_budget"] = len(open_budgets)
        totals["n_richieste"] = sum(len(b["pending"]) for b in open_budgets)
    return _templates().TemplateResponse(request, "budget.html", {
        **ctx, "totals": totals,
        "open_budgets": open_budgets,
        "closed_budgets": [b for b in budgets if b["status"] != "aperto"],
    })


@router.post("/comp/budget")
def budget_create(period: str = Form(...), year: int = Form(...),
                  pct: str = Form(None), total_cap: str = Form(None),
                  description: str = Form(None)):
    """Tetto fisso oppure % sul monte RAL (platea: attivi, esclusi gli assunti dell'anno)."""
    pct_val = float(pct) if pct else None
    acting = hrview.acting_id()
    people = db.query(
        """SELECT p.id, p.hire_date,
                  (SELECT amount FROM ral_event r WHERE r.person_id=p.id AND r.voided=0
                   ORDER BY r.effective_date DESC, r.id DESC LIMIT 1) AS ral
           FROM person p
           LEFT JOIN person_assignment pa ON pa.person_id=p.id AND pa.voided=0 AND pa.end_date IS NULL
           LEFT JOIN team t ON t.id=pa.team_id
           WHERE p.status='attivo' AND (? IS NULL OR COALESCE(t.owner_user_id, p.owner_user_id) = ?)
           ORDER BY p.full_name""", (acting, acting))
    members = []
    for r in people:
        ral = r["ral"] or 0
        hired_this_year = bool(r["hire_date"]) and str(r["hire_date"])[:4] == str(year)
        reason = "assunto nell'anno" if hired_this_year else ("senza RAL" if not ral else None)
        members.append((r["id"], ral, 0 if reason else 1, reason))
    included_amounts = [m[1] for m in members if m[2]]
    cap = budget_svc.cap_from_pct(pct_val, included_amounts) if pct_val else float(total_cap or 0)
    owner = hrview.require_acting()   # HR: il budget nasce del director scelto (e la platea sono le sue persone)
    with db.transaction() as conn:
        cur = conn.execute(
            "INSERT INTO ral_budget (period, year, pct, total_cap, description, owner_user_id) "
            "VALUES (?,?,?,?,?, COALESCE(?, teamer_owner()))",
            (period, year, pct_val, cap, description or None, owner))
        bid = cur.lastrowid
        for pid, ral, inc, reason in members:
            conn.execute(
                "INSERT INTO ral_budget_member (budget_id, person_id, ral_snapshot, included, auto_reason) "
                "VALUES (?,?,?,?,?)", (bid, pid, ral, inc, reason))
    return RedirectResponse("/comp/budget", status_code=302)


@router.post("/comp/budget/{bid}/delete")
def budget_delete(bid: int):
    """Un budget senza movimenti (nessun evento RAL imputato, nessuna proposta) si elimina, anche se
    chiuso: la platea generata con lui se ne va. Con movimenti resta nello storico (0.47)."""
    busy = db.one("SELECT (SELECT COUNT(*) FROM ral_event WHERE budget_id=? AND voided=0) + "
                  "(SELECT COUNT(*) FROM ral_proposal WHERE budget_id=? AND voided=0) AS n", (bid, bid))["n"]
    if busy == 0 and db.one("SELECT id FROM ral_budget WHERE id=?", (bid,)):
        with db.transaction() as conn:
            conn.execute("UPDATE ral_proposal SET budget_id=NULL WHERE budget_id=?", (bid,))   # le annullate
            conn.execute("UPDATE ral_event SET budget_id=NULL WHERE budget_id=?", (bid,))
            conn.execute("DELETE FROM ral_budget_member WHERE budget_id=?", (bid,))
            conn.execute("DELETE FROM ral_budget WHERE id=?", (bid,))
        return RedirectResponse("/comp/budget?deleted=1", status_code=302)
    return RedirectResponse("/comp/budget?err=movimenti", status_code=302)


@router.post("/comp/budget/{bid}/member/{mid}/toggle")
def budget_member_toggle(bid: int, mid: int):
    db.execute(
        "UPDATE ral_budget_member SET included = 1 - included WHERE id=? AND budget_id=?",
        (mid, bid))
    _budget_recompute_cap(bid)
    return RedirectResponse("/comp/budget", status_code=302)


@router.post("/comp/budget/{bid}/refresh-ral")
def budget_refresh_ral(bid: int):
    """Riallinea gli snapshot RAL della platea ai valori correnti."""
    for m in db.query("SELECT * FROM ral_budget_member WHERE budget_id=?", (bid,)):
        ral = cost.current_ral(m["person_id"])
        db.execute("UPDATE ral_budget_member SET ral_snapshot=? WHERE id=?",
                   (ral["amount"] if ral else 0, m["id"]))
    _budget_recompute_cap(bid)
    return RedirectResponse("/comp/budget", status_code=302)


# ---- budget assunzioni ----

OPEN_POSITIONS = budget_svc.OPEN_POSITIONS


def _hiring_carryover(bid: int) -> float:
    """Riporto dall'anno precedente: i trasferimenti entranti non annullati."""
    row = db.one(
        "SELECT COALESCE(SUM(amount),0) AS t FROM hiring_transfer "
        "WHERE to_budget_id=? AND voided=0", (bid,))
    return round(row["t"], 2)


def _hiring_numbers(hb) -> dict:
    """Applicato = RAL reali degli assunti collegati; impegnato = RAL previste aperte.

    Il tetto su cui si misura il residuo è quello proprio più il riporto: il
    riporto è denaro spendibile, ma resta esposto a parte perché viene da un
    altro anno.
    """
    applied, committed = [], []
    for p in db.query(
            "SELECT * FROM hiring_position WHERE budget_id=? AND voided=0", (hb["id"],)):
        if p["status"] == "assunta":
            ral = cost.current_ral(p["person_id"]) if p["person_id"] else None
            applied.append(ral["amount"] if ral else p["expected_ral"])
        elif p["status"] in OPEN_POSITIONS:
            committed.append(p["expected_ral"])
    riporto = _hiring_carryover(hb["id"])
    cap = round(hb["total_cap"] + riporto, 2)
    return {"riporto": riporto, "cap": cap,
            **budget_svc.budget_summary(cap, applied, committed)}


@router.get("/comp/hiring")
def hiring_page(request: Request):
    """Per HR (0.38) ogni budget porta il suo director, c'è il filtro Director e il totale dei
    budget aperti che il filtro mostra; ogni posizione ha il trimestre di arrivo previsto."""
    ctx = hrview.context(request)
    budgets = []
    for hb in db.query("SELECT * FROM hiring_budget ORDER BY id DESC"):
        if not hrview.keep(ctx, hb["owner_user_id"]):
            continue
        positions = db.query(
            """SELECT hp.*, t.name AS team_name, p.full_name AS hired_name,
                      rp.full_name AS replaces_name
               FROM hiring_position hp
               LEFT JOIN team t ON t.id = hp.team_id
               LEFT JOIN person p ON p.id = hp.person_id
               LEFT JOIN person rp ON rp.id = hp.replaces_person_id
               WHERE hp.budget_id=? AND hp.voided=0
               ORDER BY CASE hp.status WHEN 'in_selezione' THEN 0 WHEN 'pianificata' THEN 1
                        WHEN 'assunta' THEN 2 ELSE 3 END, hp.id""", (hb["id"],))
        transfers_out = db.query(
            "SELECT tr.*, hb2.period AS to_period, hb2.year AS to_year, "
            "(SELECT COUNT(*) FROM hiring_position WHERE transfer_id=tr.id) AS n_positions "
            "FROM hiring_transfer tr JOIN hiring_budget hb2 ON hb2.id = tr.to_budget_id "
            "WHERE tr.from_budget_id=? ORDER BY tr.id", (hb["id"],))
        transfers_in = db.query(
            "SELECT tr.*, hb2.period AS from_period, hb2.year AS from_year, "
            "(SELECT COUNT(*) FROM hiring_position WHERE transfer_id=tr.id) AS n_positions "
            "FROM hiring_transfer tr JOIN hiring_budget hb2 ON hb2.id = tr.from_budget_id "
            "WHERE tr.to_budget_id=? AND tr.voided=0 ORDER BY tr.id", (hb["id"],))
        positions = [{**dict(p), "quarter": hrview.quarter(p["expected_start"])} for p in positions]
        budgets.append({**dict(hb), "positions": positions, "transfers_out": transfers_out,
                        "transfers_in": transfers_in,
                        "aperte": [p for p in positions if p["status"] in OPEN_POSITIONS],
                        "director": ctx["directors"].get(hb["owner_user_id"]),
                        "deletable": not positions and not [t for t in transfers_out if not t["voided"]] and not transfers_in,
                        **_hiring_numbers(hb)})
    open_budgets = [b for b in budgets if b["status"] == "aperto"]
    totals = None
    if ctx["ro_hr"]:
        totals = {k: sum(b[k] for b in open_budgets) for k in ("cap", "riporto", "applicato", "impegnato", "residuo")}
        totals["n_budget"] = len(open_budgets)
        totals["n_aperte"] = sum(len(b["aperte"]) for b in open_budgets)
    return _templates().TemplateResponse(request, "hiring.html", {
        **ctx, "totals": totals,
        "open_budgets": open_budgets,
        "closed_budgets": [b for b in budgets if b["status"] != "aperto"],
        "all_budgets": db.query(
            "SELECT id, period, year FROM hiring_budget ORDER BY year DESC, id DESC"),
        "open_dest": db.query(
            "SELECT id, period, year, total_cap FROM hiring_budget WHERE status='aperto' "
            "ORDER BY year DESC, id DESC"),
        "teams": db.query("SELECT * FROM team WHERE archived_at IS NULL ORDER BY name"),
        "recent_people": db.query(
            "SELECT id, full_name FROM person WHERE status='attivo' ORDER BY id DESC LIMIT 50"),
        # chi una posizione nuova può sostituire: i cessati senza sostituzione, poi gli attivi (uscite annunciate)
        "replaceable": db.query(
            """SELECT p.id, p.full_name, p.status, p.end_date FROM person p
               WHERE NOT EXISTS (SELECT 1 FROM hiring_position hp WHERE hp.replaces_person_id=p.id AND hp.voided=0)
               ORDER BY p.status='cessato' DESC, p.end_date DESC, p.full_name"""),
    })


@router.post("/comp/hiring")
def hiring_budget_create(period: str = Form(...), year: int = Form(...),
                         total_cap: float = Form(...), note: str = Form(None)):
    owner = hrview.require_acting()   # HR: il budget nasce del director scelto
    db.execute("INSERT INTO hiring_budget (period, year, total_cap, note, owner_user_id) "
               "VALUES (?,?,?,?, COALESCE(?, teamer_owner()))",
               (period, year, total_cap, note or None, owner))
    return RedirectResponse("/comp/hiring", status_code=302)


@router.post("/comp/hiring/{bid}/update")
def hiring_budget_update(bid: int, period: str = Form(...), year: int = Form(...),
                         total_cap: float = Form(...), note: str = Form(None)):
    """Correzione dei dati del budget (errore di inserimento)."""
    db.execute("UPDATE hiring_budget SET period=?, year=?, total_cap=?, note=? WHERE id=?",
               (period.strip(), year, total_cap, note or None, bid))
    return RedirectResponse("/comp/hiring", status_code=302)


@router.post("/comp/hiring/{bid}/delete")
def hiring_budget_delete(bid: int):
    """Elimina un budget senza movimenti (nessuna posizione viva, nessun riporto), anche chiuso (0.47)."""
    busy = db.one(
        "SELECT (SELECT COUNT(*) FROM hiring_position WHERE budget_id=? AND voided=0) + "
        "(SELECT COUNT(*) FROM hiring_transfer WHERE (from_budget_id=? AND voided=0) OR to_budget_id=?) AS n",
        (bid, bid, bid))["n"]
    if busy == 0:
        with db.transaction() as conn:
            conn.execute("DELETE FROM hiring_transfer WHERE from_budget_id=?", (bid,))   # solo annullati
            conn.execute("DELETE FROM hiring_position WHERE budget_id=?", (bid,))        # solo annullate
            conn.execute("DELETE FROM hiring_budget WHERE id=?", (bid,))
        return RedirectResponse("/comp/hiring?deleted=1", status_code=302)
    return RedirectResponse("/comp/hiring?err=movimenti", status_code=302)


# ---- chiusura e riporto ----

def _open_position_ids(bid: int) -> list:
    marks = ",".join("?" * len(OPEN_POSITIONS))
    return [r["id"] for r in db.query(
        f"SELECT id FROM hiring_position WHERE budget_id=? AND voided=0 "
        f"AND status IN ({marks}) ORDER BY id", (bid, *OPEN_POSITIONS))]


@router.post("/comp/hiring/{bid}/close")
def hiring_budget_close(bid: int):
    db.execute("UPDATE hiring_budget SET status='chiuso' WHERE id=?", (bid,))
    return RedirectResponse("/comp/hiring", status_code=302)


@router.post("/comp/hiring/{bid}/reopen")
def hiring_budget_reopen(bid: int):
    db.execute("UPDATE hiring_budget SET status='aperto' WHERE id=?", (bid,))
    return RedirectResponse("/comp/hiring", status_code=302)


@router.post("/comp/hiring/{bid}/transfer")
async def hiring_transfer(bid: int, request: Request):
    """Chiude il budget portando avanti posizioni e residuo.

    Due modi: `esistente` alza un budget già aperto, `nuovo` ne inizializza uno.
    Ogni posizione ancora aperta si decide una per una (trasferisci / chiudi /
    lascia qui); l'origine si chiude solo se non ne resta nessuna, altrimenti
    resterebbero posizioni vive dentro un budget archiviato.
    """
    src = db.one("SELECT * FROM hiring_budget WHERE id=?", (bid,))
    if not src:
        return RedirectResponse("/comp/hiring", status_code=302)
    form = await request.form()
    amount = float(form.get("amount") or 0)
    with db.transaction() as conn:
        if form.get("mode") == "nuovo":
            year = int(form.get("year") or date.today().year)
            period = (form.get("period") or "").strip() or f"Assunzioni {year}"
            to_id = conn.execute(
                "INSERT INTO hiring_budget (period, year, total_cap, note, owner_user_id) "
                "VALUES (?,?,?,?, COALESCE(?, teamer_owner()))",
                (period, year, float(form.get("total_cap") or 0),
                 (form.get("new_note") or "").strip() or None, hrview.owner())).lastrowid
        else:
            dest = conn.execute("SELECT id FROM hiring_budget WHERE id=?",
                                (form.get("to_budget_id") or 0,)).fetchone()
            if not dest or dest["id"] == bid:
                return RedirectResponse("/comp/hiring", status_code=302)
            to_id = dest["id"]
        tid = conn.execute(
            "INSERT INTO hiring_transfer (from_budget_id, to_budget_id, amount, note) "
            "VALUES (?,?,?,?)",
            (bid, to_id, round(amount, 2), (form.get("note") or "").strip() or None)).lastrowid
        for pid in _open_position_ids(bid):
            action = form.get(f"pos_{pid}", "trasferisci")
            if action == "trasferisci":
                conn.execute("UPDATE hiring_position SET budget_id=?, transfer_id=? WHERE id=?",
                             (to_id, tid, pid))
            elif action == "chiudi":
                conn.execute("UPDATE hiring_position SET status='annullata' WHERE id=?", (pid,))
        if not _open_position_ids(bid):
            conn.execute("UPDATE hiring_budget SET status='chiuso' WHERE id=?", (bid,))
    return RedirectResponse("/comp/hiring", status_code=302)


@router.post("/comp/hiring/transfer/{tid}/void")
def hiring_transfer_void(tid: int):
    """Annulla un trasferimento sbagliato: torna indietro il riporto e, con lui,
    le posizioni arrivate che sono ancora aperte. Chi è già stato assunto resta
    dov'è: quel denaro è stato speso sul budget di destinazione."""
    tr = db.one("SELECT * FROM hiring_transfer WHERE id=?", (tid,))
    if not tr or tr["voided"]:
        return RedirectResponse("/comp/hiring", status_code=302)
    marks = ",".join("?" * len(OPEN_POSITIONS))
    with db.transaction() as conn:
        conn.execute("UPDATE hiring_transfer SET voided=1, void_reason='annullato da UI' "
                     "WHERE id=?", (tid,))
        conn.execute(
            f"UPDATE hiring_position SET budget_id=?, transfer_id=NULL "
            f"WHERE transfer_id=? AND voided=0 AND status IN ({marks})",
            (tr["from_budget_id"], tid, *OPEN_POSITIONS))
        conn.execute("UPDATE hiring_budget SET status='aperto' WHERE id=?",
                     (tr["from_budget_id"],))
    return RedirectResponse("/comp/hiring", status_code=302)


@router.post("/comp/hiring/{bid}/position")
def position_create(bid: int, title: str = Form(...), team_id: str = Form(None),
                    role_type: str = Form("ic"), expected_ral: float = Form(0),
                    expected_start: str = Form(None), note: str = Form(None),
                    replaces_person_id: str = Form(None)):
    """Ogni posizione dice se è un +1 al team o la sostituzione di qualcuno (0.39)."""
    db.execute(
        "INSERT INTO hiring_position (budget_id, title, team_id, role_type, expected_ral, "
        "expected_start, note, replaces_person_id) VALUES (?,?,?,?,?,?,?,?)",
        (bid, title.strip(), team_id or None, role_type, expected_ral,
         expected_start or None, note or None, int(replaces_person_id) if (replaces_person_id or "").isdigit() else None))
    return RedirectResponse("/comp/hiring", status_code=302)


@router.post("/comp/hiring/position/{pid}/ral")
def position_ral(pid: int, expected_ral: float = Form(...)):
    """HR (0.39) corregge la RAL prevista di una posizione di qualunque director, senza «in veste di»."""
    if not hrview.is_hr():
        raise HTTPException(403)
    db.execute("UPDATE hiring_position SET expected_ral=? WHERE id=? AND voided=0", (expected_ral, pid))
    return RedirectResponse("/comp/hiring", status_code=302)


@router.post("/comp/hiring/position/{pid}/status")
def position_status(pid: int, status: str = Form(...), person_id: str = Form(None)):
    if status == "assunta" and not person_id:
        return RedirectResponse("/comp/hiring", status_code=302)
    db.execute("UPDATE hiring_position SET status=?, person_id=? WHERE id=?",
               (status, person_id or None, pid))
    return RedirectResponse("/comp/hiring", status_code=302)


@router.post("/comp/hiring/position/{pid}/update")
def position_update(pid: int, title: str = Form(...), team_id: str = Form(None),
                    role_type: str = Form(None), budget_id: str = Form(None),
                    expected_ral: float = Form(0), expected_start: str = Form(None),
                    note: str = Form(None)):
    """Correzione della posizione: tutti i campi anagrafici, anche dopo l'assunzione.

    `budget_id` e `role_type` sono NOT NULL / con default: un valore vuoto o
    inesistente lascia il dato attuale invece di romperlo.
    """
    cur = db.one("SELECT budget_id, role_type FROM hiring_position WHERE id=?", (pid,))
    if not cur:
        return RedirectResponse("/comp/hiring", status_code=302)
    bid = cur["budget_id"]
    if budget_id and db.one("SELECT id FROM hiring_budget WHERE id=?", (budget_id,)):
        bid = int(budget_id)
    db.execute(
        "UPDATE hiring_position SET title=?, team_id=?, role_type=?, budget_id=?, "
        "expected_ral=?, expected_start=?, note=? WHERE id=?",
        (title.strip(), team_id or None, role_type or cur["role_type"], bid,
         expected_ral, expected_start or None, note or None, pid))
    return RedirectResponse("/comp/hiring", status_code=302)


@router.post("/comp/hiring/position/{pid}/void")
def position_void(pid: int):
    db.execute("UPDATE hiring_position SET voided=1, void_reason='annullata da UI' WHERE id=?",
               (pid,))
    return RedirectResponse("/comp/hiring", status_code=302)


# ---- montepremi ----

def _role_factors() -> dict[str, float]:
    """Moltiplicatori aziendali per ruolo (Azienda → Premi), per il premio di ruolo di HR (0.43)."""
    return {r["role_type"]: r["factor"] for r in db.query("SELECT * FROM bonus_role_factor")}


@router.get("/comp/bonus")
def bonus_list(request: Request):
    """HR (0.43) vede i suoi montepremi per ruolo e li crea qui; il director i suoi compositi."""
    ctx = hrview.context(request)
    pools, hr_pools = [], []
    for p in db.query("SELECT * FROM bonus_pool ORDER BY id DESC"):
        allocs = db.query(
            "SELECT COALESCE(SUM(final_amount),0) AS t, COUNT(*) AS n FROM bonus_allocation "
            "WHERE pool_id=? AND voided=0 AND included=1", (p["id"],))[0]
        row = {**dict(p), "allocated": allocs["t"], "n": allocs["n"],
               "deletable": p["status"] != "chiuso" or not db.one(
                   "SELECT 1 FROM bonus_allocation WHERE pool_id=? AND voided=0 AND (COALESCE(final_amount,0) > 0 OR COALESCE(proposed_amount,0) > 0)", (p["id"],))}
        if p["kind"] == "ruolo" and not ctx["hr"]:
            row["approved"] = _my_approval(p["id"]) is not None   # il director: la sua parte (vista sulle sue persone)
            hr_pools.append(row)
        elif (p["kind"] == "ruolo") == ctx["hr"]:
            pools.append(row)
    teams = db.query("SELECT id, name, owner_user_id FROM team WHERE archived_at IS NULL AND holding=0 ORDER BY name")
    return _templates().TemplateResponse(request, "bonus_list.html", {
        **ctx, "pools": pools, "hr_pools": hr_pools, "role_factors": _role_factors(), "year": date.today().year - 1,
        "team_opts": [{"id": t["id"], "name": t["name"] + (f" · {ctx['directors'][t['owner_user_id']]}"
                                                           if ctx["directors"].get(t["owner_user_id"]) else "")}
                      for t in teams],
    })


@router.post("/comp/bonus")
async def bonus_create(request: Request):
    """Tetto fisso oppure cifra a testa × platea (ricalcolato quando la platea cambia). Per HR (0.43)
    nasce un pool «ruolo»: anno di competenza, team della platea, ruoli esclusi, data «in organico»."""
    form = await request.form()
    period = (form.get("period") or "").strip()
    per_head = form.get("per_head")
    ph = float(per_head) if per_head else None
    cap = float(form.get("total_cap") or 0)
    if hrview.is_hr():
        year = int(form.get("competence_year") or date.today().year - 1)
        teams = json.dumps([int(t) for t in form.getlist("team") if str(t).isdigit()])
        roles = json.dumps([r for r in form.getlist("excluded_role") if r])
        ref_date = form.get("ref_date") or f"{year}-12-31"
        pool_id = db.execute(
            "INSERT INTO bonus_pool (period, total_cap, per_head, kind, competence_year, ref_date, teams, excluded_roles, "
            "use_box, use_rating, use_goal) VALUES (?,?,?, 'ruolo', ?,?,?,?, 0, 0, 0)",
            (period, cap, ph, year, ref_date, teams, roles))
        return bonus_generate(pool_id)
    if ph:
        n = db.one("SELECT COUNT(*) AS n FROM person WHERE status='attivo'")["n"]
        cap = round(ph * n, 2)
    pool_id = db.execute(
        "INSERT INTO bonus_pool (period, total_cap, per_head) VALUES (?,?,?)",
        (period, cap, ph))
    return RedirectResponse(f"/comp/bonus/{pool_id}", status_code=302)


def _platea_ruolo(pool) -> list[dict]:
    """Platea del premio di ruolo: persone attive nei team scelti (tutti se nessuno), in organico alla
    data di riferimento, col ruolo prevalente nell'anno di competenza non fra quelli esclusi.
    Si legge dalla connessione di sistema: il premio attraversa i perimetri dei director."""
    teams = json.loads(pool["teams"] or "[]")
    excluded = set(json.loads(pool["excluded_roles"] or "[]"))
    ref = str(pool["ref_date"] or f"{pool['competence_year']}-12-31")[:10]
    rows = db.sys.query(
        """SELECT p.id, p.full_name, p.hire_date, pa.team_id, pa.role_type AS role_now,
                  COALESCE(t.owner_user_id, p.owner_user_id) AS director_id
           FROM person p
           LEFT JOIN person_assignment pa ON pa.person_id = p.id AND pa.voided = 0 AND pa.end_date IS NULL
           LEFT JOIN team t ON t.id = pa.team_id
           WHERE p.status = 'attivo' ORDER BY p.full_name""")
    out = []
    for r in rows:
        if teams and r["team_id"] not in teams:
            continue
        if r["hire_date"] and str(r["hire_date"])[:10] > ref:
            continue
        hist = db.sys.query("SELECT role_type, start_date, end_date FROM person_assignment WHERE person_id=? AND voided=0",
                            (r["id"],))
        role = budget_svc.role_prevalente([dict(h) for h in hist], pool["competence_year"]) or r["role_now"]
        if role in excluded:
            continue
        out.append({**dict(r), "role_proposed": role})
    return out


def _generate_ruolo(pool) -> None:
    """Proposte del premio di ruolo: peso = moltiplicatore del ruolo usato (quello scelto sull'allocazione,
    altrimenti il prevalente dell'anno). Platea ricalcolata; chi ne esce resta escluso, chi era escluso
    a mano resta escluso; i finali ritoccati a mano restano. Scrive dalla connessione di sistema: il
    pool è di HR ma lo tocca anche il director che cambia un ruolo delle sue persone."""
    factors = _role_factors()
    existing = {a["person_id"]: a for a in db.sys.query("SELECT * FROM bonus_allocation WHERE pool_id=?", (pool["id"],))}
    platea = {r["id"]: r for r in _platea_ruolo(pool)}
    rows = {}
    for pid, r in platea.items():
        prev = existing.get(pid)
        role = prev["role_type"] if prev and prev["role_type"] else r["role_proposed"]
        included = prev["included"] if prev else 1
        rows[pid] = (r["role_proposed"], role, factors.get(role, 1.0), included)
    weights = {pid: f for pid, (_, _, f, inc) in rows.items() if inc}
    cap = pool["total_cap"]
    with db.sys.transaction() as conn:
        if pool["per_head"]:
            cap = round(pool["per_head"] * len(weights), 2)
            conn.execute("UPDATE bonus_pool SET total_cap=? WHERE id=?", (cap, pool["id"]))
        proposals = budget_svc.bonus_proposals(cap, weights)
        for pid, (proposed, role, f, inc) in rows.items():
            amount = proposals.get(pid, 0) if inc else 0
            prev = existing.get(pid)
            manual = prev and prev["final_amount"] is not None and prev["final_amount"] != prev["proposed_amount"]
            final = prev["final_amount"] if manual and inc else amount
            conn.execute(
                "INSERT INTO bonus_allocation (pool_id, person_id, weight, proposed_amount, final_amount, included, "
                "role_proposed, role_type, weight_detail) VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(pool_id, person_id) DO UPDATE SET weight=excluded.weight, "
                "proposed_amount=excluded.proposed_amount, final_amount=excluded.final_amount, "
                "role_proposed=excluded.role_proposed, role_type=excluded.role_type, weight_detail=excluded.weight_detail",
                (pool["id"], pid, f, amount, final, inc, proposed, role, json.dumps({"role": role, "role_f": f})))
        # chi non è più in platea (team, data, ruolo escluso) esce, ma la riga resta visibile come esclusa
        for pid, prev in existing.items():
            if pid not in rows and prev["included"]:
                conn.execute("UPDATE bonus_allocation SET included=0, proposed_amount=0, final_amount=0 WHERE id=?",
                             (prev["id"],))


def _my_approval(pool_id: int):
    s = session.current()
    return db.sys.one("SELECT * FROM bonus_pool_approval WHERE pool_id=? AND user_id=?", (pool_id, s.user_id)) if s else None


@router.post("/comp/bonus/{pool_id}/send")
def bonus_send(pool_id: int):
    """HR invia il premio di ruolo ai director: ognuno vede le sue persone, può cambiare il ruolo e approva."""
    pool = db.one("SELECT * FROM bonus_pool WHERE id=?", (pool_id,))
    if pool and pool["kind"] == "ruolo" and pool["status"] == "bozza" and hrview.is_hr():
        _generate_ruolo(pool)
        db.sys.execute("UPDATE bonus_pool SET status='in_approvazione' WHERE id=?", (pool_id,))
        perimeter.bump()   # ora lo vedono i director
    return RedirectResponse(f"/comp/bonus/{pool_id}", status_code=302)


@router.post("/comp/bonus/{pool_id}/recall")
def bonus_recall(pool_id: int):
    """HR richiama in bozza: le approvazioni date cadono, i director non lo vedono più."""
    pool = db.one("SELECT * FROM bonus_pool WHERE id=?", (pool_id,))
    if pool and pool["kind"] == "ruolo" and pool["status"] == "in_approvazione" and hrview.is_hr():
        with db.sys.transaction() as conn:
            conn.execute("DELETE FROM bonus_pool_approval WHERE pool_id=?", (pool_id,))
            conn.execute("UPDATE bonus_pool SET status='bozza' WHERE id=?", (pool_id,))
        perimeter.bump()
    return RedirectResponse(f"/comp/bonus/{pool_id}", status_code=302)


@router.post("/comp/bonus/{pool_id}/approve")
def bonus_approve(pool_id: int, note: str = Form(None)):
    """Il director approva la sua parte del premio di ruolo (una volta sola; HR può richiamare)."""
    pool = db.one("SELECT * FROM bonus_pool WHERE id=?", (pool_id,))
    s = session.current()
    if pool and pool["kind"] == "ruolo" and pool["status"] == "in_approvazione" and s and s.role == "director":
        db.sys.execute("INSERT OR IGNORE INTO bonus_pool_approval (pool_id, user_id, note) VALUES (?,?,?)",
                       (pool_id, s.user_id, (note or "").strip() or None))
    return RedirectResponse(f"/comp/bonus/{pool_id}", status_code=302)


@router.post("/comp/bonus/{pool_id}/alloc/{aid}/role")
def bonus_alloc_role(pool_id: int, aid: int, role_type: str = Form("")):
    """Premio di ruolo (0.43): il ruolo usato per questa allocazione (vuoto = torna al prevalente).
    HR finché non è chiuso; il director, sulle sue persone, mentre è in approvazione e prima di approvare."""
    pool = db.one("SELECT * FROM bonus_pool WHERE id=?", (pool_id,))
    alloc = db.one("SELECT id FROM bonus_allocation WHERE id=? AND pool_id=?", (aid, pool_id))   # la vista: solo le sue persone
    if pool and alloc and pool["kind"] == "ruolo" and pool["status"] != "chiuso":
        ok = hrview.is_hr() or (pool["status"] == "in_approvazione" and not _my_approval(pool_id))
        if ok:
            db.sys.execute("UPDATE bonus_allocation SET role_type=? WHERE id=?", (role_type or None, aid))
            _generate_ruolo(pool)
    return RedirectResponse(f"/comp/bonus/{pool_id}", status_code=302)


def _pool_recompute_cap(pool_id: int) -> None:
    """Con la cifra a testa, il tetto segue la platea inclusa."""
    pool = db.one("SELECT * FROM bonus_pool WHERE id=?", (pool_id,))
    if not pool or not pool["per_head"]:
        return
    n = db.one(
        "SELECT COUNT(*) AS n FROM bonus_allocation WHERE pool_id=? AND voided=0 AND included=1",
        (pool_id,))["n"]
    if n == 0 and not db.one(
            "SELECT 1 FROM bonus_allocation WHERE pool_id=? AND voided=0", (pool_id,)):
        n = db.one("SELECT COUNT(*) AS n FROM person WHERE status='attivo'")["n"]
    db.execute("UPDATE bonus_pool SET total_cap=? WHERE id=?",
               (round(pool["per_head"] * n, 2), pool_id))


@router.get("/comp/bonus/{pool_id}")
def bonus_detail(request: Request, pool_id: int):
    pool = db.one("SELECT * FROM bonus_pool WHERE id=?", (pool_id,))
    if not pool:
        return RedirectResponse("/comp/bonus", status_code=302)
    allocs = []
    for a in db.query(
            "SELECT ba.*, p.full_name FROM bonus_allocation ba JOIN person p ON p.id=ba.person_id "
            "WHERE ba.pool_id=? AND ba.voided=0 ORDER BY p.full_name", (pool_id,)):
        detail = json.loads(a["weight_detail"]) if a["weight_detail"] else None
        allocs.append({**dict(a), "detail": detail})
    residual = budget_svc.pool_residual(pool["total_cap"], [a["final_amount"] or 0 for a in allocs])
    ctx = hrview.context(request)
    if pool["kind"] == "ruolo":
        cur = {r["id"]: dict(r) for r in db.query(
            """SELECT p.id, t.name AS team_name, pa.role_type AS role_now, COALESCE(t.owner_user_id, p.owner_user_id) AS director_id
               FROM person p LEFT JOIN person_assignment pa ON pa.person_id=p.id AND pa.voided=0 AND pa.end_date IS NULL
               LEFT JOIN team t ON t.id=pa.team_id""")}
        for a in allocs:
            c = cur.get(a["person_id"], {})
            a.update(team_name=c.get("team_name"), role_now=c.get("role_now"),
                     director=ctx["directors"].get(c.get("director_id")))
        allocs.sort(key=lambda a: (not a["included"], a["director"] or "", a["team_name"] or "", a["full_name"]))
    teams = {t["id"]: t["name"] for t in db.query("SELECT id, name FROM team")}
    approvals, my_approval, can_edit_role = [], None, False
    if pool["kind"] == "ruolo":
        names = users.director_names()
        done = {a["user_id"]: a for a in db.sys.query("SELECT * FROM bonus_pool_approval WHERE pool_id=?", (pool_id,))}
        if ctx["hr"]:
            # i director con persone incluse nel premio, e chi ha già approvato
            dids = sorted({r["director_id"] for r in _platea_ruolo(pool) if r["director_id"]}
                          | set(done), key=lambda d: names.get(d, ""))
            approvals = [{"id": d, "name": names.get(d, f"#{d}"), "approval": done.get(d)} for d in dids]
            can_edit_role = pool["status"] != "chiuso"
        else:
            my_approval = _my_approval(pool_id)
            can_edit_role = pool["status"] == "in_approvazione" and my_approval is None
    return _templates().TemplateResponse(request, "bonus_detail.html", {
        **ctx, "pool": pool, "allocs": allocs, "residual": residual, "role_factors": _role_factors(),
        "approvals": approvals, "my_approval": my_approval, "can_edit_role": can_edit_role,
        "pool_teams": [teams.get(t, f"#{t}") for t in json.loads(pool["teams"] or "[]")],
        "pool_excluded_roles": json.loads(pool["excluded_roles"] or "[]"),
    })


def _person_bonus_inputs(pid: int) -> dict:
    """Raccoglie gli ingredienti del peso composito per una persona."""
    box = db.one(
        "SELECT box_number FROM ninebox_assessment WHERE person_id=? AND voided=0 "
        "ORDER BY eval_date DESC, id DESC LIMIT 1", (pid,))
    role = db.one(
        "SELECT role_type FROM person_assignment WHERE person_id=? AND voided=0 "
        "AND end_date IS NULL ORDER BY start_date DESC LIMIT 1", (pid,))
    review = db.one(
        """SELECT pr.id, pr.overall_rating FROM performance_review pr
           JOIN review_cycle rc ON rc.id = pr.cycle_id
           WHERE pr.person_id=? AND pr.voided=0 AND pr.status='finalizzata'
           ORDER BY rc.year DESC, pr.id DESC LIMIT 1""", (pid,))
    goal_sc = None
    if review:
        items = [dict(r) for r in db.query(
            """SELECT g.weight_pct, gr.tl_score FROM goal_review gr
               JOIN goal g ON g.id = gr.goal_id
               WHERE gr.review_id=? AND g.voided=0 AND g.category='professionale'""",
            (review["id"],))]
        goal_sc = goal_score.weighted_score(items, "tl_score")
    return {
        "box": box["box_number"] if box else None,
        "role": role["role_type"] if role else None,
        "rating": review["overall_rating"] if review else None,
        "goal_score": goal_sc,
    }


@router.post("/comp/bonus/{pool_id}/generate")
def bonus_generate(pool_id: int):
    """Proposte dal peso composito, coi soli fattori attivi sul pool e solo per gli inclusi."""
    pool = db.one("SELECT * FROM bonus_pool WHERE id=?", (pool_id,))
    if pool and pool["kind"] == "ruolo":
        _generate_ruolo(pool)
        return RedirectResponse(f"/comp/bonus/{pool_id}", status_code=302)
    _pool_recompute_cap(pool_id)
    mapping = {r["box_number"]: r["weight"] for r in db.query("SELECT * FROM weight_mapping")}
    factors = {(f["kind"], f["code"]): f["factor"] for f in db.query("SELECT * FROM bonus_factor")}
    excluded = {r["person_id"] for r in db.query(
        "SELECT person_id FROM bonus_allocation WHERE pool_id=? AND included=0", (pool_id,))}
    weights, details = {}, {}
    for p in db.query("SELECT id FROM person WHERE status='attivo'"):
        inp = _person_bonus_inputs(p["id"])
        # un fattore spento non pesa (×1); col 9-box spento la base è 1 per tutti
        box_w = mapping.get(inp["box"], 0) if pool["use_box"] else 1.0
        role_f = (factors.get(("role", inp["role"]), 1.0) if inp["role"] else 1.0) \
            if pool["use_role"] else 1.0
        rating_f = (factors.get(("rating", str(inp["rating"])), 1.0) if inp["rating"] else 1.0) \
            if pool["use_rating"] else 1.0
        goal_f = budget_svc.goal_factor(inp["goal_score"]) if pool["use_goal"] else 1.0
        weights[p["id"]] = budget_svc.composite_weight(box_w, role_f, rating_f, goal_f)
        details[p["id"]] = json.dumps({
            "box": inp["box"], "box_w": box_w, "role": inp["role"], "role_f": role_f,
            "rating": inp["rating"], "rating_f": rating_f,
            "goal_score": inp["goal_score"], "goal_f": goal_f})
    proposals = budget_svc.bonus_proposals(
        pool["total_cap"], {pid: w for pid, w in weights.items() if pid not in excluded})
    existing = {a["person_id"]: a for a in db.query(
        "SELECT * FROM bonus_allocation WHERE pool_id=?", (pool_id,))}
    with db.transaction() as conn:
        for pid, w in weights.items():
            amount = proposals.get(pid, 0)
            prev = existing.get(pid)
            manual = prev and prev["final_amount"] is not None \
                and prev["final_amount"] != prev["proposed_amount"]
            final = prev["final_amount"] if manual else amount
            conn.execute(
                "INSERT INTO bonus_allocation (pool_id, person_id, weight, proposed_amount, "
                "final_amount, weight_detail) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(pool_id, person_id) DO UPDATE SET weight=excluded.weight, "
                "proposed_amount=excluded.proposed_amount, final_amount=excluded.final_amount, "
                "weight_detail=excluded.weight_detail",
                (pool_id, pid, w, amount, final, details[pid]))
    return RedirectResponse(f"/comp/bonus/{pool_id}", status_code=302)


def _redistribute(pool_id: int) -> None:
    """Ridistribuisce le proposte tra gli inclusi; i finali ritoccati a mano restano."""
    pool = db.one("SELECT * FROM bonus_pool WHERE id=?", (pool_id,))
    if pool and pool["kind"] == "ruolo":
        return _generate_ruolo(pool)
    _pool_recompute_cap(pool_id)
    allocs = db.query("SELECT * FROM bonus_allocation WHERE pool_id=? AND voided=0", (pool_id,))
    weights = {a["person_id"]: a["weight"] for a in allocs if a["included"]}
    proposals = budget_svc.bonus_proposals(pool["total_cap"], weights)
    with db.transaction() as conn:
        for a in allocs:
            if not a["included"]:
                conn.execute(
                    "UPDATE bonus_allocation SET proposed_amount=0, final_amount=0 WHERE id=?",
                    (a["id"],))
                continue
            new_prop = proposals.get(a["person_id"], 0)
            manual = a["final_amount"] is not None and a["final_amount"] != a["proposed_amount"]
            conn.execute(
                "UPDATE bonus_allocation SET proposed_amount=?, final_amount=? WHERE id=?",
                (new_prop, a["final_amount"] if manual else new_prop, a["id"]))


@router.post("/comp/bonus/{pool_id}/alloc/{aid}/toggle")
def bonus_alloc_toggle(pool_id: int, aid: int):
    """Include/esclude una persona dalla platea del premio."""
    db.execute(
        "UPDATE bonus_allocation SET included = 1 - included WHERE id=? AND pool_id=?",
        (aid, pool_id))
    _redistribute(pool_id)
    return RedirectResponse(f"/comp/bonus/{pool_id}", status_code=302)


@router.post("/comp/bonus/{pool_id}/factors")
def bonus_factors_toggle(pool_id: int, use_box: str = Form(None), use_role: str = Form(None),
                         use_rating: str = Form(None), use_goal: str = Form(None)):
    """Accende/spegne le colonne di valutazione del pool e rigenera le proposte."""
    db.execute(
        "UPDATE bonus_pool SET use_box=?, use_role=?, use_rating=?, use_goal=? WHERE id=?",
        (1 if use_box else 0, 1 if use_role else 0,
         1 if use_rating else 0, 1 if use_goal else 0, pool_id))
    return bonus_generate(pool_id)


@router.post("/comp/bonus/{pool_id}/alloc/{aid}")
def bonus_alloc_update(request: Request, pool_id: int, aid: int,
                       final_amount: float = Form(0), note: str = Form(None)):
    db.execute(
        "UPDATE bonus_allocation SET final_amount=?, note=? WHERE id=? AND pool_id=?",
        (final_amount, note or None, aid, pool_id))
    pool = db.one("SELECT * FROM bonus_pool WHERE id=?", (pool_id,))
    allocs = db.query(
        "SELECT final_amount FROM bonus_allocation WHERE pool_id=? AND voided=0", (pool_id,))
    residual = budget_svc.pool_residual(pool["total_cap"], [a["final_amount"] or 0 for a in allocs])
    return _templates().TemplateResponse(request, "_bonus_residual.html", {
        "pool": pool, "residual": residual,
    })


@router.post("/comp/bonus/{pool_id}/close")
def bonus_close(pool_id: int):
    db.execute("UPDATE bonus_pool SET status='chiuso' WHERE id=?", (pool_id,))
    return RedirectResponse(f"/comp/bonus/{pool_id}", status_code=302)


@router.post("/comp/bonus/{pool_id}/reopen")
def bonus_reopen(pool_id: int):
    db.execute("UPDATE bonus_pool SET status='bozza' WHERE id=?", (pool_id,))
    return RedirectResponse(f"/comp/bonus/{pool_id}", status_code=302)


@router.post("/comp/bonus/{pool_id}/update")
def bonus_update(pool_id: int, period: str = Form(...), total_cap: str = Form(None),
                 per_head: str = Form(None)):
    """Correzione dei dati iniziali del pool (solo se non chiuso)."""
    pool = db.one("SELECT * FROM bonus_pool WHERE id=?", (pool_id,))
    if pool and pool["status"] != "chiuso":
        ph = float(per_head) if per_head else None
        db.execute("UPDATE bonus_pool SET period=?, total_cap=?, per_head=? WHERE id=?",
                   (period.strip(), float(total_cap or 0), ph, pool_id))
        if ph:
            _redistribute(pool_id)
    return RedirectResponse(f"/comp/bonus/{pool_id}", status_code=302)


def _competence_year(pool) -> int:
    """Anno di competenza del pool: prima sequenza di 4 cifre nel periodo, altrimenti l'anno corrente."""
    import re

    m = re.search(r"\b(20\d\d)\b", pool["period"] or "")
    return int(m.group(1)) if m else date.today().year


@router.post("/comp/bonus/{pool_id}/exclude-rule")
def bonus_exclude_rule(pool_id: int, rule: str = Form(...)):
    """Esclusioni rapide: assunti nell'ultimo anno solare, o non operativi ≥6 mesi nell'anno di competenza."""
    pool = db.one("SELECT * FROM bonus_pool WHERE id=?", (pool_id,))
    if not pool or pool["status"] == "chiuso":
        return RedirectResponse(f"/comp/bonus/{pool_id}", status_code=302)
    allocs = db.query(
        "SELECT ba.id, p.hire_date, p.end_date FROM bonus_allocation ba "
        "JOIN person p ON p.id = ba.person_id WHERE ba.pool_id=? AND ba.voided=0", (pool_id,))
    to_exclude = []
    if rule == "recent":
        limit = date.today() - timedelta(days=365)
        for a in allocs:
            if a["hire_date"] and date.fromisoformat(str(a["hire_date"])[:10]) > limit:
                to_exclude.append(a["id"])
    elif rule == "competence":
        year = _competence_year(pool)
        y_start, y_end = date(year, 1, 1), date(year, 12, 31)
        for a in allocs:
            if not a["hire_date"]:
                continue  # data ignota: resta inclusa, si valuta a mano
            start = max(date.fromisoformat(str(a["hire_date"])[:10]), y_start)
            end = min(date.fromisoformat(str(a["end_date"])[:10]), y_end) if a["end_date"] else y_end
            if (end - start).days + 1 < 182:
                to_exclude.append(a["id"])
    if to_exclude:
        db.executemany(
            "UPDATE bonus_allocation SET included=0 WHERE id=?", [(i,) for i in to_exclude])
    _redistribute(pool_id)
    qs = f"?excluded={len(to_exclude)}"
    return RedirectResponse(f"/comp/bonus/{pool_id}{qs}", status_code=302)


@router.post("/comp/bonus/{pool_id}/delete")
def bonus_delete(pool_id: int):
    """Elimina pool e allocazioni: se non chiuso, oppure chiuso ma senza importi assegnati (0.47)."""
    pool = db.one("SELECT * FROM bonus_pool WHERE id=?", (pool_id,))
    assegnato = db.one("SELECT COALESCE(SUM(final_amount), 0) + COALESCE(SUM(proposed_amount), 0) AS t "
                       "FROM bonus_allocation WHERE pool_id=? AND voided=0", (pool_id,))["t"] if pool else 0
    if pool and (pool["status"] != "chiuso" or not assegnato):
        with db.transaction() as conn:
            conn.execute("DELETE FROM bonus_allocation WHERE pool_id=?", (pool_id,))
            conn.execute("DELETE FROM bonus_pool WHERE id=?", (pool_id,))
        db.sys.execute("DELETE FROM bonus_pool_approval WHERE pool_id=?", (pool_id,))
        return RedirectResponse("/comp/bonus", status_code=302)
    return RedirectResponse(f"/comp/bonus/{pool_id}", status_code=302)
