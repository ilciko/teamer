"""Simulazioni di riorganizzazione: prove di organigramma da confrontare, approvare e applicare.

Una simulazione salva solo le differenze rispetto alla realtà (migrations/0021):
lo stato simulato lo calcola `services.reorg.simulate`, i riporti si ricalcolano
con la regola di sempre. Si modifica solo in bozza; approvata si applica con una
data (team creati/modificati, spostamenti come nuove assegnazioni storicizzate).
"""
from datetime import date, timedelta

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import RedirectResponse

from app import db
from app.routers import org as org_r
from app.services import budget as budget_svc
from app.services import org_tree as org_svc
from app.services import reorg as reorg_svc

router = APIRouter()

STATUSES = ("bozza", "approvata", "applicata", "scartata")


def _templates():
    from app.main import templates

    return templates


def _scenario(sid: int):
    return db.one("SELECT * FROM reorg_scenario WHERE id=?", (sid,))


def _reality() -> dict:
    people, teams = org_r._report_state()
    return {"teams": teams, "people": people, "positions": org_r.open_positions()}


def _rows(sid: int):
    team_rows = [dict(r) for r in db.query("SELECT * FROM reorg_team WHERE scenario_id=? ORDER BY id", (sid,))]
    moves = [dict(r) for r in db.query("SELECT * FROM reorg_move WHERE scenario_id=?", (sid,))]
    positions = [dict(r) for r in db.query(
        "SELECT * FROM reorg_position WHERE scenario_id=? ORDER BY title, id", (sid,))]
    return team_rows, moves, positions


def _pos_moves(sid: int) -> list[dict]:
    """Posizioni aperte del budget spostate di team/ruolo nella simulazione."""
    return [dict(r) for r in db.query("SELECT * FROM reorg_position_move WHERE scenario_id=?", (sid,))] if sid else []


def _state(sid: int, real: dict) -> dict:
    """Stato di una simulazione (0 = organigramma attuale).

    Anche l'attuale passa da `simulate` senza differenze: i riporti si ricalcolano con la
    regola, così il confronto mostra solo ciò che cambia la riorganizzazione e non i
    riporti reali ancora da verificare (quelli li segnala /org/riporti).
    """
    team_rows, moves, positions = _rows(sid) if sid else ([], [], [])
    return reorg_svc.simulate(real["teams"], real["people"], real["positions"],
                              team_rows, moves, positions, org_r._role_order(), _pos_moves(sid))


def _chart_ctx() -> dict:
    roles, _, role_label = org_r.chart_roles()
    return {"roles": roles, "role_label": role_label, "role_badge": org_svc.ROLE_BADGE,
            "initials": org_r.initials, "problem_label": org_r.PROBLEM_LABEL}


def _chart(state: dict) -> dict:
    return org_svc.build_chart(state["people"], state["teams"], state["positions"], org_r._role_order())


def _team_opts(teams) -> list[dict]:
    """Team in ordine d'albero con profondità, per le select."""
    out = []

    def walk(nodes):
        for n in nodes:
            out.append({"id": n["team"]["id"], "name": n["team"]["name"], "depth": n["depth"],
                        "new": n["team"]["id"] < 0})
            walk(n["children"])

    walk(org_svc.build_team_tree(teams, []))
    return out


def _editable(s) -> bool:
    return bool(s) and s["status"] == "bozza"


def _back(sid: int, anchor: str = "") -> RedirectResponse:
    return RedirectResponse(f"/org/sim/{sid}{anchor}", status_code=302)


def _ref(raw) -> int | None:
    """Riferimento a un team dal form: '' = nessuno, altrimenti id reale (>0) o nuovo (<0)."""
    try:
        return int(raw) if raw not in (None, "") else None
    except ValueError:
        return None


# ---- elenco e creazione ----

