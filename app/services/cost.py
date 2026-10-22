"""Costo totale persona e query di sintesi retributiva."""
from datetime import date

from app import db
from app.services import trends


def current_ral(person_id: int, on_date: str = None):
    """Ultimo evento RAL non annullato (riga) o None.

    Con `on_date` restituisce la RAL **vigente a quella data**: serve quando si
    inserisce un evento retrodatato, altrimenti il confronto avverrebbe con un
    evento futuro (delta sbagliato).
    """
    sql = "SELECT * FROM ral_event WHERE person_id=? AND voided=0"
    params = [person_id]
    if on_date:
        sql += " AND effective_date <= ?"
        params.append(on_date)
    return db.one(sql + " ORDER BY effective_date DESC, id DESC LIMIT 1", tuple(params))


def derive_deltas(events: list) -> list:
    """Aggiunge `delta_calc` (variazione sull'evento precedente) a eventi ordinati DESC.

    La variazione mostrata si ricava sempre dalla timeline visibile, così void e
    reinserimenti non possono sfasarla; il `delta` salvato resta il dato di budget.
    """
    rows = [dict(e) for e in events]
    for i, e in enumerate(rows):
        prev = rows[i + 1] if i + 1 < len(rows) else None
        e["delta_calc"] = round(e["amount"] - prev["amount"], 2) if prev else 0.0
    return rows


def last_ral_changes() -> dict:
    """Ultima variazione di RAL per persona: `{person_id: {"delta", "effective_date"}}`.

    Chi non ha mai avuto una variazione (neoassunti, sola RAL censita) porta
    comunque il suo ultimo evento, con delta 0: la data c'è sempre.
    Una sola query su tutti gli eventi: la lista salary ne mostra molte righe.
    """
    by_person: dict = {}
    for e in db.query(
        "SELECT person_id, effective_date, amount FROM ral_event WHERE voided=0 "
        "ORDER BY person_id, effective_date DESC, id DESC"
    ):
        by_person.setdefault(e["person_id"], []).append(e)
    out = {}
    for pid, events in by_person.items():
        rows = derive_deltas(events)
        change = next((e for e in rows if e["delta_calc"]), rows[0])
        out[pid] = {"delta": change["delta_calc"], "effective_date": change["effective_date"]}
    return out


def _plus_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 febbraio verso un anno non bisestile
        return d.replace(year=d.year + years, month=3, day=1)


def ral_stale_cutoffs(amber_years: int, red_years: int, on_date: date = None) -> tuple:
    """Le due date di taglio: prima di questi giorni la variazione è arancio / rossa."""
    today = on_date or date.today()
    return _plus_years(today, -amber_years), _plus_years(today, -red_years)


def ral_age_flag(effective_date, amber_years: int, red_years: int, on_date: date = None) -> str:
    """Anzianità dell'ultima variazione di RAL: `'red'`, `'amber'` o `''`.

    "Oltre N anni" = più vecchia di N anni rispetto a oggi: esattamente N anni
    non è ancora oltre.
    """
    d = trends._d(effective_date)
    if not d:
        return ""
    today = on_date or date.today()
    if _plus_years(d, red_years) < today:
        return "red"
    if _plus_years(d, amber_years) < today:
        return "amber"
    return ""


def active_benefits(person_id: int) -> list:
    return db.query(
        "SELECT ba.*, bt.name, bt.value_kind, bt.is_cost FROM benefit_assignment ba "
        "JOIN benefit_type bt ON bt.id = ba.benefit_type_id "
        "WHERE ba.person_id=? AND ba.voided=0 AND ba.end_date IS NULL "
        "ORDER BY bt.name",
        (person_id,),
    )


def benefit_cost(benefits: list) -> float:
    """Somma dei benefit di tipo importo che concorrono al costo."""
    tot = 0.0
    for b in benefits:
        if b["is_cost"] and b["value_kind"] == "amount":
            try:
                tot += float(b["value"] or 0)
            except ValueError:
                pass
    return round(tot, 2)


def total_cost(person_id: int, year: str) -> dict:
    """RAL corrente + benefit a costo + incentivi anno + premi finali anno."""
    ral = current_ral(person_id)
    benefits = active_benefits(person_id)
    inc = db.one(
        "SELECT COALESCE(SUM(amount),0) AS t FROM incentive "
        "WHERE person_id=? AND voided=0 AND strftime('%Y', inc_date)=?",
        (person_id, year),
    )
    bonus = db.one(
        "SELECT COALESCE(SUM(ba.final_amount),0) AS t FROM bonus_allocation ba "
        "JOIN bonus_pool bp ON bp.id = ba.pool_id "
        "WHERE ba.person_id=? AND ba.voided=0 AND bp.period LIKE ?",
        (person_id, f"%{year}%"),
    )
    parts = {
        "ral": ral["amount"] if ral else 0,
        "benefit": benefit_cost(benefits),
        "incentivi": inc["t"],
        "premi": bonus["t"],
    }
    parts["totale"] = round(sum(parts.values()), 2)
    return parts
