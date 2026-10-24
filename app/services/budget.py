"""Calcoli su budget aumenti e montepremi."""

# Posizioni a budget che impegnano il tetto assunzioni (non ancora chiuse).
OPEN_POSITIONS = ("pianificata", "in_selezione")


def budget_residual(total_cap: float, deltas: list[float]) -> float:
    return round(total_cap - sum(deltas), 2)


def cap_from_pct(pct: float, amounts: list[float]) -> float:
    """Tetto = percentuale sul monte RAL delle persone incluse."""
    return round(pct / 100 * sum(amounts), 2)


def budget_summary(total_cap: float, applied: list[float], committed: list[float]) -> dict:
    """Ripartizione del budget fra ciò che è già realtà e ciò che è solo promesso.

    applied: delta degli eventi RAL reali; committed: importi delle proposte
    non ancora applicate. Il residuo è al netto di entrambi, così il secondo
    step di un aumento non riusa denaro già impegnato.
    """
    a = round(sum(applied), 2)
    c = round(sum(committed), 2)
    return {"applicato": a, "impegnato": c, "residuo": round(total_cap - a - c, 2)}


def goal_factor(score: float | None) -> float:
    """Fattore continuo dal punteggio obiettivi TL (1–5): 3 = neutro ×1."""
    return round(score / 3, 4) if score else 1.0


def composite_weight(box_weight: float, role_f: float = 1.0,
                     rating_f: float = 1.0, goal_f: float = 1.0) -> float:
    """Peso premio = casella 9-box × ruolo × rating review × obiettivi."""
    return round(box_weight * role_f * rating_f * goal_f, 4)


def bonus_proposals(total_cap: float, weights: dict[int, float]) -> dict[int, float]:
    """Ripartisce il montepremi in proporzione ai pesi.

    weights: person_id → peso (da weight_mapping sull'ultimo box, editabile).
    Ritorna person_id → importo proposto (arrotondato a 10 €).
    """
    total_w = sum(weights.values())
    if total_w == 0:
        return {pid: 0.0 for pid in weights}
    return {pid: round(total_cap * w / total_w / 10) * 10 for pid, w in weights.items()}


def pool_residual(total_cap: float, final_amounts: list[float]) -> float:
    return round(total_cap - sum(final_amounts), 2)


def role_prevalente(assignments: list[dict], year: int) -> str | None:
    """Il ruolo tenuto più a lungo nell'anno (0.43): per ogni assegnazione che tocca l'anno si contano
    i giorni dentro l'anno; a parità vince quella più recente. None se nessuna assegnazione tocca l'anno.

    assignments: righe con role_type, start_date, end_date (None = aperta), in qualunque ordine.
    """
    from datetime import date

    y0, y1 = date(year, 1, 1), date(year, 12, 31)
    days: dict[str, int] = {}
    latest: dict[str, str] = {}
    for a in assignments:
        start = date.fromisoformat(str(a["start_date"])[:10])
        end = date.fromisoformat(str(a["end_date"])[:10]) if a["end_date"] else y1
        lo, hi = max(start, y0), min(end, y1)
        if lo > hi:
            continue
        n = (hi - lo).days + 1
        days[a["role_type"]] = days.get(a["role_type"], 0) + n
        latest[a["role_type"]] = max(latest.get(a["role_type"], ""), str(a["start_date"]))
    if not days:
        return None
    return max(days, key=lambda r: (days[r], latest[r]))