@router.get("/org/sim")
def sim_list(request: Request):
    scenarios = db.query(
        """SELECT s.*,
                  (SELECT COUNT(*) FROM reorg_move m WHERE m.scenario_id = s.id AND m.hidden = 0) AS n_moves,
                  (SELECT COUNT(*) FROM reorg_move m WHERE m.scenario_id = s.id AND m.hidden = 1) AS n_exits,
                  (SELECT COUNT(*) FROM reorg_team t WHERE t.scenario_id = s.id AND t.team_id IS NULL) AS n_new,
                  (SELECT COUNT(*) FROM reorg_team t WHERE t.scenario_id = s.id AND t.team_id IS NOT NULL) AS n_mod,
                  (SELECT COUNT(*) FROM reorg_position p WHERE p.scenario_id = s.id) AS n_pos,
                  (SELECT COUNT(*) FROM reorg_position_move p WHERE p.scenario_id = s.id AND p.hidden = 0) AS n_pos_moves,
                  (SELECT COUNT(*) FROM reorg_position_move p WHERE p.scenario_id = s.id AND p.hidden = 1) AS n_pos_hidden
           FROM reorg_scenario s
           ORDER BY CASE s.status WHEN 'bozza' THEN 0 WHEN 'approvata' THEN 1 WHEN 'applicata' THEN 2 ELSE 3 END,
                    s.created_at DESC, s.id DESC""")
    return _templates().TemplateResponse(request, "reorg_list.html", {"scenarios": scenarios})


@router.get("/org/sim/compare")
def sim_compare(request: Request, a: int = Query(0), b: int = Query(0)):
    """Confronto 1:1 tra due stati (0 = organigramma attuale): grafici affiancati con le
    differenze evidenziate, elenco persona per persona e organico per team."""
    real = _reality()
    scenarios = db.query("SELECT id, name, status FROM reorg_scenario ORDER BY created_at DESC, id DESC")
    known = {x["id"] for x in scenarios}
    a = a if a in known else 0
    b = b if b in known else 0
    sa, sb = _state(a, real), _state(b, real)
    hc = reorg_svc.headcount(sa, sb)
    names = {x["id"]: x["name"] for x in scenarios}
    return _templates().TemplateResponse(request, "reorg_compare.html", {
        "scenarios": scenarios, "a": a, "b": b,
        "name_a": names.get(a, "Organigramma attuale"), "name_b": names.get(b, "Organigramma attuale"),
        "chart_a": _chart(sa), "chart_b": _chart(sb),
        "mk_a": reorg_svc.marks(sb, sa), "mk_b": reorg_svc.marks(sa, sb),
        "diff": reorg_svc.diff(sa, sb), "headcount": hc, "hc_tot": reorg_svc.headcount_totals(hc),
        "pos_diff": reorg_svc.position_diff(sa, sb), **_chart_ctx(),
    })


@router.post("/org/sim")
def sim_create(name: str = Form(...), description: str = Form(None)):
    sid = db.execute("INSERT INTO reorg_scenario (name, description) VALUES (?,?)",
                     (name.strip(), (description or "").strip() or None))
    return _back(sid)


@router.post("/org/sim/{sid}/duplicate")
def sim_duplicate(sid: int):
    """Copia per provare una variante: stesse differenze, nuova bozza."""
    s = _scenario(sid)
    if not s:
        return RedirectResponse("/org/sim", status_code=302)
    team_rows, moves, positions = _rows(sid)
    with db.transaction() as conn:
        new = conn.execute("INSERT INTO reorg_scenario (name, description) VALUES (?,?)",
                           (f"{s['name']} (copia)", s["description"])).lastrowid
        remap = {}
        for r in team_rows:
            remap[-r["id"]] = -conn.execute(
                "INSERT INTO reorg_team (scenario_id, team_id, name, parent_ref, lead_person_id, sort_order, removed) "
                "VALUES (?,?,?,?,?,?,?)",
                (new, r["team_id"], r["name"], r["parent_ref"], r["lead_person_id"], r["sort_order"],
                 r["removed"])).lastrowid

        def ref(x):
            return remap.get(x, x) if x is not None and x < 0 else x

        for r in team_rows:
            if r["parent_ref"] is not None and r["parent_ref"] < 0:
                conn.execute("UPDATE reorg_team SET parent_ref=? WHERE id=?", (ref(r["parent_ref"]), -remap[-r["id"]]))
        for m in moves:
            conn.execute("INSERT INTO reorg_move (scenario_id, person_id, team_ref, role_type, hidden) "
                         "VALUES (?,?,?,?,?)", (new, m["person_id"], ref(m["team_ref"]), m["role_type"], m["hidden"]))
        for p in positions:
            conn.execute("INSERT INTO reorg_position (scenario_id, title, team_ref, role_type, internal) "
                         "VALUES (?,?,?,?,?)", (new, p["title"], ref(p["team_ref"]), p["role_type"], p["internal"]))
        for pm in _pos_moves(sid):
            conn.execute("INSERT INTO reorg_position_move (scenario_id, position_id, team_ref, role_type, hidden) "
                         "VALUES (?,?,?,?,?)",
                         (new, pm["position_id"], ref(pm["team_ref"]), pm["role_type"], pm["hidden"]))
    return _back(new)


