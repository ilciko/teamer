"""Listino: costo giornaliero di vendita.

Costo azienda annuo diviso per i giorni fatturabili dell'anno. Il moltiplicatore
oneri copre INPS, INAIL e TFR: l'IRAP resta fuori perché dal 2015 il costo del
lavoro a tempo indeterminato è interamente deducibile. Il calendario è quello
vero dell'anno scelto (weekend e festività nazionali in giorno feriale), non
una stima fissa. Nessun accesso al DB: il router carica RAL, benefit e
part-time, qui si calcola e si aggrega.
"""
from collections.abc import Mapping
from datetime import date, timedelta

# festività nazionali a data fissa (mese, giorno); il lunedì dell'Angelo si calcola
FESTIVITA_FISSE = ((1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15),
                   (11, 1), (12, 8), (12, 25), (12, 26))

DEFAULTS = {
    "oneri_mult": 1.41,        # INPS + INAIL + TFR sulla RAL
    "premi_pct": 0.0,          # premi/MBO attesi, % RAL, soggetti a oneri
    "altri_costi": 2000.0,     # € annui a persona: postazione, PC, licenze, rimborsi non rifatturati
    "festivita_gg": None,      # None = festività feriali dal calendario dell'anno
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


def pasqua(anno: int) -> date:
    """Domenica di Pasqua (algoritmo di Meeus/Jones/Butcher)."""
    a, b, c = anno % 19, anno // 100, anno % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    mese = (h + m - 7 * n + 114) // 31
    giorno = (h + m - 7 * n + 114) % 31 + 1
    return date(anno, mese, giorno)


def festivita(anno: int) -> list[date]:
    """Le 11 festività nazionali dell'anno, ordinate."""
    out = [date(anno, m, d) for m, d in FESTIVITA_FISSE]
    out.append(pasqua(anno) + timedelta(days=1))
    return sorted(out)


def calendario(anno: int) -> dict:
    """Giorni dell'anno, weekend e festività contate davvero sul calendario."""
    primo = date(anno, 1, 1)
    giorni = (date(anno, 12, 31) - primo).days + 1
    weekend = sum(1 for n in range(giorni) if (primo + timedelta(days=n)).weekday() >= 5)
    fest = festivita(anno)
    feriali = sum(1 for f in fest if f.weekday() < 5)
    return {"giorni": giorni, "weekend": weekend,
            "festivita_feriali": feriali, "festivita_weekend": len(fest) - feriali}


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).strip().replace(",", "."))
    except ValueError:
        return None


def parse_params(form: Mapping, saved: Mapping[str, str] | None = None) -> dict:
    """Parametri effettivi: form → salvati (app_meta) → DEFAULTS.

    Un campo vuoto o non numerico nel form ricade sul valore salvato; per
    `festivita_gg` il vuoto è una scelta («dal calendario») e resta None.
    """
    saved = saved or {}
    p = {}
    for k, default in DEFAULTS.items():
        if k in form:
            v = _num(form.get(k))
            if v is not None or k == "festivita_gg":
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
            if k == "festivita_gg":
                p[k] = None
                continue
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
    """Valori da scrivere in app_meta (stringhe; festività automatiche = '')."""
    out = {}
    for k, meta_key in META_KEYS.items():
        v = p.get(k)
        out[meta_key] = "" if v is None else f"{v:g}"
    return out


def giorni(anno: int, p: dict) -> dict:
    """Dai giorni dell'anno ai giorni fatturabili di un full-time, con i passaggi."""
    cal = calendario(anno)
    auto = p["festivita_gg"] is None
    fest_base = cal["festivita_feriali"] if auto else p["festivita_gg"]
    fest_tot = fest_base + p["festivita_extra_gg"]
    lavorabili = cal["giorni"] - cal["weekend"] - fest_tot
    presenza = lavorabili - p["ferie_gg"] - p["malattia_gg"]
    fatturabili = fatturabili_fte(presenza, p["formazione_pct"], p["interne_pct"], p["saturazione_pct"])
    return {**cal, "festivita_auto": auto, "festivita_base": fest_base, "festivita_tot": fest_tot,
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
