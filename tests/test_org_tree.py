from app.services import org_tree as ot


def _t(id, parent=None, lead=None, name=None):
    return {"id": id, "name": name or f"T{id}", "parent_team_id": parent, "lead_person_id": lead}


def _m(team, pid):
    return {"team_id": team, "id": pid, "full_name": f"P{pid}", "role_type": "ic"}


def _p(id, team=None, manager=None, role="ic", name=None):
    return {"id": id, "full_name": name or f"P{id}", "role_type": role, "team_id": team,
            "team_name": f"T{team}" if team else None, "manager_person_id": manager}


def _flat(nodes, out=None):
    out = out if out is not None else {}
    for n in nodes:
        out[n["team"]["id"]] = n
        _flat(n["children"], out)
    return out


# ---- cascata ----

def test_cascata_tre_livelli():
    teams = [_t(1), _t(2, 1), _t(3, 2)]
    members = [_m(1, 10), _m(2, 20), _m(2, 21), _m(3, 30), _m(3, 31), _m(3, 32)]
    f = _flat(ot.build_team_tree(teams, members))
    assert (f[1]["direct"], f[1]["total"]) == (1, 6)
    assert (f[2]["direct"], f[2]["total"]) == (2, 5)
    assert (f[3]["direct"], f[3]["total"]) == (3, 3)
    assert [f[i]["depth"] for i in (1, 2, 3)] == [0, 1, 2]


def test_persona_in_due_team_contata_una_volta():
    teams = [_t(1), _t(2, 1), _t(3, 1)]
    f = _flat(ot.build_team_tree(teams, [_m(2, 7), _m(3, 7)]))
    assert f[2]["direct"] == 1 and f[1]["total"] == 1


def test_lead_non_assegnato_non_conta():
    f = _flat(ot.build_team_tree([_t(1, lead=99)], []))
    assert (f[1]["direct"], f[1]["total"]) == (0, 0)


def test_ciclo_team_non_esplode():
    teams = [_t(9), _t(1, 2), _t(2, 1)]
    tree = ot.build_team_tree(teams, [_m(1, 5), _m(2, 6)])
    f = _flat(tree)
    assert set(f) == {9, 1, 2}
    assert ot.descendant_ids(teams, 1) == {1, 2}


def test_padre_inesistente_e_radice():
    tree = ot.build_team_tree([_t(1, parent=42)], [])
    assert [n["team"]["id"] for n in tree] == [1] and tree[0]["depth"] == 0


def test_team_totals_coerente_con_albero():
    teams = [_t(1), _t(2, 1)]
    members = [_m(1, 1), _m(2, 2)]
    assert ot.team_totals(teams, members) == {1: {"direct": 1, "total": 2}, 2: {"direct": 1, "total": 1}}


def test_descendant_ids_team_sconosciuto():
    assert ot.descendant_ids([_t(1)], 77) == {77}


# ---- linee di riporto ----

ORDER = {"ic": 1, "tl": 2, "mgr": 3, "sr": 4}


def _chart(people, teams=(), positions=(), focus=None):
    return ot.build_chart(people, list(teams), list(positions), ORDER, focus)


def _pos(id, team, role="ic", title=None, hint=None):
    return {"id": id, "title": title or f"Pos{id}", "role_type": role, "team_id": team,
            "status": "pianificata", "manager_hint": hint}


def _ids(items):
    """Persone e posizioni in ordine di visita (nodo, poi figli; colonne in ordine)."""
    out = []
    for it in items:
        if it["kind"] == "node":
            out.append(it["entry"]["id"])
            out += _ids(it["children"])
        else:
            out += [e["id"] if e["kind"] == "person" else ("pos", e["pos"]["id"]) for e in it["members"]]
    return out


def test_solo_riporto_esplicito_niente_lead_implicito():
    teams = [_t(1, lead=1)]
    c = _chart([_p(1, team=1, role="sr"), _p(2, team=1)], teams)
    assert all(it["kind"] == "col" for it in c["roots"])   # 2 non si aggancia al lead: nessun nodo con riporti
    assert [w["person"]["id"] for w in c["warnings"]] == [2]
    assert c["warnings"][0]["problem"] == "missing"