@router.post("/org/sim/{sid}/delete")
def sim_delete(sid: int):
    """Una prova si butta via; quella applicata resta come traccia di cosa si è fatto."""
    s = _scenario(sid)
    if s and s["status"] != "applicata":
        db.execute("DELETE FROM reorg_scenario WHERE id=?", (sid,))
    return RedirectResponse("/org/sim", status_code=302)


# ---- editor ----

@router.get("/org/sim/{sid}")
def sim_edit(request: Request, sid: int, err: str = ""):
    s = _scenario(sid)
    if not s:
        return RedirectResponse("/org/sim", status_code=302)
    real = _reality()
    base = _state(0, real)
    sim = _state(sid, real)
    team_rows, moves, positions = _rows(sid)
    sim_by_id = {p["id"]: p for p in sim["people"]}
    real_teams = {t["id"]: t for t in real["teams"]}
    sim_teams = {t["id"]: t for t in sim["teams"]}
    overrides = {r["team_id"]: r for r in team_rows if r["team_id"]}
    tree = org_svc.build_team_tree(sim["teams"], [{"team_id": p["team_id"], "id": p["id"]} for p in sim["people"]])
    pos_count = {}
    for pos in sim["positions"]:
        pos_count[pos.get("team_id")] = pos_count.get(pos.get("team_id"), 0) + 1
    team_info = {}

    def walk(nodes):
        for n in nodes:
            t = n["team"]
            blockers = []
            if n["children"]:
                blockers.append(f"{len(n['children'])} sotto-team")
            if n["direct"]:
                blockers.append(f"{n['direct']} person{'a' if n['direct'] == 1 else 'e'}")
            if pos_count.get(t["id"]):
                blockers.append(f"{pos_count[t['id']]} posizion{'e' if pos_count[t['id']] == 1 else 'i'}")
            team_info[t["id"]] = {"blockers": blockers, "modified": t["id"] in overrides,
                                  "descendants": org_svc.descendant_ids(sim["teams"], t["id"])}
            walk(n["children"])

    walk(tree)
    removed = [{"id": r["team_id"], "name": real_teams[r["team_id"]]["name"]}
               for r in team_rows if r["team_id"] and r["removed"] and r["team_id"] in real_teams]
    team_opts = _team_opts(sim["teams"])
    order = {t["id"]: i for i, t in enumerate(team_opts)}
    _, role_order, _ = org_r.chart_roles()
    # dalle persone reali: chi esce nella simulazione resta in tabella (in fondo) per poter rientrare
    move_by = {m["person_id"]: m for m in moves}
    people_rows = []
    for q in real["people"]:
        m = move_by.get(q["id"])
        hidden = bool(m and m["hidden"])
        shown = sim_by_id.get(q["id"]) or {**q, "team_id": m["team_ref"] if m else q["team_id"],
                                           "role_type": m["role_type"] if m else q["role_type"],
                                           "manager_person_id": None}
        people_rows.append({"sim": shown, "real": q, "hidden": hidden, "moved": bool(m) and not hidden})
    people_rows.sort(key=lambda r: (r["hidden"], order.get(r["sim"]["team_id"], len(order)),
                                    -role_order.get(r["sim"]["role_type"], 0), r["sim"]["full_name"] or ""))
    # posizioni aperte del budget: com'è oggi e com'è nella simulazione
    budget_info = {r["id"]: r for r in db.query(
        "SELECT hp.id, hb.period, hp.expected_start, hp.status FROM hiring_position hp "
        "JOIN hiring_budget hb ON hb.id = hp.budget_id")}
    sim_pos = {p["id"]: p for p in sim["positions"] if p["id"] > 0}
    pmoves = {m["position_id"]: m for m in _pos_moves(sid)}
    budget_rows = [{"real": p, "sim": sim_pos.get(p["id"], p), "info": budget_info.get(p["id"], {}),
                    "moved": p["id"] in pmoves and not pmoves[p["id"]]["hidden"],
                    "hidden": bool(pmoves.get(p["id"], {}).get("hidden")),
                    "move": pmoves.get(p["id"])}
                   for p in sorted(real["positions"], key=lambda x: x.get("title") or "")]
    # riepilogo dei cambi ai team, per la lista stampabile
    names = {p["id"]: p["full_name"] for p in real["people"]}

    def tname(ref):
        t = sim_teams.get(ref) or real_teams.get(ref)
        return t["name"] if t else "— radice —"

    team_changes = []
    for r in team_rows:
        if not r["team_id"]:
            team_changes.append({"kind": "nuovo", "name": r["name"],
                                 "details": [f"sotto {tname(r['parent_ref'])}"]
                                 + ([f"responsabile {names[r['lead_person_id']]}"] if r["lead_person_id"] in names else [])})
            continue
        old = real_teams.get(r["team_id"])
        if not old:
            continue
        if r["removed"]:
            team_changes.append({"kind": "tolto", "name": old["name"], "details": []})
            continue
        details = []
        if r["name"] != old["name"]:
            details.append(f"rinominato da {old['name']}")
        if r["parent_ref"] != old["parent_team_id"]:
            details.append(f"da sotto {tname(old['parent_team_id'])} a sotto {tname(r['parent_ref'])}")
        if r["lead_person_id"] != old["lead_person_id"]:
            details.append(f"responsabile {names.get(old['lead_person_id'], '—')} → {names.get(r['lead_person_id'], '—')}")
        if details:
            team_changes.append({"kind": "modificato", "name": r["name"], "details": details})
    return _templates().TemplateResponse(request, "reorg_edit.html", {
        "s": s, "editable": _editable(s), "err": err, "budget_rows": budget_rows, "team_changes": team_changes,
        "chart": _chart(sim), "mk": reorg_svc.marks(base, sim), **_chart_ctx(),
        "diff": reorg_svc.diff(base, sim), "pos_diff": reorg_svc.position_diff(base, sim), "team_opts": team_opts, "team_info": team_info,
        "sim_teams": sim_teams, "real_teams": real_teams, "removed": removed,
        "people_rows": people_rows, "people_opts": sorted(sim["people"], key=lambda p: p["full_name"] or ""),
        "sim_by_id": sim_by_id, "positions": positions, "today": date.today().isoformat(),
    })


