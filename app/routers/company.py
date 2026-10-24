"""Configurazione aziendale: liste valori, catalogo benefit, valori predefiniti (CCNL) e, dalla
0.41, il listino (codici con tariffa e parametri del costo giornaliero).

Una sola per l'istanza (migrazione 0030): la leggono tutti i director, la modifica solo chi la
gestisce: HR (`MANAGED_BY`, controllo d'accesso in `auth.allowed`; senza ripiego sull'admin, che
non vede dati del personale). Le scritture passano dalla connessione di sistema: su quelle dei
director (e di HR) l'authorizer nega la modifica di queste tabelle.
"""
import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import db
from app.services import listino

router = APIRouter()

PREFIX = "/azienda"
MANAGED_BY = "hr"


def _back(tab: str, saved: str = "1") -> RedirectResponse:
    return RedirectResponse(f"{PREFIX}?tab={tab}&saved={saved}", status_code=302)


@router.get(PREFIX)
def company_page(request: Request, tab: str = "liste", saved: str = ""):
    from app.main import templates

    categories: dict[str, list] = {}
    for r in db.sys.query("SELECT * FROM lookup ORDER BY category, sort_order, code"):
        categories.setdefault(r["category"], []).append(r)
    saved_params = {k: db.get_meta(meta_key, "") for k, meta_key in listino.META_KEYS.items()}
    p = listino.parse_params({}, saved_params)
    return templates.TemplateResponse(request, "company.html", {
        "tab": tab, "saved": saved, "categories": categories,
        "benefit_types": db.sys.query("SELECT * FROM benefit_type ORDER BY name"),
        "default_ccnl": db.get_meta("default_ccnl", ""),
        "listino_profiles": db.sys.query(
            "SELECT lp.*, (SELECT COUNT(*) FROM person_assignment pa WHERE pa.listino_profile_id=lp.id) AS n_ref "
            "FROM listino_profile lp ORDER BY lp.sort_order, lp.code"),
        "p": p, "g": listino.giorni(p),
        "role_factors": {r["role_type"]: r["factor"] for r in db.sys.query("SELECT * FROM bonus_role_factor")},
    })


# ---- premi di ruolo: moltiplicatori per ruolo (0.43) ----

@router.post(f"{PREFIX}/premi")
async def role_factors_save(request: Request):
    """Un moltiplicatore per ogni ruolo della lista aziendale: junior/specialist ×1, TL ×2, manager ×3…"""
    form = await request.form()
    for r in db.lookups("role_type"):
        raw = str(form.get(f"f_{r['code']}") or "").strip().replace(",", ".")
        try:
            v = float(raw)
        except ValueError:
            return _back("premi", "err")
        if v < 0:
            return _back("premi", "err")
        db.sys.execute("INSERT INTO bonus_role_factor (role_type, factor) VALUES (?,?) "
                       "ON CONFLICT(role_type) DO UPDATE SET factor=excluded.factor", (r["code"], v))
    return _back("premi")


# ---- listino: codici e parametri (0.41) ----

def _day_rate(raw: str) -> float | None:
    """Tariffa €/gg dal form: vuota = non definita; non numerica o negativa → ValueError."""
    raw = (raw or "").strip().replace(",", ".")
    if not raw:
        return None
    v = float(raw)
    if v < 0:
        raise ValueError("tariffa negativa")
    return v


@router.post(f"{PREFIX}/listino")
def listino_profile_save(code: str = Form(""), description: str = Form(""), sort_order: int = Form(0),
                         day_rate: str = Form("")):
    """Nuovo codice di listino; lo stesso codice aggiorna descrizione, ordine e tariffa."""
    code, description = code.strip().upper(), description.strip()
    try:
        rate = _day_rate(day_rate)
    except ValueError:
        rate, code = None, ""
    if not code or not description:
        return _back("listino", "err")
    db.sys.execute(
        "INSERT INTO listino_profile (code, description, sort_order, day_rate) VALUES (?,?,?,?) "
        "ON CONFLICT(code) DO UPDATE SET description=excluded.description, "
        "sort_order=excluded.sort_order, day_rate=excluded.day_rate",
        (code, description, sort_order, rate))
    return _back("listino")


