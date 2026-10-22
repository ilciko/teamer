"""Organigramma: persone, team, assegnazioni, situazione contrattuale."""
import base64
from datetime import date, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Query, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from app import db
from app.services import budget as budget_svc
from app.services import org_tree as org_svc
from app.services import cost

router = APIRouter()


def _templates():
    from app.main import templates

    return templates


def initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    return "".join(p[0].upper() for p in parts[:2]) or "?"


def avatar_data(row) -> str | None:
    if row["avatar"]:
        return "data:image/jpeg;base64," + base64.b64encode(row["avatar"]).decode()
    return None


def current_assignment(person_id: int):
    return db.one(
        "SELECT pa.*, t.name AS team_name, m.full_name AS manager_name, "
        "lp.code AS listino_code, lp.description AS listino_desc, lp.active AS listino_active "
        "FROM person_assignment pa "
        "JOIN team t ON t.id = pa.team_id "
        "LEFT JOIN person m ON m.id = pa.manager_person_id "
        "LEFT JOIN listino_profile lp ON lp.id = pa.listino_profile_id "
        "WHERE pa.person_id=? AND pa.voided=0 AND pa.end_date IS NULL "
        "ORDER BY pa.start_date DESC LIMIT 1",
        (person_id,),
    )


def _lp(raw: str | None) -> int | None:
    """Codice di listino dal form: vuoto = nessuno."""
    return int(raw) if raw else None


def seniority_from(start_date: str | None) -> str:
    """new < 12 mesi, mid 1–3 anni, sen > 3 anni (dalla data di inizio assegnazione)."""
    if not start_date:
        return "mid"
    days = (date.today() - date.fromisoformat(str(start_date)[:10])).days
    return "new" if days < 365 else "mid" if days <= 3 * 365 else "sen"


# ---- riporti derivati da team e ruolo ----

def _role_order() -> dict:
    return {r["code"]: r["sort_order"] for r in db.query(
        "SELECT code, sort_order FROM lookup WHERE category='role_type'")}


def _report_state():
    """Persone attive con l'assegnazione corrente, e team: l'input del calcolo riporti."""
    people = [dict(r) for r in db.query(
        """SELECT p.id, p.full_name, pa.id AS assignment_id, pa.role_type, pa.team_id,
                  pa.manager_person_id, pa.start_date, pa.listino_profile_id
           FROM person p
           LEFT JOIN person_assignment pa ON pa.id = (
               SELECT pa2.id FROM person_assignment pa2
               WHERE pa2.person_id = p.id AND pa2.voided=0 AND pa2.end_date IS NULL
               ORDER BY pa2.start_date DESC, pa2.id DESC LIMIT 1)
           WHERE p.status='attivo' ORDER BY p.full_name""")]
    teams = [dict(r) for r in db.query(
        "SELECT id, name, parent_team_id, lead_person_id, sort_order FROM team WHERE archived_at IS NULL")]
    return people, teams


def _derive_manager(pid: int) -> None:
    """Il riporto diretto non si sceglie: si ricalcola sull'assegnazione corrente della persona."""
    people, teams = _report_state()
    me = next((p for p in people if p["id"] == pid), None)
    if me and me["assignment_id"]:
        db.execute("UPDATE person_assignment SET manager_person_id=? WHERE id=?",
                   (org_svc.expected_manager(me, people, teams, _role_order()), me["assignment_id"]))


def _verify_reports(next_url: str, mode: str = "correzione", on_date: str | None = None) -> RedirectResponse:
    """Trigger dopo responsabile del team, ruolo o team cambiati: se qualche riporto non
    torna più si passa dalla verifica, altrimenti si prosegue dove si stava andando."""
    people, teams = _report_state()
    if not org_svc.report_mismatches(people, teams, _role_order()):
        return RedirectResponse(next_url, status_code=302)
    q = urlencode({"next": next_url, "mode": mode, "date": on_date or date.today().isoformat()})
    return RedirectResponse(f"/org/riporti?{q}", status_code=302)


@router.get("/org/riporti")
def reports_check(request: Request, next: str = "/org", mode: str = "correzione", date_: str = Query("", alias="date")):
    people, teams = _report_state()
    names = {p["id"]: p["full_name"] for p in people}
    team_names = {t["id"]: t["name"] for t in teams}
    rows = [{**m, "current_name": names.get(m["current"]) if m["current"] else None,
             "expected_name": names.get(m["expected"]) if m["expected"] else None,
             "inactive": m["current"] is not None and m["current"] not in names,
             "team_name": team_names.get(m["person"]["team_id"], "—")}
            for m in org_svc.report_mismatches(people, teams, _role_order())]
    return _templates().TemplateResponse(request, "org_riporti.html", {
        "rows": rows, "next": next if next.startswith("/") else "/org",
        "mode": "cambiamento" if mode == "cambiamento" else "correzione",
        "on_date": date_ or date.today().isoformat(),
    })


@router.post("/org/riporti")
async def reports_apply(request: Request):
    """Applica i riporti attesi alle persone spuntate.

    `correzione` sovrascrive l'assegnazione corrente; `cambiamento` la chiude il giorno
    prima della data e ne apre una nuova uguale col riporto nuovo (storico conservato).
    """
    form = await request.form()
    chosen = {int(x) for x in form.getlist("pid") if str(x).isdigit()}
    mode = form.get("mode", "correzione")
    on_date = form.get("date") or date.today().isoformat()
    nxt = form.get("next") or "/org"
    people, teams = _report_state()
    todo = [m for m in org_svc.report_mismatches(people, teams, _role_order()) if m["person"]["id"] in chosen]
    with db.transaction() as conn:
        for m in todo:
            a = m["person"]
            if mode == "cambiamento" and str(a["start_date"]) < on_date:
                prev_end = (date.fromisoformat(on_date) - timedelta(days=1)).isoformat()
                conn.execute("UPDATE person_assignment SET end_date=? WHERE id=?", (prev_end, a["assignment_id"]))
                conn.execute(
                    "INSERT INTO person_assignment (person_id, team_id, manager_person_id, role_type, start_date, "
                    "listino_profile_id) VALUES (?,?,?,?,?,?)",
                    (a["id"], a["team_id"], m["expected"], a["role_type"], on_date, a["listino_profile_id"]))
            else:
                conn.execute("UPDATE person_assignment SET manager_person_id=? WHERE id=?",
                             (m["expected"], a["assignment_id"]))
    return RedirectResponse(nxt if nxt.startswith("/") else "/org", status_code=302)


