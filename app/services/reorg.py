"""Simulazioni di riorganizzazione: stato simulato e confronti, puri e senza DB.

Una simulazione = realtà + differenze (vedi migrations/0021_simulazioni.sql).
I team nuovi hanno id negativo (-reorg_team.id), così convivono con quelli reali
nelle stesse funzioni di org_tree. I riporti dello stato simulato si ricalcolano
con `org_tree.expected_manager`, la stessa regola dell'organigramma reale.
"""

from __future__ import annotations

from app.services import org_tree


def team_ref(row) -> int:
    """Riferimento di una riga reorg_team: id reale se modifica, -id se team nuovo."""
    return row["team_id"] if row.get("team_id") else -row["id"]


def simulate(teams, people, positions, team_rows, moves, sim_positions, role_order, pos_moves=()) -> dict:
    """Stato simulato: {"teams", "people", "positions"} pronti per org_tree.build_chart.

    `teams`: team reali (id, name, parent_team_id, lead_person_id, sort_order).
    `people`: persone attive con l'assegnazione corrente (id, full_name, role_type, team_id, …).
    `positions`: posizioni aperte reali (id, title, role_type, team_id, status, manager_hint).
    `team_rows`: reorg_team; `moves`: reorg_move; `sim_positions`: reorg_position;
    `pos_moves`: reorg_position_move (posizioni reali spostate di team/ruolo, o nascoste:
    `hidden` = nella simulazione la posizione non c'è).
    Gli spostamenti verso un team che non esiste più si ignorano; chi resta in un
    team tolto finisce senza team. I riporti sono tutti ricalcolati.
    """
    out_teams = {t["id"]: dict(t) for t in teams}
    for r in team_rows:
        ref = team_ref(r)
        if r.get("team_id") and r["team_id"] not in out_teams:
            continue  # il team reale non c'è più: la modifica cade
        if r.get("removed"):
            out_teams.pop(ref, None)
            continue
        out_teams[ref] = {"id": ref, "name": r["name"], "parent_team_id": r.get("parent_ref"),
                          "lead_person_id": r.get("lead_person_id"), "sort_order": r.get("sort_order") or 0,
                          "new": ref < 0}
    for t in out_teams.values():
        if t.get("parent_team_id") not in out_teams:
            t["parent_team_id"] = None

    move_by = {m["person_id"]: m for m in moves}
    out_people = []
    for p in people:
        q = dict(p)
        m = move_by.get(p["id"])
        if m and m.get("hidden"):
            continue  # esce: nella simulazione non c'è (riporti ricalcolati senza di lei)
        if m and m["team_ref"] in out_teams:
            q["team_id"], q["role_type"] = m["team_ref"], m["role_type"]
        if q.get("team_id") not in out_teams:
            q["team_id"] = None
        out_people.append(q)
    for q in out_people:
        q["manager_person_id"] = org_tree.expected_manager(q, out_people, list(out_teams.values()), role_order)

    pmove_by = {m["position_id"]: m for m in pos_moves}
    out_pos = []
    for pos in positions:
        q = dict(pos)
        m = pmove_by.get(pos["id"])
        if m and m.get("hidden"):
            continue
        if m and m["team_ref"] in out_teams:
            q["team_id"], q["role_type"] = m["team_ref"], m["role_type"]
        if q.get("team_id") not in out_teams:
            q["team_id"] = None
        out_pos.append(q)
    for sp in sim_positions:
        out_pos.append({"id": -sp["id"], "title": sp["title"], "role_type": sp["role_type"],
                        "team_id": sp["team_ref"] if sp.get("team_ref") in out_teams else None,
                        "status": "ipotetica", "manager_hint": None, "hypothetical": True,
                        "internal": bool(sp.get("internal"))})
    return {"teams": list(out_teams.values()), "people": out_people, "positions": out_pos}


def team_key(team) -> str:
    """Chiave per confrontare team fra stati: id reale, o nome per i team nuovi
    (due simulazioni che creano lo stesso «Team X» parlano dello stesso team)."""
    return f"t{team['id']}" if team["id"] > 0 else "n:" + (team["name"] or "").strip().lower()


def diff(a: dict, b: dict) -> list[dict]:
    """Persone che cambiano team, ruolo o riporto da A a B, o che escono.

    [{person, a: {team, role, manager} | None, b: {…} | None, changes}], con nomi di team e
    responsabili già risolti. `changes` ⊆ {"team", "role", "manager"}, oppure {"exit"} per chi
    c'è in uno solo dei due stati (uscita simulata: `b` None se esce in B, `a` None se in A).
    """
    def view(state):
        teams = {t["id"]: t for t in state["teams"]}
        names = {p["id"]: p["full_name"] for p in state["people"]}
        out = {}
        for p in state["people"]:
            t = teams.get(p.get("team_id"))
            out[p["id"]] = {"team": t["name"] if t else None, "team_key": team_key(t) if t else None,
                            "role": p.get("role_type"), "manager": names.get(p.get("manager_person_id")),
                            "manager_id": p.get("manager_person_id"), "person": p}
        return out

    va, vb = view(a), view(b)
    rows = []
    for pid in set(vb) - set(va):
        rows.append({"person": vb[pid]["person"], "a": None, "b": vb[pid], "changes": {"exit"}})
    for pid, x in va.items():
        y = vb.get(pid)
        if y is None:
            rows.append({"person": x["person"], "a": x, "b": None, "changes": {"exit"}})
            continue
        changes = set()
        if x["team_key"] != y["team_key"]:
            changes.add("team")
        if x["role"] != y["role"]:
            changes.add("role")
        if x["manager_id"] != y["manager_id"]:
            changes.add("manager")
        if changes:
            rows.append({"person": y["person"], "a": x, "b": y, "changes": changes})
    rows.sort(key=lambda r: r["person"]["full_name"] or "")
    return rows


