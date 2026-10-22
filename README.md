# Teamer

Tool di gestione team per il COO (ruolo *Director*), con un *Site admin* IT che gestisce
utenti, audit, backup e aggiornamenti: organigramma, retribuzione (RAL, benefit,
budget, montepremi), valutazioni 9-box con coefficienti dinamici, ciclo annuale
obiettivi/review/benessere, note 1:1 e azioni.

- **Stack**: FastAPI + Jinja2 + htmx, SQLite cifrato con **SQLCipher** (chiave di sistema su file, nota solo all'IT; gli utenti entrano con la propria password), Python gestito da `uv`.
- **Schema dati**: 28 tabelle append-only — vedi `docs/schema_team_tool.md` e il diagramma ER.
- **Nessuna risorsa esterna a runtime**: font, htmx e Chart.js sono vendored in `app/static/`.

## Sviluppo (Mac)

```bash
brew install uv sqlcipher
make setup          # uv sync (su mac sqlcipher3 compila contro brew sqlcipher)
make seed           # DB demo con 10 persone (utenti coo / admin, password demo12345678)
make dev            # http://127.0.0.1:8000
make test           # pytest
```

Se la build di `sqlcipher3` non trova le librerie:
`CFLAGS="-I$(brew --prefix sqlcipher)/include" LDFLAGS="-L$(brew --prefix sqlcipher)/lib" make setup`

In sviluppo la chiave del DB sta in `data/dev.key` (`make key`, la creano già `make dev` e
`make seed`). Le password degli utenti non cifrano niente: se una si perde, il site admin ne
assegna una provvisoria (*Amministrazione → Utenti*, o `python -m app.admin_cli reset-password <nome>`).

## Utenti, chiave e sicurezza

- **Chiave di sistema** (`TEAMER_DB_KEY_FILE`, in produzione `/etc/teamer/db.key`, root:teamer 0640):
  32 byte casuali che cifrano `data/teamer.db`. La conosce solo l'IT, l'app non la mostra mai.
  **Perderla = perdere i dati**: conservane una copia fuori dal server. I backup del DB si aprono
  solo con questa chiave.
- **Ruoli**: *Site admin* (IT: utenti, audit, backup, aggiornamenti; nessun dato del personale) e
  *Director* (il COO: tutto il resto). Password di almeno 12 caratteri, hash scrypt; dopo 5 errori
  l'utente è bloccato per qualche minuto (lo sblocca l'admin).
- **Sessioni**: il DB resta aperto finché gira il servizio; ogni utente si blocca quando chiude la
  sua ultima pagina Teamer e riprende in place con la password. Il blocco di uno non tocca gli altri.
- **Audit** (*Amministrazione → Audit*): accessi, errori, blocchi, gestione utenti, backup,
  aggiornamenti e ogni azione che modifica dati (chi, quando, quale indirizzo; mai il contenuto).
- **`teamer-admin`** (root, sul container): `init`, `create-admin`, `create-user --role`,
  `reset-password`, `unlock`, `enable`/`disable`, `list-users`. Ogni azione finisce nell'audit come `cli`.

## Produzione (LXC su Proxmox)

Dalla shell del nodo Proxmox:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/ilciko/teamer/main/deploy/ct/teamer.sh)"
```

Lo script crea un LXC Debian 13 unprivileged (1 vCPU / 1 GB / 4 GB), installa l'app in
`/opt/teamer` (codice in `src/`, DB in `data/`, config in `.env`), crea il servizio
systemd `teamer` (utente non-root, hardening), genera la chiave del DB e stampa l'IP interno
e le **credenziali provvisorie del primo site admin**.
L'app espone **HTTP semplice sulla porta 8080**: va messa dietro un reverse proxy
che termina il TLS.

Da terminale lo script mostra un riepilogo (whiptail) con i valori rilevati sul nodo: primo CTID
libero, storage per il disco e per il template, bridge. **Crea** per procedere, **Modifica** per
sceglierli uno per uno (storage e bridge da elenco, IP DHCP o statico con gateway, VLAN, risorse,
porta). Le stesse impostazioni si passano come variabili d'ambiente, che fanno da valore proposto:
`CTID`, `CT_HOSTNAME`, `DISK_GB`, `RAM_MB`, `CORES`, `STORAGE`, `TEMPLATE_STORAGE`, `BRIDGE`, `VLAN`,
`NET_IP` (dhcp o CIDR), `GATEWAY`, `APP_PORT`; `NONINTERACTIVE=1` salta le domande, `DRY_RUN=1`
mostra cosa verrebbe creato senza toccare nulla. Per un fork `GH_REPO=<owner>/teamer` (e `GH_TOKEN`
solo se il fork è privato).

### Aggiornamenti

- **Dall'app** (site admin): *Amministrazione → Aggiornamenti*. Una volta al giorno l'app controlla l'ultima
  release e lo segnala nella barra laterale; "Aggiorna" fa partire l'aggiornamento senza
  accesso al nodo Proxmox. L'app non ha privilegi: scrive `data/update/request` e la path unit
  systemd `teamer-update.path` lancia `teamer-update` come root.
- **Da riga di comando**: `pct exec <ctid> -- /usr/local/bin/teamer-update` dal nodo Proxmox.

`teamer-update` scarica l'ultima release, copia il DB in `data/backups/` (ultimi 5), ricrea il
venv e riavvia il servizio; `.env`, i dati e la chiave non vengono toccati e le migrazioni di
schema si applicano al riavvio. Se `uv sync` fallisce, ripristina la versione precedente.

### Passaggio dalla versione mono-utente (≤ 0.29) alla 0.30

Fino alla 0.29 la password di login era la chiave del DB. Dopo l'aggiornamento alla 0.30:

1. l'app mostra «manca la chiave di sistema»;
2. sul nodo: `pct exec <ctid> -- /usr/local/bin/teamer-update` una seconda volta (il vecchio
   updater non installa ancora `teamer-admin`; la seconda passata sì), poi
   `pct exec <ctid> -- /usr/local/bin/teamer-admin init` → crea `/etc/teamer/db.key`;
3. il COO apre Teamer: inserisce la password di sempre e sceglie il suo nome utente → il DB viene
   ricifrato con la chiave e lui diventa il primo *Director*, con la stessa password (da cambiare
   se è più corta di 12 caratteri);
4. `pct exec <ctid> -- /usr/local/bin/teamer-admin create-admin <nome>` → site admin con password
   provvisoria.

I backup fatti prima del passaggio (`data/backups/`) restano cifrati con la vecchia password.

### Backup

- In-app (site admin): *Amministrazione → Sistema → Scarica backup cifrato* (copia consistente via `VACUUM INTO`, cifrata con la chiave di sistema).
- Proxmox: i normali backup vzdump del container coprono tutto (`/opt/teamer/data` e `/etc/teamer/db.key`).
- La chiave va salvata **anche** fuori dal container: un backup del solo DB senza chiave è illeggibile.

## Struttura

```
app/            FastAPI: routers/ services/ templates/ static/
migrations/     SQL numerati, applicati all'avvio (schema_version in app_meta)
scripts/        seed_demo.py (+ app/admin_cli.py: amministrazione da shell)
tests/          pytest (servizi di calcolo, cifratura, migrazioni)
deploy/         ct/teamer.sh (Proxmox host) · install/ (container) · systemd
docs/           schema dati, ER, proposte, modulo review, artefatto 9-box
```

## Licenza

Apache License 2.0 — vedi [LICENSE](LICENSE) e [NOTICE](NOTICE).
