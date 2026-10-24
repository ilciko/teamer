"""Listino: costo giornaliero di vendita per codice di listino, team e ruolo.

Dalla 0.41 codici e parametri sono aziendali (Azienda → Listino, di HR): qui tutti leggono gli
stessi numeri. Il director imposta il codice e la produttività delle sue persone; HR consulta.
Filtri cumulabili: codice, team, ruolo e, per HR, director.
"""
from fastapi import APIRouter, HTTPException, Request

from app import db
from app.routers import hrview
from app.services import cost, listino

router = APIRouter()


def _templates():
    from app.main import templates

    return templates


def _saved_params() -> dict[str, str]:
    return {k: db.get_meta(meta_key, "") for k, meta_key in listino.META_KEYS.items()}


def _profiles() -> list:
    return db.query("SELECT * FROM listino_profile WHERE active=1 ORDER BY sort_order, code")


def _rows() -> list[dict]:
    """Persone attive con assegnazione corrente, codice, part-time, RAL, benefit a costo e director."""
    rows = db.query(
        """SELECT p.id, p.full_name, pa.id AS assignment_id, pa.role_type, t.name AS team_name, t.id AS team_id,
                  COALESCE(t.owner_user_id, p.owner_user_id) AS director_id,
                  pa.listino_profile_id, lp.code AS listino_code, lp.description AS listino_desc,
                  lp.active AS listino_active, lp.day_rate AS listino_rate,
                  COALESCE(e.part_time_pct, 100) AS part_time_pct,
                  pp.formazione_pct AS ov_formazione_pct, pp.interne_pct AS ov_interne_pct,
                  pp.saturazione_pct AS ov_saturazione_pct,
                  (SELECT r.amount FROM ral_event r WHERE r.person_id=p.id AND r.voided=0
                    ORDER BY r.effective_date DESC, r.id DESC LIMIT 1) AS ral
           FROM person p
           LEFT JOIN person_assignment pa ON pa.person_id=p.id AND pa.voided=0 AND pa.end_date IS NULL
           LEFT JOIN team t ON t.id=pa.team_id
           LEFT JOIN listino_profile lp ON lp.id=pa.listino_profile_id
           LEFT JOIN employment e ON e.person_id=p.id AND e.voided=0 AND e.end_date IS NULL
           LEFT JOIN listino_person_param pp ON pp.person_id=p.id
           WHERE p.status='attivo'
           ORDER BY lp.sort_order, lp.code, t.name, p.full_name"""
    )
    out = []
    for r in rows:
        d = dict(r)
        d["benefit"] = cost.benefit_cost(cost.active_benefits(d["id"]))
        d["override"] = {k: d[f"ov_{k}"] for k in listino.PROD_KEYS}
        out.append(d)
    return out


def _sorted(groups: list[dict]) -> list[dict]:
    return sorted(groups, key=lambda g: (g["key"] is None, str(g["key"] or "")))


def _filters(request) -> dict:
    q = request.query_params
    ints = lambda name: {int(v) for v in q.getlist(name) if str(v).isdigit()}
    return {"codice": set(q.getlist("codice")), "team": ints("team"), "ruolo": set(q.getlist("ruolo"))}


def _compute(ctx: dict, flt: dict) -> dict:
    """Costi con i parametri aziendali salvati; i filtri restringono platea e aggregati."""
    p = listino.parse_params({}, _saved_params())
    g = listino.giorni(p)
    platea, senza_codice, senza_assegnazione = [], [], []
    for r in _rows():
        if not hrview.keep(ctx, r["director_id"]):
            continue
        if flt["team"] and r["team_id"] not in flt["team"]:
            continue
        if flt["ruolo"] and r["role_type"] not in flt["ruolo"]:
            continue
        if flt["codice"] and r["listino_code"] not in flt["codice"]:
            continue
        r["director"] = ctx["directors"].get(r["director_id"])
        if r["assignment_id"] is None:
            senza_assegnazione.append(r)
        elif r["listino_profile_id"] is None:
            senza_codice.append(r)
        else:
            r.update(listino.costo_persona(r["ral"], r["benefit"], r["part_time_pct"], p, g, r["override"]))
            r["scost"] = listino.scostamento(r["listino_rate"], r["costo_gg"])
            platea.append(r)
    per_codice = listino.aggregate(platea, "listino_code", "listino_desc", carry=("listino_rate",))
    for c in per_codice:
        c["scost"] = listino.scostamento(c["listino_rate"], c["blended"])
        c["max_sopra"] = (c["listino_rate"] is not None and c["max"] is not None
                          and c["max"] > c["listino_rate"])
    totale = listino.aggregate(platea, "_tutti")
    return {
        "p": p, "g": g, "flt": flt, "filtro_attivo": any(flt.values()) or bool(ctx["sel"]),
        "platea": platea, "senza_codice": senza_codice, "senza_assegnazione": senza_assegnazione,
        "escluse": sum(1 for r in platea if r["motivo"] == "ral"),
        "per_codice": per_codice,
        "per_team": _sorted(listino.aggregate(platea, "team_name")),
        "totale": totale[0] if totale else None,
    }


