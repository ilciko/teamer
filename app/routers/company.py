"""Configurazione aziendale: liste valori, catalogo benefit, valori predefiniti (CCNL).

Una sola per l'istanza (migrazione 0030): la leggono tutti i director, la modifica solo
chi la gestisce. Oggi il site admin; quando arriverà HR basta cambiare `MANAGED_BY` (il
controllo d'accesso è in `auth.allowed`). Le scritture passano dalla connessione di
sistema: su quelle dei director l'authorizer nega la modifica di queste tabelle.
"""
import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import db

router = APIRouter()

PREFIX = "/azienda"
MANAGED_BY = "admin"


def _back(tab: str, saved: str = "1") -> RedirectResponse:
    return RedirectResponse(f"{PREFIX}?tab={tab}&saved={saved}", status_code=302)


@router.get(PREFIX)
def company_page(request: Request, tab: str = "liste", saved: str = ""):
    from app.main import templates

    categories: dict[str, list] = {}
    for r in db.sys.query("SELECT * FROM lookup ORDER BY category, sort_order, code"):
        categories.setdefault(r["category"], []).append(r)
    return templates.TemplateResponse(request, "company.html", {
        "tab": tab, "saved": saved, "categories": categories,
        "benefit_types": db.sys.query("SELECT * FROM benefit_type ORDER BY name"),
        "default_ccnl": db.get_meta("default_ccnl", ""),
    })


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
