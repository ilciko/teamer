"""E2E su organigramma: conteggi a cascata, linee di riporto, anti-ciclo e filtro report."""


def _team(client, name, parent=None, lead=None):
    from app import db

    client.post("/org/team", data={"name": name, "parent_team_id": parent or "",
                                   "lead_person_id": lead or ""})
    return db.one("SELECT id FROM team WHERE name=?", (name,))["id"]


def _person(client, name, team, manager=None, role="ic"):
    from app import db

    pid = db.execute("INSERT INTO person (full_name, hire_date) VALUES (?, '2024-01-01')", (name,))
    client.post(f"/people/{pid}/assignment", data={
        "team_id": team, "role_type": role, "start_date": "2024-01-01",
        "manager_person_id": manager or ""})
    return pid


def _tre_livelli(client):
    a = _team(client, "Area")
    b = _team(client, "Reparto", parent=a)
    c = _team(client, "Squadra", parent=b)
    _person(client, "Anna Area", a)
    _person(client, "Bruno Reparto", b)
    _person(client, "Carla Squadra", c)
    return a, b, c


def test_org_mostra_persone_a_cascata(client):
    a, b, c = _tre_livelli(client)
    html = client.get("/org").text
    assert "3 persone<" in html                # Area, a cascata
    assert "2 persone<" in html                # Reparto
    assert "1 persona<" in html                # Squadra, nessun sotto-team
    assert 'href="/org/chart"' in html


def test_team_card_totale_a_cascata(client):
    from app import db

    a, b, c = _tre_livelli(client)
    for name, ral in (("Anna Area", 30000), ("Bruno Reparto", 40000), ("Carla Squadra", 50000)):
        pid = db.one("SELECT id FROM person WHERE full_name=?", (name,))["id"]
        db.execute("INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type) "
                   "VALUES (?, '2024-01-01', ?, 0, 'censimento')", (pid, ral))
    bid = db.execute("INSERT INTO hiring_budget (period, year, total_cap) VALUES ('2026', 2026, 0)")
    db.execute("INSERT INTO hiring_position (budget_id, title, team_id, expected_ral) VALUES (?, 'Dev squadra', ?, 33000)",
               (bid, c))
    html = client.get(f"/org/team/{a}").text
    # gruppi in ordine di organigramma, ciascuno coi suoi membri e il subtotale
    assert html.index("Anna Area") < html.index(f'href="/org/team/{b}"><strong>Reparto') < html.index("Bruno Reparto") \
        < html.index(f'href="/org/team/{c}"><strong>Squadra') < html.index("Carla Squadra")
    assert "Subtotale Reparto" in html and "Subtotale Squadra" in html
    assert "Totale Area con sotto-team" in html and "€ 120.000" in html          # Monte RAL complessivo
    assert "Persone con sotto-team · 1 diretta" in html and "diretti € 30.000" in html
    assert "Dev squadra" in html and "<td class=\"muted\">Squadra</td>" in html  # posizioni dei sotto-team
    html_c = client.get(f"/org/team/{c}").text                                     # foglia: come prima
    assert "Subtotale" not in html_c and "con sotto-team" not in html_c and "€ 50.000" in html_c


def test_org_chart_riporti_espliciti_posizioni_e_filtro(client):
    from app import db

    area = _team(client, "Area")
    rep = _team(client, "Reparto", parent=area)
    altro = _team(client, "Altro", parent=area)
    dir_ = _person(client, "Dora Director", area, role="sr")
    db.execute("UPDATE team SET lead_person_id=? WHERE id=?", (dir_, area))
    tl = _person(client, "Lea Lead", rep, manager=dir_, role="tl")
    _person(client, "Ester Esplicita", rep, manager=tl)
    _person(client, "Olga Altro", altro, manager=dir_)
    orfeo = _person(client, "Orfeo Orfano", rep)
    db.execute("UPDATE person_assignment SET manager_person_id=NULL WHERE person_id=?", (orfeo,))
    bid = db.execute("INSERT INTO hiring_budget (period, year, total_cap) VALUES ('2026', 2026, 0)")
    db.execute("INSERT INTO hiring_position (budget_id, title, team_id, role_type) VALUES (?,?,?, 'ic')",
               (bid, "Backend developer", rep))
    html = client.get("/org/chart").text
    assert "diretti" not in html and "totali" not in html     # niente conteggi sul grafico
    assert "Esporta PDF" in html and "Tutti i reparti" in html
    title = html[html.index("<title>"):html.index("</title>")]
    assert "<script" not in title and title.startswith("<title>Linee di riporto - 20")   # nome del PDF
    assert "Orfeo Orfano</a> <span class=\"muted\">(senza responsabile)" in html
    assert 'class="oc-mini pos"' in html and "Backend developer" in html
    assert html.count('class="oc-team"') >= 2

    html = client.get(f"/org/chart?team_id={rep}").text
    assert "Ester Esplicita" in html and "Dora Director" in html and "Olga Altro" not in html
    assert 'class="oc-node ctx"' in html and "Reparti (1)" in html
    html = client.get(f"/org/chart?team_id={rep}&team_id={altro}").text
    assert "Ester Esplicita" in html and "Olga Altro" in html and "Reparti (2)" in html
    assert "Reparto, Altro" in html or "Altro, Reparto" in html
    assert "<title>Linee di riporto - Reparto, Altro - " in html or "<title>Linee di riporto - Altro, Reparto - " in html
    html = client.get("/org").text
    assert "lead: Dora Director" in html and "2 diretti" in html