@router.get("/comp/listino")
def listino_page(request: Request):
    ctx = hrview.context(request)
    flt = _filters(request)
    teams = db.query("SELECT id, name, owner_user_id FROM team WHERE archived_at IS NULL ORDER BY name")
    team_opts = [{"id": t["id"], "name": t["name"] + (f" · {ctx['directors'][t['owner_user_id']]}"
                                                       if ctx["directors"].get(t["owner_user_id"]) else "")}
                 for t in teams]
    return _templates().TemplateResponse(request, "listino.html", {
        **ctx, **_compute(ctx, flt), "profiles": _profiles(),
        "team_opts": team_opts,
        "code_opts": [{"id": lp["code"], "name": f"{lp['code']} · {lp['description']}"} for lp in _profiles()],
        "role_opts": [{"id": r["code"], "name": r["label"]} for r in db.lookups("role_type")],
    })


def _fragment(request: Request):
    ctx = hrview.context(request)
    return _templates().TemplateResponse(request, "_listino_out.html", _compute(ctx, _filters(request)))


@router.post("/comp/listino/person/{pid}/code")
async def listino_person_code(request: Request, pid: int):
    """Imposta (o toglie) il codice sull'assegnazione corrente e ricalcola.

    È una correzione in place: compila un dato mancante dell'assegnazione,
    non è un movimento. Il cambio reale passa da «Nuova assegnazione».
    """
    form = await request.form()
    raw = (form.get("listino_profile_id") or "").strip()
    lp_id = None
    if raw:
        lp = db.one("SELECT id FROM listino_profile WHERE id=?", (int(raw),))
        if not lp:
            raise HTTPException(400, "codice di listino inesistente")
        lp_id = lp["id"]
    cur = db.one(
        "SELECT id FROM person_assignment WHERE person_id=? AND voided=0 AND end_date IS NULL "
        "ORDER BY start_date DESC LIMIT 1", (pid,))
    if not cur:
        raise HTTPException(400, "la persona non ha un'assegnazione corrente")
    db.execute("UPDATE person_assignment SET listino_profile_id=? WHERE id=?", (lp_id, cur["id"]))
    return _fragment(request)


@router.post("/comp/listino/person/{pid}/prod")
async def listino_person_prod(request: Request, pid: int):
    """Produttività della persona (formazione, interne, saturazione): vuoto = predefinito.

    Aggiorna solo i campi arrivati col form; un valore non valido lascia il
    precedente e ricalcola comunque.
    """
    form = await request.form()
    if not db.one("SELECT id FROM person WHERE id=?", (pid,)):
        raise HTTPException(404, "persona inesistente")
    values, errors = listino.parse_prod(form)
    if values:
        with db.transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO listino_person_param (person_id) VALUES (?)", (pid,))
            for k, v in values.items():
                conn.execute(f"UPDATE listino_person_param SET {k}=? WHERE person_id=?", (v, pid))
            conn.execute(
                "DELETE FROM listino_person_param WHERE person_id=? AND formazione_pct IS NULL "
                "AND interne_pct IS NULL AND saturazione_pct IS NULL", (pid,))
    ctx = hrview.context(request)
    out = _compute(ctx, _filters(request))
    if errors:
        persona = db.one("SELECT full_name FROM person WHERE id=?", (pid,))["full_name"]
        out["prod_errori"] = {"persona": persona, "campi": errors}
    return _templates().TemplateResponse(request, "_listino_out.html", out)
