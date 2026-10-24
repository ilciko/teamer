"""Dashboard, sezione report (trend) e processi in corso."""
from datetime import date, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app import db, session
from app.params import OptInt
from app.routers import hrview
from app.services import org_tree as org_svc
from app.services import trends

router = APIRouter()

# palette categorica per le serie (ordine fisso, validata con dataviz/validate_palette)
SERIES_COLORS = ["#378ADD", "#1D9E75", "#EF9F27", "#E24B4A", "#7A5FD0", "#C2508F"]
OTHER_COLOR = "#a09d98"


def _templates():
    from app.main import templates

    return templates


@router.get("/reports")
def reports_page(request: Request, team_id: OptInt = None, group: str = ""):
    events_by_person: dict = {}
    for e in db.query(
            "SELECT person_id, effective_date, amount FROM ral_event WHERE voided=0"):
        events_by_person.setdefault(e["person_id"], []).append(dict(e))
    # Chi non ha la data di assunzione entra comunque, dal suo primo evento RAL:
    # altrimenti sparirebbe da entrambe le serie e il monte RAL di oggi non
    # tornerebbe con l'analisi salary. Fuori resta solo chi non ha né l'una né l'altro.
    people, esclusi = [], []
    for r in db.query(
            "SELECT id, full_name, hire_date, end_date, report_excluded FROM person "
            "ORDER BY full_name"):
        p = dict(r)
        p["prima_ral"] = trends.first_ral_date(events_by_person.get(p["id"], []))
        p["hire_reale"] = p["hire_date"]
        if p["report_excluded"]:
            esclusi.append(p)
            continue
        if not p["hire_date"]:
            if not p["prima_ral"]:
                continue
            p["hire_date"] = p["prima_ral"].isoformat()
        people.append(p)
    assignments_by_person: dict = {}
    for a in db.query(
            "SELECT person_id, team_id, start_date, end_date FROM person_assignment WHERE voided=0"):
        assignments_by_person.setdefault(a["person_id"], []).append(dict(a))
    team_rows = [dict(t) for t in db.query("SELECT id, name, parent_team_id FROM team")]
    teams = {t["id"]: t["name"] for t in team_rows}

    start = min((trends._d(p["hire_date"]) for p in people), default=date.today())
    months = trends.month_range(start, date.today())
    labels = [m.strftime("%m/%Y") for m in months]

    def dataset(label, data, color):
        return {"label": label, "data": data, "borderColor": color,
                "backgroundColor": color, "fill": False}

    def somma(a, b):
        """Un mese senza il dato di qualcuno resta senza dato anche nell'aggregato."""
        return None if a is None or b is None else round(a + b, 2)

    if group == "team":
        hc_by_team = trends.headcount_by_team(people, assignments_by_person, months)
        ral_by_team = trends.ral_by_team(people, assignments_by_person, events_by_person, months)
        # ordine fisso: per id team; oltre 6 squadre le eccedenti in "Altri"
        ordered = sorted(k for k in hc_by_team if k is not None)
        headcount_ds, ral_ds = [], []
        other_hc = [0] * len(months)
        other_ral: list = [0.0] * len(months)
        extra = False
        for i, tid in enumerate(ordered):
            if i < len(SERIES_COLORS):
                color = SERIES_COLORS[i]
                headcount_ds.append(dataset(teams.get(tid, "?"), hc_by_team[tid], color))
                if tid in ral_by_team:
                    ral_ds.append(dataset(teams.get(tid, "?"), ral_by_team[tid], color))
            else:
                extra = True
                for j in range(len(months)):
                    other_hc[j] += hc_by_team[tid][j]
                    other_ral[j] = somma(other_ral[j],
                                         ral_by_team.get(tid, [0.0] * len(months))[j])
        if None in hc_by_team:
            extra = True
            for j in range(len(months)):
                other_hc[j] += hc_by_team[None][j]
                other_ral[j] = somma(other_ral[j],
                                     ral_by_team.get(None, [0.0] * len(months))[j])
        if extra:
            headcount_ds.append(dataset("Altri / senza team", other_hc, OTHER_COLOR))
            ral_ds.append(dataset("Altri / senza team",
                                  [None if v is None else round(v, 2) for v in other_ral],
                                  OTHER_COLOR))
    else:
        if team_id:
            hc_by_team = trends.headcount_by_team(people, assignments_by_person, months)
            ral_by_team = trends.ral_by_team(people, assignments_by_person, events_by_person, months)
            # il filtro per team include i sotto-team: si sommano le serie del sottoalbero
            ids = org_svc.descendant_ids(team_rows, team_id)
            n = len(months)
            hc = [sum(hc_by_team.get(t, [0] * n)[j] for t in ids) for j in range(n)]
            ral = [0.0] * n
            for t in ids:
                if t in ral_by_team:
                    ral = [somma(ral[j], ral_by_team[t][j]) for j in range(n)]
            name = teams.get(team_id, "?") + (" (incl. sotto-team)" if len(ids) > 1 else "")
        else:
            hc = trends.headcount_series(people, months)
            ral = trends.ral_series(people, events_by_person, months)
            name = "Totale azienda"
        headcount_ds = [dataset(name, hc, SERIES_COLORS[0])]
        ral_ds = [dataset(name, ral, SERIES_COLORS[1])]

    # Gli addetti si ricostruiscono dalle date di assunzione, che sono dato vero:
    # tengono tutta la storia. Il monte RAL invece parte da dove è leggibile —
    # dopo l'ultimo mese in cui a qualcuno mancava la RAL — e i due grafici hanno
    # perciò assi diversi.
    inizio = trends.data_start(trends.ral_series(people, events_by_person, months))
    ral_labels = labels[inizio:]
    ral_ds = [{**d, "data": d["data"][inizio:]} for d in ral_ds] if ral_labels else []

    return _templates().TemplateResponse(request, "reports.html", {
        "labels": labels, "headcount_ds": headcount_ds,
        "ral_labels": ral_labels, "ral_ds": ral_ds,
        "teams": db.query("SELECT * FROM team WHERE archived_at IS NULL ORDER BY name"),
        "team_id": team_id, "group": group,
        "da": months[inizio] if inizio < len(months) else None,
        "inclusi": people, "esclusi": esclusi,
    })


