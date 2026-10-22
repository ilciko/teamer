"""Simulazioni di riorganizzazione: stato simulato puro (services.reorg) ed e2e del flusso."""
from app.services import reorg

ORDER = {"ic": 1, "tl": 2, "mgr": 3, "sr": 4}


def _t(id, parent=None, lead=None, name=None, order=0):
    return {"id": id, "name": name or f"T{id}", "parent_team_id": parent, "lead_person_id": lead, "sort_order": order}


def _p(id, team, role="ic", manager=None, name=None):
    return {"id": id, "full_name": name or f"P{id}", "team_id": team, "role_type": role, "manager_person_id": manager}


def _base():
    teams = [_t(1, name="Direzione"), _t(2, 1, name="Factory")]
    people = [_p(1, 1, "sr"), _p(2, 2, "mgr", 1), _p(3, 2, "ic", 2), _p(4, 2, "ic", 2)]
    return teams, people


def _sim(team_rows=(), moves=(), positions=(), real_positions=()):
    teams, people = _base()
    return reorg.simulate(teams, people, list(real_positions), list(team_rows), list(moves), list(positions), ORDER)


def test_team_nuovo_e_spostamento_ricalcola_i_riporti():
    rows = [{"id": 7, "team_id": None, "name": "Team X", "parent_ref": 2, "lead_person_id": None,
             "sort_order": 0, "removed": 0}]
    moves = [{"person_id": 3, "team_ref": -7, "role_type": "tl"}, {"person_id": 4, "team_ref": -7, "role_type": "ic"}]
    s = _sim(rows, moves)
    x = next(t for t in s["teams"] if t["id"] == -7)
    assert x["parent_team_id"] == 2 and x["new"] is True
    by = {p["id"]: p for p in s["people"]}
    assert (by[3]["team_id"], by[3]["role_type"], by[3]["manager_person_id"]) == (-7, "tl", 2)
    assert by[4]["manager_person_id"] == 3                      # il nuovo TL diventa il riporto
    teams, people = _base()
    assert people[2]["team_id"] == 2                            # la realtà non si tocca


def test_override_team_reale_e_rimozione():
    rows = [{"id": 1, "team_id": 2, "name": "Fabbrica", "parent_ref": 1, "lead_person_id": 2, "sort_order": 0,
             "removed": 0},
            {"id": 2, "team_id": 99, "name": "Sparito", "parent_ref": None, "lead_person_id": None, "sort_order": 0,
             "removed": 0}]
    s = _sim(rows)
    assert {t["id"]: t["name"] for t in s["teams"]} == {1: "Direzione", 2: "Fabbrica"}   # override di team sparito ignorato
    rows = [{"id": 1, "team_id": 2, "name": "Factory", "parent_ref": 1, "lead_person_id": None, "sort_order": 0,
             "removed": 1}]
    s = _sim(rows)
    assert [t["id"] for t in s["teams"]] == [1]
    assert {p["id"]: p["team_id"] for p in s["people"]}[3] is None   # chi resta in un team tolto: senza team


def test_spostamento_verso_team_inesistente_ignorato_e_posizioni():
    s = _sim(moves=[{"person_id": 3, "team_ref": -42, "role_type": "tl"}],
             positions=[{"id": 5, "title": "Dev", "team_ref": 2, "role_type": "ic"}],
             real_positions=[{"id": 9, "title": "Vera", "team_id": 77, "role_type": "ic", "manager_hint": None}])
    by = {p["id"]: p for p in s["people"]}
    assert (by[3]["team_id"], by[3]["role_type"]) == (2, "ic")
    pos = {p["id"]: p for p in s["positions"]}
    assert pos[-5]["hypothetical"] and pos[-5]["team_id"] == 2 and pos[9]["team_id"] is None