def test_vertice_senza_responsabile_non_e_un_avviso():
    c = _chart([_p(1, role="sr"), _p(2, manager=1)])
    assert c["warnings"] == [] and len(c["roots"]) == 1


def test_diretti_e_totali():
    people = [_p(1, role="sr"), _p(2, manager=1, role="mgr"), _p(3, manager=2, role="tl"),
              _p(4, manager=3), _p(5, manager=3), _p(6, manager=1, role="mgr")]
    root = _chart(people)["roots"][0]
    e = root["entry"]
    assert (e["direct"], e["total"]) == (2, 5)
    mgr = next(it for it in root["children"] if it["kind"] == "node")
    assert (mgr["entry"]["direct"], mgr["entry"]["total"]) == (1, 3)


def test_righe_per_ruolo_saltano_i_livelli_mancanti():
    # director → TL senza manager in mezzo; director → IC diretti
    people = [_p(1, team=1, role="sr"), _p(2, team=2, manager=1, role="tl"), _p(3, team=2, manager=2),
              _p(4, team=3, manager=1)]
    root = _chart(people, [_t(1), _t(2), _t(3)])["roots"][0]
    assert root["skip"] == 0
    by_team = {it["team_id"]: it for it in root["children"]}
    assert by_team[2]["kind"] == "node" and by_team[2]["skip"] == 1     # salta la riga manager
    assert by_team[3]["kind"] == "col" and by_team[3]["skip"] == 2      # salta manager e TL
    assert by_team[2]["children"][0]["skip"] == 0                       # IC sotto il TL: riga successiva


def test_colonna_unica_per_team_ordinata_per_ruolo_e_nome():
    people = [_p(1, team=1, role="mgr"), _p(2, team=1, manager=1, name="Zeta"),
              _p(3, team=1, manager=1, role="tl", name="Beta"), _p(4, team=1, manager=1, name="Alfa"),
              _p(5, team=2, manager=1, name="Altro")]
    root = _chart(people, [_t(1), _t(2)])["roots"][0]
    cols = [it for it in root["children"] if it["kind"] == "col"]
    assert len(cols) == 2
    same = next(c for c in cols if c["team_id"] == 1)
    assert [e["id"] for e in same["members"]] == [3, 4, 2]
    assert same["label"] is None                      # stesso team del padre: niente etichetta
    assert next(c for c in cols if c["team_id"] == 2)["label"] == "T2"


def test_etichetta_team_una_volta_per_gruppo():
    people = [_p(1, team=1, role="sr"), _p(2, team=2, manager=1, role="tl"), _p(3, team=2, manager=1, role="tl"),
              _p(4, team=2, manager=2), _p(5, team=2, manager=3)]
    root = _chart(people, [_t(1), _t(2)])["roots"][0]
    assert root["label"] == "T1"
    assert [it["label"] for it in root["children"]] == ["T2", None]
    assert [it["children"][0]["label"] for it in root["children"]] == [None, None]


def test_responsabile_non_attivo_e_avviso():
    c = _chart([_p(1, role="sr"), _p(2, manager=99)])
    assert c["warnings"][0]["problem"] == "inactive"


def test_ciclo_manager():
    c = _chart([_p(1, manager=3), _p(2, manager=1), _p(3, manager=2)])
    assert c["stats"]["cycle_cuts"] == 1 and len(c["roots"]) == 1
    assert sorted(_ids(c["roots"])) == [1, 2, 3]
    assert c["roots"][0]["entry"]["total"] == 2 and c["warnings"][0]["problem"] == "cycle"


def test_posizioni_aperte_sotto_il_ruolo_piu_vicino():
    people = [_p(1, team=1, role="mgr"), _p(2, team=1, manager=1, role="tl"), _p(3, team=1, manager=2)]
    c = _chart(people, [_t(1)], [_pos(10, 1), _pos(11, 1, role="tl")])
    ids = _ids(c["roots"])
    assert ids.index(("pos", 10)) > ids.index(3)            # IC aperta sotto il TL, dopo le persone
    tl_kids = c["roots"][0]["children"][0]["children"]
    assert ("pos", 10) in _ids(tl_kids)
    assert ("pos", 11) in _ids([it for it in c["roots"][0]["children"] if it["kind"] == "col"])
    assert c["stats"]["positions"] == 2
    assert c["roots"][0]["entry"]["total"] == 2              # le posizioni non contano come persone