@router.get("/people")
def people_list(request: Request, show: str = "attivi"):
    where = "WHERE p.status = 'attivo'" if show == "attivi" else ""
    rows = db.query(
        f"""SELECT p.*, pa.role_type, t.name AS team_name
        FROM person p
        LEFT JOIN person_assignment pa ON pa.person_id = p.id AND pa.voided=0 AND pa.end_date IS NULL
        LEFT JOIN team t ON t.id = pa.team_id
        {where} ORDER BY p.full_name"""
    )
    people = []
    for r in rows:
        ral = cost.current_ral(r["id"])
        people.append({**dict(r), "ral": ral["amount"] if ral else None,
                       "initials": initials(r["full_name"]), "avatar_uri": avatar_data(r)})
    teams = db.query("SELECT * FROM team WHERE archived_at IS NULL ORDER BY name")
    listino_profiles = db.query("SELECT * FROM listino_profile WHERE active=1 ORDER BY sort_order, code")
    return _templates().TemplateResponse(request, "people_list.html",
                                         {"people": people, "show": show, "teams": teams,
                                          "listino_profiles": listino_profiles})


@router.post("/people")
def person_create(full_name: str = Form(...), hire_date: str = Form(None), email: str = Form(None),
                  team_id: str = Form(None), role_type: str = Form("ic"),
                  livello: str = Form(None), tipo_contratto: str = Form(None),
                  ral: str = Form(None), ref_date: str = Form(None),
                  listino_profile_id: str = Form(None)):
    """Censimento: crea la persona e, se forniti, lo stato attuale (team, contratto, RAL)."""
    start = ref_date or hire_date or date.today().isoformat()
    with db.transaction() as conn:
        cur = conn.execute(
            "INSERT INTO person (full_name, hire_date, email) VALUES (?,?,?)",
            (full_name.strip(), hire_date or None, email or None))
        pid = cur.lastrowid
        if team_id:
            conn.execute(
                "INSERT INTO person_assignment (person_id, team_id, role_type, start_date, listino_profile_id) "
                "VALUES (?,?,?,?,?)", (pid, int(team_id), role_type, start, _lp(listino_profile_id)))
        if livello or tipo_contratto:
            conn.execute(
                "INSERT INTO employment (person_id, livello, tipo_contratto, ccnl, start_date) "
                "VALUES (?,?,?,?,?)",
                (pid, livello or None, tipo_contratto or None,
                 db.get_meta("default_ccnl") or None, start))
        if ral:
            # chi è assunto dopo il censimento parte dalla sua assunzione
            ral_start = max(start, hire_date) if hire_date else start
            conn.execute(
                "INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type) "
                "VALUES (?,?,?,0,'censimento')", (pid, ral_start, float(ral)))
    if team_id:
        _derive_manager(pid)
        return _verify_reports(f"/people/{pid}", "cambiamento", start)
    return RedirectResponse(f"/people/{pid}", status_code=302)