def test_diff_marks_e_organico():
    teams, people = _base()
    real = {"teams": teams, "people": people, "positions": []}
    rows = [{"id": 7, "team_id": None, "name": "Team X", "parent_ref": 2, "lead_person_id": None,
             "sort_order": 0, "removed": 0}]
    sim = _sim(rows, [{"person_id": 3, "team_ref": -7, "role_type": "tl"},
                      {"person_id": 4, "team_ref": -7, "role_type": "ic"}],
               [{"id": 1, "title": "Dev", "team_ref": -7, "role_type": "ic"}])
    d = {r["person"]["id"]: r for r in reorg.diff(real, sim)}
    assert d[3]["changes"] == {"team", "role"} and d[4]["changes"] == {"team", "manager"}
    assert d[4]["a"]["manager"] == "P2" and d[4]["b"]["manager"] == "P3" and d[4]["b"]["team"] == "Team X"
    assert reorg.marks(real, sim) == {3: "team", 4: "team"}
    hc = {h["name"]: h for h in reorg.headcount(real, sim)}
    assert (hc["Factory"]["a"], hc["Factory"]["b"], hc["Factory"]["plus_b"]) == (3, 1, -2)
    assert (hc["Team X"]["a"], hc["Team X"]["b"], hc["Team X"]["only"], hc["Team X"]["pos_b"]) == (None, 2, "b", 1)
    assert (hc["Team X"]["plus_a"], hc["Team X"]["plus_b"]) == (0, 3)        # 2 persone + 1 posizione vs 0
    tot = reorg.headcount_totals(reorg.headcount(real, sim))
    assert tot == {"a": 4, "plus_a": 0, "b": 4, "plus_b": 1}


def test_team_nuovi_con_lo_stesso_nome_si_confrontano():
    rows = [{"id": 7, "team_id": None, "name": "Team X", "parent_ref": 2, "lead_person_id": None,
             "sort_order": 0, "removed": 0}]
    rows2 = [{**rows[0], "id": 8}]
    mv = [{"person_id": 4, "team_ref": -7, "role_type": "ic"}]
    a = _sim(rows, mv)
    b = _sim(rows2, [{**mv[0], "team_ref": -8}])
    assert reorg.diff(a, b) == []


# ---- e2e ----

def _setup(client):
    from app import db

    def team(name, parent=None):
        client.post("/org/team", data={"name": name, "parent_team_id": parent or "", "lead_person_id": ""})
        return db.one("SELECT id FROM team WHERE name=?", (name,))["id"]

    def person(name, team_id, role="ic"):
        pid = db.execute("INSERT INTO person (full_name, hire_date) VALUES (?, '2024-01-01')", (name,))
        client.post(f"/people/{pid}/assignment", data={"team_id": team_id, "role_type": role,
                                                       "start_date": "2024-01-01"})
        return pid

    d_t = team("Direzione")
    f_t = team("Factory", d_t)
    d = person("Dora", d_t, "sr")
    m = person("Mario", f_t, "mgr")
    a = person("Anna", f_t)
    b = person("Bruno", f_t)
    return d_t, f_t, d, m, a, b


def _cur(pid):
    from app import db

    return db.one("SELECT team_id, role_type, manager_person_id, start_date FROM person_assignment "
                  "WHERE person_id=? AND voided=0 AND end_date IS NULL", (pid,))


