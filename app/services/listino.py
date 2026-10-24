"""Listino: costo giornaliero di vendita.

Costo azienda annuo diviso per i giorni fatturabili dell'anno. Il moltiplicatore
oneri copre INPS, INAIL e TFR: l'IRAP resta fuori perché dal 2015 il costo del
lavoro a tempo indeterminato è interamente deducibile. L'anno è quello
convenzionale: 365 giorni, 104 di weekend e le festività feriali come numero
medio (10), più le chiusure aziendali — nessun conteggio sull'anno vero (0.41: i
parametri sono aziendali e uguali per tutti). Nessun accesso al DB: il router
carica RAL, benefit e part-time, qui si calcola e si aggrega.
"""
from collections.abc import Mapping

GIORNI_ANNO = 365
WEEKEND = 104

DEFAULTS = {
    "oneri_mult": 1.41,        # INPS + INAIL + TFR sulla RAL
    "premi_pct": 0.0,          # premi/MBO attesi, % RAL, soggetti a oneri
    "altri_costi": 2000.0,     # € annui a persona: postazione, PC, licenze, rimborsi non rifatturati
    "festivita_gg": 10.0,      # festività nazionali in giorno feriale, numero medio
    "festivita_extra_gg": 1.0, # patrono / chiusura aziendale
    "ferie_gg": 33.0,          # ferie + PAR/ROL/ex festività
    "malattia_gg": 5.0,        # assenze impreviste medie
    "formazione_pct": 5.0,     # quota dei giorni di presenza
    "interne_pct": 5.0,        # riunioni, pre-sales, attività interne
    "saturazione_pct": 100.0,  # quota venduta dei giorni fatturabili (< 100 recupera il bench)
}
META_KEYS = {k: f"listino_{k}" for k in DEFAULTS}
PCT_KEYS = ("premi_pct", "formazione_pct", "interne_pct", "saturazione_pct")
PROD_KEYS = ("formazione_pct", "interne_pct", "saturazione_pct")  # sovrascrivibili per persona
# limiti delle percentuali: la saturazione può superare il 100 (MLO, ore oltre lo standard)
PCT_MAX = {"premi_pct": 100.0, "formazione_pct": 100.0, "interne_pct": 100.0, "saturazione_pct": 200.0}


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).strip().replace(",", "."))
    except ValueError:
        return None


def parse_params(form: Mapping, saved: Mapping[str, str] | None = None) -> dict:
    """Parametri effettivi: form → salvati (app_meta) → DEFAULTS.

    Un campo vuoto o non numerico nel form ricade sul valore salvato.
    """
    saved = saved or {}
    p = {}
    for k, default in DEFAULTS.items():
        if k in form:
            v = _num(form.get(k))
            if v is not None:
                p[k] = v
                continue
        v = _num(saved.get(k))
        p[k] = v if v is not None else default
    return p


def validate_params(form: Mapping) -> tuple[dict, list[str]]:
    """Versione stretta per il salvataggio: ogni campo presente deve essere valido."""
    p, errors = {}, []
    for k, default in DEFAULTS.items():
        raw = form.get(k)
        if raw is None or str(raw).strip() == "":
            errors.append(f"{k}: mancante")
            continue
        v = _num(raw)
        if v is None:
            errors.append(f"{k}: non numerico")
            continue
        if k == "oneri_mult" and v <= 0:
            errors.append("oneri_mult: deve essere > 0")
        elif k in PCT_KEYS and not 0 <= v <= PCT_MAX[k]:
            errors.append(f"{k}: fuori da 0–{PCT_MAX[k]:g}")
        elif v < 0:
            errors.append(f"{k}: negativo")
        p[k] = v
    return p, errors


def params_to_meta(p: dict) -> dict[str, str]:
    """Valori da scrivere in app_meta (stringhe)."""
    return {meta_key: f"{p[k]:g}" for k, meta_key in META_KEYS.items()}


def giorni(p: dict) -> dict:
    """Dall'anno convenzionale (365 giorni, 104 weekend) ai giorni fatturabili di un full-time, con i passaggi."""
    fest_tot = p["festivita_gg"] + p["festivita_extra_gg"]
    lavorabili = GIORNI_ANNO - WEEKEND - fest_tot
    presenza = lavorabili - p["ferie_gg"] - p["malattia_gg"]
    fatturabili = fatturabili_fte(presenza, p["formazione_pct"], p["interne_pct"], p["saturazione_pct"])
    return {"giorni": GIORNI_ANNO, "weekend": WEEKEND, "festivita_tot": fest_tot,
            "lavorabili": lavorabili, "presenza": presenza, "fatturabili_fte": fatturabili}


