# Guida HR — Teamer 0.47.4

HR vede le persone di **tutti** i director e registra i fatti contrattuali: censimento, contratti, RAL, benefit, incentivi, cessazioni, spostamenti fra director. Gestisce la configurazione aziendale e il premio di ruolo. Le scelte di organizzazione (team, riporti, assegnazioni) e le valutazioni restano ai director.

Guide degli altri profili: [Site admin](guida_admin.md) · [Director](guida_director.md).

## Orientarsi

Barra laterale: **Dashboard**; **Organizzazione** (Persone, Organigramma, Assunzioni); **Retribuzione** (Analisi salary, Piano aumenti, Budget aumenti, Montepremi, Listino); **Valutazione** (9-Box, Cicli & obiettivi, in consultazione); **Interazioni** (Note 1:1, Azioni); **Sistema** → **Azienda**. In fondo: Modalità pubblica, Account, Esci.

Non sono previsti per HR: Report, Simulazioni, Verifica riporti, Configurazione del director, pannello Amministrazione.

### Consultazione o «in veste di»

Una fascia in cima a ogni pagina dice in che modo stai lavorando.

- **Consultazione** (predefinito): vedi i dati di tutti i director, con filtro «Director» multiplo e totali. Non crei budget né proposte.
- **In veste di** un director: il selettore «In veste di» compare in Analisi salary, Piano aumenti, Budget aumenti e Assunzioni. Scelto un director, quelle pagine diventano le sue, con tutti i form; ciò che crei nasce intestato a lui. La scelta dura fino a «Esci»; «— solo consultazione —» la toglie.

## Dashboard

| Riquadro | Contenuto |
| --- | --- |
| Persone attive · N director | Organico complessivo |
| Proposte da validare | Proposte di aumento inviate dai director, per director, con «valida →» |
| Contratti a termine — prossimi 90 giorni | Scadenze di tutti i director |
| Le mie azioni | In ritardo e in arrivo |
| In attesa dei director | Cessazioni da decidere (sostituire o no) e persone da collocare in un team |
| Scorciatoie | + Persona, Nuove RAL, Piano aumenti, + Nota, Azienda |

## Persone

La lista mostra Nome, **Director**, Team, Ruolo, Assunzione. Filtri: director e «Mostra cessati». La RAL si vede nella scheda.

### Censire una persona

Riquadro **Nuova persona — censimento dello stato attuale**: obbligatori «Nome e cognome» e «Director». Il resto (team del director, ruolo, codice listino, livello, contratto, CCNL, smart working, timbratura, part-time, ore, RAL) diventa lo stato attuale; la RAL è registrata come «censimento iniziale». Senza team la persona è del director ma non compare in organigramma: la colloca lui dalla scheda. Pulsante **Censisci →**.

### Import da Excel

**Import da Excel →** (`/people/import`): scarica il template (**↓ Scarica template**), compilalo, scegli la «Data di riferimento censimento» e premi **Importa →**.

| Colonna | Note |
| --- | --- |
| `nome` | Obbligatoria |
| `director` | Obbligatoria: nome utente o nome visualizzato di un director attivo |
| `email`, `data_assunzione`, `data_nascita` | Date come GG/MM/AAAA (anche AAAA-MM-GG) |
| `team` | Team del director; creato se non esiste |
| `ruolo` | `ic` / `tl` / `mgr` / `sr` |
| `codice_listino` | Codice esistente in Azienda → Listino (vale solo con un team) |
| `livello`, `ccnl` | Un livello nuovo viene aggiunto alla lista; CCNL vuoto = predefinito |
| `contratto`, `scadenza_contratto` | `indeterminato` / `determinato` / `apprendistato` / `collaborazione` |
| `smartwork`, `timbratura` | `no` / `parziale` / `full`; `esente` / `4_timbrate` / `solo_presenza` |
| `part_time_pct`, `ore_settimanali`, `ral`, `note` | |

Ogni riga entra tutta o niente. Un nome già presente viene saltato. L'esito mostra create, già presenti ed errori riga per riga.

### Spostare una persona a un altro director

Nella colonna **Director** scegli il nuovo director: si apre il dialogo «Spostare a un altro director».