@router.get("/people/{pid}")
def person_card(request: Request, pid: int):
    p = db.one("SELECT * FROM person WHERE id=?", (pid,))
    if not p:
        return RedirectResponse("/people", status_code=302)
    assignment = current_assignment(pid)
    assignments = db.query(
        "SELECT pa.*, t.name AS team_name, m.full_name AS manager_name, lp.code AS listino_code "
        "FROM person_assignment pa "
        "JOIN team t ON t.id=pa.team_id LEFT JOIN person m ON m.id=pa.manager_person_id "
        "LEFT JOIN listino_profile lp ON lp.id=pa.listino_profile_id "
        "WHERE pa.person_id=? AND pa.voided=0 ORDER BY pa.start_date DESC", (pid,))
    employment = db.one(
        "SELECT * FROM employment WHERE person_id=? AND voided=0 AND end_date IS NULL "
        "ORDER BY start_date DESC LIMIT 1", (pid,))
    employments = db.query(
        "SELECT * FROM employment WHERE person_id=? AND voided=0 ORDER BY start_date DESC", (pid,))
    ral_events = cost.derive_deltas(db.query(
        "SELECT * FROM ral_event WHERE person_id=? AND voided=0 "
        "ORDER BY effective_date DESC, id DESC", (pid,)))
    proposals = db.query(
        "SELECT pr.*, b.period FROM ral_proposal pr LEFT JOIN ral_budget b ON b.id=pr.budget_id "
        "WHERE pr.person_id=? AND pr.voided=0 AND pr.status IN ('bozza','proposta','approvata') "
        "ORDER BY pr.effective_date", (pid,))
    benefits = cost.active_benefits(pid)
    incentives = db.query(
        "SELECT * FROM incentive WHERE person_id=? AND voided=0 ORDER BY inc_date DESC", (pid,))
    nineboxes = db.query(
        "SELECT * FROM ninebox_assessment WHERE person_id=? AND voided=0 ORDER BY eval_date DESC", (pid,))
    goals = db.query(
        "SELECT g.*, rc.name AS cycle_name FROM goal g JOIN review_cycle rc ON rc.id=g.cycle_id "
        "WHERE g.person_id=? AND g.voided=0 ORDER BY rc.year DESC, g.category", (pid,))
    reviews = db.query(
        "SELECT pr.*, rc.name AS cycle_name FROM performance_review pr "
        "JOIN review_cycle rc ON rc.id=pr.cycle_id "
        "WHERE pr.person_id=? AND pr.voided=0 ORDER BY rc.year DESC", (pid,))
    notes = db.query(
        "SELECT * FROM meeting_note WHERE person_id=? AND archived_at IS NULL "
        "ORDER BY note_date DESC LIMIT 10", (pid,))
    actions = db.query(
        "SELECT * FROM action_item WHERE person_id=? AND status != 'chiuso' ORDER BY due_date", (pid,))
    attachments = db.query(
        "SELECT id, filename, note, created_at FROM attachment WHERE person_id=? ORDER BY id DESC", (pid,))
    replacement = None
    if p["status"] == "cessato":
        replacement = db.one(
            "SELECT hp.*, hb.period, hired.full_name AS hired_name FROM hiring_position hp "
            "JOIN hiring_budget hb ON hb.id = hp.budget_id "
            "LEFT JOIN person hired ON hired.id = hp.person_id "
            "WHERE hp.replaces_person_id=? AND hp.voided=0 ORDER BY hp.id DESC LIMIT 1", (pid,))
    teams = db.query("SELECT * FROM team WHERE archived_at IS NULL ORDER BY name")
    people_opts = db.query("SELECT id, full_name FROM person WHERE status='attivo' ORDER BY full_name")
    # navigazione precedente/prossimo in ordine alfabetico (tra i cessati se la scheda è di un cessato)
    nav_pool = people_opts if p["status"] == "attivo" else db.query(
        "SELECT id, full_name FROM person ORDER BY full_name")
    prev_p = next_p = None
    for i, row in enumerate(nav_pool):
        if row["id"] == pid:
            prev_p = nav_pool[i - 1] if i > 0 else None
            next_p = nav_pool[i + 1] if i < len(nav_pool) - 1 else None
            break
    # riporto atteso: se quello salvato non torna, la scheda rimanda alla verifica
    report_mismatch = False
    if assignment and p["status"] == "attivo":
        r_people, r_teams = _report_state()
        me = next((x for x in r_people if x["id"] == pid), None)
        report_mismatch = bool(me) and me["manager_person_id"] != org_svc.expected_manager(
            me, r_people, r_teams, _role_order())
    year = str(date.today().year)
    ral_trend = [
        {"x": str(r["effective_date"]), "y": r["amount"]}
        for r in reversed(ral_events)
    ]
    return _templates().TemplateResponse(request, "person_card.html", {
        "p": p, "initials": initials(p["full_name"]), "avatar_uri": avatar_data(p),
        "assignment": assignment, "assignments": assignments,
        "employment": employment, "employments": employments,
        "ral_events": ral_events, "ral_trend": ral_trend, "proposals": proposals,
        "benefits": benefits, "incentives": incentives,
        "benefit_types": db.query("SELECT * FROM benefit_type WHERE active=1 ORDER BY name"),
        "nineboxes": nineboxes, "goals": goals, "reviews": reviews,
        "notes": notes, "actions": actions, "attachments": attachments,
        "teams": teams, "people_opts": people_opts,
        "listino_profiles": db.query("SELECT * FROM listino_profile WHERE active=1 ORDER BY sort_order, code"),
        "prev_p": prev_p, "next_p": next_p, "replacement": replacement,
        "report_mismatch": report_mismatch,
        "total_cost": cost.total_cost(pid, year), "year": year,
    })


@router.post("/people/{pid}/update")
def person_update(pid: int, full_name: str = Form(...), hire_date: str = Form(None),
                  birth_date: str = Form(None), email: str = Form(None), notes: str = Form(None)):
    db.execute(
        "UPDATE person SET full_name=?, hire_date=?, birth_date=?, email=?, notes=? WHERE id=?",
        (full_name.strip(), hire_date or None, birth_date or None, email or None, notes or None, pid),
    )
    return RedirectResponse(f"/people/{pid}", status_code=302)


@router.post("/people/{pid}/avatar")
async def person_avatar(pid: int, avatar: UploadFile):
    data = await avatar.read()
    if data:
        db.execute("UPDATE person SET avatar=? WHERE id=?", (data, pid))
    return RedirectResponse(f"/people/{pid}", status_code=302)


@router.post("/people/{pid}/cessation")
def person_cessation(pid: int, end_date: str = Form(...)):
    with db.transaction() as conn:
        conn.execute("UPDATE person SET status='cessato', end_date=? WHERE id=?", (end_date, pid))
        conn.execute(
            "UPDATE person_assignment SET end_date=? WHERE person_id=? AND end_date IS NULL AND voided=0",
            (end_date, pid))
        conn.execute(
            "UPDATE employment SET end_date=? WHERE person_id=? AND end_date IS NULL AND voided=0",
            (end_date, pid))
    return RedirectResponse(f"/people/{pid}/replacement", status_code=302)


def _last_assignment(pid: int):
    """Ultima assegnazione anche se già chiusa (per i cessati)."""
    return db.one(
        "SELECT pa.*, t.name AS team_name FROM person_assignment pa "
        "JOIN team t ON t.id = pa.team_id "
        "WHERE pa.person_id=? AND pa.voided=0 ORDER BY pa.start_date DESC LIMIT 1", (pid,))


@router.get("/people/{pid}/replacement")
def replacement_page(request: Request, pid: int):
    p = db.one("SELECT * FROM person WHERE id=?", (pid,))
    if not p or p["status"] != "cessato":
        return RedirectResponse(f"/people/{pid}", status_code=302)
    assignment = _last_assignment(pid)
    ral = cost.current_ral(pid)
    start = (date.fromisoformat(str(p["end_date"])[:10]) + timedelta(days=1)).isoformat() \
        if p["end_date"] else date.today().isoformat()
    role_label = db.lookup_label("role_type", assignment["role_type"]) if assignment else ""
    return _templates().TemplateResponse(request, "replacement.html", {
        "p": p, "assignment": assignment,
        "ral": ral["amount"] if ral else 0,
        "title_suggestion": f"Sostituzione {p['full_name']}" + (f" — {role_label}" if role_label else ""),
        "expected_start": start,
        "budgets": db.query(
            "SELECT * FROM hiring_budget WHERE status='aperto' ORDER BY year DESC, id DESC"),
        "teams": db.query("SELECT * FROM team WHERE archived_at IS NULL ORDER BY name"),
    })


