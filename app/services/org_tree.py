"""Gerarchia team e linee di riporto: alberi e conteggi puri, senza DB.

Input = liste di dict (righe SQL già convertite), come in trends.py.
Le gerarchie reali possono contenere cicli (nessun vincolo in schema):
ogni attraversamento usa un insieme di visitati e non perde nessun nodo.
"""

from __future__ import annotations

# colore del badge per role_type (codici seed fissi; le etichette vengono da lookup)
ROLE_BADGE = {"ic": "", "tl": "green", "mgr": "blue", "sr": "purple"}
# primo ruolo che può avere riporti diretti: sotto di lui nessuno fa da responsabile
MIN_MANAGER_ROLE = "tl"


# ---- team ----

def sibling_key(t):
    """Ordine tra fratelli: `sort_order`, poi nome (a parità o se manca)."""
    return (t.get("sort_order") or 0, t.get("name") or "", t["id"])


def children_map(teams) -> dict[int | None, list[dict]]:
    """parent_team_id → [team], in ordine tra fratelli."""
    out: dict[int | None, list[dict]] = {}
    for t in sorted(teams, key=sibling_key):
        out.setdefault(t["parent_team_id"], []).append(t)
    return out


def team_order(teams) -> list[int]:
    """Id dei team in ordine di visita dell'albero (padre, poi figli in ordine)."""
    out: list[int] = []

    def walk(nodes):
        for n in nodes:
            out.append(n["team"]["id"])
            walk(n["children"])

    walk(build_team_tree(teams, []))
    return out


def move_team(teams, team_id: int, direction: str) -> dict[int, int]:
    """Sposta su/giù un team tra i suoi fratelli: {team_id: nuovo sort_order}.

    Rinumera i fratelli 0..n-1 nell'ordine attuale e scambia il team con quello
    adiacente; il padre non cambia mai. Primo/ultimo o team ignoto: {}.
    """
    t = next((x for x in teams if x["id"] == team_id), None)
    if t is None:
        return {}
    sibs = children_map(teams).get(t["parent_team_id"], [])
    ids = [s["id"] for s in sibs]
    i = ids.index(team_id)
    j = i - 1 if direction == "up" else i + 1 if direction == "down" else i
    if j == i or not 0 <= j < len(ids):
        return {}
    ids[i], ids[j] = ids[j], ids[i]
    return {tid: n for n, tid in enumerate(ids)}


def descendant_ids(teams, team_id: int) -> set[int]:
    """Il team stesso più tutti i discendenti (BFS, regge i cicli)."""
    children = children_map(teams)
    seen = {team_id}
    queue = [team_id]
    while queue:
        tid = queue.pop()
        for c in children.get(tid, []):
            if c["id"] not in seen:
                seen.add(c["id"])
                queue.append(c["id"])
    return seen


def build_team_tree(teams, members) -> list[dict]:
    """Albero dei team con conteggi a cascata.

    Nodo: {"team", "members" (diretti), "children", "direct", "total", "depth"}.
    `direct` = persone distinte assegnate al team; `total` = persone distinte nel
    sottoalbero (ognuna contata una volta anche se compare in più team).
    Il lead del team non conta se non è assegnato.
    Radici = team senza padre o con padre inesistente; i team di un ciclo puro
    (mai raggiunti da una radice) vengono aggiunti come radici extra.
    """
    by_team: dict[int, list] = {}
    for m in members:
        by_team.setdefault(m["team_id"], []).append(m)
    children = children_map(teams)
    ids = {t["id"] for t in teams}
    visited: set[int] = set()

    def _build(t, depth):
        visited.add(t["id"])
        direct = by_team.get(t["id"], [])
        people = {m["id"] for m in direct}
        kids = []
        for c in children.get(t["id"], []):
            if c["id"] in visited:
                continue
            node, sub = _build(c, depth + 1)
            kids.append(node)
            people |= sub
        node = {"team": t, "members": direct, "children": kids,
                "direct": len({m["id"] for m in direct}), "total": len(people), "depth": depth}
        return node, people

    roots = []
    ordered = sorted(teams, key=sibling_key)
    for t in ordered:
        if t["parent_team_id"] is None or t["parent_team_id"] not in ids:
            roots.append(_build(t, 0)[0])
    for t in ordered:  # cicli puri: nessuna radice li raggiunge
        if t["id"] not in visited:
            roots.append(_build(t, 0)[0])
    return roots