- **Sposta →** è il cambiamento reale. Dalla data «Dal», la persona passa al nuovo director: l'assegnazione corrente si chiude il giorno prima. Ne nasce una nuova nel team «Da collocare» del nuovo director, con lo stesso ruolo. La data deve essere successiva all'inizio dell'assegnazione corrente.
- **Correggi** rimedia a un director sbagliato (uno spostamento fatto per errore, o un director sbagliato al censimento o all'import). Si può sempre fare. L'assegnazione corrente si annulla e la persona va nel «Da collocare» del director scelto, **dalla stessa data di inizio**, senza aggiungere storico. La data nel dialogo non conta. Vale anche per riportarla al director di prima: la ritroverà in «Da collocare» e la ricollocherà lui.

In entrambi i casi tutto lo storico segue la persona. Le proposte di aumento pendenti del vecchio director si annullano, e le righe nei suoi budget e montepremi si staccano. Obiettivi e review passano a un ciclo con lo stesso nome del nuovo director. Le note restano a chi le ha scritte. I team non si spostano mai.

Non si spostano le persone cessate né quelle collegate a un utente director: prima l'IT le scollega.

## Scheda persona

| Area | Cambiamento reale | Correzione di un errore |
| --- | --- | --- |
| Anagrafica | — | Modifica in place, **Salva** |
| Situazione contrattuale | **Nuova situazione contrattuale** (livello, contratto, CCNL, part-time, scadenza…): la precedente si chiude il giorno prima | **Correggi situazione contrattuale corrente** |
| RAL | **Nuovo evento RAL** (nuova RAL, decorrenza, tipo, motivo) | **✕** annulla l'evento: resta visibile come annullato |
| Benefit | **Assegna benefit**: assegnare lo stesso benefit chiude il precedente | **✕** termina il benefit |
| Incentivi | **Incentivo one-shot** (importo, data, motivo) | — |
| Allegati | **Carica** | **✕** elimina |

Team, ruolo e riporto non li modifica HR: li gestisce il director con «Nuova assegnazione» o «Correggi assegnazione corrente». HR non elimina persone e non registra valutazioni 9-box o review.

### Cessazione

In **Avatar / cessazione** indica la «Data cessazione» e premi **Cessa**: la persona diventa cessata e assegnazione e contratto si chiudono a quella data. Da lì il director la trova in «Cessazioni da decidere» e sceglie se sostituirla, con una posizione nel budget assunzioni, o no. Anche la tua dashboard la mostra finché lui non decide. Una persona collegata a un utente director non si cessa finché l'IT non la scollega.

## Retribuzione

### Analisi salary: variazioni dirette

In consultazione la pagina diventa **Nuove RAL e livelli — scrittura diretta**. Serve per le variazioni comunicate dallo studio paghe (rinnovi CCNL, scatti, adeguamenti). Quello che salvi diventa subito un evento RAL reale, senza passare dal piano aumenti. Un livello nuovo apre una nuova situazione contrattuale dalla stessa data.

Compila la «Decorrenza (comune)», il «Tipo» (predefinito «Variazione CCNL») e il «Motivo / nota». Poi, riga per riga, inserisci la «Nuova RAL €» (l'importo assoluto, non l'aumento) e/o il «Nuovo livello». Premi **Registra le variazioni →**: si registrano solo le righe compilate.

In veste di un director la pagina diventa la sua analisi: gli aumenti salvati con **Salva nel piano →** nascono come proposte in bozza nel suo piano.

### Piano aumenti

Il percorso di una proposta è: **Bozza → Proposta a HR → Approvata → Applicata** (oppure **Respinta**). Solo l'applicazione tocca la RAL reale.

- In consultazione vedi le richieste in attesa di tutti i director (filtro Director, totali di variazione e nuove RAL), in sola lettura.
- **Per validare scegli il director «in veste di»**: sulle proposte inviate puoi correggere la «Nuova RAL», poi **Approva**, **Respingi** o rimandare in bozza (**↩ bozza**). Il controllo sul tetto del budget non ti blocca.
- Approva e applica chi arriva prima fra te e il director. **Applica** (o **Applica le N approvate →**) registra l'evento RAL reale, e un cambio di livello apre una nuova situazione contrattuale.

### Budget aumenti e Assunzioni

In consultazione vedi i budget aperti di tutti i director con tetto, applicato, impegnato e residuo. Nelle Assunzioni puoi correggere la «RAL prevista» delle posizioni pianificate o in selezione. In veste di un director crei e gestisci i suoi budget e le sue posizioni, come farebbe lui (vedi la [guida del director](guida_director.md)).

### Montepremi per ruolo

Il premio di ruolo è di HR e copre persone di più director.

1. **Nuovo montepremi per ruolo**: compila «Periodo», «Anno di competenza», «In organico al», «Tetto fisso €» oppure «cifra a testa €». La platea è fatta dai team scelti (vuoto = tutti) e dai ruoli esclusi. Premi **Crea →**: nasce in bozza con le proposte già calcolate.
2. Ognuno pesa per il **moltiplicatore del suo ruolo prevalente nell'anno di competenza** (non quello attuale), modificabile per persona in «Ruolo per il premio». I «Finale €» ritoccati a mano restano quando premi **Rigenera proposte**.
3. **Invia ai director →**: ognuno vede solo le sue persone, può cambiarne il ruolo per il premio e approva la sua parte. Nel dettaglio vedi chi ha approvato e chi è in attesa. **↩ Richiama in bozza** fa cadere le approvazioni.
4. **Chiudi montepremi**: si può chiudere anche se non tutti hanno approvato (la conferma lo segnala). **Riapri** lo riporta in bozza.

I moltiplicatori si impostano in Azienda → Premi.

### Listino

In consultazione, con filtro per director: costo giornaliero per codice, team e persona. I codici e i parametri si gestiscono in Azienda → Listino; codice e produttività delle singole persone li imposta il director.

## Azienda

Configurazione unica per tutta l'azienda: la usano tutti i director, che non la possono modificare.

| Tab | Contenuto |
| --- | --- |
| Liste valori | Le pick-list (livelli, tipi di contratto, ruoli, tipi di variazione RAL, categorie di obiettivi…). Il codice resta fisso; l'etichetta si rinomina e si propaga ovunque, storico compreso. Le voci si disattivano, non si cancellano |
| Catalogo benefit | Nome, tipo di valore (sì/no, opzioni, importo €), se concorre al costo totale |
| Valori predefiniti | CCNL predefinito per censimenti e import |
| Listino | Parametri del costo giornaliero (oneri, premi, festività, ferie, malattia, formazione, interne, saturazione) e codici di listino con la tariffa €/gg |
| Premi | Moltiplicatore per ruolo del premio di ruolo |

## Note 1:1 e azioni

Note e azioni sono **solo tue**: nessun altro le legge, e tu non leggi quelle dei director. **Nuova nota** (persona, data, tipo, titolo, testo, eventuale azione collegata); le azioni si avviano e si chiudono dalla pagina Azioni.
