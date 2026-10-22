"""Serie storiche mensili ricostruite dagli eventi (addetti, monte RAL, per team)."""
from datetime import date


def month_range(start: date, end: date) -> list[date]:
    """Primi giorno di ogni mese da start a end inclusi."""
    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(date(y, m, 1))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return months


def _d(v) -> date | None:
    if v in (None, ""):
        return None
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def is_active(person: dict, on: date) -> bool:
    """Attivo alla data: assunto entro quella data e non ancora cessato."""
    hire = _d(person.get("hire_date"))
    end = _d(person.get("end_date"))
    if hire is None or hire > on:
        return False
    return end is None or end >= on


def headcount_series(people: list[dict], months: list[date]) -> list[int]:
    return [sum(1 for p in people if is_active(p, m)) for m in months]


def ral_at(events: list[dict], on: date) -> float | None:
    """Ultimo evento RAL con decorrenza ≤ data (gli eventi arrivano già senza i voided)."""
    best = None
    for e in events:
        eff = _d(e["effective_date"])
        if eff is not None and eff <= on and (best is None or eff >= best[0]):
            best = (eff, e["amount"])
    return best[1] if best else None


def ral_series(people: list[dict], events_by_person: dict,
               months: list[date]) -> list[float | None]:
    """Monte RAL mensile: somma della RAL vigente per le persone attive a quella data.

    Il mese vale `None` — un buco nel grafico, non uno zero — se di almeno un
    attivo non si conosce ancora la RAL. Prima del censimento quel dato non
    esiste: sommarlo come zero farebbe sembrare un balzo quello che è solo
    l'inizio della rilevazione.
    """
    out = []
    for m in months:
        tot, completo = 0.0, True
        for p in people:
            if not is_active(p, m):
                continue
            ral = ral_at(events_by_person.get(p["id"], []), m)
            if ral is None:
                completo = False
                break
            tot += ral
        out.append(round(tot, 2) if completo else None)
    return out


def data_start(series: list) -> int:
    """Primo indice da cui il dato è continuo fino alla fine: subito dopo l'ultimo buco.

    Il monte RAL si può leggere solo da lì in poi; prima il grafico
    disegnerebbe un vuoto lungo quanto la storia non censita.
    """
    last_gap = -1
    for i, v in enumerate(series):
        if v is None:
            last_gap = i
    return last_gap + 1


def missing_ral(people: list[dict], events_by_person: dict, on: date) -> list[dict]:
    """Chi è attivo a quella data senza una RAL nota: è chi tiene indietro l'analisi."""
    return [p for p in people
            if is_active(p, on) and ral_at(events_by_person.get(p["id"], []), on) is None]


def first_ral_date(events: list[dict]):
    """Decorrenza del primo evento RAL noto (None se la persona non ne ha)."""
    dates = [_d(e["effective_date"]) for e in events]
    dates = [d for d in dates if d]
    return min(dates) if dates else None


def team_of(assignments: list[dict], on: date):
    """team_id della persona alla data, via intervalli di person_assignment."""
    for a in assignments:
        start = _d(a["start_date"])
        end = _d(a["end_date"])
        if start is not None and start <= on and (end is None or end >= on):
            return a["team_id"]
    return None


def headcount_by_team(people: list[dict], assignments_by_person: dict,
                      months: list[date]) -> dict:
    """team_id → serie addetti. Le persone senza team a quella data finiscono sotto None."""
    series: dict = {}
    for m_idx, m in enumerate(months):
        for p in people:
            if not is_active(p, m):
                continue
            tid = team_of(assignments_by_person.get(p["id"], []), m)
            series.setdefault(tid, [0] * len(months))[m_idx] += 1
    return series


def ral_by_team(people: list[dict], assignments_by_person: dict,
                events_by_person: dict, months: list[date]) -> dict:
    """team_id → serie monte RAL, con la stessa regola di `ral_series`: il mese
    del team è `None` finché a qualcuno dei suoi attivi manca la RAL."""
    series: dict = {}
    incompleti: dict = {}
    for m_idx, m in enumerate(months):
        for p in people:
            if not is_active(p, m):
                continue
            tid = team_of(assignments_by_person.get(p["id"], []), m)
            row = series.setdefault(tid, [0.0] * len(months))
            ral = ral_at(events_by_person.get(p["id"], []), m)
            if ral is None:
                incompleti.setdefault(tid, set()).add(m_idx)
                continue
            row[m_idx] = round(row[m_idx] + ral, 2)
    for tid, idxs in incompleti.items():
        for i in idxs:
            series[tid][i] = None
    return series
