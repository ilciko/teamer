# Teamer

Tool di gestione team per il COO (ruolo *Director*), con un *Site admin* IT che gestisce
utenti, audit, backup e aggiornamenti: organigramma, retribuzione (RAL, benefit,
budget, montepremi), valutazioni 9-box con coefficienti dinamici, ciclo annuale
obiettivi/review/benessere, note 1:1 e azioni.

- **Stack**: FastAPI + Jinja2 + htmx, SQLite cifrato con **SQLCipher** (chiave di sistema su file, nota solo all'IT; gli utenti entrano con la propria password), Python gestito da `uv`.
- **Schema dati**: tabelle append-only in 5 aree (organigramma, valutazioni, retribuzione, interazioni, utenti e audit) — vedi `docs/schema_team_tool.md` e il diagramma ER.
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
  `reset-password`, `unlock`, `enable`/`disable`, `list-users`, `restore`. Ogni azione finisce nell'audit come `cli`.

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

Fino alla 0.29 la password di login era la chiave del DB. Il passaggio richiede un intervento
dell'IT sul nodo Proxmox e, una volta sola, la password attuale del COO. Fino al passo 4 il DB
non viene modificato. Comandi dalla shell del nodo:

```bash
# 0. situazione di partenza: versione 0.29.x e data/teamer.db presente
pct exec <ctid> -- cat /opt/teamer/.version
pct exec <ctid> -- ls -l /opt/teamer/data/

# 1. aggiornamento: backup del DB in data/backups/, installa la 0.30 e riavvia.
#    Da qui l'app mostra «manca la chiave di sistema» (previsto)
pct exec <ctid> -- /usr/local/bin/teamer-update

# 2. seconda passata: «già alla versione più recente», ma installa teamer-admin
#    (il vecchio updater non lo conosceva)
pct exec <ctid> -- /usr/local/bin/teamer-update
pct exec <ctid> -- ls -l /usr/local/bin/teamer-admin

# 3. chiave di sistema: /etc/teamer/db.key (root:teamer 0640). Non serve riavviare il servizio
pct exec <ctid> -- /usr/local/bin/teamer-admin init
pct exec <ctid> -- ls -l /etc/teamer/
```

4. **Dal browser**, il COO ricarica Teamer: compare «Aggiornamento della cifratura». Inserisce la
   password di sempre e sceglie il suo nome utente → il DB viene ricifrato con la chiave e lui
   diventa il primo *Director*, con la stessa password (da cambiare subito se è più corta di 12
   caratteri: l'app lo porta su *Account*).

```bash
# 5. site admin: stampa una password provvisoria, da cambiare al primo accesso.
#    Verifica: con questo utente si apre solo Amministrazione, Persone dà 403
pct exec <ctid> -- /usr/local/bin/teamer-admin create-admin <nome>

# 6. copia della chiave fuori dal container (password manager o vault dell'IT)
pct exec <ctid> -- cat /etc/teamer/db.key
```

Se qualcosa non torna:

```bash
pct exec <ctid> -- systemctl status teamer --no-pager
pct exec <ctid> -- journalctl -u teamer -n 50 --no-pager
pct exec <ctid> -- /usr/local/bin/teamer-admin list-users
```

I backup fatti prima del passaggio (`data/backups/`) restano cifrati con la vecchia password;
quelli successivi si aprono con la chiave.

### Accesso perso

- **Password dimenticata**: il site admin la resetta da *Amministrazione → Utenti* (password
  provvisoria, mostrata una volta) o da shell con `teamer-admin reset-password <nome>`.
- **Troppi tentativi errati**: il blocco scade da solo dopo qualche minuto; prima lo toglie
  *Sblocca* nel pannello o `teamer-admin unlock <nome>`.
- **Nessun site admin utilizzabile**: `teamer-admin create-admin <nome>` o `reset-password`.
- **Chiave persa**: non c'è recupero. Servono la copia della chiave salvata fuori dal server
  oppure un backup vzdump del container che la contenga.

### Backup

- In-app (site admin): *Amministrazione → Sistema → Scarica backup cifrato* (copia consistente via `VACUUM INTO`, cifrata con la chiave di sistema).
- Proxmox: i normali backup vzdump del container coprono tutto (`/opt/teamer/data` e `/etc/teamer/db.key`).
- La chiave va salvata **anche** fuori dal container: un backup del solo DB senza chiave è illeggibile.

### Ripristino e import da un'altra istanza

*Amministrazione → Sistema → Ripristino e import* (o `teamer-admin restore FILE`) sostituisce
**tutti i dati** con quelli di un file: un backup di questa istanza, un DB di un'altra istanza 0.30
(serve la sua chiave) o un DB della 0.29 (serve la password di allora). **Utenti e audit restano
quelli dell'istanza**: chi ripristina non resta chiuso fuori. Il file viene verificato
(`integrity_check`, che sia un DB di Teamer, non più recente di questa versione), ricifrato con la
chiave dell'istanza e migrato; prima dello scambio il DB attuale va in
`data/backups/teamer-pre-ripristino-*.db`. L'evento finisce nell'audit.

Import una tantum da un'altra istanza, dal nodo Proxmox:

```bash
# sul nodo di ORIGINE: copia consistente del DB (servizio fermo per un attimo)
pct exec <ct-origine> -- systemctl stop teamer
pct pull <ct-origine> /opt/teamer/data/teamer.db /root/teamer-origine.db
pct exec <ct-origine> -- systemctl start teamer
# (se i nodi sono diversi: scp /root/teamer-origine.db root@<nodo-destinazione>:/root/)

# sul nodo di DESTINAZIONE: dentro il container e ripristino. Il servizio si ferma e riparte da solo
pct push <ct-destinazione> /root/teamer-origine.db /root/teamer-origine.db
pct exec <ct-destinazione> -- /usr/local/bin/teamer-admin restore /root/teamer-origine.db --password
#   --password    origine 0.29: chiede la password del DB di allora
#   --source-key  origine 0.30: chiede la chiave dell'origine (cat /etc/teamer/db.key sull'origine)
pct exec <ct-destinazione> -- rm /root/teamer-origine.db
rm /root/teamer-origine.db
```

In alternativa si scarica il file sul proprio computer e lo si carica dal pannello.

## Struttura

```
app/            FastAPI: routers/ services/ templates/ static/
migrations/     SQL numerati, applicati all'avvio (schema_version in app_meta)
scripts/        seed_demo.py (+ app/admin_cli.py: amministrazione da shell)
tests/          pytest (servizi di calcolo, cifratura, migrazioni, utenti e ruoli)
deploy/         ct/teamer.sh (Proxmox host) · install/ (container: installer, teamer-update, teamer-admin) · systemd
docs/           schema dati, ER, proposte, modulo review, artefatto 9-box
```

## Licenza

Apache License 2.0 — vedi [LICENSE](LICENSE) e [NOTICE](NOTICE).