def test_simulazione_flusso_completo(client):
    from app import db

    d_t, f_t, d, m, a, b = _setup(client)
    r = client.post("/org/sim", data={"name": "Team X"}, follow_redirects=False)
    sid = int(r.headers["location"].rsplit("/", 1)[1])
    client.post(f"/org/sim/{sid}/team", data={"name": "Team X", "parent_ref": f_t, "lead_person_id": ""})
    x = -db.one("SELECT id FROM reorg_team WHERE scenario_id=?", (sid,))["id"]
    client.post(f"/org/sim/{sid}/moves", data={
        f"team_{a}": x, f"role_{a}": "tl", f"team_{b}": x, f"role_{b}": "ic",
        f"team_{d}": d_t, f"role_{d}": "sr", f"team_{m}": f_t, f"role_{m}": "mgr"})
    assert db.one("SELECT COUNT(*) AS n FROM reorg_move WHERE scenario_id=?", (sid,))["n"] == 2   # solo chi cambia
    client.post(f"/org/sim/{sid}/position", data={"title": "Backend dev", "team_ref": x, "role_type": "ic"})
    assert _cur(a)["team_id"] == f_t                                   # la realtà non cambia

    html = client.get(f"/org/sim/{sid}").text
    assert "Team X" in html and "mk-team" in html and "Backend dev" in html and "oc-team new" in html
    html = client.get(f"/org/sim/compare?a=0&b={sid}").text
    assert "Differenze persona per persona" in html and "solo in B" in html and "Anna" in html
    assert "A (4)" in html and 'B (4)' in html and "Δ" not in html.split("Organico per team")[1].split("</table>")[0]

    # variante: duplicata con i riferimenti al team nuovo rimappati
    client.post(f"/org/sim/{sid}/duplicate")
    sid2 = db.one("SELECT MAX(id) AS n FROM reorg_scenario")["n"]
    x2 = -db.one("SELECT id FROM reorg_team WHERE scenario_id=?", (sid2,))["id"]
    assert x2 != x and db.one("SELECT team_ref FROM reorg_move WHERE scenario_id=? AND person_id=?",
                              (sid2, a))["team_ref"] == x2
    assert "Nessuna differenza" in client.get(f"/org/sim/compare?a={sid}&b={sid2}").text

    # approvata: bloccata; applicata dalla data
    client.post(f"/org/sim/{sid}/status", data={"action": "approva"})
    client.post(f"/org/sim/{sid}/team", data={"name": "Ignorato"})
    assert db.one("SELECT COUNT(*) AS n FROM reorg_team WHERE scenario_id=?", (sid,))["n"] == 1
    r = client.post(f"/org/sim/{sid}/apply", data={"effective_date": "2026-11-01"}, follow_redirects=False)
    assert r.status_code == 302
    new_team = db.one("SELECT id, parent_team_id FROM team WHERE name='Team X'")
    assert new_team["parent_team_id"] == f_t
    ca, cb = _cur(a), _cur(b)
    assert (ca["team_id"], ca["role_type"], str(ca["start_date"])) == (new_team["id"], "tl", "2026-11-01")
    assert cb["team_id"] == new_team["id"] and cb["manager_person_id"] == a and ca["manager_person_id"] == m
    old = db.one("SELECT end_date FROM person_assignment WHERE person_id=? AND team_id=?", (a, f_t))
    assert str(old["end_date"]) == "2026-10-31"                        # storico conservato
    assert db.one("SELECT status FROM reorg_scenario WHERE id=?", (sid,))["status"] == "applicata"
    client.post(f"/org/sim/{sid}/delete")
    assert db.one("SELECT id FROM reorg_scenario WHERE id=?", (sid,)) is not None   # l'applicata resta


def test_simulazione_togli_team_solo_se_vuoto(client):
    from app import db

    d_t, f_t, d, m, a, b = _setup(client)
    sid = db.execute("INSERT INTO reorg_scenario (name) VALUES ('Prova')")
    r = client.post(f"/org/sim/{sid}/team/{f_t}/remove", follow_redirects=False)
    assert r.headers["location"].endswith("?err=team_busy")
    client.post(f"/org/sim/{sid}/team", data={"name": "Vuoto", "parent_ref": d_t})
    v = -db.one("SELECT id FROM reorg_team WHERE scenario_id=?", (sid,))["id"]
    client.post(f"/org/sim/{sid}/team/{v}/remove")
    assert db.one("SELECT COUNT(*) AS n FROM reorg_team WHERE scenario_id=?", (sid,))["n"] == 0
    # rinomina un team reale e ripristina
    client.post(f"/org/sim/{sid}/team/{f_t}/update", data={"name": "Fabbrica", "parent_ref": d_t, "lead_person_id": ""})
    assert "Fabbrica" in client.get(f"/org/sim/{sid}").text
    assert db.one("SELECT name FROM team WHERE id=?", (f_t,))["name"] == "Factory"
    client.post(f"/org/sim/{sid}/team/{f_t}/restore")
    assert db.one("SELECT COUNT(*) AS n FROM reorg_team WHERE scenario_id=?", (sid,))["n"] == 0


