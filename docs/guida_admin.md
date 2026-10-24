# Guida del site admin — Teamer 0.47.4

Il site admin è l'IT che gestisce l'istanza: utenti, registro attività, backup, ripristini e aggiornamenti. **Non vede i dati del personale**, con un'unica eccezione: i nomi delle persone con ruolo Director+, per collegarle agli utenti director. Le configurazioni aziendali (liste, benefit, CCNL, listino) e gli spostamenti di persone sono di HR.

Guide degli altri profili: [HR](guida_hr.md) · [Director](guida_director.md).

## Accesso

- Dopo il login si arriva su **Amministrazione**. Le altre pagine dell'app rispondono «Pagina non disponibile» con il pulsante «Vai alla tua pagina iniziale →».
- In fondo alla barra laterale: «👤 *utente* · Site admin» apre **Account** (cambio password), **Esci** chiude la propria sessione.
- Quando c'è una versione più nuova compare il pulsante **↑ Aggiornamento vX.Y.Z**, che porta al tab Aggiornamenti.

La pagina Amministrazione ha quattro tab: **Utenti**, **Audit**, **Sistema**, **Aggiornamenti** (con « ●» se c'è una versione nuova).

## Utenti

### Ruoli

| Ruolo | Cosa fa |
| --- | --- |
| Site admin | Solo il pannello Amministrazione e il proprio account |
| Director | Gestisce i propri team; è collegato alla persona che lo rappresenta in organigramma |
| HR | Vede le persone di tutti i director; contratti, RAL, cessazioni, configurazione aziendale |

Gli utenti **non si cancellano**: si correggono e si disattivano (l'audit continua a puntare a loro). Deve restare sempre almeno un site admin attivo, e non si può disattivare il proprio utente.

### Creare un utente

Riquadro **Nuovo utente**: «Nome utente» (senza spazi, max 64 caratteri), «Ruolo», «Nome visualizzato» e, per un director, «Persona (Director+ non ancora collegata)». Pulsante **Crea utente**.

- L'utente nasce con una **password provvisoria di 16 caratteri, mostrata una volta sola** in cima alla pagina: comunicala all'utente. Al primo accesso dovrà cambiarla (minimo 12 caratteri).
- Un director va collegato alla sua persona: sono collegabili le persone attive con ruolo «Senior Manager / Director+» nell'assegnazione corrente e senza un altro utente. Se non ce n'è nessuna («Nessuna persona Director+ libera»), HR deve prima censirla con quel ruolo; il collegamento si fa poi da **Gestisci**.

### Gestisci (per ogni utente)

| Azione | Effetto |
| --- | --- |
| **Correggi** (nome visualizzato, ruolo) | Un cambio di ruolo chiude le sessioni dell'utente; un director che cambia ruolo viene scollegato dalla persona |
| **Collega / Aggiorna** (Persona Director+) | Collega il director alla persona; «— nessuna —» lo scollega |
| **Reset password** | Nuova password provvisoria, mostrata una volta; chiude le sessioni e toglie il blocco |
| **Sblocca** | Azzera errori e blocco per troppi tentativi |
| **Chiudi sessioni** | Chiude le sessioni aperte dell'utente |
| **Disattiva / Riattiva** | Un utente disattivato non può entrare; le sessioni si chiudono subito |
| **Audit** | Apre il registro filtrato su quell'utente |

Una persona collegata a un utente director **non si sposta** ad altro director né si cessa finché non la scolleghi.

La tabella mostra per ogni utente stato («attivo», «bloccato (N errori)», «disattivato»), ultimo accesso, password («da cambiare» o data dell'ultimo cambio) e sessioni attive o bloccate.

### Dati da assegnare

Il riquadro compare solo se nel database ci sono dati senza proprietario (dopo il passaggio alla 0.32 o un ripristino da un'altra istanza): finché non li assegni non li vede nessuno. Scegli il **Director**, scrivi `ASSEGNA` nel campo di conferma e premi **Assegna**: tutti i dati vanno a quel director, con le persone dei loro team.

## Audit

Il registro è in sola aggiunta. Ogni richiesta che modifica dati lascia un evento `azione` con metodo, indirizzo ed esito, **mai il contenuto inviato**; login, blocchi, gestione utenti, backup, ripristini, aggiornamenti e spostamenti di persone hanno eventi propri. Le azioni da shell compaiono con utente `cli`.

- Filtri: «Utente», «Evento», «Dal», «Al» → **Filtra**. 100 eventi per pagina.
- **↓ CSV** / **↓ Excel** esportano tutti gli eventi del filtro, non solo la pagina. Anche l'esportazione viene registrata.

## Sistema

- **Installazione**: versione, schema del database, percorsi di database e chiave, numero di utenti.
- **Backup**: **Scarica backup cifrato ↓** scarica una copia consistente del database, ancora cifrata: si apre solo con la chiave di sistema.
- **Ripristino e import**: sostituisce tutti i dati con quelli di un file. Utenti e audit restano quelli di questa istanza; prima dello scambio il database attuale viene copiato in `data/backups/teamer-pre-ripristino-*.db`.
  - Backup di questa istanza: lascia vuoti chiave e password.
  - Database di un'altra istanza: incolla nella «Chiave dell'istanza di origine» il contenuto del suo `/etc/teamer/db.key` (64 caratteri esadecimali).
  - Database della versione 0.29 o precedente: la password di allora.
  - Scrivi `SOSTITUISCI` e premi **Ripristina**. Il file viene verificato (integrità, che sia Teamer, che non venga da una versione più recente) e migrato.
  - Dopo un import da un'altra istanza, assegna i dati da **Utenti → Dati da assegnare**.

> **La chiave di sistema** (`/etc/teamer/db.key`) cifra il database e non si legge dall'app. Perderla significa perdere i dati: conservane una copia fuori dal server. Un backup del solo database senza la chiave è illeggibile.

## Aggiornamenti

- **Canale**: «Stabile — release pubblicate» per la produzione; «Anteprima — ultimo tag, anche senza release» per un'istanza di test. Non si torna mai a una versione più vecchia.
- Il controllo parte da solo una volta al giorno e avvisa soltanto; **Controlla ora** lo ripete. Senza rete l'app resta utilizzabile.
- **Aggiorna a vX.Y.Z**: scarica la versione, fa un backup del database e riavvia il servizio (circa un minuto). Il riavvio blocca le sessioni di tutti: avvisa gli utenti e fai salvare il lavoro aperto. La pagina si ricarica da sola quando il servizio è pronto, poi si rientra con la propria password.
- Se l'aggiornamento fallisce si torna alla versione precedente; l'esito e il **Log** restano nel riquadro «Ultimo aggiornamento».
- **Backup automatici del database**: le ultime 5 copie fatte prima di ogni aggiornamento, in `data/backups/`.

Se manca l'updater di sistema (`teamer-update.path`) l'aggiornamento dall'app non è disponibile: si aggiorna da shell con `teamer-update`.

## Sessioni e blocco

- Non c'è scadenza per inattività. La sessione si blocca quando l'utente chiude l'ultima pagina di Teamer o preme **Esci**; il blocco di un utente non tocca gli altri.
- Su una pagina rimasta aperta compare «Sessione bloccata»: utente e password sbloccano sul posto, senza perdere quello che era scritto.
- Un riavvio del servizio blocca tutti.
- Dopo 5 password sbagliate l'utente resta bloccato per 1, 2, 4… minuti, fino a 60: il blocco scade da solo, oppure **Sblocca**.

## Riga di comando: `teamer-admin`

Sul container, come root. Ogni azione finisce nell'audit come utente `cli`.

| Comando | Effetto |
| --- | --- |
| `init [--admin NOME]` | Crea la chiave di sistema se manca e il primo site admin |
| `create-admin NOME` | Nuovo site admin con password provvisoria |
| `create-user NOME --role admin\|director\|hr [--person "Nome Cognome"]` | Nuovo utente; per un director la persona da collegare |
| `link-person NOME "Nome Cognome"` / `unlink-person NOME` | Collega o scollega la persona di un director |
| `reset-password NOME` | Stampa una password provvisoria |
| `unlock NOME` | Toglie il blocco per troppi tentativi |
| `enable NOME` / `disable NOME` | Riattiva o disattiva |
| `list-users` | Utenti con ruolo, stato, ultimo accesso e persona |
| `list-teams` | Albero dei team con il titolare |
| `assign-unassigned NOME` | Assegna i dati senza proprietario al director NOME |
| `restore FILE [--source-key \| --password]` | Ripristino da file; ferma il servizio durante lo scambio |

## Accesso perso

| Situazione | Rimedio |
| --- | --- |
| Password dimenticata | **Reset password** dal pannello o `teamer-admin reset-password NOME` |
| Troppi tentativi | Attendere, oppure **Sblocca** / `teamer-admin unlock NOME` |
| Nessun site admin utilizzabile | `teamer-admin create-admin NOME` o `reset-password` |
| Chiave di sistema persa | Nessun recupero possibile |
