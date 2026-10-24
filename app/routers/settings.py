"""Configurazione del director: soglie, 9-box (questionario, aggiustamenti, pesi premio),
moltiplicatori premio.

Liste valori, catalogo benefit, CCNL e listino (0.41) sono aziendali (`app/routers/company.py`,
di HR); sicurezza, backup e aggiornamenti sono del site admin (`app/routers/admin.py`)."""
import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import db
from app.services import cost, ninebox_calc

router = APIRouter()


def _templates():
    from app.main import templates

    return templates


def _ninebox_model():
    row = db.one("SELECT id, config FROM evaluation_model WHERE type='nine_box' AND active=1")
    return row["id"], ninebox_calc.normalize(json.loads(row["config"]))


def _context(tab: str, saved: str = "", draft: dict | None = None, errors: list | None = None) -> dict:
    roles, seniorities = db.lookups("role_type"), db.lookups("seniority")
    ratings = db.lookups("overall_rating")
    # aggiustamenti e moltiplicatori seguono le liste aziendali: una voce nuova compare da sola (neutra)
    weights = {(r["role_type"], r["seniority"]): r for r in db.query("SELECT * FROM ninebox_weight")}
    factors = {(r["kind"], r["code"]): r["factor"] for r in db.query("SELECT * FROM bonus_factor")}
    amber = int(db.get_meta("ral_stale_amber_years", "2"))
    red = int(db.get_meta("ral_stale_red_years", "4"))
    amber_from, red_from = cost.ral_stale_cutoffs(amber, red)
    model = draft or _ninebox_model()[1]
    return {
        "tab": tab, "saved": saved, "errors": errors or [], "draft": draft is not None,
        "ral_stale_from": {"amber": amber_from.isoformat(), "red": red_from.isoformat()},
        "roles": roles, "seniorities": seniorities, "ratings": ratings,
        "weights": [{"role": r, "sen": sn,
                     "perf": weights[(r["code"], sn["code"])]["perf_adj"] if (r["code"], sn["code"]) in weights else 0,
                     "pot": weights[(r["code"], sn["code"])]["pot_adj"] if (r["code"], sn["code"]) in weights else 0}
                    for sn in seniorities for r in roles],
        "mapping": db.query("SELECT * FROM weight_mapping ORDER BY box_number"),
        "role_factors": [{"code": r["code"], "label": r["label"], "factor": factors.get(("role", r["code"]), 1.0)}
                         for r in roles],
        "rating_factors": [{"code": r["code"], "label": r["label"], "factor": factors.get(("rating", r["code"]), 1.0)}
                           for r in ratings],
        "model": model, "axes": ninebox_calc.AXES, "box_keys": ninebox_calc.BOX_KEYS,
        "ctx_keys": [(r["code"], r["label"]) for r in roles] + [(sn["code"], sn["label"]) for sn in seniorities],
        "tags": [ninebox_calc.tag(model["questions"], i) for i in range(len(model["questions"]))],
    }


def _form_float(form, key: str, default: float) -> float:
    try:
        return float(str(form.get(key, default)).replace(",", "."))
    except ValueError:
        return default


@router.get("/settings")
def settings_page(request: Request, tab: str = "general", saved: str = ""):
    return _templates().TemplateResponse(request, "settings.html", _context(tab, saved))


# ---- generale ----

@router.post("/settings/general")
def general_save(ral_stale_amber_years: str = Form("2"), ral_stale_red_years: str = Form("4")):
    try:
        amber, red = int(ral_stale_amber_years), int(ral_stale_red_years)
    except ValueError:
        return RedirectResponse("/settings?tab=general&saved=err", status_code=302)
    if amber < 1 or red <= amber:
        return RedirectResponse("/settings?tab=general&saved=err", status_code=302)
    db.set_meta("ral_stale_amber_years", str(amber))
    db.set_meta("ral_stale_red_years", str(red))
    return RedirectResponse("/settings?tab=general&saved=1", status_code=302)


