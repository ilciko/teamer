"""Punteggi del ciclo obiettivi (scala 1–5, pesi %)."""


def weighted_score(items: list[dict], score_key: str = "tl_score") -> float | None:
    """Σ(weight_pct × score)/Σ(weight_pct) sugli item con punteggio presente.

    items: [{'weight_pct': 80, 'tl_score': 4, 'self_score': 5}, ...]
    Ritorna None se nessun punteggio inserito.
    """
    scored = [i for i in items if i.get(score_key) is not None]
    total_w = sum(i["weight_pct"] for i in scored)
    if not scored or total_w == 0:
        return None
    return round(sum(i["weight_pct"] * i[score_key] for i in scored) / total_w, 2)


def weights_by_category(items: list[dict]) -> dict:
    """Somma dei pesi per categoria: ogni categoria fa storia a sé (100% + 100%)."""
    sums: dict = {}
    for i in items:
        cat = i.get("category", "professionale")
        sums[cat] = round(sums.get(cat, 0) + i["weight_pct"], 2)
    return sums


def weights_complete(items: list[dict]) -> bool:
    """True se, per ogni categoria presente, i pesi sommano a 100 (tolleranza 0.01).

    Professionale e personale sono scopi diversi: 100+100 è la situazione attesa.
    """
    sums = weights_by_category(items)
    return bool(sums) and all(abs(v - 100) < 0.01 for v in sums.values())