def test_posizione_del_budget_spostata():
    teams, people = _base()
    real_pos = [{"id": 9, "title": "Dev", "team_id": 2, "role_type": "ic", "manager_hint": None}]
    rows = [{"id": 7, "team_id": None, "name": "Team X", "parent_ref": 2, "lead_person_id": None,
             "sort_order": 0, "removed": 0}]
    real = reorg.simulate(teams, people, real_pos, [], [], [], ORDER)
    sim = reorg.simulate(teams, people, real_pos, rows, [], [], ORDER,
                         [{"position_id": 9, "team_ref": -7, "role_type": "tl"},
                          {"position_id": 77, "team_ref": -7, "role_type": "ic"}])   # posizione sparita: ignorata
    pos = {p["id"]: p for p in sim["positions"]}
    assert (pos[9]["team_id"], pos[9]["role_type"]) == (-7, "tl")
    d = reorg.position_diff(real, sim)
    assert len(d) == 1 and d[0]["changes"] == {"team", "role"} and d[0]["b"]["team"] == "Team X"
    assert reorg.marks(real, sim) == {"pos9": "team"}
    assert real_pos[0]["team_id"] == 2


def test_simulazione_sposta_posizione_in_budget_e_applica(client):
    from app import db

    d_t, f_t, d, m, a, b = _setup(client)
    bid = db.execute("INSERT INTO hiring_budget (period, year, total_cap) VALUES ('Assunzioni 2026', 2026, 0)")
    pos = db.execute("INSERT INTO hiring_position (budget_id, title, team_id, role_type, expected_ral) "
                     "VALUES (?, 'Backend dev', ?, 'ic', 35000)", (bid, f_t))
    sid = db.execute("INSERT INTO reorg_scenario (name) VALUES ('Prova')")
    client.post(f"/org/sim/{sid}/team", data={"name": "Team X", "parent_ref": f_t})
    x = -db.one("SELECT id FROM reorg_team WHERE scenario_id=?", (sid,))["id"]
    html = client.get(f"/org/sim/{sid}").text
    assert 'id="budget"' in html and "Assunzioni 2026" in html and f'name="pteam_{pos}"' in html

    client.post(f"/org/sim/{sid}/position-moves", data={f"pteam_{pos}": x, f"prole_{pos}": "ic"})
    assert db.one("SELECT team_ref FROM reorg_position_move WHERE scenario_id=?", (sid,))["team_ref"] == x
    assert db.one("SELECT team_id FROM hiring_position WHERE id=?", (pos,))["team_id"] == f_t   # realtà intatta
    html = client.get(f"/org/sim/compare?a=0&b={sid}").text
    assert "Posizioni spostate" in html and "Backend dev" in html
    # riportarla com'era toglie la riga
    client.post(f"/org/sim/{sid}/position-moves", data={f"pteam_{pos}": f_t, f"prole_{pos}": "ic"})
    assert db.one("SELECT COUNT(*) AS n FROM reorg_position_move WHERE scenario_id=?", (sid,))["n"] == 0
    client.post(f"/org/sim/{sid}/position-moves", data={f"pteam_{pos}": x, f"prole_{pos}": "tl"})

    client.post(f"/org/sim/{sid}/duplicate")
    sid2 = db.one("SELECT MAX(id) AS n FROM reorg_scenario")["n"]
    x2 = -db.one("SELECT id FROM reorg_team WHERE scenario_id=?", (sid2,))["id"]
    assert db.one("SELECT team_ref FROM reorg_position_move WHERE scenario_id=?", (sid2,))["team_ref"] == x2

    client.post(f"/org/sim/{sid}/status", data={"action": "approva"})
    client.post(f"/org/sim/{sid}/apply", data={"effective_date": "2026-11-01"})
    new_team = db.one("SELECT id FROM team WHERE name='Team X'")["id"]
    hp = db.one("SELECT team_id, role_type, expected_ral FROM hiring_position WHERE id=?", (pos,))
    assert (hp["team_id"], hp["role_type"], hp["expected_ral"]) == (new_team, "tl", 35000)
    # eliminare il budget porta via anche gli spostamenti simulati della sua posizione
    db.execute("DELETE FROM hiring_position WHERE budget_id=?", (bid,))
    assert db.one("SELECT COUNT(*) AS n FROM reorg_position_move")["n"] == 0