@router.post("/people/{pid}/replacement")
def replacement_create(pid: int, title: str = Form(...), team_id: str = Form(None),
                       role_type: str = Form("ic"), expected_ral: float = Form(0),
                       expected_start: str = Form(...), budget_id: str = Form(""),
                       add_ral_to_cap: str = Form(None), note: str = Form(None)):
    p = db.one("SELECT * FROM person WHERE id=?", (pid,))
    if not p:
        return RedirectResponse("/people", status_code=302)
    year = int(expected_start[:4])
    with db.transaction() as conn:
        if budget_id:
            bid = int(budget_id)
        else:
            existing = conn.execute(
                "SELECT id FROM hiring_budget WHERE year=? AND status='aperto' "
                "ORDER BY id LIMIT 1", (year,)).fetchone()
            if existing:
                bid = existing["id"]
            else:
                bid = conn.execute(
                    "INSERT INTO hiring_budget (period, year, total_cap, note) VALUES (?,?,0,?)",
                    (f"Assunzioni {year}", year,
                     "creato automaticamente per sostituzione")).lastrowid
        if add_ral_to_cap:
            ral = cost.current_ral(pid)
            if ral:
                conn.execute("UPDATE hiring_budget SET total_cap = total_cap + ? WHERE id=?",
                             (ral["amount"], bid))
        conn.execute(
            "INSERT INTO hiring_position (budget_id, title, team_id, role_type, expected_ral, "
            "expected_start, note, replaces_person_id) VALUES (?,?,?,?,?,?,?,?)",
            (bid, title.strip(), team_id or None, role_type, expected_ral,
             expected_start, note or f"sostituzione di {p['full_name']}", pid))
    return RedirectResponse("/comp/hiring", status_code=302)


@router.post("/people/{pid}/delete")
def person_delete(pid: int, confirm_name: str = Form(...)):
    """Eliminazione definitiva (persona inserita per errore): rimuove tutti i dati collegati.

    Per l'uscita di una persona reale usare la cessazione, che conserva lo storico.
    """
    p = db.one("SELECT * FROM person WHERE id=?", (pid,))
    if not p or confirm_name.strip().lower() != p["full_name"].strip().lower():
        return RedirectResponse(f"/people/{pid}?err=confirm", status_code=302)
    with db.transaction() as conn:
        conn.execute("DELETE FROM goal_review WHERE goal_id IN (SELECT id FROM goal WHERE person_id=?)", (pid,))
        conn.execute("DELETE FROM goal_review WHERE review_id IN (SELECT id FROM performance_review WHERE person_id=?)", (pid,))
        conn.execute("DELETE FROM wellbeing_entry WHERE review_id IN (SELECT id FROM performance_review WHERE person_id=?)", (pid,))
        conn.execute("DELETE FROM attachment WHERE person_id=?", (pid,))
        conn.execute("DELETE FROM performance_review WHERE person_id=?", (pid,))
        conn.execute("DELETE FROM goal WHERE person_id=?", (pid,))
        conn.execute("DELETE FROM ninebox_assessment WHERE person_id=?", (pid,))
        conn.execute("DELETE FROM ral_event WHERE person_id=?", (pid,))
        conn.execute("DELETE FROM benefit_assignment WHERE person_id=?", (pid,))
        conn.execute("DELETE FROM incentive WHERE person_id=?", (pid,))
        conn.execute("DELETE FROM bonus_allocation WHERE person_id=?", (pid,))
        conn.execute("DELETE FROM action_item WHERE person_id=?", (pid,))
        conn.execute("DELETE FROM meeting_note WHERE person_id=?", (pid,))
        conn.execute("DELETE FROM person_assignment WHERE person_id=?", (pid,))
        conn.execute("DELETE FROM listino_person_param WHERE person_id=?", (pid,))
        conn.execute("UPDATE person_assignment SET manager_person_id=NULL WHERE manager_person_id=?", (pid,))
        conn.execute("DELETE FROM employment WHERE person_id=?", (pid,))
        conn.execute("UPDATE team SET lead_person_id=NULL WHERE lead_person_id=?", (pid,))
        conn.execute("DELETE FROM reorg_move WHERE person_id=?", (pid,))
        conn.execute("UPDATE reorg_team SET lead_person_id=NULL WHERE lead_person_id=?", (pid,))
        conn.execute("DELETE FROM person WHERE id=?", (pid,))
    return RedirectResponse("/people", status_code=302)


def _new_assignment(pid: int, team_id: int, role_type: str, start_date: str, listino_profile_id) -> None:
    """Cambiamento reale: chiude l'assegnazione corrente e ne apre una nuova, col riporto calcolato."""
    prev_end = (date.fromisoformat(start_date) - timedelta(days=1)).isoformat()
    with db.transaction() as conn:
        conn.execute(
            "UPDATE person_assignment SET end_date=? WHERE person_id=? AND end_date IS NULL AND voided=0",
            (prev_end, pid))
        conn.execute(
            "INSERT INTO person_assignment (person_id, team_id, role_type, start_date, listino_profile_id) "
            "VALUES (?,?,?,?,?)", (pid, team_id, role_type, start_date, listino_profile_id))
    _derive_manager(pid)


@router.post("/people/{pid}/assignment")
def assignment_create(pid: int, team_id: int = Form(...), role_type: str = Form(...),
                      start_date: str = Form(...), listino_profile_id: str = Form(None)):
    _new_assignment(pid, team_id, role_type, start_date, _lp(listino_profile_id))
    return _verify_reports(f"/people/{pid}", "cambiamento", start_date)