@router.post("/org/sim/{sid}/meta")
def sim_meta(sid: int, name: str = Form(...), description: str = Form(None)):
    if _scenario(sid):
        db.execute("UPDATE reorg_scenario SET name=?, description=? WHERE id=?",
                   (name.strip(), (description or "").strip() or None, sid))
    return _back(sid)


@router.post("/org/sim/{sid}/team")
def sim_team_add(sid: int, name: str = Form(...), parent_ref: str = Form(None), lead_person_id: str = Form(None)):
    if not _editable(_scenario(sid)):
        return _back(sid)
    sim = _state(sid, _reality())
    parent = _ref(parent_ref)
    if parent not in {t["id"] for t in sim["teams"]}:
        parent = None
    order = 1 + max((t.get("sort_order") or 0 for t in sim["teams"] if t.get("parent_team_id") == parent), default=-1)
    rid = db.execute(
        "INSERT INTO reorg_team (scenario_id, name, parent_ref, lead_person_id, sort_order) VALUES (?,?,?,?,?)",
        (sid, name.strip(), parent, lead_person_id or None, order))
    return _back(sid, f"#st{-rid}")


def _upsert_team(sid: int, ref: int, sim_team: dict, **fields) -> None:
    """Scrive la modifica di un team: riga propria se nuovo, override completo se reale."""
    vals = {"name": sim_team["name"], "parent_ref": sim_team.get("parent_team_id"),
            "lead_person_id": sim_team.get("lead_person_id"), "sort_order": sim_team.get("sort_order") or 0,
            "removed": 0, **fields}
    if ref < 0:
        db.execute("UPDATE reorg_team SET name=?, parent_ref=?, lead_person_id=?, sort_order=?, removed=? "
                   "WHERE id=? AND scenario_id=?",
                   (vals["name"], vals["parent_ref"], vals["lead_person_id"], vals["sort_order"], vals["removed"],
                    -ref, sid))
        return
    existing = db.one("SELECT id FROM reorg_team WHERE scenario_id=? AND team_id=?", (sid, ref))
    if existing:
        db.execute("UPDATE reorg_team SET name=?, parent_ref=?, lead_person_id=?, sort_order=?, removed=? WHERE id=?",
                   (vals["name"], vals["parent_ref"], vals["lead_person_id"], vals["sort_order"], vals["removed"],
                    existing["id"]))
    else:
        db.execute("INSERT INTO reorg_team (scenario_id, team_id, name, parent_ref, lead_person_id, sort_order, removed) "
                   "VALUES (?,?,?,?,?,?,?)",
                   (sid, ref, vals["name"], vals["parent_ref"], vals["lead_person_id"], vals["sort_order"],
                    vals["removed"]))