def headcount(a: dict, b: dict) -> list[dict]:
    """Persone per team in A e in B (solo dirette), ordinate come l'albero di B e poi i team che
    esistono solo in A. [{name, a, b, plus_a, plus_b, pos_a, pos_b, only}]:
    `plus_a` = di quanto cambia il totale di A con le sue posizioni aperte (reali e ipotetiche);
    `plus_b` = totale di B (persone + posizioni) rispetto alle persone di A, l'attuale nel
    confronto tipico. a/b None se il team lì non c'è (vale 0 nei conti)."""
    def count(state):
        teams = {t["id"]: t for t in state["teams"]}
        out = {}
        for t in state["teams"]:
            out[team_key(t)] = {"name": t["name"], "people": 0, "positions": 0}
        for p in state["people"]:
            t = teams.get(p.get("team_id"))
            if t:
                out[team_key(t)]["people"] += 1
        for pos in state["positions"]:
            t = teams.get(pos.get("team_id"))
            if t:
                out[team_key(t)]["positions"] += 1
        return out

    ca, cb = count(a), count(b)
    order = [team_key(t) for t in _ordered(b["teams"])] + [team_key(t) for t in _ordered(a["teams"])]
    rows, seen = [], set()
    for k in order:
        if k in seen:
            continue
        seen.add(k)
        x, y = ca.get(k), cb.get(k)
        na, nb = (x or {}).get("people", 0), (y or {}).get("people", 0)
        pa, pb = (x or {}).get("positions", 0), (y or {}).get("positions", 0)
        rows.append({"name": (y or x)["name"], "a": na if x else None, "b": nb if y else None,
                     "plus_a": pa, "plus_b": nb + pb - na, "pos_a": pa, "pos_b": pb,
                     "only": "a" if y is None else "b" if x is None else None})
    return rows


def headcount_totals(rows) -> dict:
    """Totali delle colonne di `headcount` (un team assente vale 0)."""
    keys = ("a", "plus_a", "b", "plus_b")
    return {k: sum(r[k] or 0 for r in rows) for k in keys}


def _ordered(teams) -> list[dict]:
    by_id = {t["id"]: t for t in teams}
    return [by_id[i] for i in org_tree.team_order(teams)]


def position_diff(a: dict, b: dict) -> list[dict]:
    """Posizioni con team o ruolo diversi fra A e B, e posizioni del budget nascoste in uno dei due.

    [{position, a: {team, role} | None, b: {…} | None, changes}]: `changes` = {"team", "role"},
    oppure {"hidden"} se la posizione reale (id > 0) c'è in un solo stato. Le ipotetiche
    (id < 0) di una sola simulazione non sono né spostate né nascoste e restano fuori.
    """
    def view(state):
        teams = {t["id"]: t for t in state["teams"]}
        out = {}
        for p in state["positions"]:
            t = teams.get(p.get("team_id"))
            out[p["id"]] = {"team": t["name"] if t else None, "team_key": team_key(t) if t else None,
                            "role": p.get("role_type"), "position": p}
        return out

    va, vb = view(a), view(b)
    rows = []
    for pid in set(va) | set(vb):
        x, y = va.get(pid), vb.get(pid)
        if x is None or y is None:
            if pid > 0:
                rows.append({"position": (y or x)["position"], "a": x, "b": y, "changes": {"hidden"}})
            continue
        changes = {k for k, ka in (("team", "team_key"), ("role", "role")) if x[ka] != y[ka]}
        if changes:
            rows.append({"position": y["position"], "a": x, "b": y, "changes": changes})
    rows.sort(key=lambda r: r["position"].get("title") or "")
    return rows


def marks(a: dict, b: dict) -> dict:
    """Cosa evidenziare nel grafico di B rispetto ad A: persone per id (team > ruolo > riporto;
    "exit" = in B c'è ma in A esce), posizioni come "pos<id>" (team > ruolo)."""
    out = {}
    for r in diff(a, b):
        c = r["changes"]
        if "exit" in c:
            if r["b"] is not None:  # c'è in B ma esce in A: nel grafico di B la si segnala
                out[r["person"]["id"]] = "exit"
            continue
        out[r["person"]["id"]] = "team" if "team" in c else "role" if "role" in c else "manager"
    for r in position_diff(a, b):
        if r["b"] is not None:  # una posizione nascosta in B non è nel grafico di B
            out[f"pos{r['position']['id']}"] = "team" if "team" in r["changes"] else "role"
    return out