@router.post("/reports/exclusions")
async def reports_exclusions(request: Request):
    """Chi resta fuori dalle serie del report (entrambe: addetti e monte RAL)."""
    form = await request.form()
    tenuti = {int(v) for v in form.getlist("include")}
    with db.transaction() as conn:
        for r in conn.execute("SELECT id FROM person").fetchall():
            conn.execute("UPDATE person SET report_excluded=? WHERE id=?",
                         (0 if r["id"] in tenuti else 1, r["id"]))
    dest = "/reports"
    if form.get("team_id"):
        dest += f"?team_id={form['team_id']}"
    elif form.get("group"):
        dest += "?group=team"
    return RedirectResponse(dest, status_code=302)


def _dashboard_hr(request: Request, today: str, horizon: str):
    """Dashboard di HR (0.42): le sue azioni in scadenza, i contratti a termine in scadenza di tutti
    i director, le proposte del piano aumenti arrivate da validare, le cessazioni e le persone che
    aspettano un director."""
    ctx = hrview.context(request)
    directors = ctx["directors"]
    director_of = "COALESCE(t.owner_user_id, p.owner_user_id)"
    person_join = """LEFT JOIN person_assignment pa ON pa.person_id = p.id AND pa.voided = 0 AND pa.end_date IS NULL
                     LEFT JOIN team t ON t.id = pa.team_id"""
    def with_director(rows):
        return [{**dict(r), "director": directors.get(r["director_id"])} for r in rows]
    expiring_contracts = with_director(db.query(
        f"""SELECT e.*, p.full_name, {director_of} AS director_id FROM employment e
            JOIN person p ON p.id = e.person_id {person_join}
            WHERE e.voided = 0 AND p.status = 'attivo' AND e.end_date IS NOT NULL AND e.end_date BETWEEN ? AND ?
            ORDER BY e.end_date""", (today, horizon)))
    overdue_actions = db.query(
        """SELECT a.*, p.full_name FROM action_item a JOIN person p ON p.id = a.person_id
           WHERE a.status != 'chiuso' AND a.due_date IS NOT NULL AND a.due_date < ? ORDER BY a.due_date""", (today,))
    upcoming_actions = db.query(
        """SELECT a.*, p.full_name FROM action_item a JOIN person p ON p.id = a.person_id
           WHERE a.status != 'chiuso' AND a.due_date IS NOT NULL AND a.due_date BETWEEN ? AND ?
           ORDER BY a.due_date LIMIT 10""", (today, horizon))
    proposals = with_director(db.query(
        f"""SELECT COALESCE(b.owner_user_id, {director_of}) AS director_id, COUNT(*) AS n,
                   COALESCE(SUM(pr.amount), 0) AS delta, MIN(pr.proposed_at) AS since
            FROM ral_proposal pr JOIN person p ON p.id = pr.person_id
            LEFT JOIN ral_budget b ON b.id = pr.budget_id {person_join}
            WHERE pr.voided = 0 AND pr.status = 'proposta'
            GROUP BY 1 ORDER BY since"""))
    da_decidere = with_director(db.query(
        f"""SELECT p.id, p.full_name, p.end_date, {director_of} AS director_id FROM person p {person_join}
            WHERE p.status = 'cessato' AND p.end_date >= ?
              AND NOT EXISTS (SELECT 1 FROM hiring_position hp WHERE hp.replaces_person_id = p.id AND hp.voided = 0)
              AND NOT EXISTS (SELECT 1 FROM replacement_decision d WHERE d.person_id = p.id AND d.voided = 0)
            ORDER BY p.end_date DESC""", ((date.today() - timedelta(days=365)).isoformat(),)))
    da_collocare = with_director(db.query(
        f"""SELECT p.id, p.full_name, pa.start_date, t.owner_user_id AS director_id FROM person p
            JOIN person_assignment pa ON pa.person_id = p.id AND pa.voided = 0 AND pa.end_date IS NULL
            JOIN team t ON t.id = pa.team_id WHERE p.status = 'attivo' AND t.holding = 1 ORDER BY pa.start_date"""))
    headcount = db.one("SELECT COUNT(*) AS n FROM person WHERE status='attivo'")["n"]
    return _templates().TemplateResponse(request, "dashboard_hr.html", {
        **ctx, "headcount": headcount, "n_directors": len(directors),
        "expiring_contracts": expiring_contracts, "overdue_actions": overdue_actions,
        "upcoming_actions": upcoming_actions, "proposals": proposals,
        "n_proposals": sum(r["n"] for r in proposals), "delta_proposals": sum(r["delta"] for r in proposals),
        "da_decidere": da_decidere, "da_collocare": da_collocare,
    })