@router.post("/org/sim/{sid}/team/{ref}/update")
def sim_team_update(sid: int, ref: int, name: str = Form(...), parent_ref: str = Form(None),
                    lead_person_id: str = Form(None)):
    if not _editable(_scenario(sid)):
        return _back(sid)
    sim = _state(sid, _reality())
    t = next((x for x in sim["teams"] if x["id"] == ref), None)
    if t is None:
        return _back(sid)
    parent = _ref(parent_ref)
    # un team non può finire sotto sé stesso né sotto un proprio discendente
    if parent not in {x["id"] for x in sim["teams"]} or parent in org_svc.descendant_ids(sim["teams"], ref):
        parent = None
    _upsert_team(sid, ref, t, name=name.strip(), parent_ref=parent,
                 lead_person_id=int(lead_person_id) if lead_person_id else None,
                 sort_order=t.get("sort_order") if parent == t.get("parent_team_id") else
                 1 + max((x.get("sort_order") or 0 for x in sim["teams"] if x.get("parent_team_id") == parent),
                         default=-1))
    return _back(sid, f"#st{ref}")


@router.post("/org/sim/{sid}/team/{ref}/remove")
def sim_team_remove(sid: int, ref: int):
    """Toglie un team dalla simulazione: solo se lì è vuoto (né persone, né sotto-team, né posizioni)."""
    if not _editable(_scenario(sid)):
        return _back(sid)
    sim = _state(sid, _reality())
    t = next((x for x in sim["teams"] if x["id"] == ref), None)
    busy = (any(p.get("team_id") == ref for p in sim["people"])
            or any(x.get("parent_team_id") == ref for x in sim["teams"])
            or any(p.get("team_id") == ref for p in sim["positions"]))
    if t is None or busy:
        return _back(sid, "?err=team_busy")
    if ref < 0:
        db.execute("DELETE FROM reorg_team WHERE id=? AND scenario_id=?", (-ref, sid))
    else:
        _upsert_team(sid, ref, t, removed=1)
    return _back(sid)


@router.post("/org/sim/{sid}/team/{ref}/restore")
def sim_team_restore(sid: int, ref: int):
    """Annulla le modifiche (o la rimozione) di un team reale: torna com'è nella realtà."""
    if _editable(_scenario(sid)) and ref > 0:
        db.execute("DELETE FROM reorg_team WHERE scenario_id=? AND team_id=?", (sid, ref))
    return _back(sid)


@router.post("/org/sim/{sid}/moves")
async def sim_moves(request: Request, sid: int):
    """Team e ruolo per persona, o "esce": si salva una riga solo per chi differisce dalla realtà."""
    if not _editable(_scenario(sid)):
        return _back(sid)
    form = await request.form()
    real = _reality()
    sim = _state(sid, real)
    sim_teams = {t["id"] for t in sim["teams"]}
    roles = {r["code"] for r in org_r.chart_roles()[0]}
    with db.transaction() as conn:
        for p in real["people"]:
            hidden = 1 if form.get(f"hide_{p['id']}") else 0
            team = _ref(form.get(f"team_{p['id']}"))
            role = form.get(f"role_{p['id']}")
            if team not in sim_teams:
                team = p.get("team_id")
            if role not in roles:
                role = p.get("role_type")
            if not hidden and (team is None or (team == p.get("team_id") and role == p.get("role_type"))):
                conn.execute("DELETE FROM reorg_move WHERE scenario_id=? AND person_id=?", (sid, p["id"]))
            else:
                conn.execute(
                    "INSERT INTO reorg_move (scenario_id, person_id, team_ref, role_type, hidden) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(scenario_id, person_id) DO UPDATE SET team_ref=excluded.team_ref, "
                    "role_type=excluded.role_type, hidden=excluded.hidden",
                    (sid, p["id"], team if team is not None else 0, role, hidden))
    return _back(sid, "#persone")


