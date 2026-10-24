"""Aggiornamenti: versione installata contro ultima release pubblicata, richiesta all'updater.

L'app gira senza privilegi (systemd: utente `teamer`, filesystem in sola lettura tranne
`data/`), l'aggiornamento invece richiede root. Quindi l'app non aggiorna: **chiede**,
scrivendo `data/update/request`; la path unit `teamer-update.path` (root) lo vede e lancia
`teamer-update`, che scrive stato e log in `data/update/` (vedi deploy/install/).

Il controllo della versione (`check`) interroga l'API pubblica di GitHub e salva il risultato
in `data/update/latest.json`: un file e non `app_meta`, perché gira anche di notte, quando il DB
è bloccato. Offline o in errore non succede niente: l'app resta utilizzabile senza rete.

Canali (0.47.1, `data/update/channel`, scelto dall'admin): `stable` = l'ultima Release pubblicata
(il default, per la produzione); `tag` = il tag più alto, anche senza Release (anteprima: gli
incrementi intermedi arrivano subito, per l'istanza di test). Lo legge anche `teamer-update`.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path

from app import config

REPO = os.environ.get("TEAMER_UPDATE_REPO", "ilciko/teamer")
# la path unit installata da deploy/install: senza, l'aggiornamento dall'app non è possibile
UNIT_FILE = Path(os.environ.get("TEAMER_UPDATE_UNIT", "/etc/systemd/system/teamer-update.path"))
CHECK_INTERVAL_SECONDS = 24 * 3600
FIRST_CHECK_DELAY_SECONDS = 60


def update_dir() -> Path:
    return config.DB_PATH.parent / "update"


CHANNELS = {"stable": "Stabile — release pubblicate", "tag": "Anteprima — ultimo tag, anche senza release"}


def channel() -> str:
    try:
        c = (update_dir() / "channel").read_text().strip()
    except OSError:
        return "stable"
    return c if c in CHANNELS else "stable"


def set_channel(c: str) -> None:
    if c not in CHANNELS:
        raise ValueError(c)
    update_dir().mkdir(parents=True, exist_ok=True)
    (update_dir() / "channel").write_text(c + "\n")


# ---- versioni ----

def parse_version(s) -> tuple[int, int, int] | None:
    """'v0.29.0' / '0.29.0' → (0, 29, 0); tutto il resto (dev, main-…) → None."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(s or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def is_newer(candidate, current) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    return bool(a and b and a > b)


def parse_release(payload) -> dict | None:
    """Risposta di /releases/latest → {tag, url, name, published_at}; None se non utilizzabile."""
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        return None
    tag = payload.get("tag_name")
    if not parse_version(tag):
        return None
    return {"tag": tag, "url": payload.get("html_url"), "name": payload.get("name") or tag,
            "published_at": payload.get("published_at")}


def parse_tags(payload) -> dict | None:
    """Risposta di /tags → il tag più alto in versione (v0.47.1 > v0.47.0 > v0.46.2); None se nessuno."""
    if not isinstance(payload, list):
        return None
    best = max((t.get("name") for t in payload if isinstance(t, dict) and parse_version(t.get("name"))),
               key=parse_version, default=None)
    if not best:
        return None
    return {"tag": best, "url": f"https://github.com/{REPO}/releases/tag/{best}", "name": best, "published_at": None}


# ---- file di stato ----

def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def latest() -> dict | None:
    """Esito dell'ultimo controllo: {checked_at, tag?, url?, error?}."""
    return _read_json(update_dir() / "latest.json")


def state() -> dict | None:
    """Ultimo aggiornamento scritto dall'updater: {status: running|ok|error, from, to, started, finished, message}."""
    return _read_json(update_dir() / "state.json")


def log_tail(lines: int = 40) -> str:
    try:
        return "\n".join((update_dir() / "update.log").read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def backups() -> list[dict]:
    """Copie del DB fatte da teamer-update prima di ogni aggiornamento (le più recenti prima)."""
    folder = config.DB_PATH.parent / "backups"
    try:
        files = sorted(folder.glob("teamer-*.db"), key=lambda f: f.stat().st_mtime, reverse=True)
    except OSError:
        return []
    return [{"name": f.name, "at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
             "size_kb": round(f.stat().st_size / 1024)} for f in files]


def available(current: str | None = None) -> dict | None:
    """La release più nuova dell'installata, se il controllo ne ha trovata una."""
    info = latest()
    if info and info.get("tag") and is_newer(info["tag"], current or config.APP_VERSION):
        return info
    return None


# ---- controllo e richiesta ----

def _fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"teamer/{config.APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 (URL fisso https)
        return json.loads(r.read().decode())


def check(fetch=None) -> dict:
    """Interroga l'ultima versione del canale e salva l'esito; in errore tiene l'ultima nota."""
    now = datetime.now().isoformat(timespec="seconds")
    ch = channel()
    if ch == "tag":
        url, parse = f"https://api.github.com/repos/{REPO}/tags?per_page=100", parse_tags
    else:
        url, parse = f"https://api.github.com/repos/{REPO}/releases/latest", parse_release
    previous = latest() or {}
    try:
        release = parse((fetch or _fetch)(url))
    except Exception as exc:  # rete assente, rate limit, JSON strano: non è un problema dell'app
        result = {**{k: previous[k] for k in ("tag", "url", "name", "published_at") if k in previous},
                  "checked_at": now, "channel": ch, "error": str(exc)[:200]}
    else:
        result = {"checked_at": now, "channel": ch, **(release or {"tag": None})}
    try:
        _write_json(update_dir() / "latest.json", result)
    except OSError:
        pass
    return result


def can_request() -> bool:
    """L'aggiornamento dall'app funziona solo dove l'installer ha messo la path unit."""
    return UNIT_FILE.exists()


def pending() -> bool:
    """Richiesta già fatta o aggiornamento in corso."""
    st = state() or {}
    return (update_dir() / "request").exists() or st.get("status") == "running"


def request_update() -> bool:
    if not can_request() or pending():
        return False
    _write_json(update_dir() / "request", {"requested_at": datetime.now().isoformat(timespec="seconds"),
                                           "from": config.APP_VERSION})
    return True