def _processes() -> list[dict]:
    """Processi aperti da mostrare in dashboard, con avanzamento e link."""
    out = []
    for b in db.query(
            """SELECT b.id, b.period,
                 SUM(CASE WHEN pr.status='bozza' THEN 1 ELSE 0 END) AS bozze,
                 SUM(CASE WHEN pr.status='proposta' THEN 1 ELSE 0 END) AS a_hr,
                 SUM(CASE WHEN pr.status='approvata' THEN 1 ELSE 0 END) AS approvate,
                 SUM(CASE WHEN pr.status IN ('bozza','proposta','approvata') THEN pr.amount ELSE 0 END) AS impegnato
               FROM ral_proposal pr JOIN ral_budget b ON b.id = pr.budget_id
               WHERE pr.voided=0 GROUP BY b.id
               HAVING bozze + a_hr + approvate > 0 ORDER BY b.id DESC"""):
        parts = []
        if b["bozze"]:
            parts.append(f"{b['bozze']} in bozza")
        if b["a_hr"]:
            parts.append(f"{b['a_hr']} inviate a HR in attesa")
        if b["approvate"]:
            parts.append(f"{b['approvate']} approvate da applicare")
        out.append({"kind": "Piano aumenti", "title": b["period"],
                    "detail": ", ".join(parts) + f" · impegnato {b['impegnato'] or 0:,.0f} €".replace(",", "."),
                    "url": f"/comp/plan?budget_id={b['id']}",
                    "attention": bool(b["approvate"])})
    orphan = db.one(
        """SELECT COUNT(*) AS n FROM ral_proposal
           WHERE voided=0 AND budget_id IS NULL AND status IN ('bozza','proposta','approvata')""")
    if orphan["n"]:
        out.append({"kind": "Piano aumenti", "title": "Senza budget",
                    "detail": f"{orphan['n']} proposte pendenti", "url": "/comp/plan",
                    "attention": False})
    # premi di ruolo di HR in attesa della mia approvazione (0.46)
    me = session.current()
    for p in db.query("SELECT id, period, competence_year FROM bonus_pool WHERE kind='ruolo' AND status='in_approvazione' ORDER BY id DESC"):
        if me and not db.sys.one("SELECT 1 FROM bonus_pool_approval WHERE pool_id=? AND user_id=?", (p["id"], me.user_id)):
            out.append({"kind": "Premio di ruolo", "title": p["period"],
                        "detail": f"competenza {p['competence_year']}: da approvare la tua parte",
                        "url": f"/comp/bonus/{p['id']}", "attention": True})
    for c in db.query("SELECT * FROM review_cycle WHERE status='aperto' ORDER BY year DESC"):
        n = db.one(
            """SELECT
                 (SELECT COUNT(*) FROM person WHERE status='attivo') AS tot,
                 (SELECT COUNT(*) FROM performance_review WHERE cycle_id=? AND voided=0
                  AND status='finalizzata') AS done""", (c["id"],))
        out.append({"kind": "Ciclo review", "title": c["name"],
                    "detail": f"{n['done']}/{n['tot']} review finalizzate",
                    "url": f"/cycles/{c['id']}", "attention": False})
    for p in db.query("SELECT * FROM bonus_pool WHERE status='bozza' ORDER BY id DESC"):
        out.append({"kind": "Montepremi", "title": p["period"],
                    "detail": f"in bozza, tetto {p['total_cap']:,.0f} €".replace(",", "."),
                    "url": f"/comp/bonus/{p['id']}", "attention": False})
    for h in db.query(
            """SELECT hb.id, hb.period, COUNT(*) AS n FROM hiring_position hp
               JOIN hiring_budget hb ON hb.id = hp.budget_id
               WHERE hp.voided=0 AND hp.status IN ('pianificata','in_selezione')
                 AND hb.status='aperto'
               GROUP BY hb.id ORDER BY hb.id DESC"""):
        out.append({"kind": "Assunzioni", "title": h["period"],
                    "detail": f"{h['n']} posizioni aperte", "url": "/comp/hiring",
                    "attention": False})
    return out