@router.post("/org/sim/{sid}/position-moves")
async def sim_position_moves(request: Request, sid: int):
    """Team e ruolo delle posizioni aperte del budget: una riga solo per chi differisce dalla realtà."""
    if not _editable(_scenario(sid)):
        return _back(sid)
    form = await request.form()
    real = _reality()
    sim_teams = {t["id"] for t in _state(sid, real)["teams"]}
    roles = {r["code"] for r in org_r.chart_roles()[0]}
    with db.transaction() as conn:
        for p in real["positions"]:
            hidden = 1 if form.get(f"phide_{p['id']}") else 0
            team = _ref(form.get(f"pteam_{p['id']}"))
            role = form.get(f"prole_{p['id']}")
            if team not in sim_teams:
                team = p.get("team_id")
            if role not in roles:
                role = p.get("role_type")
            if not hidden and (team is None or (team == p.get("team_id") and role == p.get("role_type"))):
                conn.execute("DELETE FROM reorg_position_move WHERE scenario_id=? AND position_id=?", (sid, p["id"]))
            else:
                conn.execute(
                    "INSERT INTO reorg_position_move (scenario_id, position_id, team_ref, role_type, hidden) "
                    "VALUES (?,?,?,?,?) ON CONFLICT(scenario_id, position_id) DO UPDATE SET "
                    "team_ref=excluded.team_ref, role_type=excluded.role_type, hidden=excluded.hidden",
                    (sid, p["id"], team if team is not None else 0, role, hidden))
    return _back(sid, "#budget")


@router.post("/org/sim/{sid}/position")
def sim_position_add(sid: int, title: str = Form(...), team_ref: str = Form(None), role_type: str = Form("ic"),
                     internal: str = Form(None)):
    """Posizione ipotetica: nuova assunzione, o figura interna di un altro team (titolo = nome)."""
    if _editable(_scenario(sid)):
        db.execute("INSERT INTO reorg_position (scenario_id, title, team_ref, role_type, internal) VALUES (?,?,?,?,?)",
                   (sid, title.strip(), _ref(team_ref), role_type, 1 if internal else 0))
    return _back(sid, "#posizioni")


@router.post("/org/sim/{sid}/position/{pid}/update")
def sim_position_update(sid: int, pid: int, title: str = Form(...), team_ref: str = Form(None),
                        role_type: str = Form("ic"), internal: str = Form(None)):
    """Correzione in place di una posizione ipotetica (è un'ipotesi: niente storico)."""
    if _editable(_scenario(sid)):
        db.execute("UPDATE reorg_position SET title=?, team_ref=?, role_type=?, internal=? "
                   "WHERE id=? AND scenario_id=?",
                   (title.strip(), _ref(team_ref), role_type, 1 if internal else 0, pid, sid))
    return _back(sid, "#posizioni")


@router.post("/org/sim/{sid}/position/{pid}/delete")
def sim_position_delete(sid: int, pid: int):
    if _editable(_scenario(sid)):
        db.execute("DELETE FROM reorg_position WHERE id=? AND scenario_id=?", (pid, sid))
    return _back(sid, "#posizioni")


# ---- stato e applicazione ----

@router.post("/org/sim/{sid}/status")
def sim_status(sid: int, action: str = Form(...)):
    """bozza → approvata (bloccata) → di nuovo bozza se serve; scartata da bozza o approvata."""
    s = _scenario(sid)
    if not s or s["status"] == "applicata":
        return _back(sid)
    if action == "approva" and s["status"] == "bozza":
        db.execute("UPDATE reorg_scenario SET status='approvata', approved_at=datetime('now','localtime') "
                   "WHERE id=?", (sid,))
    elif action == "bozza" and s["status"] in ("approvata", "scartata"):
        db.execute("UPDATE reorg_scenario SET status='bozza', approved_at=NULL WHERE id=?", (sid,))
    elif action == "scarta" and s["status"] in ("bozza", "approvata"):
        db.execute("UPDATE reorg_scenario SET status='scartata' WHERE id=?", (sid,))
    return _back(sid)