def test_posizione_sostituzione_va_al_responsabile_del_sostituito():
    people = [_p(1, team=1, role="mgr"), _p(2, team=1, role="mgr")]
    c = _chart(people, [_t(1)], [_pos(10, 1, hint=2)])
    root2 = next(r for r in c["roots"] if r["kind"] == "node" and r["entry"]["id"] == 2)
    assert ("pos", 10) in _ids(root2["children"])


def test_posizione_senza_aggancio_e_radice():
    c = _chart([], [_t(1)], [_pos(10, 1)])
    assert _ids(c["roots"]) == [("pos", 10)] and c["roots"][0]["skip"] == 3


def test_filtro_reparto_mostra_reparto_e_catena_sopra():
    teams = [_t(1), _t(2, parent=1), _t(3, parent=1), _t(4, parent=2)]
    people = [_p(1, team=1, role="sr"), _p(2, team=2, manager=1, role="mgr"), _p(3, team=3, manager=1, role="mgr"),
              _p(4, team=4, manager=2), _p(5, team=3, manager=3), _p(6, team=1, manager=1)]
    c = _chart(people, teams, [_pos(10, 3, hint=3), _pos(11, 4)], focus=[2])
    assert sorted(i for i in _ids(c["roots"]) if isinstance(i, int)) == [1, 2, 4]
    assert ("pos", 11) in _ids(c["roots"]) and ("pos", 10) not in _ids(c["roots"])
    root = c["roots"][0]
    assert root["entry"]["ctx"] is True and root["entry"]["total"] == 5     # conteggi sull'intero
    assert root["children"][0]["entry"]["ctx"] is False
    assert c["stats"]["shown"] == 3


def test_filtro_piu_reparti_insieme():
    teams = [_t(1), _t(2, parent=1), _t(3, parent=1), _t(4, parent=1)]
    people = [_p(1, team=1, role="sr"), _p(2, team=2, manager=1), _p(3, team=3, manager=1), _p(4, team=4, manager=1)]
    c = _chart(people, teams, focus=[2, 3])
    assert sorted(_ids(c["roots"])) == [1, 2, 3]
    assert _chart(people, teams, focus=[])["stats"]["shown"] == 4      # nessun reparto = tutti


# ---- ordine dei team ----

def _o(id, parent=None, order=0, name=None):
    return {**_t(id, parent, name=name), "sort_order": order}


def test_ordine_tra_fratelli_prima_di_nome():
    teams = [_o(1, name="Zeta", order=0), _o(2, name="Alfa", order=1), _o(3, 1, name="B", order=1),
             _o(4, 1, name="A", order=0)]
    assert ot.team_order(teams) == [1, 4, 3, 2]


def test_ordine_parita_alfabetico():
    assert ot.team_order([_o(1, name="Beta"), _o(2, name="Alfa")]) == [2, 1]


def test_sposta_su_e_giu_tra_fratelli():
    teams = [_o(1), _o(2, 1, 0), _o(3, 1, 1), _o(4, 1, 2)]
    assert ot.move_team(teams, 4, "up") == {2: 0, 4: 1, 3: 2}
    assert ot.move_team(teams, 2, "down") == {3: 0, 2: 1, 4: 2}


def test_sposta_non_esce_dal_padre():
    teams = [_o(1), _o(2, 1, 0), _o(3, 1, 1), _o(9, None, 1)]
    assert ot.move_team(teams, 2, "up") == {}           # primo dei fratelli
    assert ot.move_team(teams, 3, "down") == {}         # ultimo: il team 9 sta a un altro livello
    assert ot.move_team(teams, 77, "up") == {}


def test_sposta_rinumera_ordini_duplicati():
    teams = [_o(1, name="C"), _o(2, name="A"), _o(3, name="B")]   # tutti 0: vale il nome
    assert ot.move_team(teams, 1, "up") == {2: 0, 1: 1, 3: 2}