@router.get("/")
def dashboard(request: Request):
    today = date.today().isoformat()
    horizon = (date.today() + timedelta(days=90)).isoformat()
    if hrview.is_hr():
        return _dashboard_hr(request, today, horizon)

    headcount = db.one("SELECT COUNT(*) AS n FROM person WHERE status='attivo'")["n"]
    ral = db.one(
        """SELECT COALESCE(SUM(amount),0) AS tot, COALESCE(AVG(amount),0) AS media FROM (
             SELECT (SELECT amount FROM ral_event r WHERE r.person_id=p.id AND r.voided=0
                     ORDER BY r.effective_date DESC, r.id DESC LIMIT 1) AS amount
             FROM person p WHERE p.status='attivo') WHERE amount IS NOT NULL""")

    expiring_contracts = db.query(
        """SELECT e.*, p.full_name FROM employment e JOIN person p ON p.id=e.person_id
           WHERE e.voided=0 AND p.status='attivo' AND e.end_date IS NOT NULL
             AND e.end_date BETWEEN ? AND ?
           ORDER BY e.end_date""", (today, horizon))
    overdue_actions = db.query(
        """SELECT a.*, p.full_name FROM action_item a JOIN person p ON p.id=a.person_id
           WHERE a.status != 'chiuso' AND a.due_date IS NOT NULL AND a.due_date < ?
           ORDER BY a.due_date""", (today,))
    upcoming_actions = db.query(
        """SELECT a.*, p.full_name FROM action_item a JOIN person p ON p.id=a.person_id
           WHERE a.status != 'chiuso' AND a.due_date IS NOT NULL AND a.due_date BETWEEN ? AND ?
           ORDER BY a.due_date LIMIT 10""", (today, horizon))
    open_cycles = db.query("SELECT * FROM review_cycle WHERE status='aperto' ORDER BY year DESC")
    ending_benefits = db.query(
        """SELECT ba.*, bt.name, p.full_name FROM benefit_assignment ba
           JOIN benefit_type bt ON bt.id=ba.benefit_type_id
           JOIN person p ON p.id=ba.person_id
           WHERE ba.voided=0 AND ba.end_date IS NOT NULL AND ba.end_date BETWEEN ? AND ?
           ORDER BY ba.end_date""", (today, horizon))
    never_rated = db.one(
        """SELECT COUNT(*) AS n FROM person p WHERE p.status='attivo'
           AND NOT EXISTS (SELECT 1 FROM ninebox_assessment n WHERE n.person_id=p.id AND n.voided=0)""")["n"]
    recent_notes = db.query(
        """SELECT mn.*, p.full_name FROM meeting_note mn JOIN person p ON p.id=mn.person_id
           WHERE mn.archived_at IS NULL ORDER BY mn.note_date DESC LIMIT 5""")
    # cessazioni (ultimo anno) senza posizione di sostituzione né decisione «non sostituire» (0.39)
    da_decidere = db.query(
        """SELECT p.id, p.full_name, p.end_date FROM person p
           WHERE p.status='cessato' AND p.end_date >= ?
             AND NOT EXISTS (SELECT 1 FROM hiring_position hp WHERE hp.replaces_person_id=p.id AND hp.voided=0)
             AND NOT EXISTS (SELECT 1 FROM replacement_decision d WHERE d.person_id=p.id AND d.voided=0)
           ORDER BY p.end_date DESC""", ((date.today() - timedelta(days=365)).isoformat(),))

    # persone arrivate da un altro director (HR, 0.40): stanno nel team «Da collocare» finché non le assegno
    da_collocare = db.query(
        """SELECT p.id, p.full_name, pa.start_date FROM person p
           JOIN person_assignment pa ON pa.person_id = p.id AND pa.voided = 0 AND pa.end_date IS NULL
           JOIN team t ON t.id = pa.team_id
           WHERE p.status = 'attivo' AND t.holding = 1 ORDER BY pa.start_date DESC""")

    return _templates().TemplateResponse(request, "dashboard.html", {
        "da_decidere": da_decidere, "da_collocare": da_collocare,
        "headcount": headcount, "ral_tot": ral["tot"], "ral_media": ral["media"],
        "expiring_contracts": expiring_contracts,
        "overdue_actions": overdue_actions, "upcoming_actions": upcoming_actions,
        "open_cycles": open_cycles, "ending_benefits": ending_benefits,
        "never_rated": never_rated, "recent_notes": recent_notes,
        "processes": _processes(),
    })
