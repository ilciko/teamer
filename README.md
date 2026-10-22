# Teamer

Tool di gestione team mono-utente (COO): organigramma, retribuzione (RAL, benefit,
budget, montepremi), valutazioni 9-box con coefficienti dinamici, ciclo annuale
obiettivi/review/benessere, note 1:1 e azioni.

- **Stack**: FastAPI + Jinja2 + htmx, SQLite cifrato con **SQLCipher** (passphrase = password di login), Python gestito da `uv`.
- **Schema dati**: 28 tabelle append-only — vedi `docs/schema_team_tool.md` e il diagramma ER.
- **Nessuna risorsa esterna a runtime**: font, htmx e Chart.js sono vendored in `app/static/`.

## Sviluppo (Mac)

```bash
brew install uv sqlcipher
make setup          # uv sync (su mac sqlcipher3 compila contro brew sqlcipher)
make seed           # DB demo con 10 persone (password: demo1234)
make dev            # http://127.0.0.1:8000
make test           # pytest
```

Se la build di `sqlcipher3` non trova le librerie:
`CFLAGS="-I$(brew --prefix sqlcipher)/include" LDFLAGS="-L$(brew --prefix sqlcipher)/lib" make setup`

Al primo avvio senza DB l'app chiede di creare la password: quella password **è** la
chiave di cifratura del file (`data/teamer.db`). Non esiste recupero password.

## Produzione (LXC su Proxmox)

Dalla shell del nodo Proxmox:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/ilciko/teamer/main/deploy/ct/teamer.sh)"
```

Lo script crea un LXC Debian 13 unprivileged (1 vCPU / 1 GB / 4 GB), installa l'app in
`/opt/teamer` (codice in `src/`, DB in `data/`, config in `.env`), crea il servizio
systemd `teamer` (utente non-root, hardening) e stampa l'IP interno.
L'app espone **HTTP semplice sulla porta 8080**: va messa dietro un reverse proxy
che termina il TLS.

Variabili opzionali: `CTID`, `HOSTNAME`, `DISK_GB`, `RAM_MB`, `CORES`, `BRIDGE`,
`NET_IP` (dhcp o CIDR), `GATEWAY`, `STORAGE`, `APP_PORT`; per un fork `GH_REPO=<owner>/teamer`
(e `GH_TOKEN` solo se il fork è privato).

### Aggiornamenti

- **Dall'app**: *Configurazione → Aggiornamenti*. Una volta al giorno l'app controlla l'ultima
  release e lo segnala nella barra laterale; "Aggiorna" fa partire l'aggiornamento senza
  accesso al nodo Proxmox. L'app non ha privilegi: scrive `data/update/request` e la path unit
  systemd `teamer-update.path` lancia `teamer-update` come root.
- **Da riga di comando**: `pct exec <ctid> -- /usr/local/bin/teamer-update` dal nodo Proxmox.

`teamer-update` scarica l'ultima release, copia il DB in `data/backups/` (ultimi 5), ricrea il
venv e riavvia il servizio; `.env` e i dati non vengono toccati e le migrazioni di schema si
applicano al successivo sblocco. Se `uv sync` fallisce, ripristina la versione precedente.

### Backup

- In-app: *Configurazione → Sicurezza → Scarica backup cifrato* (copia consistente via `VACUUM INTO`, ancora cifrata).
- Proxmox: i normali backup vzdump del container coprono tutto (`/opt/teamer/data`).

## Struttura

```
app/            FastAPI: routers/ services/ templates/ static/
migrations/     SQL numerati, applicati all'avvio (schema_version in app_meta)
scripts/        seed_demo.py
tests/          pytest (servizi di calcolo, cifratura, migrazioni)
deploy/         ct/teamer.sh (Proxmox host) · install/ (container) · systemd
docs/           schema dati, ER, proposte, modulo review, artefatto 9-box
```

## Licenza

Apache License 2.0 — vedi [LICENSE](LICENSE) e [NOTICE](NOTICE).