def team_totals(teams, members) -> dict[int, dict]:
    """{team_id: {"direct", "total"}} ricavato dall'albero."""
    out: dict[int, dict] = {}

    def walk(nodes):
        for n in nodes:
            out[n["team"]["id"]] = {"direct": n["direct"], "total": n["total"]}
            walk(n["children"])

    walk(build_team_tree(teams, members))
    return out


# ---- linee di riporto ----

def role_rows(role_order) -> dict[str, int]:
    """role_type → riga orizzontale del grafico: il ruolo più alto sta in riga 0.

    Una riga per ogni ruolo che può avere riporti (dal TL in su); quelli sotto
    (Specialist, Junior…) stanno tutti sull'ultima riga, insieme: l'ordine fra
    loro è dentro la colonna, non in altezza.
    """
    codes = sorted(role_order, key=lambda c: -role_order[c])
    floor = role_order.get(MIN_MANAGER_ROLE)
    if floor is None:
        return {c: i for i, c in enumerate(codes)}
    managers = [c for c in codes if role_order[c] >= floor]
    return {c: (managers.index(c) if c in managers else len(managers)) for c in codes}


# riporto atteso fuori perimetro: sopra il team più alto del director c'è un team che lui non
# vede (è di un altro director). Non si calcola e non si sovrascrive: resta quello salvato.
OUTSIDE = "fuori-perimetro"


def expected_manager(person, people, teams, role_order) -> int | None:
    """Riporto diretto atteso da team e ruolo: Specialist → TL → Manager → Director.

    `person`: dict con id (None per una posizione aperta), role_type, team_id.
    `people`: persone attive con id, full_name, role_type, team_id.
    Si parte dal team della persona e si risale ai team padre: in ogni team i
    candidati sono i membri attivi più il lead del team, con un ruolo sopra quello
    della persona e almeno da TL: chi sta sotto il TL (Specialist, Junior…) non è mai
    riporto di nessuno, quindi un Junior va al TL e non allo Specialist. Vince il
    ruolo più vicino (se manca il TL si sale al Manager, e così via); a parità il
    lead del team, poi il nome. Nessuno sopra → None. Se la risalita arriva a un team
    padre non visibile (o a un team marcato `outside` dalla simulazione) → OUTSIDE.
    """
    def rank(p):
        return role_order.get(p.get("role_type"), 0)

    me = max(rank(person), role_order.get(MIN_MANAGER_ROLE, 0) - 1)
    by_id = {p["id"]: p for p in people}
    team_by_id = {t["id"]: t for t in teams}
    tid, seen = person.get("team_id"), set()
    while tid is not None and tid not in seen:
        seen.add(tid)
        t = team_by_id.get(tid)
        if t is None and seen != {person.get("team_id")}:
            return OUTSIDE  # padre di un altro director
        lead = t.get("lead_person_id") if t else None
        cands = {p["id"]: p for p in people if p.get("team_id") == tid}
        if lead in by_id:
            cands.setdefault(lead, by_id[lead])
        above = [c for c in cands.values() if c["id"] != person.get("id") and rank(c) > me]
        if above:
            return min(above, key=lambda c: (rank(c), c["id"] != lead, c.get("full_name") or ""))["id"]
        if t is None:
            break
        if t.get("outside"):
            return OUTSIDE
        tid = t.get("parent_team_id")
    return None


def report_mismatches(people, teams, role_order) -> list[dict]:
    """Persone il cui riporto salvato non è quello atteso da team e ruolo.

    `people` come in `expected_manager` più `manager_person_id`; chi non ha team
    è escluso (non c'è niente da cui derivare). [{person, current, expected}].
    """
    out = []
    for p in people:
        if p.get("team_id") is None:
            continue
        exp = expected_manager(p, people, teams, role_order)
        if exp is not OUTSIDE and p.get("manager_person_id") != exp:
            out.append({"person": p, "current": p.get("manager_person_id"), "expected": exp})
    return out


def _position_parent(pos, by_id, teams, role_order) -> int | None:
    """A chi si aggancia una posizione aperta: al responsabile della persona che
    sostituisce se ancora attivo, altrimenti con la stessa regola delle persone."""
    hint = pos.get("manager_hint")
    if hint in by_id:
        return hint
    exp = expected_manager({"id": None, "role_type": pos.get("role_type"), "team_id": pos.get("team_id")},
                           list(by_id.values()), teams, role_order)
    return None if exp is OUTSIDE else exp