def test_grafico_segue_ordine_team():
    teams = [_o(1, order=0), _o(2, 1, 1, name="A"), _o(3, 1, 0, name="B")]
    people = [_p(1, team=1, role="sr"), _p(2, team=2, manager=1), _p(3, team=3, manager=1)]
    root = ot.build_chart(people, teams, (), ORDER)["roots"][0]
    assert [it["team_id"] for it in root["children"]] == [3, 2]


# ---- riporto atteso da team e ruolo ----

def _q(id, team, role, name=None, manager=None):
    return {**_p(id, team=team, manager=manager, role=role, name=name)}


def test_riporto_atteso_scala_i_livelli_mancanti():
    teams = [_t(1), _t(2, 1), _t(3, 2)]                       # Direzione > Factory > Backend
    people = [_q(1, 1, "sr"), _q(2, 2, "mgr"), _q(3, 3, "tl"), _q(4, 3, "ic"), _q(5, 2, "ic"), _q(6, 1, "ic")]
    exp = {p["id"]: ot.expected_manager(p, people, teams, ORDER) for p in people}
    assert exp == {1: None, 2: 1, 3: 2, 4: 3, 5: 2, 6: 1}


def test_riporto_atteso_vince_il_ruolo_piu_vicino_poi_il_lead():
    teams = [_t(1, lead=9)]
    people = [_q(9, 1, "mgr", name="Zeno"), _q(8, 1, "mgr", name="Anna"), _q(7, 1, "tl"), _q(6, 1, "ic")]
    assert ot.expected_manager(people[3], people, teams, ORDER) == 7      # TL prima del Manager
    assert ot.expected_manager(people[2], people, teams, ORDER) == 9      # due manager: il lead
    assert ot.expected_manager(people[0], people, teams, ORDER) is None   # nessun ruolo sopra


def test_riporto_atteso_lead_di_un_altro_team():
    teams = [_t(1), _t(2, 1, lead=5)]
    people = [_q(5, 1, "mgr"), _q(6, 2, "ic")]                # il lead del team sta nel team padre
    assert ot.expected_manager(people[1], people, teams, ORDER) == 5


def test_mismatch_solo_chi_non_torna():
    teams = [_t(1), _t(2, 1)]
    people = [_q(1, 1, "sr"), _q(2, 2, "mgr", manager=1), _q(3, 2, "ic", manager=1), _q(4, None, "ic")]
    mm = ot.report_mismatches(people, teams, ORDER)
    assert [(m["person"]["id"], m["current"], m["expected"]) for m in mm] == [(3, 1, 2)]


def test_sotto_il_tl_nessuno_e_responsabile():
    order = {"jr": 0, "ic": 1, "tl": 2, "mgr": 3, "sr": 4}
    teams = [_t(1), _t(2, 1)]
    people = [_q(1, 1, "mgr"), _q(2, 2, "ic"), _q(3, 2, "jr"), _q(4, 2, "tl")]
    assert ot.expected_manager(people[2], people, teams, order) == 4      # Junior → TL, non Specialist
    no_tl = people[:3]
    assert ot.expected_manager(no_tl[2], no_tl, teams, order) == 1        # senza TL si sale al Manager
    assert ot.expected_manager(no_tl[1], no_tl, teams, order) == 1


def test_ruoli_sotto_il_tl_sulla_stessa_riga():
    order = {"jr": 0, "ic": 1, "tl": 2, "mgr": 3, "sr": 4}
    assert ot.role_rows(order) == {"sr": 0, "mgr": 1, "tl": 2, "ic": 3, "jr": 3}
    teams = [_t(1), _t(2), _t(3)]
    people = [_q(1, 1, "tl"), _q(2, 2, "jr", manager=1, name="Alfa"), _q(3, 3, "ic", manager=1),
              _q(4, 3, "jr", manager=1, name="Aldo"), _q(5, 3, "ic", manager=1, name="Zoe")]
    root = ot.build_chart(people, teams, (), order)["roots"][0]
    cols = {it["team_id"]: it for it in root["children"]}
    assert cols[2]["skip"] == cols[3]["skip"] == 0                       # solo Junior o misto: stessa altezza
    assert [e["id"] for e in cols[3]["members"]] == [3, 5, 4]           # Specialist prima, poi Junior