def test_posizione_nascosta_in_simulazione():
    teams, people = _base()
    real_pos = [{"id": 9, "title": "Dev", "team_id": 2, "role_type": "ic", "manager_hint": None}]
    real = reorg.simulate(teams, people, real_pos, [], [], [], ORDER)
    sim = reorg.simulate(teams, people, real_pos, [], [], [], ORDER,
                         [{"position_id": 9, "team_ref": 2, "role_type": "ic", "hidden": 1}])
    assert sim["positions"] == []
    d = reorg.position_diff(real, sim)
    assert len(d) == 1 and d[0]["changes"] == {"hidden"} and d[0]["b"] is None and d[0]["a"]["team"] == "Factory"
    assert reorg.marks(real, sim) == {}
    assert reorg.position_diff(sim, real)[0]["a"] is None                       # nascosta in A
    hc = {h["name"]: h for h in reorg.headcount(real, sim)}
    assert (hc["Factory"]["pos_a"], hc["Factory"]["pos_b"]) == (1, 0)


def test_nascondi_posizione_e2e(client):
    from app import db

    d_t, f_t, d, m, a, b = _setup(client)
    bid = db.execute("INSERT INTO hiring_budget (period, year, total_cap) VALUES ('2026', 2026, 0)")
    pos = db.execute("INSERT INTO hiring_position (budget_id, title, team_id, role_type) "
                     "VALUES (?, 'Backend dev', ?, 'ic')", (bid, f_t))
    sid = db.execute("INSERT INTO reorg_scenario (name) VALUES ('Prova')")
    client.post(f"/org/sim/{sid}/position-moves", data={f"pteam_{pos}": f_t, f"prole_{pos}": "ic",
                                                        f"phide_{pos}": "1"})
    assert db.one("SELECT hidden FROM reorg_position_move WHERE scenario_id=?", (sid,))["hidden"] == 1
    html = client.get(f"/org/sim/{sid}").text
    assert "row-hidden" in html and 'oc-mini pos' not in html.split('class="card oc-wrap"')[1].split("</ul></div>")[0]
    assert "nascosta" in client.get(f"/org/sim/compare?a=0&b={sid}").text
    client.post(f"/org/sim/{sid}/status", data={"action": "approva"})
    client.post(f"/org/sim/{sid}/apply", data={"effective_date": "2026-11-01"})
    hp = db.one("SELECT team_id, status FROM hiring_position WHERE id=?", (pos,))
    assert (hp["team_id"], hp["status"]) == (f_t, "pianificata")                  # nel budget resta com'è
    # togliere "nascosta" senza altri cambi cancella la riga
    sid2 = db.execute("INSERT INTO reorg_scenario (name) VALUES ('Prova 2')")
    client.post(f"/org/sim/{sid2}/position-moves", data={f"pteam_{pos}": f_t, f"prole_{pos}": "ic", f"phide_{pos}": "1"})
    client.post(f"/org/sim/{sid2}/position-moves", data={f"pteam_{pos}": f_t, f"prole_{pos}": "ic"})
    assert db.one("SELECT COUNT(*) AS n FROM reorg_position_move WHERE scenario_id=?", (sid2,))["n"] == 0


def test_simulazione_export_pdf_grafico_e_lista_cambi(client):
    from app import db

    d_t, f_t, d, m, a, b = _setup(client)
    sid = db.execute("INSERT INTO reorg_scenario (name) VALUES ('Prova PDF')")
    client.post(f"/org/sim/{sid}/team", data={"name": "Team X", "parent_ref": f_t})
    client.post(f"/org/sim/{sid}/team/{f_t}/update", data={"name": "Fabbrica", "parent_ref": d_t, "lead_person_id": m})
    x = -db.one("SELECT id FROM reorg_team WHERE scenario_id=? AND team_id IS NULL", (sid,))["id"]
    client.post(f"/org/sim/{sid}/moves", data={f"team_{a}": x, f"role_{a}": "ic"})
    html = client.get(f"/org/sim/{sid}").text
    assert "Esporta PDF" in html and "oc-print.js" in html and 'class="card oc-wrap" data-print' in html
    lista = html.split('class="print-only print-break"')[1]
    assert "Cambi della simulazione" in lista and "<strong>Team X</strong></td><td>nuovo</td><td>sotto Fabbrica" in lista
    assert "rinominato da Factory" in lista and "responsabile — → Mario" in lista
    assert "<strong>Anna</strong>" in lista
    assert "<title>Simulazione Prova PDF - 20" in html



