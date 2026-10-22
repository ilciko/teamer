"""Configurazione da variabili d'ambiente, con .env opzionale."""
import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:  # marca gli asset: dopo un update il browser non può servire il CSS vecchio
    APP_VERSION = version("teamer")
except PackageNotFoundError:  # sorgenti non installati (test, script)
    APP_VERSION = "dev"


def _load_dotenv() -> None:
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

DB_PATH = Path(os.environ.get("TEAMER_DB_PATH", BASE_DIR / "data" / "teamer.db"))
# Chiave di sistema del DB: la conosce solo l'IT (file root:teamer 0640), gli utenti mai.
# Sta fuori da data/ perché i backup del DB non viaggino insieme alla chiave.
DB_KEY_FILE = Path(os.environ.get("TEAMER_DB_KEY_FILE", "/etc/teamer/db.key"))
HOST = os.environ.get("TEAMER_HOST", "127.0.0.1")
PORT = int(os.environ.get("TEAMER_PORT", "8000"))
SECRET = os.environ.get("TEAMER_SECRET", "dev-secret-non-usare-in-produzione")
# Sessione: nessun timeout di inattività. Il DB resta aperto finché almeno una
# pagina Teamer manda il suo battito; si blocca quando l'ultima si chiude.
HEARTBEAT_SECONDS = int(os.environ.get("TEAMER_HEARTBEAT_SECONDS", "20"))
LOCK_GRACE_SECONDS = int(os.environ.get("TEAMER_LOCK_GRACE_SECONDS", "90"))
AUTOLOCK = os.environ.get("TEAMER_AUTOLOCK", "1").lower() not in ("0", "false", "no")
REAPER_TICK_SECONDS = 5
# una sessione bloccata (overlay di sblocco) dopo quanto viene dimenticata del tutto
LOCKED_SESSION_HOURS = int(os.environ.get("TEAMER_LOCKED_SESSION_HOURS", "12"))
# controllo giornaliero dell'ultima release (solo avviso; l'aggiornamento si lancia a mano)
UPDATE_CHECK = os.environ.get("TEAMER_UPDATE_CHECK", "1").lower() not in ("0", "false", "no")