@router.post("/people/{pid}/assignment/{aid}/update")
def assignment_update(pid: int, aid: int, team_id: int = Form(...), role_type: str = Form(...),
                      start_date: str = Form(...), listino_profile_id: str = Form(None)):
    """Correzione in place di un'assegnazione inserita con dati errati (non è un movimento)."""
    db.execute(
        "UPDATE person_assignment SET team_id=?, role_type=?, start_date=?, listino_profile_id=? "
        "WHERE id=? AND person_id=?",
        (team_id, role_type, start_date, _lp(listino_profile_id), aid, pid))
    _derive_manager(pid)
    return _verify_reports(f"/people/{pid}", "correzione")


@router.post("/people/{pid}/employment")
def employment_create(pid: int, livello: str = Form(None), ccnl: str = Form(None),
                      tipo_contratto: str = Form(None), smartwork: str = Form(None),
                      timbratura_scheme: str = Form(None), part_time_pct: float = Form(100),
                      weekly_hours: str = Form(None), start_date: str = Form(...),
                      end_date: str = Form(None), note: str = Form(None)):
    prev_end = (date.fromisoformat(start_date) - timedelta(days=1)).isoformat()
    with db.transaction() as conn:
        conn.execute(
            "UPDATE employment SET end_date=? WHERE person_id=? AND end_date IS NULL AND voided=0",
            (prev_end, pid))
        conn.execute(
            "INSERT INTO employment (person_id, livello, ccnl, tipo_contratto, smartwork, "
            "timbratura_scheme, part_time_pct, weekly_hours, start_date, end_date, note) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pid, livello or None, ccnl or None, tipo_contratto or None, smartwork or None,
             timbratura_scheme or None, part_time_pct, weekly_hours or None,
             start_date, end_date or None, note or None))
    return RedirectResponse(f"/people/{pid}", status_code=302)


@router.post("/people/{pid}/employment/{eid}/update")
def employment_update(pid: int, eid: int, livello: str = Form(None), ccnl: str = Form(None),
                      tipo_contratto: str = Form(None), smartwork: str = Form(None),
                      timbratura_scheme: str = Form(None), part_time_pct: float = Form(100),
                      weekly_hours: str = Form(None), start_date: str = Form(...),
                      end_date: str = Form(None), note: str = Form(None)):
    """Correzione in place della situazione contrattuale (non è un nuovo contratto)."""
    db.execute(
        "UPDATE employment SET livello=?, ccnl=?, tipo_contratto=?, smartwork=?, "
        "timbratura_scheme=?, part_time_pct=?, weekly_hours=?, start_date=?, end_date=?, note=? "
        "WHERE id=? AND person_id=?",
        (livello or None, ccnl or None, tipo_contratto or None, smartwork or None,
         timbratura_scheme or None, part_time_pct, weekly_hours or None,
         start_date, end_date or None, note or None, eid, pid))
    return RedirectResponse(f"/people/{pid}", status_code=302)


# ---- organigramma ----

def _team_blockers() -> dict[int, dict[str, list[str]]]:
    """Perché un team non si può eliminare: {team_id: {"block": [...], "history": [...]}}.

    `block` = c'è ancora qualcosa di vivo (sotto-team attivi, persone attive assegnate,
    posizioni aperte): né eliminabile né archiviabile. `history` = solo storia
    (assegnazioni passate, posizioni chiuse, sotto-team archiviati): non eliminabile
    senza perderla, ma archiviabile. Team assente = eliminabile. Lo stesso controllo
    lo fanno le FK, qui diventa un motivo leggibile.
    """
    out: dict[int, dict[str, list[str]]] = {}

    def add(kind, rows, fmt):
        for r in rows:
            if r["k"] is not None and r["n"]:
                out.setdefault(r["k"], {"block": [], "history": []})[kind].append(fmt(r["n"]))

    add("block", db.query("SELECT parent_team_id AS k, COUNT(*) AS n FROM team WHERE archived_at IS NULL "
                          "GROUP BY parent_team_id"),
        lambda n: f"{n} sotto-team")
    add("history", db.query("SELECT parent_team_id AS k, COUNT(*) AS n FROM team WHERE archived_at IS NOT NULL "
                            "GROUP BY parent_team_id"),
        lambda n: f"{n} sotto-team archiviat{'o' if n == 1 else 'i'}")
    current = ("pa.voided=0 AND pa.end_date IS NULL AND EXISTS "
               "(SELECT 1 FROM person p WHERE p.id = pa.person_id AND p.status='attivo')")
    add("block", db.query(f"SELECT pa.team_id AS k, COUNT(DISTINCT pa.person_id) AS n FROM person_assignment pa "
                          f"WHERE {current} GROUP BY pa.team_id"),
        lambda n: f"{n} person{'a' if n == 1 else 'e'} assegnat{'a' if n == 1 else 'e'}")
    add("history", db.query(f"SELECT pa.team_id AS k, COUNT(*) AS n FROM person_assignment pa "
                            f"WHERE NOT ({current}) GROUP BY pa.team_id"),
        lambda n: f"storico di {n} assegnazion{'e' if n == 1 else 'i'} passat{'a' if n == 1 else 'e'}")
    marks = ",".join("?" * len(budget_svc.OPEN_POSITIONS))
    add("block", db.query(f"SELECT team_id AS k, COUNT(*) AS n FROM hiring_position "
                          f"WHERE voided=0 AND status IN ({marks}) GROUP BY team_id", budget_svc.OPEN_POSITIONS),
        lambda n: f"{n} posizion{'e' if n == 1 else 'i'} apert{'a' if n == 1 else 'e'}")
    add("history", db.query(f"SELECT team_id AS k, COUNT(*) AS n FROM hiring_position "
                            f"WHERE voided=1 OR status NOT IN ({marks}) GROUP BY team_id", budget_svc.OPEN_POSITIONS),
        lambda n: f"{n} posizion{'e' if n == 1 else 'i'} nello storico assunzioni")
    return out