def fatturabili_fte(presenza: float, formazione_pct: float, interne_pct: float,
                    saturazione_pct: float) -> float:
    """Giorni fatturabili di un full-time dai giorni di presenza.

    Prodotto prima, divisione dopo: con i default 215 × 90 × 100 / 10000 fa 193,5 esatto.
    """
    return presenza * (100 - formazione_pct - interne_pct) * saturazione_pct / 10000


def prod_persona(p: dict, override: Mapping | None) -> dict:
    """Produttività effettiva di una persona: override dove c'è, altrimenti il globale."""
    out = {k: p[k] for k in PROD_KEYS}
    if override:
        for k in PROD_KEYS:
            v = override.get(k)
            if v is not None:
                out[k] = float(v)
    return out


def costo_persona(ral: float | None, benefit: float | None, part_time_pct: float | None,
                  p: dict, g: dict, override: Mapping | None = None) -> dict:
    """Costo annuo e giornaliero di una persona; `motivo` spiega un costo_gg None.

    `override` porta formazione/interne/saturazione della persona (None = globale).
    """
    pt = 100.0 if part_time_pct is None else float(part_time_pct)
    prod = prod_persona(p, override)
    fatturabili = fatturabili_fte(g["presenza"], prod["formazione_pct"], prod["interne_pct"],
                                  prod["saturazione_pct"]) * pt / 100
    base = {"fatturabili": fatturabili, "prod": prod,
            "prod_custom": bool(override) and any(override.get(k) is not None for k in PROD_KEYS)}
    if ral is None:
        return {**base, "costo_annuo": None, "costo_gg": None, "motivo": "ral"}
    costo_annuo = ral * p["oneri_mult"] * (1 + p["premi_pct"] / 100) + (benefit or 0.0) + p["altri_costi"]
    if fatturabili <= 0:
        return {**base, "costo_annuo": costo_annuo, "costo_gg": None, "motivo": "giorni"}
    return {**base, "costo_annuo": costo_annuo, "costo_gg": costo_annuo / fatturabili, "motivo": None}


PROD_PREFIX = "pp_"  # i campi per persona nel form: pp_formazione_pct… (mai come i globali)


def parse_prod(form: Mapping) -> tuple[dict, list[str]]:
    """Override di produttività dal form (`pp_*`): vuoto = torna al globale, fuori limite = errore.

    Restituisce solo le chiavi presenti nel form: un input solo aggiorna solo sé stesso.
    """
    out, errors = {}, []
    for k in PROD_KEYS:
        if PROD_PREFIX + k not in form:
            continue
        raw = str(form.get(PROD_PREFIX + k) or "").strip()
        if not raw:
            out[k] = None
            continue
        v = _num(raw)
        if v is None or not 0 <= v <= PCT_MAX[k]:
            errors.append(k)
            continue
        out[k] = v
    return out, errors


def scostamento(tariffa: float | None, costo: float | None) -> dict | None:
    """Tariffa a listino meno costo/gg: delta in € e margine sul prezzo.

    None se manca uno dei due: nessun confronto, non zero.
    """
    if tariffa is None or costo is None:
        return None
    delta = tariffa - costo
    return {"delta": delta, "pct": delta / tariffa * 100 if tariffa else None}


def aggregate(rows: list[dict], key: str, label_key: str | None = None,
              carry: tuple = ()) -> list[dict]:
    """Per gruppo: n, n_escluse, min, media semplice, blended (Σcosti/Σgiorni), max.

    Le righe senza costo (RAL mancante, giorni nulli) contano in `n_escluse` e
    non toccano le medie: mai leggere zero dove il dato non c'è. L'ordine dei
    gruppi è quello di prima apparizione. `carry` copia dalla prima riga i
    campi che valgono per tutto il gruppo (es. la tariffa del codice).
    """
    groups: dict = {}
    for r in rows:
        k = r.get(key)
        g = groups.get(k)
        if g is None:
            g = groups[k] = {"key": k, "label": r.get(label_key) if label_key else None,
                             "n": 0, "n_escluse": 0, "min": None, "max": None,
                             "costi": 0.0, "giorni": 0.0, "_somma": 0.0,
                             **{c: r.get(c) for c in carry}}
        c = r.get("costo_gg")
        if c is None:
            g["n_escluse"] += 1
            continue
        g["n"] += 1
        g["_somma"] += c
        g["costi"] += r["costo_annuo"]
        g["giorni"] += r["fatturabili"]
        g["min"] = c if g["min"] is None else min(g["min"], c)
        g["max"] = c if g["max"] is None else max(g["max"], c)
    out = []
    for g in groups.values():
        g["media"] = g.pop("_somma") / g["n"] if g["n"] else None
        g["blended"] = g["costi"] / g["giorni"] if g["giorni"] > 0 else None
        out.append(g)
    return out
