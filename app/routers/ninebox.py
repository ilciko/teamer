"""9-box: wizard guidato (dall'artefatto) con persistenza e griglia team."""
import json
from datetime import date

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import db
from app.routers.org import current_assignment, initials, seniority_from
from app.services import ninebox_calc

router = APIRouter()


def _templates():
    from app.main import templates

    return templates


def _model():
    row = db.one("SELECT * FROM evaluation_model WHERE type='nine_box' AND active=1")
    return row, json.loads(row["config"])


def _weights() -> dict:
    return {
        (r["role_type"], r["seniority"]): (r["perf_adj"], r["pot_adj"])
        for r in db.query("SELECT * FROM ninebox_weight")
    }


@router.get("/ninebox")
def ninebox_home(request: Request):
    _, config = _model()
    latest = db.query(
        """SELECT n.*, p.full_name FROM ninebox_assessment n
           JOIN person p ON p.id = n.person_id
           WHERE n.voided=0 AND p.status='attivo'
             AND n.id = (SELECT id FROM ninebox_assessment n2
                         WHERE n2.person_id = n.person_id AND n2.voided=0
                         ORDER BY n2.eval_date DESC, n2.id DESC LIMIT 1)
           ORDER BY p.full_name""")
    by_box: dict[int, list] = {}
    for r in latest:
        by_box.setdefault(r["box_number"], []).append(r)
    boxes_by_n = {b["n"]: {**b, "key": k} for k, b in config["boxes"].items()}
    unrated = db.query(
        """SELECT p.id, p.full_name FROM person p WHERE p.status='attivo'
           AND NOT EXISTS (SELECT 1 FROM ninebox_assessment n WHERE n.person_id=p.id AND n.voided=0)
           ORDER BY p.full_name""")
    people = db.query("SELECT id, full_name FROM person WHERE status='attivo' ORDER BY full_name")
    return _templates().TemplateResponse(request, "ninebox_home.html", {
        "by_box": by_box, "boxes_by_n": boxes_by_n, "latest": latest,
        "unrated": unrated, "people": people, "initials": initials,
    })


@router.get("/ninebox/start/{pid}")
def ninebox_start(request: Request, pid: int):
    p = db.one("SELECT * FROM person WHERE id=?", (pid,))
    if not p:
        return RedirectResponse("/ninebox", status_code=302)
    model, config = _model()
    assignment = current_assignment(pid)
    role = assignment["role_type"] if assignment else "ic"
    seniority = seniority_from(assignment["start_date"]) if assignment else "mid"
    weights = {f"{k[0]}|{k[1]}": v for k, v in _weights().items()}
    return _templates().TemplateResponse(request, "ninebox_wizard.html", {
        "p": p, "initials": initials(p["full_name"]),
        "config_json": json.dumps(config, ensure_ascii=False),
        "weights_json": json.dumps(weights),
        "role": role, "seniority": seniority,
        "roles": db.lookups("role_type"), "seniorities": db.lookups("seniority"),
    })


@router.post("/ninebox/save")
def ninebox_save(person_id: int = Form(...), role_type: str = Form(...),
                 seniority: str = Form(...), answers: str = Form(...),
                 eval_date: str = Form(None)):
    model, config = _model()
    ans = [int(a) for a in answers.split(",")]
    w = _weights().get((role_type, seniority), (0.0, 0.0))
    result = ninebox_calc.compute(ans, w[0], w[1], config["boxes"])
    aid = db.execute(
        "INSERT INTO ninebox_assessment (person_id, eval_date, role_type, seniority, "
        "raw_perf, raw_pot, adj_perf, adj_pot, perf_level, pot_level, box_number, "
        "weights_snapshot, answers) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (person_id, eval_date or date.today().isoformat(), role_type, seniority,
         result["raw_perf"], result["raw_pot"], result["adj_perf"], result["adj_pot"],
         result["perf_level"], result["pot_level"], result["box_number"],
         json.dumps({"perf_adj": w[0], "pot_adj": w[1]}),
         json.dumps(ans)))
    return RedirectResponse(f"/ninebox/result/{aid}", status_code=302)


@router.get("/ninebox/result/{aid}")
def ninebox_result(request: Request, aid: int):
    a = db.one(
        "SELECT n.*, p.full_name FROM ninebox_assessment n JOIN person p ON p.id=n.person_id "
        "WHERE n.id=?", (aid,))
    if not a:
        return RedirectResponse("/ninebox", status_code=302)
    _, config = _model()
    box = next(b for b in config["boxes"].values() if b["n"] == a["box_number"])
    answers = json.loads(a["answers"])
    snapshot = json.loads(a["weights_snapshot"])
    labels = config.get("labels", [])
    questions = config["questions"]
    detail = []
    for i, v in enumerate(answers):
        label = labels[i] if i < len(labels) else f"Domanda {i+1}"
        opt = next((o["text"] for o in questions[i]["options"] if o["value"] == v), str(v))
        detail.append({"label": label, "value": v, "text": opt})
    history = db.query(
        "SELECT * FROM ninebox_assessment WHERE person_id=? AND voided=0 "
        "ORDER BY eval_date DESC, id DESC", (a["person_id"],))
    return _templates().TemplateResponse(request, "ninebox_result.html", {
        "a": a, "box": box, "detail": detail, "snapshot": snapshot,
        "history": history, "boxes": config["boxes"],
    })


@router.post("/ninebox/{aid}/void")
def ninebox_void(aid: int, reason: str = Form(""), back: str = Form("")):
    """Annulla una valutazione sbagliata (persona o contesto errati).

    Non si cancella: `voided=1` la toglie dalla griglia, dal peso composito del
    montepremi e dai report, ma resta nello storico. La strada del cambiamento
    reale è "Rivaluta", che aggiunge una valutazione nuova.
    """
    db.execute("UPDATE ninebox_assessment SET voided=1, void_reason=? WHERE id=?",
               (reason.strip() or "annullata da UI", aid))
    return RedirectResponse(back or "/ninebox", status_code=302)