@router.post("/org/team/{tid}/delete")
def team_delete(tid: int):
    """Correzione: un team creato per errore (vuoto e senza storia) si elimina."""
    t = db.one("SELECT id FROM team WHERE id=?", (tid,))
    if not t:
        return RedirectResponse("/org", status_code=302)
    if _team_blockers().get(tid):
        return RedirectResponse(f"/org?blocked={tid}#team-{tid}", status_code=302)
    with db.transaction() as conn:
        # nelle simulazioni le modifiche a questo team cadono (i riferimenti senza FK si ignorano già)
        conn.execute("DELETE FROM reorg_team WHERE team_id=?", (tid,))
        conn.execute("DELETE FROM team WHERE id=?", (tid,))
    return RedirectResponse("/org", status_code=302)


@router.post("/org/team/{tid}/archive")
def team_archive(tid: int):
    """Team vuoto ma con storico: sparisce dall'organigramma, la storia delle persone resta."""
    t = db.one("SELECT id FROM team WHERE id=? AND archived_at IS NULL", (tid,))
    if not t:
        return RedirectResponse("/org", status_code=302)
    if _team_blockers().get(tid, {}).get("block"):
        return RedirectResponse(f"/org?blocked={tid}#team-{tid}", status_code=302)
    db.execute("UPDATE team SET archived_at=datetime('now','localtime') WHERE id=?", (tid,))
    return RedirectResponse("/org#archiviati", status_code=302)


@router.post("/org/team/{tid}/restore")
def team_restore(tid: int):
    """Torna nell'organigramma, in coda ai fratelli; sotto la radice se il padre è archiviato."""
    t = db.one("SELECT parent_team_id FROM team WHERE id=? AND archived_at IS NOT NULL", (tid,))
    if t:
        parent = t["parent_team_id"]
        if parent and db.one("SELECT archived_at FROM team WHERE id=?", (parent,))["archived_at"]:
            parent = None
        db.execute("UPDATE team SET archived_at=NULL, parent_team_id=?, sort_order=? WHERE id=?",
                   (parent, _next_sort_order(parent), tid))
    return RedirectResponse(f"/org#team-{tid}", status_code=302)


@router.get("/org")
def org_tree(request: Request, blocked: str = ""):
    teams = db.query(
        "SELECT t.*, l.full_name AS lead_name FROM team t "
        "LEFT JOIN person l ON l.id = t.lead_person_id WHERE t.archived_at IS NULL ORDER BY t.sort_order, t.name")
    archived = db.query("SELECT id, name, archived_at FROM team WHERE archived_at IS NOT NULL ORDER BY name")
    members = db.query(
        "SELECT pa.team_id, p.id, p.full_name, pa.role_type FROM person_assignment pa "
        "JOIN person p ON p.id = pa.person_id "
        "WHERE pa.voided=0 AND pa.end_date IS NULL AND p.status='attivo' ORDER BY p.full_name")
    tree = org_svc.build_team_tree([dict(t) for t in teams], [dict(m) for m in members])
    # riporti diretti del lead: chi lo ha come responsabile nell'assegnazione corrente
    direct_reports = {r["manager_person_id"]: r["n"] for r in db.query(
        "SELECT pa.manager_person_id, COUNT(DISTINCT pa.person_id) AS n FROM person_assignment pa "
        "JOIN person p ON p.id = pa.person_id "
        "WHERE pa.voided=0 AND pa.end_date IS NULL AND p.status='attivo' "
        "AND pa.manager_person_id IS NOT NULL GROUP BY pa.manager_person_id")}
    people_opts = db.query("SELECT id, full_name FROM person WHERE status='attivo' ORDER BY full_name")
    return _templates().TemplateResponse(request, "org_tree.html", {
        "tree": tree, "teams": teams, "people_opts": people_opts, "direct_reports": direct_reports,
        "initials": initials, "blockers": _team_blockers(), "archived": archived,
        "blocked": next((t for t in teams if str(t["id"]) == blocked), None),
    })


def open_positions() -> list[dict]:
    """Posizioni aperte per il grafico, con il responsabile del sostituito come aggancio."""
    marks = ",".join("?" * len(budget_svc.OPEN_POSITIONS))
    return [dict(r) for r in db.query(
        f"""SELECT hp.id, hp.title, hp.role_type, hp.team_id, hp.status, hp.expected_start,
                  (SELECT pa.manager_person_id FROM person_assignment pa
                   WHERE pa.person_id = hp.replaces_person_id AND pa.voided=0
                   ORDER BY pa.end_date IS NULL DESC, pa.start_date DESC, pa.id DESC LIMIT 1) AS manager_hint
           FROM hiring_position hp
           WHERE hp.voided=0 AND hp.status IN ({marks}) ORDER BY hp.title, hp.id""",
        budget_svc.OPEN_POSITIONS)]


def chart_roles():
    """(ruoli attivi dal più alto, {code: sort_order}, {code: etichetta}) per il grafico."""
    roles = db.query("SELECT code, label, sort_order FROM lookup WHERE category='role_type' "
                     "AND active=1 ORDER BY sort_order DESC")
    return roles, {r["code"]: r["sort_order"] for r in roles}, {r["code"]: r["label"] for r in roles}


PROBLEM_LABEL = {"missing": "senza responsabile", "inactive": "responsabile non attivo",
                 "cycle": "ciclo interrotto"}