def build_chart(people, teams, positions=(), role_order=None, focus_team_ids=None) -> dict:
    """Grafico delle linee di riporto, a righe allineate per ruolo.

    `people`: una riga per persona attiva con l'assegnazione corrente
    (id, full_name, role_type, team_id, manager_person_id). Il riporto è solo
    `manager_person_id`: niente agganci impliciti al lead del team. Chi non ne ha
    uno valido (assente, non attivo, sé stesso, ciclo) diventa radice e, se non è
    del ruolo più alto, finisce negli avvisi.
    `positions`: posizioni aperte (id, title, role_type, team_id, status,
    manager_hint = responsabile della persona sostituita), una casella ciascuna.
    `focus_team_ids`: mostra solo quei team coi sotto-team, più la catena dei
    responsabili sopra (marcata `ctx`).

    Ogni elemento è un nodo (persona con riporti visibili, `children`) o una
    colonna (`members`: i riporti senza sotto-riporti dello stesso team, per
    ruolo e poi nome). `skip` = righe vuote sopra l'elemento per tenere il ruolo
    alla sua riga; `label` = nome del team, solo dove cambia rispetto al padre.
    `direct`/`total` contano le persone sull'organigramma intero, anche col filtro.
    """
    role_order = role_order or {}
    rows = role_rows(role_order)
    last = max(rows.values(), default=0)

    def row(code):
        return rows.get(code, last)

    by_id = {p["id"]: p for p in people}
    team_by_id = {t["id"]: t for t in teams}

    parent: dict[int, int | None] = {}
    problem: dict[int, str] = {}
    for p in people:
        mid = p.get("manager_person_id")
        if mid in by_id and mid != p["id"]:
            parent[p["id"]] = mid
        else:
            parent[p["id"]] = None
            if not p.get("outside"):  # chi riporta fuori dal perimetro è una radice, non un'anomalia
                problem[p["id"]] = "inactive" if mid is not None and mid != p["id"] else "missing"

    def reachable():
        kids: dict[int | None, list[int]] = {}
        for pid, mid in parent.items():
            kids.setdefault(mid, []).append(pid)
        seen, stack = set(), list(kids.get(None, []))
        while stack:
            x = stack.pop()
            if x not in seen:
                seen.add(x)
                stack.extend(kids.get(x, []))
        return seen

    # cicli: da un nodo irraggiungibile risali i manager fino al primo che si ripete, e taglia lì
    cycle_cuts = 0
    seen = reachable()
    while len(seen) < len(by_id):
        cur = min(pid for pid in by_id if pid not in seen)
        path: set[int] = set()
        while cur not in path:
            path.add(cur)
            cur = parent[cur]
        parent[cur] = None
        problem[cur] = "cycle"
        cycle_cuts += 1
        seen = reachable()

    kids: dict[int | None, list[int]] = {}
    for pid in sorted(by_id):
        kids.setdefault(parent[pid], []).append(pid)
    total: dict[int, int] = {}

    def count(pid):
        total[pid] = sum(1 + count(c) for c in kids.get(pid, []))
        return total[pid]

    for r in kids.get(None, []):
        count(r)

    pos_parent = [_position_parent(pos, by_id, teams, role_order) for pos in positions]

    if focus_team_ids:
        focus = set().union(*(descendant_ids(teams, tid) for tid in focus_team_ids))
        sel_people = {pid for pid, p in by_id.items() if p.get("team_id") in focus}
        sel_pos = {i for i, pos in enumerate(positions) if pos.get("team_id") in focus}
    else:
        sel_people, sel_pos = set(by_id), set(range(len(positions)))
    visible = set(sel_people)

    def climb(mid):
        while mid is not None and mid not in visible:
            visible.add(mid)
            mid = parent[mid]

    for pid in sel_people:
        climb(parent[pid])
    for i in sel_pos:
        climb(pos_parent[i])

    def warn(pid):
        return problem.get(pid) if problem.get(pid) != "missing" or row(by_id[pid].get("role_type")) > 0 else None

    entries: dict[int | None, list[dict]] = {}
    for pid in sorted(visible):
        p = by_id[pid]
        entries.setdefault(parent[pid], []).append({
            "kind": "person", "id": pid, "person": p, "role": p.get("role_type"),
            "team_id": p.get("team_id"), "name": p["full_name"] or "",
            "direct": len(kids.get(pid, [])), "total": total[pid],
            "problem": warn(pid), "ctx": pid not in sel_people})
    for i in sorted(sel_pos):
        pos = positions[i]
        entries.setdefault(pos_parent[i], []).append({
            "kind": "pos", "pos": pos, "role": pos.get("role_type"), "team_id": pos.get("team_id"),
            "name": pos.get("title") or ""})

    rank = {tid: n for n, tid in enumerate(team_order(teams))}

    def team_name(tid):
        t = team_by_id.get(tid)
        return t["name"] if t else ""

    def member_key(e):
        # in colonna: per ruolo (Specialist prima di Junior anche se stanno sulla stessa riga), poi nome
        return (-role_order.get(e["role"], float("-inf")), e["kind"] == "pos", e["name"])

    def layout(group, parent_row, parent_team):
        items, cols = [], {}
        for e in group:
            if e["kind"] == "person" and entries.get(e["id"]):
                items.append({"kind": "node", "entry": e, "team_id": e["team_id"], "top": row(e["role"]),
                              "name": e["name"],
                              "children": layout(entries[e["id"]], row(e["role"]), e["team_id"])})
            else:
                cols.setdefault(e["team_id"], []).append(e)
        for tid, members in cols.items():
            members.sort(key=member_key)
            items.append({"kind": "col", "members": members, "team_id": tid,
                          "top": row(members[0]["role"]), "name": members[0]["name"]})
        return finish(group_by_team(items, parent_team), parent_row, parent_team)

    def finish(items, parent_row, parent_team):
        items.sort(key=lambda it: (it["team_id"] != parent_team, rank.get(it["team_id"], len(rank)),
                                   it["top"], it["kind"] == "col", it["name"]))
        prev = object()
        for it in items:
            if it["kind"] == "group":
                # sta nella riga del manager che il team non ha: quella sopra i suoi rami. Se i rami
                # sono già subito sotto il responsabile non c'è una riga libera e scendono di una.
                it["top"] = max(min(ch["top"] for ch in it["children"]) - 1, parent_row + 1)
                it["skip"] = it["top"] - parent_row - 1
                finish(it["children"], it["top"], it["team_id"])
                prev = it["team_id"]
                continue
            it["skip"] = max(0, it["top"] - parent_row - 1)
            it["label"] = (team_name(it["team_id"]) or None) if it["team_id"] not in (parent_team, prev) else None
            prev = it["team_id"]
        return items

    parent_of = {t["id"]: t.get("parent_team_id") for t in teams}

    def between(tid, stop):
        """Team intermedi fra `stop` (escluso) e `tid` (escluso), dall'alto; None se `stop` non è un antenato."""
        path, cur, seen = [], parent_of.get(tid), set()
        while cur is not None and cur not in seen:
            if cur == stop:
                return path[::-1]
            seen.add(cur)
            path.append(cur)
            cur = parent_of.get(cur)
        return None

    def group_by_team(items, parent_team):
        """Rami che passano da team intermedi senza un responsabile in mezzo (es. Operation → PMO →
        PM Lead / PM Tech): si raccolgono in una casella di raggruppamento col nome del team, nella
        riga in cui starebbe il suo manager, da cui si biforcano. Più intermedi di fila diventano
        una sola casella ("Operation › PMO")."""
        if parent_team is None:
            return items
        chains = {id(it): between(it["team_id"], parent_team) for it in items if it["team_id"] is not None}
        keys = {tuple(ch) for ch in chains.values() if ch}
        if not keys:
            return items
        assign = {}
        for it in items:
            ch = chains.get(id(it))
            if ch is None:
                continue
            own = tuple(ch + [it["team_id"]])
            if own in keys:      # chi sta proprio nel team di un raggruppamento entra lì
                assign[id(it)] = own
            elif ch:
                assign[id(it)] = tuple(ch)
        groups: dict[tuple, list] = {}
        for it in items:
            if id(it) in assign:
                groups.setdefault(assign[id(it)], []).append(it)
        out = [it for it in items if id(it) not in assign]
        for key, members in groups.items():
            lead = (team_by_id.get(key[-1]) or {}).get("lead_person_id")
            out.append({"kind": "group", "team_id": key[-1], "chain": list(key),
                        "label": " › ".join(team_name(t) for t in key),
                        # responsabile dalla scheda team (se attivo): non ha riporti, coordina
                        "coordinator": by_id[lead]["full_name"] if lead in by_id else None,
                        "top": min(m["top"] for m in members), "name": team_name(key[-1]),
                        "children": members})
        has_groups[0] = True
        return out

    has_groups = [False]

    warnings = [{"person": by_id[pid], "problem": warn(pid)}
                for pid in sorted(visible, key=lambda x: by_id[x]["full_name"] or "") if warn(pid)]
    roots = layout(entries.get(None, []), -1, None)
    return {
        "roots": roots,
        "groups": has_groups[0],
        "warnings": warnings,
        "rows": last + 1,
        "stats": {"people": len(by_id), "shown": len(visible), "positions": len(sel_pos),
                  "cycle_cuts": cycle_cuts,
                  "no_team": sum(1 for p in people if p.get("team_id") is None)},
    }
