"""Calcolo 9-box: replica esatta della logica dell'artefatto HTML, con il questionario del director.

Il questionario (evaluation_model.config) è di ogni director: domande su due assi
(`type` = `perf` prestazione / `pot` potenziale), ciascuna con un peso e N risposte con un
punteggio da 1 a 3. Ogni asse è la media pesata dei punteggi delle sue risposte; poi gli
aggiustamenti ruolo × anzianità, i livelli (low/med/high) e la casella.
"""
AXES = {"perf": "Prestazione", "pot": "Potenziale"}
BOX_KEYS = [f"{p}-{q}" for q in ("low", "med", "high") for p in ("low", "med", "high")]


def to_level(v: float) -> str:
    return "low" if v < 1.67 else "med" if v < 2.34 else "high"


def clamp(v: float, mn: float = 1.0, mx: float = 3.0) -> float:
    return max(mn, min(mx, v))


def normalize(config: dict) -> dict:
    """Questionario nel formato corrente: ogni domanda con `label` (nome breve), `weight` e
    `type`. I modelli di prima della 0.35 avevano i nomi in una lista `labels` a parte."""
    labels = config.get("labels", [])
    questions = []
    for i, q in enumerate(config.get("questions", [])):
        questions.append({
            "type": q.get("type", "perf"),
            "label": q.get("label") or (labels[i] if i < len(labels) else f"Domanda {i + 1}"),
            "weight": float(q.get("weight", 1) or 1),
            "text": q.get("text", ""),
            "ctx_notes": {k: v for k, v in (q.get("ctx_notes") or {}).items() if v},
            "options": [{"text": o.get("text", ""), "value": float(o.get("value", 1))} for o in q.get("options", [])],
        })
    return {"questions": questions, "boxes": config.get("boxes", {})}


def tag(questions: list, i: int) -> str:
    """«Prestazione · 2»: asse e posizione della domanda nel suo asse."""
    q = questions[i]
    n = sum(1 for x in questions[: i + 1] if x["type"] == q["type"])
    return f"{AXES.get(q['type'], q['type'])} · {n}"


def validate(config: dict) -> list[str]:
    """Errori che renderebbero il questionario inutilizzabile (lista vuota = valido)."""
    errors = []
    qs = config.get("questions", [])
    for axis, name in AXES.items():
        if not any(q["type"] == axis for q in qs):
            errors.append(f"Serve almeno una domanda di {name.lower()}.")
    for i, q in enumerate(qs, 1):
        if q["type"] not in AXES:
            errors.append(f"Domanda {i}: asse non valido.")
        if not q["text"].strip():
            errors.append(f"Domanda {i}: manca il testo.")
        if q["weight"] <= 0:
            errors.append(f"Domanda {i}: il peso deve essere maggiore di zero.")
        if len(q["options"]) < 2:
            errors.append(f"Domanda {i}: servono almeno due risposte.")
        for j, o in enumerate(q["options"], 1):
            if not o["text"].strip():
                errors.append(f"Domanda {i}, risposta {j}: manca il testo.")
            if not 1 <= o["value"] <= 3:
                errors.append(f"Domanda {i}, risposta {j}: il punteggio va da 1 a 3.")
    boxes = config.get("boxes", {})
    for k in BOX_KEYS:
        if not (boxes.get(k) or {}).get("label", "").strip():
            errors.append(f"Casella {(boxes.get(k) or {}).get('n', k)}: manca il nome.")
    return errors


def score(choices: list[int], questions: list) -> tuple[float, float, list[float]]:
    """Indici delle risposte scelte → (prestazione, potenziale, punteggi). Medie pesate per asse."""
    if len(choices) != len(questions):
        raise ValueError(f"servono {len(questions)} risposte")
    values, sums = [], {a: [0.0, 0.0] for a in AXES}
    for c, q in zip(choices, questions, strict=True):
        if not 0 <= c < len(q["options"]):
            raise ValueError("risposta inesistente")
        v = q["options"][c]["value"]
        values.append(v)
        sums[q["type"]][0] += q["weight"] * v
        sums[q["type"]][1] += q["weight"]
    if not all(w for _, w in sums.values()):
        raise ValueError("il questionario deve avere domande su entrambi gli assi")
    return sums["perf"][0] / sums["perf"][1], sums["pot"][0] / sums["pot"][1], values


def compute(answers: list, perf_adj: float, pot_adj: float, boxes: dict, questions: list | None = None) -> dict:
    """Casella 9-box.

    Con `questions` (questionario normalizzato) `answers` sono gli indici delle risposte scelte.
    Senza, il questionario storico: 6 valori 1–3, primi 3 prestazione e ultimi 3 potenziale.
    perf_adj/pot_adj: aggiustamenti da ninebox_weight per (ruolo, anzianità).
    boxes: mappa 'perf-pot' → {n, label, ...} dal questionario.
    """
    if questions is not None:
        raw_perf, raw_pot, _ = score(answers, questions)
    else:
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