@router.get("/org/chart")
def org_chart(request: Request, team_id: list[str] = Query([]), pos: str = "1"):
    """Linee di riporto: persone attive per responsabile esplicito, più le posizioni aperte.

    `team_id` (ripetibile) = filtro reparti: quei team coi sotto-team e la catena dei responsabili sopra.
    `pos=0` = senza posizioni aperte (il grafico si ridisegna, niente colonne vuote).
    """
    show_pos = pos != "0"
    teams = [dict(t) for t in db.query(
        "SELECT id, name, parent_team_id, lead_person_id, sort_order FROM team WHERE archived_at IS NULL")]
    people = db.query(
        """SELECT p.id, p.full_name, pa.role_type, pa.team_id, pa.manager_person_id
           FROM person p
           LEFT JOIN person_assignment pa ON pa.id = (
               SELECT pa2.id FROM person_assignment pa2
               WHERE pa2.person_id = p.id AND pa2.voided=0 AND pa2.end_date IS NULL
               ORDER BY pa2.start_date DESC, pa2.id DESC LIMIT 1)
           WHERE p.status='attivo' ORDER BY p.full_name""")
    positions = open_positions() if show_pos else []
    roles, role_order, role_label = chart_roles()
    known = {t["id"] for t in teams}
    focus = [int(x) for x in team_id if x.isdigit() and int(x) in known]
    # interruttore posizioni: stesso filtro reparti, posizioni invertite
    toggle_pos_url = "/org/chart?" + urlencode([("team_id", t) for t in focus] + [("pos", "0" if show_pos else "1")])
    chart = org_svc.build_chart([dict(p) for p in people], teams, positions, role_order, focus)
    team_opts = []

    def walk(nodes):
        for n in nodes:
            team_opts.append({"id": n["team"]["id"], "name": n["team"]["name"], "depth": n["depth"]})
            walk(n["children"])

    walk(org_svc.build_team_tree(teams, []))
    return _templates().TemplateResponse(request, "org_chart.html", {
        "chart": chart, "roles": roles, "focus": focus, "team_opts": team_opts,
        "show_pos": show_pos, "toggle_pos_url": toggle_pos_url,
        "focus_names": [t["name"] for t in team_opts if t["id"] in focus],
        "problem_label": PROBLEM_LABEL,
        "role_label": role_label, "role_badge": org_svc.ROLE_BADGE, "initials": initials,
    })


def _team_members(team_id: int, year: str) -> list[dict]:
    """Membri attivi assegnati direttamente al team, con RAL, benefit, aumenti a piano e costo dell'anno."""
    rows = db.query(
        """SELECT p.id, p.full_name, p.hire_date, pa.role_type,
                  e.livello, e.tipo_contratto, e.part_time_pct,
                  (SELECT box_number FROM ninebox_assessment n WHERE n.person_id=p.id AND n.voided=0
                   ORDER BY n.eval_date DESC, n.id DESC LIMIT 1) AS box
           FROM person_assignment pa
           JOIN person p ON p.id = pa.person_id
           LEFT JOIN employment e ON e.person_id=p.id AND e.voided=0 AND e.end_date IS NULL
           WHERE pa.team_id=? AND pa.voided=0 AND pa.end_date IS NULL AND p.status='attivo'
           ORDER BY p.full_name""", (team_id,))
    out = []
    for r in rows:
        ral = cost.current_ral(r["id"])
        benefits = cost.active_benefits(r["id"])
        pending = db.one(
            "SELECT COALESCE(SUM(amount),0) AS t FROM ral_proposal "
            "WHERE person_id=? AND voided=0 AND status IN ('bozza','proposta','approvata')",
            (r["id"],))["t"]
        out.append({**dict(r), "ral": ral["amount"] if ral else None,
                    "benefits": benefits, "benefit_cost": cost.benefit_cost(benefits),
                    "pending": pending, "total_cost": cost.total_cost(r["id"], year)["totale"],
                    "initials": initials(r["full_name"])})
    return out


@router.get("/org/team/{tid}")
def team_card(request: Request, tid: int):
    t = db.one(
        "SELECT t.*, l.full_name AS lead_name, pt.name AS parent_name FROM team t "
        "LEFT JOIN person l ON l.id = t.lead_person_id "
        "LEFT JOIN team pt ON pt.id = t.parent_team_id WHERE t.id=?", (tid,))
    if not t:
        return RedirectResponse("/org", status_code=302)
    year = str(date.today().year)
    # il team e i suoi sotto-team (a ogni profondità, in ordine di organigramma), ciascuno coi suoi membri
    all_teams = [dict(r) for r in db.query(
        "SELECT id, name, parent_team_id, lead_person_id, sort_order, archived_at FROM team")]
    ids = org_svc.descendant_ids(all_teams, tid)
    live = [r for r in all_teams if not r["archived_at"] or r["id"] == tid]
    by_team = {r["id"]: r for r in all_teams}
    order = [i for i in org_svc.team_order(live) if i in ids] or [tid]

    def depth(team_id):
        d, cur, seen = 0, team_id, set()
        while cur != tid and cur is not None and cur not in seen:
            seen.add(cur)
            cur = by_team.get(cur, {}).get("parent_team_id")
            d += 1
        return d

    groups = []
    tot = {"ral": 0.0, "benefit": 0.0, "costo": 0.0, "n": 0}
    for team_id in order:
        group = {"team": by_team[team_id], "depth": depth(team_id), "members": _team_members(team_id, year),
                 "tot": {"ral": 0.0, "benefit": 0.0, "costo": 0.0}}
        for m in group["members"]:
            for k, v in (("ral", m["ral"] or 0), ("benefit", m["benefit_cost"]), ("costo", m["total_cost"])):
                group["tot"][k] += v
                tot[k] += v
        tot["n"] += len(group["members"])
        groups.append(group)
    members = groups[0]["members"]          # diretti del team
    direct = groups[0]["tot"]
    open_cycle = db.one("SELECT * FROM review_cycle WHERE status='aperto' ORDER BY year DESC LIMIT 1")
    goals = []
    everyone = [m for g in groups for m in g["members"]]
    if open_cycle and everyone:
        person_ids = ",".join(str(m["id"]) for m in everyone)
        goals = db.query(
            f"""SELECT g.*, p.full_name,
                  (SELECT status FROM performance_review pr
                   WHERE pr.person_id=g.person_id AND pr.cycle_id=g.cycle_id AND pr.voided=0) AS review_status
                FROM goal g JOIN person p ON p.id=g.person_id
                WHERE g.cycle_id=? AND g.voided=0 AND g.person_id IN ({person_ids})
                ORDER BY p.full_name, g.category""", (open_cycle["id"],))
    # headcount già impegnato: posizioni a budget ancora aperte sul team e sui suoi sotto-team
    marks = ",".join("?" * len(budget_svc.OPEN_POSITIONS))
    marks_t = ",".join("?" * len(ids))
    rank = {team_id: n for n, team_id in enumerate(order)}
    open_positions = sorted(db.query(
        f"""SELECT hp.*, hb.period AS budget_period, rp.full_name AS replaces_name, tm.name AS team_name
            FROM hiring_position hp
            JOIN hiring_budget hb ON hb.id = hp.budget_id
            JOIN team tm ON tm.id = hp.team_id
            LEFT JOIN person rp ON rp.id = hp.replaces_person_id
            WHERE hp.team_id IN ({marks_t}) AND hp.voided=0 AND hp.status IN ({marks})
            ORDER BY hb.year DESC, hp.expected_start, hp.id""",
        (*ids, *budget_svc.OPEN_POSITIONS)), key=lambda hp: rank.get(hp["team_id"], len(rank)))
    tot_hiring = round(sum(hp["expected_ral"] or 0 for hp in open_positions), 2)
    # navigazione precedente/prossimo nell'ordine dell'organigramma
    nav_live = [r for r in all_teams if not r["archived_at"]]
    by_id = {r["id"]: r for r in nav_live}
    nav_pool = [by_id[i] for i in org_svc.team_order(nav_live)]
    prev_t = next_t = None
    for i, row in enumerate(nav_pool):
        if row["id"] == tid:
            prev_t = nav_pool[i - 1] if i > 0 else None
            next_t = nav_pool[i + 1] if i < len(nav_pool) - 1 else None
            break
    return _templates().TemplateResponse(request, "team_card.html", {
        "t": t, "members": members, "groups": groups, "tot": tot, "direct": direct, "year": year,
        "goals": goals, "open_cycle": open_cycle,
        "open_positions": open_positions, "tot_hiring": tot_hiring,
        "prev_t": prev_t, "next_t": next_t,
    })