def test_persona_che_esce_e_figura_interna():
    teams, people = _base()
    real = reorg.simulate(teams, people, [], [], [], [], ORDER)
    sim = reorg.simulate(teams, people, [], [], [{"person_id": 2, "team_ref": 2, "role_type": "mgr", "hidden": 1}],
                         [{"id": 4, "title": "Lucia Interna", "team_ref": 2, "role_type": "mgr", "internal": 1}], ORDER)
    by = {p["id"]: p for p in sim["people"]}
    assert 2 not in by and by[3]["manager_person_id"] == 1                  # senza il manager si sale al director
    d = {r["person"]["id"]: r for r in reorg.diff(real, sim)}
    assert d[2]["changes"] == {"exit"} and d[2]["b"] is None
    assert reorg.marks(sim, real)[2] == "exit"                               # nel grafico di A è segnata
    assert 2 not in reorg.marks(real, sim)
    pos = sim["positions"][0]
    assert pos["internal"] is True and pos["hypothetical"] is True and pos["title"] == "Lucia Interna"
    hc = {h["name"]: h for h in reorg.headcount(real, sim)}
    assert (hc["Factory"]["a"], hc["Factory"]["b"], hc["Factory"]["plus_b"]) == (3, 2, 0)   # -1 persona +1 interna


def test_uscita_e_interna_e2e(client):
    from app import db

    d_t, f_t, d, m, a, b = _setup(client)
    sid = db.execute("INSERT INTO reorg_scenario (name) VALUES ('Prova')")
    client.post(f"/org/sim/{sid}/moves", data={f"team_{b}": f_t, f"role_{b}": "ic", f"hide_{b}": "1"})
    assert db.one("SELECT hidden FROM reorg_move WHERE scenario_id=? AND person_id=?", (sid, b))["hidden"] == 1
    html = client.get(f"/org/sim/{sid}").text
    assert "row-hidden" in html and f'name="hide_{b}" value="1" checked' in html   # resta in tabella
    cmp = client.get(f"/org/sim/compare?a=0&b={sid}").text
    assert "mk-exit" in cmp and "esce" in cmp
    # figura interna: aggiunta, poi corretta in place
    client.post(f"/org/sim/{sid}/position", data={"title": "Lucia", "team_ref": f_t, "role_type": "ic", "internal": "1"})
    pid = db.one("SELECT id FROM reorg_position WHERE scenario_id=?", (sid,))["id"]
    html = client.get(f"/org/sim/{sid}").text
    assert 'class="oc-mini internal mk-team"' in html                     # figura interna = cambia team
    client.post(f"/org/sim/{sid}/position/{pid}/update", data={"title": "Giada Fittizia", "team_ref": d_t,
                                                               "role_type": "tl"})
    row = db.one("SELECT title, team_ref, role_type, internal FROM reorg_position WHERE id=?", (pid,))
    assert (row["title"], row["team_ref"], row["role_type"], row["internal"]) == ("Giada Fittizia", d_t, "tl", 0)
    # rientro: togliere "esce" senza altri cambi cancella la riga
    client.post(f"/org/sim/{sid}/moves", data={f"team_{b}": f_t, f"role_{b}": "ic"})
    assert db.one("SELECT COUNT(*) AS n FROM reorg_move WHERE scenario_id=?", (sid,))["n"] == 0
    # applicando, chi esce resta nella realtà
    client.post(f"/org/sim/{sid}/moves", data={f"team_{b}": f_t, f"role_{b}": "ic", f"hide_{b}": "1"})
    client.post(f"/org/sim/{sid}/status", data={"action": "approva"})
    client.post(f"/org/sim/{sid}/apply", data={"effective_date": "2026-11-01"})
    assert _cur(b)["team_id"] == f_t
    assert db.one("SELECT status FROM person WHERE id=?", (b,))["status"] == "attivo"
