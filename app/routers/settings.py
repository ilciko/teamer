"""Configurazione: lookup, benefit, pesi 9-box, modelli, listino, import.

Sicurezza, backup e aggiornamenti sono del site admin (`app/routers/admin.py`)."""
import json

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from app import db
from app.services import cost, importer

router = APIRouter()


def _templates():
    from app.main import templates

    return templates


@router.get("/settings")
def settings_page(request: Request, tab: str = "lookup", saved: str = ""):
    lookup_rows = db.query("SELECT * FROM lookup ORDER BY category, sort_order, code")
    categories: dict[str, list] = {}
    for r in lookup_rows:
        categories.setdefault(r["category"], []).append(r)
    benefit_types = db.query("SELECT * FROM benefit_type ORDER BY name")
    weights = db.query(
        "SELECT * FROM ninebox_weight ORDER BY CASE seniority WHEN 'new' THEN 0 WHEN 'mid' THEN 1 ELSE 2 END, role_type")
    mapping = db.query("SELECT * FROM weight_mapping ORDER BY box_number")
    models = db.query("SELECT * FROM evaluation_model ORDER BY id")
    factors = db.query(
        "SELECT * FROM bonus_factor ORDER BY kind, CASE kind WHEN 'rating' THEN code END, "
        "CASE code WHEN 'ic' THEN 1 WHEN 'tl' THEN 2 WHEN 'mgr' THEN 3 WHEN 'sr' THEN 4 END")
    listino_profiles = db.query(
        "SELECT lp.*, (SELECT COUNT(*) FROM person_assignment pa WHERE pa.listino_profile_id=lp.id) AS n_ref "
        "FROM listino_profile lp ORDER BY lp.sort_order, lp.code")
    amber = int(db.get_meta("ral_stale_amber_years", "2"))
    red = int(db.get_meta("ral_stale_red_years", "4"))
    amber_from, red_from = cost.ral_stale_cutoffs(amber, red)
    return _templates().TemplateResponse(request, "settings.html", {
        "tab": tab, "saved": saved, "categories": categories,
        "ral_stale_from": {"amber": amber_from.isoformat(), "red": red_from.isoformat()},
        "benefit_types": benefit_types, "weights": weights, "mapping": mapping,
        "models": models, "listino_profiles": listino_profiles,
        "role_factors": [f for f in factors if f["kind"] == "role"],
        "rating_factors": [f for f in factors if f["kind"] == "rating"],
    })


# ---- generale ----

@router.post("/settings/general")
def general_save(default_ccnl: str = Form(""), ral_stale_amber_years: str = Form("2"),
                 ral_stale_red_years: str = Form("4")):
    try:
        amber, red = int(ral_stale_amber_years), int(ral_stale_red_years)
    except ValueError:
        return RedirectResponse("/settings?tab=general&saved=err", status_code=302)
    if amber < 1 or red <= amber:
        return RedirectResponse("/settings?tab=general&saved=err", status_code=302)
    db.set_meta("default_ccnl", default_ccnl.strip())
    db.set_meta("ral_stale_amber_years", str(amber))
    db.set_meta("ral_stale_red_years", str(red))
    return RedirectResponse("/settings?tab=general&saved=1", status_code=302)


# ---- lookup ----

@router.post("/settings/lookup")
def lookup_save(category: str = Form(...), code: str = Form(...), label: str = Form(...),
                sort_order: int = Form(0)):
    db.execute(
        "INSERT INTO lookup (category, code, label, sort_order) VALUES (?,?,?,?) "
        "ON CONFLICT(owner_user_id, category, code) DO UPDATE SET label=excluded.label, sort_order=excluded.sort_order",
        (category.strip(), code.strip(), label.strip(), sort_order))
    return RedirectResponse("/settings?tab=lookup&saved=1", status_code=302)


@router.post("/settings/lookup/{lid}/update")
def lookup_update(lid: int, label: str = Form(...), sort_order: int = Form(0)):
    """Rinomina l'etichetta: il codice resta stabile, la modifica si propaga ovunque."""
    db.execute("UPDATE lookup SET label=?, sort_order=? WHERE id=?",
               (label.strip(), sort_order, lid))
    return RedirectResponse("/settings?tab=lookup&saved=1", status_code=302)


@router.post("/settings/lookup/{lid}/toggle")
def lookup_toggle(lid: int):
    db.execute("UPDATE lookup SET active = 1 - active WHERE id=?", (lid,))
    return RedirectResponse("/settings?tab=lookup", status_code=302)


# ---- benefit ----

@router.post("/settings/benefit")
def benefit_type_save(name: str = Form(...), value_kind: str = Form(...),
                      enum_options: str = Form(None), is_cost: str = Form(None)):
    opts = None
    if value_kind == "enum" and enum_options:
        opts = json.dumps([o.strip() for o in enum_options.split(",") if o.strip()])
    db.execute(
        "INSERT INTO benefit_type (name, value_kind, enum_options, is_cost) VALUES (?,?,?,?)",
        (name.strip(), value_kind, opts, 1 if is_cost else 0))
    return RedirectResponse("/settings?tab=benefit&saved=1", status_code=302)


@router.post("/settings/benefit/{bid}/update")
def benefit_type_update(bid: int, name: str = Form(...), enum_options: str = Form(None),
                        is_cost: str = Form(None)):
    """Rinomina il benefit: le assegnazioni puntano all'id, la modifica si propaga."""
    bt = db.one("SELECT * FROM benefit_type WHERE id=?", (bid,))
    opts = bt["enum_options"]
    if bt["value_kind"] == "enum" and enum_options is not None:
        opts = json.dumps([o.strip() for o in enum_options.split(",") if o.strip()])
    db.execute("UPDATE benefit_type SET name=?, enum_options=?, is_cost=? WHERE id=?",
               (name.strip(), opts, 1 if is_cost else 0, bid))
    return RedirectResponse("/settings?tab=benefit&saved=1", status_code=302)