@router.post("/org/team")
def team_create(name: str = Form(...), parent_team_id: str = Form(None),
                lead_person_id: str = Form(None), description: str = Form(None)):
    db.execute(
        "INSERT INTO team (name, parent_team_id, lead_person_id, description, sort_order) VALUES (?,?,?,?,?)",
        (name.strip(), parent_team_id or None, lead_person_id or None, description or None,
         _next_sort_order(parent_team_id or None)))
    return _verify_reports("/org")


def _next_sort_order(parent_team_id) -> int:
    """In coda ai fratelli: un team nuovo o spostato sotto un altro padre va per ultimo."""
    return db.one("SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM team "
                  "WHERE parent_team_id IS ? AND archived_at IS NULL",
                  (parent_team_id,))["n"]


@router.post("/org/team/{tid}/move")
def team_move(tid: int, direction: str = Form(...)):
    """Sposta su/giù tra i fratelli: cambia solo l'ordine, mai il padre."""
    teams = [dict(r) for r in db.query(
        "SELECT id, name, parent_team_id, sort_order FROM team WHERE archived_at IS NULL")]
    changes = org_svc.move_team(teams, tid, direction)
    if changes:
        with db.transaction() as conn:
            for team_id, n in changes.items():
                conn.execute("UPDATE team SET sort_order=? WHERE id=?", (n, team_id))
    return RedirectResponse(f"/org#team-{tid}", status_code=302)


@router.post("/org/team/{tid}")
def team_update(tid: int, name: str = Form(...), parent_team_id: str = Form(None),
                lead_person_id: str = Form(None), description: str = Form(None)):
    if parent_team_id:
        # un team non può stare sotto sé stesso né sotto un proprio discendente
        all_teams = [dict(r) for r in db.query("SELECT id, parent_team_id FROM team")]
        if int(parent_team_id) in org_svc.descendant_ids(all_teams, tid):
            parent_team_id = None
    parent = int(parent_team_id) if parent_team_id else None
    old = db.one("SELECT parent_team_id, sort_order FROM team WHERE id=?", (tid,))
    order = old["sort_order"] if old and old["parent_team_id"] == parent else _next_sort_order(parent)
    db.execute(
        "UPDATE team SET name=?, parent_team_id=?, lead_person_id=?, description=?, sort_order=? WHERE id=?",
        (name.strip(), parent, lead_person_id or None, description or None, order, tid))
    return _verify_reports("/org")


@router.post("/people/{pid}/attachment")
async def attachment_upload(pid: int, file: UploadFile, note: str = Form(None), review_id: str = Form(None)):
    data = await file.read()
    if data:
        db.execute(
            "INSERT INTO attachment (person_id, review_id, filename, mime, content, note) "
            "VALUES (?,?,?,?,?,?)",
            (pid, review_id or None, file.filename, file.content_type, data, note or None))
    return RedirectResponse(f"/people/{pid}", status_code=302)


@router.post("/people/{pid}/attachment/{aid}/delete")
def attachment_delete(pid: int, aid: int):
    """Correzione: un allegato caricato sulla persona sbagliata si toglie."""
    db.execute("DELETE FROM attachment WHERE id=? AND person_id=?", (aid, pid))
    return RedirectResponse(f"/people/{pid}", status_code=302)


@router.get("/attachments/{aid}")
def attachment_download(aid: int):
    a = db.one("SELECT * FROM attachment WHERE id=?", (aid,))
    if not a:
        return Response(status_code=404)
    return Response(
        content=a["content"],
        media_type=a["mime"] or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{a["filename"]}"'},
    )
