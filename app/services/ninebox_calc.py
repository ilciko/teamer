"""Calcolo 9-box: replica esatta della logica dell'artefatto HTML."""


def to_level(v: float) -> str:
    return "low" if v < 1.67 else "med" if v < 2.34 else "high"


def clamp(v: float, mn: float = 1.0, mx: float = 3.0) -> float:
    return max(mn, min(mx, v))


def compute(answers: list[int], perf_adj: float, pot_adj: float, boxes: dict) -> dict:
    """answers: 6 valori 1–3 (primi 3 = prestazione, ultimi 3 = potenziale).

    perf_adj/pot_adj: aggiustamenti da ninebox_weight per (ruolo, anzianità).
    boxes: mappa 'perf-pot' → {n, label, ...} dal config del modello.
    """
    if len(answers) != 6 or any(a not in (1, 2, 3) for a in answers):
        raise ValueError("servono 6 risposte con valore 1–3")
    raw_perf = sum(answers[:3]) / 3
    raw_pot = sum(answers[3:]) / 3
    adj_perf = clamp(raw_perf + perf_adj)
    adj_pot = clamp(raw_pot + pot_adj)
    perf_level = to_level(adj_perf)
    pot_level = to_level(adj_pot)
    box = boxes[f"{perf_level}-{pot_level}"]
    return {
        "raw_perf": round(raw_perf, 4),
        "raw_pot": round(raw_pot, 4),
        "adj_perf": round(adj_perf, 4),
        "adj_pot": round(adj_pot, 4),
        "perf_level": perf_level,
        "pot_level": pot_level,
        "box_number": box["n"],
        "box_label": box["label"],
        "box_desc": box.get("desc", ""),
        "box_zone": box.get("zone", ""),
    }