def test_org_chart_vuoto(client):
    r = client.get("/org/chart")
    assert r.status_code == 200 and "Nessuna persona attiva" in r.text


def test_reports_team_include_sottoteam(client):
    a, b, c = _tre_livelli(client)
    r = client.get(f"/reports?team_id={a}")
    assert r.status_code == 200 and "incl. sotto-team" in r.text
    assert "incl. sotto-team" not in client.get(f"/reports?team_id={c}").text


def test_team_update_rifiuta_ciclo(client):
    from app import db

    a, b, c = _tre_livelli(client)
    client.post(f"/org/team/{a}", data={"name": "Area", "parent_team_id": c})
    assert db.one("SELECT parent_team_id FROM team WHERE id=?", (a,))["parent_team_id"] is None
    # un padre legittimo invece passa
    client.post(f"/org/team/{c}", data={"name": "Squadra", "parent_team_id": a})
    assert db.one("SELECT parent_team_id FROM team WHERE id=?", (c,))["parent_team_id"] == a


def test_team_sposta_su_giu_e_ordine_in_pagina(client):
    from app import db

    area = _team(client, "Area")
    a = _team(client, "Alfa", parent=area)
    b = _team(client, "Beta", parent=area)
    c = _team(client, "Gamma", parent=area)
    assert [r["id"] for r in db.query("SELECT id FROM team WHERE parent_team_id=? ORDER BY sort_order",
                                      (area,))] == [a, b, c]
    r = client.post(f"/org/team/{c}/move", data={"direction": "up"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"/org#team-{c}"
    html = client.get("/org").text
    assert html.index(">Alfa<") < html.index(">Gamma<") < html.index(">Beta<")
    client.post(f"/org/team/{a}/move", data={"direction": "up"})       # già primo: nulla
    client.post(f"/org/team/{area}/move", data={"direction": "down"})  # unico alla radice: nulla
    order = [r["id"] for r in db.query("SELECT id FROM team WHERE parent_team_id=? ORDER BY sort_order", (area,))]
    assert order == [a, c, b]
    assert db.one("SELECT parent_team_id FROM team WHERE id=?", (area,))["parent_team_id"] is None
    # cambiare padre lo mette in coda ai nuovi fratelli
    altro = _team(client, "Altro")
    client.post(f"/org/team/{a}", data={"name": "Alfa", "parent_team_id": altro})
    client.post(f"/org/team/{b}", data={"name": "Beta", "parent_team_id": altro})
    assert [r["id"] for r in db.query("SELECT id FROM team WHERE parent_team_id=? ORDER BY sort_order",
                                      (altro,))] == [a, b]


# ---- riporti derivati da team e ruolo ----

def _mgr(pid):
    from app import db

    return db.one("SELECT manager_person_id FROM person_assignment WHERE person_id=? AND voided=0 "
                  "AND end_date IS NULL", (pid,))["manager_person_id"]


def _struttura(client):
    area = _team(client, "Direzione")
    fac = _team(client, "Factory", parent=area)
    be = _team(client, "Backend", parent=fac)
    d = _person(client, "Dora Director", area, role="sr")
    m = _person(client, "Mario Manager", fac, role="mgr")
    return area, fac, be, d, m


def test_nuova_persona_eredita_il_riporto(client):
    area, fac, be, d, m = _struttura(client)
    ic = _person(client, "Ivo Specialist", be, manager=d)      # il manager passato è ignorato
    assert _mgr(m) == d and _mgr(ic) == m                      # niente TL: si sale al Manager
    tl = _person(client, "Tea Lead", be, role="tl")
    assert _mgr(tl) == m


def test_censimento_con_team_calcola_il_riporto(client):
    from app import db

    area, fac, be, d, m = _struttura(client)
    client.post("/people", data={"full_name": "Nuovo Arrivo", "team_id": be, "role_type": "ic"})
    pid = db.one("SELECT id FROM person WHERE full_name='Nuovo Arrivo'")["id"]
    assert _mgr(pid) == m


def test_nuovo_tl_fa_scattare_la_verifica(client):
    area, fac, be, d, m = _struttura(client)
    ic = _person(client, "Ivo Specialist", be)
    from app import db

    tl = db.execute("INSERT INTO person (full_name) VALUES ('Tea Lead')")
    r = client.post(f"/people/{tl}/assignment", data={"team_id": be, "role_type": "tl",
                                                      "start_date": "2026-03-01"}, follow_redirects=False)
    assert r.headers["location"].startswith("/org/riporti?")
    html = client.get(r.headers["location"]).text
    assert "Ivo Specialist" in html and "Mario Manager" in html and "Tea Lead" in html
    assert 'value="cambiamento" checked' in html and 'value="2026-03-01"' in html
    # cambiamento reale: chiude l'assegnazione dell'IC e ne apre una nuova col TL
    client.post("/org/riporti", data={"pid": ic, "mode": "cambiamento", "date": "2026-03-01",
                                      "next": f"/people/{tl}"})
    assert _mgr(ic) == tl
    rows = db.query("SELECT manager_person_id, end_date FROM person_assignment WHERE person_id=? "
                    "ORDER BY start_date", (ic,))
    assert [(r["manager_person_id"], str(r["end_date"]) if r["end_date"] else None) for r in rows] == \
        [(m, "2026-02-28"), (tl, None)]
    r = client.get("/org/riporti")
    assert "Tutti i riporti corrispondono" in r.text


def test_cambio_lead_del_team_e_correzione(client):
    from app import db

    area, fac, be, d, m = _struttura(client)
    m2 = _person(client, "Marta Manager", fac, role="mgr")
    ic = _person(client, "Ivo Specialist", be)
    assert _mgr(ic) == m                                       # due manager, nessun lead: vince il nome
    r = client.post(f"/org/team/{fac}", data={"name": "Factory", "parent_team_id": area,
                                              "lead_person_id": m2}, follow_redirects=False)
    assert r.headers["location"].startswith("/org/riporti?") and "mode=correzione" in r.headers["location"]
    client.post("/org/riporti", data={"pid": ic, "mode": "correzione", "next": "/org"})
    assert _mgr(ic) == m2                                      # a parità di ruolo vince il lead del team
    assert db.one("SELECT COUNT(*) AS n FROM person_assignment WHERE person_id=?", (ic,))["n"] == 1


def test_correzione_ruolo_ricalcola_e_verifica(client):
    area, fac, be, d, m = _struttura(client)
    a = _person(client, "Anna", be)
    b = _person(client, "Bruno", be)
    assert _mgr(a) == m and _mgr(b) == m
    from app import db

    aid = db.one("SELECT id FROM person_assignment WHERE person_id=?", (b,))["id"]
    r = client.post(f"/people/{b}/assignment/{aid}/update", data={
        "team_id": be, "role_type": "tl", "start_date": "2024-01-01"}, follow_redirects=False)
    assert _mgr(b) == m
    assert r.headers["location"].startswith("/org/riporti?") and "mode=correzione" in r.headers["location"]
    client.post("/org/riporti", data={"pid": a, "mode": "correzione", "next": "/org"})
    assert _mgr(a) == b


def test_scheda_persona_team_e_riporto_in_sola_lettura(client):
    from app import db

    area, fac, be, d, m = _struttura(client)
    ic = _person(client, "Ivo Specialist", be)
    html = client.get(f"/people/{ic}").text
    assert "Riporto diretto" in html and 'name="manager_person_id"' not in html
    assert f'action="/people/{ic}/team"' not in html and f'href="/org/team/{be}">Backend</a>' in html
    client.post(f"/people/{ic}/assignment", data={"team_id": fac, "role_type": "ic", "start_date": "2026-05-01"})
    cur = db.one("SELECT team_id, role_type, manager_person_id FROM person_assignment WHERE person_id=? "
                 "AND end_date IS NULL AND voided=0", (ic,))
    assert (cur["team_id"], cur["role_type"], cur["manager_person_id"]) == (fac, "ic", m)
    db.execute("UPDATE person_assignment SET manager_person_id=? WHERE person_id=? AND end_date IS NULL", (d, ic))
    assert "da verificare" in client.get(f"/people/{ic}").text


def test_elimina_team_solo_se_vuoto(client):
    from app import db

    area = _team(client, "Area")
    vuoto = _team(client, "Ufficio d'Arte", parent=area)
    pieno = _team(client, "Pieno", parent=area)
    storico = _team(client, "Storico", parent=area)
    pos = _team(client, "Con posizione", parent=area)
    _person(client, "Ivo", pieno)
    old = _person(client, "Olga", storico)
    client.post(f"/people/{old}/assignment", data={"team_id": pieno, "role_type": "ic", "start_date": "2025-01-01"})
    bid = db.execute("INSERT INTO hiring_budget (period, year, total_cap) VALUES ('2026', 2026, 0)")
    db.execute("INSERT INTO hiring_position (budget_id, title, team_id) VALUES (?, 'X', ?)", (bid, pos))

    html = client.get("/org").text
    assert 'confirm("Eliminare il team " + "Ufficio d\\u0027Arte" + "?")' in html
    assert "Non eliminabile: 4 sotto-team" in html and "Non eliminabile: 2 persone assegnate" in html
    assert "storico di 1 assegnazione passata" in html and "1 posizione aperta" in html

    for tid in (area, pieno, storico, pos):
        r = client.post(f"/org/team/{tid}/delete", follow_redirects=False)
        assert r.headers["location"] == f"/org?blocked={tid}#team-{tid}"
    assert db.one("SELECT COUNT(*) AS n FROM team")["n"] == 5
    assert "non si può eliminare" in client.get(f"/org?blocked={pieno}").text

    r = client.post(f"/org/team/{vuoto}/delete", follow_redirects=False)
    assert r.headers["location"] == "/org"
    assert db.one("SELECT id FROM team WHERE id=?", (vuoto,)) is None


def test_archivia_team_vuoto_con_storico_e_ripristina(client):
    from app import db

    area = _team(client, "Area")
    deploy = _team(client, "Deploy")                      # in radice, come in produzione
    pieno = _team(client, "Pieno", parent=area)
    p = _person(client, "Olga", deploy)
    client.post(f"/people/{p}/assignment", data={"team_id": pieno, "role_type": "ic", "start_date": "2025-01-01"})

    html = client.get("/org").text
    assert f'action="/org/team/{deploy}/archive"' in html                 # solo storico: si archivia
    assert f'action="/org/team/{pieno}/archive"' not in html              # persone dentro: no
    r = client.post(f"/org/team/{pieno}/archive", follow_redirects=False)
    assert r.headers["location"].startswith(f"/org?blocked={pieno}")
    client.post(f"/org/team/{deploy}/delete")                             # eliminare no: c'è storico
    assert db.one("SELECT id FROM team WHERE id=?", (deploy,))

    client.post(f"/org/team/{deploy}/archive")
    assert db.one("SELECT archived_at FROM team WHERE id=?", (deploy,))["archived_at"]
    html = client.get("/org").text
    assert 'id="archiviati"' in html and f'href="/org/team/{deploy}">Deploy</a>' in html
    assert f'id="team-{deploy}"' not in html                              # fuori dall'albero
    assert ">Deploy</option>" not in client.get(f"/people/{p}").text      # e dai menu
    assert ">Deploy<" not in client.get("/org/chart").text
    assert "<td>Deploy</td>" in client.get(f"/people/{p}").text            # lo storico lo mostra ancora

    client.post(f"/org/team/{deploy}/restore")
    assert db.one("SELECT archived_at FROM team WHERE id=?", (deploy,))["archived_at"] is None
    assert f'id="team-{deploy}"' in client.get("/org").text


def test_org_chart_nasconde_posizioni_aperte(client):
    from app import db

    t = _team(client, "Team")
    _person(client, "Lea Lead", t, role="tl")
    bid = db.execute("INSERT INTO hiring_budget (period, year, total_cap) VALUES ('2026', 2026, 0)")
    db.execute("INSERT INTO hiring_position (budget_id, title, team_id, role_type) VALUES (?, 'Backend dev', ?, 'ic')",
               (bid, t))
    html = client.get("/org/chart").text
    assert "Backend dev" in html and 'href="/org/chart?pos=0"' in html and "Nascondi posizioni aperte" in html
    html = client.get(f"/org/chart?team_id={t}&pos=0").text
    assert "Backend dev" not in html and "Mostra posizioni aperte" in html
    assert f'href="/org/chart?team_id={t}&amp;pos=1"' in html and 'name="pos" value="0"' in html