def test_raggruppamento_team_intermedio_senza_responsabile():
    # Operation > PMO > (PM Lead, PM Tech): PMO vuoto, i TL riportano al manager di Operation
    teams = [_t(1, name="Operation"), _t(2, 1, name="PMO"), _t(3, 2, name="PM Lead"), _t(4, 2, name="PM Tech"),
             _t(5, 1, name="Altro")]
    people = [_q(1, 1, "mgr", manager=None), _q(2, 3, "tl", manager=1), _q(3, 4, "tl", manager=1),
              _q(4, 3, "ic", manager=2), _q(5, 5, "ic", manager=1)]
    c = ot.build_chart(people, teams, (), ORDER)
    assert c["groups"] is True
    kids = c["roots"][0]["children"]
    grp = next(k for k in kids if k["kind"] == "group")
    assert grp["label"] == "PMO"
    assert sorted(ch["team_id"] for ch in grp["children"]) == [3, 4]
    assert [ch["label"] for ch in grp["children"]] == ["PM Lead", "PM Tech"]
    # TL subito sotto il manager: non c'è una riga libera per PMO, che prende la riga TL e li fa scendere
    assert (grp["top"], grp["skip"], grp["children"][0]["skip"]) == (2, 0, 0)
    assert any(k["kind"] == "col" and k["team_id"] == 5 for k in kids)       # figlio diretto: niente gruppo


def test_raggruppamento_intermedi_in_fila_e_membri_del_team():
    teams = [_t(1, name="Direzione"), _t(2, 1, name="Operation"), _t(3, 2, name="PMO"), _t(4, 3, name="PM Lead")]
    people = [_q(1, 1, "sr"), _q(2, 4, "tl", manager=1), _q(3, 3, "ic", manager=1)]
    c = ot.build_chart(people, teams, (), ORDER)
    grps = [k for k in c["roots"][0]["children"] if k["kind"] == "group"]
    labels = sorted(g["label"] for g in grps)
    # l'IC in PMO entra nel raggruppamento "Operation › PMO" insieme al ramo PM Lead
    assert labels == ["Operation › PMO"]
    assert sorted(ch["team_id"] for ch in grps[0]["children"]) == [3, 4]


def test_senza_intermedi_niente_raggruppamenti():
    teams = [_t(1), _t(2, 1)]
    people = [_q(1, 1, "mgr"), _q(2, 2, "ic", manager=1)]
    assert ot.build_chart(people, teams, (), ORDER)["groups"] is False


def test_raggruppamento_nella_riga_del_manager_mancante():
    # Director → (PMO senza manager) → TL: PMO sta nella riga manager, i TL restano nella loro
    teams = [_t(1, name="Direzione"), _t(2, 1, name="PMO"), _t(3, 2, name="PM Lead"), _t(4, 2, name="PM Tech")]
    people = [_q(1, 1, "sr"), _q(2, 3, "tl", manager=1), _q(3, 4, "tl", manager=1), _q(4, 3, "ic", manager=2)]
    root = ot.build_chart(people, teams, (), ORDER)["roots"][0]
    grp = root["children"][0]
    assert grp["kind"] == "group" and (grp["top"], grp["skip"]) == (1, 0)
    assert [(ch["top"], ch["skip"]) for ch in grp["children"]] == [(2, 0), (2, 0)]


def test_raggruppamento_mostra_il_coordinatore_dalla_scheda_team():
    teams = [_t(1, name="Direzione"), _t(2, 1, name="PMO", lead=9), _t(3, 2, name="PM Lead"), _t(4, 2, name="PM Tech")]
    people = [_q(1, 1, "sr"), _q(2, 3, "tl", manager=1), _q(3, 4, "tl", manager=1),
              _q(9, 1, "ic", manager=1, name="Giada Fittizia")]
    grp = next(k for k in ot.build_chart(people, teams, (), ORDER)["roots"][0]["children"] if k["kind"] == "group")
    assert grp["label"] == "PMO" and grp["coordinator"] == "Giada Fittizia"
    teams[1]["lead_person_id"] = 77                                       # non attivo: niente coordinatore
    grp = next(k for k in ot.build_chart(people, teams, (), ORDER)["roots"][0]["children"] if k["kind"] == "group")
    assert grp["coordinator"] is None