@router.post("/settings/ninebox-weights")
async def ninebox_weights_save(request: Request):
    """Aggiustamenti ruolo × anzianità: una riga per coppia delle liste aziendali (creata se manca)."""
    form = await request.form()
    pairs = {tuple(k.split("|")[1:]) for k in form if k.startswith(("p|", "q|")) and k.count("|") == 2}
    with db.transaction() as conn:
        for role, sen in pairs:
            conn.execute(
                "INSERT INTO ninebox_weight (role_type, seniority, perf_adj, pot_adj) VALUES (?,?,?,?) "
                "ON CONFLICT(owner_user_id, role_type, seniority) DO UPDATE SET "
                "perf_adj=excluded.perf_adj, pot_adj=excluded.pot_adj",
                (role, sen, _form_float(form, f"p|{role}|{sen}", 0), _form_float(form, f"q|{role}|{sen}", 0)))
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
    """Moltiplicatori per ruolo e rating: seguono le liste aziendali (righe create se mancano)."""
    form = await request.form()
    with db.transaction() as conn:
        for key in form:
            if "|" not in key:
                continue
            kind, code = key.split("|", 1)
            if kind not in ("role", "rating"):
                continue
            conn.execute(
                "INSERT INTO bonus_factor (kind, code, factor) VALUES (?,?,?) "
                "ON CONFLICT(owner_user_id, kind, code) DO UPDATE SET factor=excluded.factor",
                (kind, code, _form_float(form, key, 1.0)))
    return RedirectResponse("/settings?tab=premi&saved=1", status_code=302)


# ---- questionario 9-box ----

def _model_from_form(form, old: dict) -> dict:
    """Il questionario come arriva dal form (domande, risposte, note, caselle)."""
    questions = []
    for i in range(int(form.get("nq", 0))):
        p = f"q{i}_"
        options = [{"text": (form.get(f"{p}o{j}_text") or "").strip(),
                    "value": _form_float(form, f"{p}o{j}_value", 0)}
                   for j in range(int(form.get(f"{p}no", 0)))]
        questions.append({
            "type": form.get(f"{p}type", "perf"),
            "label": (form.get(f"{p}label") or "").strip() or f"Domanda {i + 1}",
            "weight": _form_float(form, f"{p}weight", 1),
            "text": (form.get(f"{p}text") or "").strip(),
            "ctx_notes": {k[len(p) + 4:]: v.strip() for k, v in form.items()
                          if k.startswith(f"{p}ctx_") and v.strip()},
            "options": options,
        })
    boxes = {}
    for k in ninebox_calc.BOX_KEYS:
        b = dict(old["boxes"].get(k, {}))
        b["label"] = (form.get(f"box_{k}_label") or "").strip()
        b["desc"] = (form.get(f"box_{k}_desc") or "").strip()
        boxes[k] = b
    return {"questions": questions, "boxes": boxes}


def _apply_op(model: dict, op: str) -> None:
    """Pulsanti strutturali dell'editor: aggiungi/togli/sposta domande e risposte."""
    qs = model["questions"]
    parts = op.split("-")
    name, idx = parts[0], [int(x) for x in parts[1:] if x.isdigit()]
    if name == "add_q":
        qs.append({"type": "perf", "label": f"Domanda {len(qs) + 1}", "weight": 1.0, "text": "", "ctx_notes": {},
                   "options": [{"text": "", "value": v} for v in (1.0, 2.0, 3.0)]})
    elif name == "del_q" and idx and idx[0] < len(qs):
        qs.pop(idx[0])
    elif name in ("up_q", "down_q") and idx:
        i, j = idx[0], idx[0] + (-1 if name == "up_q" else 1)
        if 0 <= i < len(qs) and 0 <= j < len(qs):
            qs[i], qs[j] = qs[j], qs[i]
    elif name == "add_o" and idx and idx[0] < len(qs):
        qs[idx[0]]["options"].append({"text": "", "value": 2.0})
    elif name == "del_o" and len(idx) == 2 and idx[0] < len(qs) and idx[1] < len(qs[idx[0]]["options"]):
        qs[idx[0]]["options"].pop(idx[1])


@router.post("/settings/ninebox-model")
async def ninebox_model_save(request: Request):
    """Salva il questionario; i pulsanti strutturali ridisegnano il form senza salvare."""
    form = await request.form()
    mid, old = _ninebox_model()
    model = _model_from_form(form, old)
    op = form.get("op", "save")
    if op != "save":
        _apply_op(model, op)
        return _templates().TemplateResponse(request, "settings.html", _context("ninebox", draft=model))
    errors = ninebox_calc.validate(model)
    if errors:
        return _templates().TemplateResponse(request, "settings.html",
                                             _context("ninebox", draft=model, errors=errors))
    db.execute("UPDATE evaluation_model SET config=? WHERE id=?", (json.dumps(model, ensure_ascii=False), mid))
    return RedirectResponse("/settings?tab=ninebox&saved=1", status_code=302)