@router.post(PREFIX + "/listino/{lid}/update")
def listino_profile_update(lid: int, description: str = Form(...), sort_order: int = Form(0),
                           day_rate: str = Form("")):
    """Il codice è stabile: si cambiano descrizione (si propaga ovunque), ordine e tariffa."""
    try:
        rate = _day_rate(day_rate)
    except ValueError:
        return _back("listino", "err")
    db.sys.execute("UPDATE listino_profile SET description=?, sort_order=?, day_rate=? WHERE id=?",
                   (description.strip(), sort_order, rate, lid))
    return _back("listino")


@router.post(PREFIX + "/listino/{lid}/toggle")
def listino_profile_toggle(lid: int):
    db.sys.execute("UPDATE listino_profile SET active = 1 - active WHERE id=?", (lid,))
    return _back("listino", "")


@router.post(f"{PREFIX}/listino/parametri")
async def listino_params_save(request: Request):
    """I parametri del costo giornaliero, uguali per tutti: tutto o niente."""
    form = await request.form()
    p, errors = listino.validate_params(form)
    if errors:
        return _back("listino", "err")
    for key, value in listino.params_to_meta(p).items():
        db.set_meta(key, value)
    return _back("listino")


# ---- liste valori ----

@router.post(f"{PREFIX}/liste")
def lookup_save(category: str = Form(...), code: str = Form(...), label: str = Form(...),
                sort_order: int = Form(0)):
    db.sys.execute(
        "INSERT INTO lookup (category, code, label, sort_order) VALUES (?,?,?,?) "
        "ON CONFLICT(category, code) DO UPDATE SET label=excluded.label, sort_order=excluded.sort_order",
        (category.strip(), code.strip(), label.strip(), sort_order))
    return _back("liste")


@router.post(PREFIX + "/liste/{lid}/update")
def lookup_update(lid: int, label: str = Form(...), sort_order: int = Form(0)):
    """Rinomina l'etichetta: il codice resta stabile, la modifica si propaga ovunque."""
    db.sys.execute("UPDATE lookup SET label=?, sort_order=? WHERE id=?", (label.strip(), sort_order, lid))
    return _back("liste")


@router.post(PREFIX + "/liste/{lid}/toggle")
def lookup_toggle(lid: int):
    db.sys.execute("UPDATE lookup SET active = 1 - active WHERE id=?", (lid,))
    return _back("liste", "")


# ---- catalogo benefit ----

@router.post(f"{PREFIX}/benefit")
def benefit_type_save(name: str = Form(...), value_kind: str = Form(...),
                      enum_options: str = Form(None), is_cost: str = Form(None)):
    opts = None
    if value_kind == "enum" and enum_options:
        opts = json.dumps([o.strip() for o in enum_options.split(",") if o.strip()])
    db.sys.execute("INSERT INTO benefit_type (name, value_kind, enum_options, is_cost) VALUES (?,?,?,?)",
                   (name.strip(), value_kind, opts, 1 if is_cost else 0))
    return _back("benefit")


@router.post(PREFIX + "/benefit/{bid}/update")
def benefit_type_update(bid: int, name: str = Form(...), enum_options: str = Form(None),
                        is_cost: str = Form(None)):
    """Rinomina il benefit: le assegnazioni puntano all'id, la modifica si propaga."""
    bt = db.sys.one("SELECT * FROM benefit_type WHERE id=?", (bid,))
    opts = bt["enum_options"]
    if bt["value_kind"] == "enum" and enum_options is not None:
        opts = json.dumps([o.strip() for o in enum_options.split(",") if o.strip()])
    db.sys.execute("UPDATE benefit_type SET name=?, enum_options=?, is_cost=? WHERE id=?",
                   (name.strip(), opts, 1 if is_cost else 0, bid))
    return _back("benefit")


@router.post(PREFIX + "/benefit/{bid}/toggle")
def benefit_type_toggle(bid: int):
    db.sys.execute("UPDATE benefit_type SET active = 1 - active WHERE id=?", (bid,))
    return _back("benefit", "")


# ---- valori predefiniti ----

@router.post(f"{PREFIX}/default")
def defaults_save(default_ccnl: str = Form("")):
    db.set_meta("default_ccnl", default_ccnl.strip())
    return _back("default")