@router.post("/settings/benefit/{bid}/toggle")
def benefit_type_toggle(bid: int):
    db.execute("UPDATE benefit_type SET active = 1 - active WHERE id=?", (bid,))
    return RedirectResponse("/settings?tab=benefit", status_code=302)


# ---- listino ----

def _day_rate(raw: str) -> float | None:
    """Tariffa €/gg dal form: vuota = non definita; non numerica o negativa → ValueError."""
    raw = (raw or "").strip().replace(",", ".")
    if not raw:
        return None
    v = float(raw)
    if v < 0:
        raise ValueError("tariffa negativa")
    return v


@router.post("/settings/listino")
def listino_profile_save(code: str = Form(""), description: str = Form(""), sort_order: int = Form(0),
                         day_rate: str = Form("")):
    """Nuovo codice di listino; lo stesso codice aggiorna descrizione, ordine e tariffa."""
    code, description = code.strip().upper(), description.strip()
    try:
        rate = _day_rate(day_rate)
    except ValueError:
        rate, code = None, ""
    if not code or not description:
        return RedirectResponse("/settings?tab=listino&saved=err", status_code=302)
    db.execute(
        "INSERT INTO listino_profile (code, description, sort_order, day_rate) VALUES (?,?,?,?) "
        "ON CONFLICT(owner_user_id, code) DO UPDATE SET description=excluded.description, "
        "sort_order=excluded.sort_order, day_rate=excluded.day_rate",
        (code, description, sort_order, rate))
    return RedirectResponse("/settings?tab=listino&saved=1", status_code=302)


@router.post("/settings/listino/{lid}/update")
def listino_profile_update(lid: int, description: str = Form(...), sort_order: int = Form(0),
                           day_rate: str = Form("")):
    """Il codice è stabile: si cambiano descrizione (si propaga ovunque), ordine e tariffa."""
    try:
        rate = _day_rate(day_rate)
    except ValueError:
        return RedirectResponse("/settings?tab=listino&saved=err", status_code=302)
    db.execute("UPDATE listino_profile SET description=?, sort_order=?, day_rate=? WHERE id=?",
               (description.strip(), sort_order, rate, lid))
    return RedirectResponse("/settings?tab=listino&saved=1", status_code=302)


@router.post("/settings/listino/{lid}/toggle")
def listino_profile_toggle(lid: int):
    db.execute("UPDATE listino_profile SET active = 1 - active WHERE id=?", (lid,))
    return RedirectResponse("/settings?tab=listino", status_code=302)


# ---- 9-box ----

@router.post("/settings/ninebox-weights")
async def ninebox_weights_save(request: Request):
    form = await request.form()
    with db.transaction() as conn:
        for key, val in form.items():
            if "|" not in key:
                continue
            field, role, sen = key.split("|")
            try:
                v = float(val)
            except ValueError:
                continue
            conn.execute(
                f"UPDATE ninebox_weight SET {'perf_adj' if field == 'p' else 'pot_adj'}=? "
                "WHERE role_type=? AND seniority=?", (v, role, sen))
    return RedirectResponse("/settings?tab=ninebox&saved=1", status_code=302)


@router.post("/settings/weight-mapping")
async def weight_mapping_save(request: Request):
    form = await request.form()
    with db.transaction() as conn:
        for key, val in form.items():
            if not key.startswith("box_"):
                continue
            try:
                conn.execute(
                    "UPDATE weight_mapping SET weight=? WHERE box_number=?",
                    (float(val), int(key[4:])))
            except ValueError:
                continue
    return RedirectResponse("/settings?tab=ninebox&saved=1", status_code=302)


@router.post("/settings/bonus-factors")
async def bonus_factors_save(request: Request):
    form = await request.form()
    with db.transaction() as conn:
        for key, val in form.items():
            if "|" not in key:
                continue
            kind, code = key.split("|", 1)
            try:
                conn.execute("UPDATE bonus_factor SET factor=? WHERE kind=? AND code=?",
                             (float(val), kind, code))
            except ValueError:
                continue
    return RedirectResponse("/settings?tab=ninebox&saved=1", status_code=302)


# ---- modelli ----

@router.post("/settings/model/{mid}")
def model_save(mid: int, name: str = Form(...), config_json: str = Form(...)):
    try:
        parsed = json.loads(config_json)
    except json.JSONDecodeError:
        return RedirectResponse("/settings?tab=models&saved=err", status_code=302)
    db.execute(
        "UPDATE evaluation_model SET name=?, config=? WHERE id=?",
        (name.strip(), json.dumps(parsed, ensure_ascii=False), mid))
    return RedirectResponse("/settings?tab=models&saved=1", status_code=302)


# ---- import excel ----

@router.get("/settings/import/template")
def import_template():
    return Response(
        content=importer.build_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="teamer-import.xlsx"'})


@router.post("/settings/import")
async def import_run(request: Request, file: UploadFile, ref_date: str = Form(...)):
    from app.main import templates

    content = await file.read()
    try:
        result = importer.import_workbook(content, ref_date)
    except Exception as exc:
        result = {"created": [], "skipped": [], "errors": [(0, f"file non leggibile: {exc}")]}
    return templates.TemplateResponse(request, "_import_result.html", {"r": result})