@router.post("/org/sim/{sid}/apply")
def sim_apply(sid: int, effective_date: str = Form(...)):
    """Applica una simulazione approvata dalla data indicata.

    Crea i team nuovi e aggiorna quelli modificati (il team non è storicizzato:
    modifica in place), registra ogni spostamento come nuova assegnazione dalla
    data (cambiamento reale, lo storico resta) e toglie i team rimossi se sono
    eliminabili. Poi i riporti: calcolati per chi si è spostato, e per gli altri
    la verifica riporti di sempre, come cambiamento dalla stessa data.
    """
    s = _scenario(sid)
    if not s or s["status"] != "approvata":
        return _back(sid)
    real = _reality()
    team_rows, moves, _ = _rows(sid)
    real_ids = {t["id"] for t in real["teams"]}
    current = {p["id"]: p for p in real["people"]}
    prev_end = (date.fromisoformat(effective_date) - timedelta(days=1)).isoformat()
    moved = []
    with db.transaction() as conn:
        created = {}
        new_rows = [r for r in team_rows if not r["team_id"] and not r["removed"]]
        for r in new_rows:
            created[-r["id"]] = conn.execute(
                "INSERT INTO team (name, lead_person_id, sort_order) VALUES (?,?,?)",
                (r["name"], r["lead_person_id"] if r["lead_person_id"] in current else None,
                 r["sort_order"])).lastrowid

        def real_ref(x):
            if x is None:
                return None
            return created.get(x) if x < 0 else (x if x in real_ids else None)

        for r in new_rows:
            conn.execute("UPDATE team SET parent_team_id=? WHERE id=?", (real_ref(r["parent_ref"]), created[-r["id"]]))
        for r in team_rows:
            if r["team_id"] in real_ids and not r["removed"]:
                conn.execute("UPDATE team SET name=?, parent_team_id=?, lead_person_id=?, sort_order=? WHERE id=?",
                             (r["name"], real_ref(r["parent_ref"]),
                              r["lead_person_id"] if r["lead_person_id"] in current else None,
                              r["sort_order"], r["team_id"]))
        for m in moves:
            if m["hidden"]:
                continue  # uscita simulata: nella realtà la persona resta (la cessazione è a parte)
            p = current.get(m["person_id"])
            target = real_ref(m["team_ref"])
            if not p or not p["assignment_id"] or target is None:
                continue
            if target == p["team_id"] and m["role_type"] == p["role_type"]:
                continue
            if str(p["start_date"]) < effective_date:
                conn.execute("UPDATE person_assignment SET end_date=? WHERE id=?", (prev_end, p["assignment_id"]))
                conn.execute(
                    "INSERT INTO person_assignment (person_id, team_id, role_type, start_date, listino_profile_id) "
                    "VALUES (?,?,?,?,?)", (p["id"], target, m["role_type"], effective_date, p["listino_profile_id"]))
            else:  # l'assegnazione corrente parte già da quella data o dopo: si aggiorna lei
                conn.execute("UPDATE person_assignment SET team_id=?, role_type=? WHERE id=?",
                             (target, m["role_type"], p["assignment_id"]))
            moved.append(p["id"])
        # posizioni del budget: pianificazione, si aggiornano in place (solo se ancora aperte)
        marks = ",".join("?" * len(budget_svc.OPEN_POSITIONS))
        for pm in _pos_moves(sid):
            target = real_ref(pm["team_ref"])
            if target is not None and not pm["hidden"]:  # nascosta: resta nel budget com'è
                conn.execute(f"UPDATE hiring_position SET team_id=?, role_type=? WHERE id=? AND voided=0 "
                             f"AND status IN ({marks})", (target, pm["role_type"], pm["position_id"],
                                                         *budget_svc.OPEN_POSITIONS))
        conn.execute("UPDATE reorg_scenario SET status='applicata', effective_date=?, "
                     "applied_at=datetime('now','localtime') WHERE id=?", (effective_date, sid))
    # team tolti: eliminati se ora sono vuoti e senza storia, archiviati se hanno solo storia,
    # altrimenti restano (avviso in pagina)
    blockers = org_r._team_blockers()
    for r in team_rows:
        if r["team_id"] not in real_ids or not r["removed"]:
            continue
        why = blockers.get(r["team_id"])
        if not why:
            with db.transaction() as conn:
                conn.execute("DELETE FROM reorg_team WHERE team_id=?", (r["team_id"],))
                conn.execute("DELETE FROM team WHERE id=?", (r["team_id"],))
        elif not why["block"]:
            db.execute("UPDATE team SET archived_at=datetime('now','localtime') WHERE id=?", (r["team_id"],))
    for pid in moved:
        org_r._derive_manager(pid)
    return org_r._verify_reports(f"/org/sim/{sid}", "cambiamento", effective_date)
