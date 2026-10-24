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
- **Ruoli**: *Site admin* (IT: utenti, audit, backup, aggiornamenti; nessun dato del personale),
  *Director* (i suoi team e le loro persone) e *HR* (dalla 0.36: vede le persone di tutti i
  director; scrive le sue note e azioni, il resto per ora in sola lettura: le altre modifiche di
  HR arrivano nelle versioni successive). Note 1:1 e azioni sono di chi le scrive: nessuno legge
  quelle degli altri.
  Password di almeno 12 caratteri, hash scrypt; dopo 5 errori l'utente è bloccato per qualche
  minuto (lo sblocca l'admin).
- **Sessioni**: il DB resta aperto finché gira il servizio; ogni utente si blocca quando chiude la
  sua ultima pagina Teamer e riprende in place con la password. Il blocco di uno non tocca gli altri.
- **Audit** (*Amministrazione → Audit*): accessi, errori, blocchi, gestione utenti, backup,
  aggiornamenti e ogni azione che modifica dati (chi, quando, quale indirizzo; mai il contenuto).
- **Director separati** (`docs/perimetri.md`): ogni director vede solo i suoi team e le persone che
  ci lavorano, con tutto il loro storico; ha la sua configurazione (questionario 9-box, aggiustamenti,
  pesi e moltiplicatori premio, listino, soglie: parte da quella di default), i suoi cicli, budget,
  montepremi e simulazioni.
- **Configurazione aziendale** (*Azienda*, oggi del site admin, poi di HR): liste valori, catalogo
  benefit e CCNL predefinito, uguali per tutti i director. Il site admin assegna i team e li trasferisce da un
  director all'altro (*Amministrazione → Team*, vede solo i nomi): le persone passano con lo storico,
  a chi cede non resta nulla di loro; budget e montepremi non si spostano. La separazione la applica
  il database stesso (viste, guardie e authorizer per sessione), non le singole pagine; resta
  visibile solo quante righe ha una tabella in totale, mai il loro contenuto.
- **`teamer-admin`** (root, sul container): `init`, `create-admin`, `create-user --role [--person]`,
  `link-person`/`unlink-person`, `reset-password`, `unlock`, `enable`/`disable`, `list-users`,
  `assign-unassigned`, `list-teams`, `restore`. Ogni azione finisce nell'audit come `cli`. Un utente
  director si collega alla persona Director+ che lo rappresenta (anche dal pannello). Una persona passa a un altro director per
  mano di HR, dalla pagina Persone (nel team «Da collocare» del destinatario).

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
`NET_IP` (dhcp o CIDR), `GATEWAY`, `BRIDGE2`, `VLAN2`, `NET_IP2`, `GATEWAY2` (seconda rete, vedi sotto),
`APP_PORT`; `NONINTERACTIVE=1` salta le domande, `DRY_RUN=1` mostra cosa verrebbe creato senza toccare
nulla. Per un fork `GH_REPO=<owner>/teamer` (e `GH_TOKEN` solo se il fork è privato).

### Container su due reti

Se il container deve rispondere da due reti (es. la LAN dei colleghi e una rete raggiunta in VPN),
nel riepilogo si sceglie una **Seconda rete** (bridge, VLAN, IP DHCP o statico con gateway): diventa
`eth1`. Il kernel ha un solo default gateway, quindi senza altro chi arriva dalla seconda rete da
un'altra subnet riceverebbe la risposta dalla prima scheda e non la vedrebbe mai: il servizio è
vivo, i colleghi sulla rete «giusta» lavorano, da fuori nemmeno il ping risponde. Per questo
l'installer mette nel container `/usr/local/sbin/teamer-multihome` (una tabella di routing per
interfaccia, scelta in base all'indirizzo sorgente) con un hook dhclient che la aggiorna a ogni
lease; con IP statico la richiama `post-up` in `/etc/network/interfaces`, che Proxmox conserva
quando rigenera la sezione. Il gateway della seconda rete **non** va nella configurazione del
container (`gw=`): due default in `interfaces` fanno fallire `ifup`.

Su un container esistente a cui si aggiunge una scheda dalla console di Proxmox:

```bash
pct exec <ctid> -- install -m 755 /opt/teamer/src/deploy/install/teamer-multihome /usr/local/sbin/teamer-multihome
pct exec <ctid> -- install -m 644 /opt/teamer/src/deploy/install/teamer-multihome.dhclient /etc/dhcp/dhclient-exit-hooks.d/teamer-multihome
pct exec <ctid> -- bash -c 'ifdown eth1; ifup eth1'     # DHCP; statico: post-up/pre-down come sopra
```

Da lì `teamer-update` tiene aggiornati i due file; su un container che non li ha non li aggiunge mai.

### Dimensionamento

Teamer è un solo processo (uvicorn) con un DB SQLite: le risorse servono per il sistema, i backup
e gli allegati, molto meno per gli utenti. Misure su 500 persone (20 director × 25 persone, 5 RAL
e 10 note a persona):

| Voce | Misura |
|---|---|
| Memoria del processo | ~75 MB all'avvio, ~100 MB con un director collegato, ~125 MB con 20 |
| Memoria per sessione aperta | ~1,5 MB (connessione con viste e guardie del perimetro) |
| Tempo di risposta | mediana 4 ms, la pagina più lenta (ricerca note) ~50 ms |
| Database | ~7 KB a persona, **più gli allegati** (salvati dentro il DB) |

Il disco serve soprattutto alle copie: `teamer-update` tiene gli ultimi 5 backup del DB, più i
backup scaricati e le copie fatte prima di un ripristino. Regola pratica: sistema e runtime ~1,5 GB,
più **8 volte la dimensione del DB**.

| Uso | vCPU | RAM | Disco |
|---|---|---|---|
| fino a 10 director, ~500 persone, pochi allegati (default dello script) | 1 | 1 GB | 4 GB |
| fino a 30 director, ~2.000 persone | 1–2 | 1 GB | 8 GB |
| allegati frequenti (review in PDF per tutti, ogni anno) | come sopra | 1 GB | 1,5 GB + 8 × DB (es. DB da 1 GB → 10 GB) |

Più CPU servono poco: le richieste sono brevi e SQLite scrive una volta alla volta. La seconda
vCPU aiuta solo nelle operazioni lunghe (import Excel, report, aggiornamento) mentre altri lavorano.
Teamer gira come un solo processo per scelta (le sessioni stanno in memoria): non si scala
aggiungendo repliche. Il disco di un LXC si allarga anche dopo, da Proxmox (`pct resize <ctid>
rootfs +4G`), senza fermare Teamer.

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

### Passaggio alla 0.32: dati da assegnare

Dopo l'aggiornamento alla 0.32 configurazione, team, cicli, budget, montepremi e simulazioni
esistenti **non appartengono a nessun director** e nessuno li vede. Il site admin li assegna in
*Amministrazione → Utenti → Dati da assegnare* (o `teamer-admin assign-unassigned <nome>`) al
director che deve riceverli. Gli altri director partono dalla configurazione di default.
Lo stesso succede dopo un ripristino da un'altra istanza.

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
