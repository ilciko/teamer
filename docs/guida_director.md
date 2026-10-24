# Guida del director — Teamer 0.47.4

Il director gestisce i **suoi** team e le persone che ci lavorano: organizzazione, piano aumenti, assunzioni, valutazioni, ciclo annuale, note 1:1. Non vede i team degli altri director, e nessun director è sopra gli altri. Contratti, RAL, benefit e cessazioni li registra HR: il director li legge e decide aumenti, sostituzioni e organizzazione.

Guide degli altri profili: [Site admin](guida_admin.md) · [HR](guida_hr.md).

## Orientarsi

Barra laterale: **Dashboard**, **Report**; **Organizzazione** (Persone, Organigramma, Assunzioni); **Retribuzione** (Analisi salary, Piano aumenti, Budget aumenti, Montepremi, Listino); **Valutazione** (9-Box, Cicli & obiettivi); **Interazioni** (Note 1:1, Azioni); **Sistema** → **Configurazione**. In fondo: Modalità pubblica, Account, Esci.

**Modalità pubblica**: nasconde le cifre (•••) e le pagine riservate, per condividere lo schermo. Restano Persone, Organigramma, Assunzioni e Listino. Vale solo per te, finché non la spegni.

**Cambiamento o correzione**: quasi ogni dato offre due strade. Il **cambiamento reale** (nuova assegnazione, nuova valutazione) aggiunge un record datato e conserva lo storico. La **correzione** («Correggi», annulla) rimedia a un errore di inserimento senza creare storia.

## Dashboard

| Riquadro | Contenuto |
| --- | --- |
| Persone attive, Monte RAL, RAL media | Il tuo perimetro |
| Persone da collocare | Persone che HR ti ha spostato: sono nel team tecnico «Da collocare» finché non le assegni |
| Cessazioni da decidere | Uscite registrate da HR: decidi se sostituire (**sostituisci →**) o no |
| Processi in corso | Piano aumenti per budget, premio di ruolo da approvare, cicli di review, montepremi, posizioni aperte |
| Scadenze — prossimi 90 giorni | Contratti a termine e benefit in scadenza |
| Azioni, Valutazione, Ultime note | Azioni in ritardo e in arrivo, cicli aperti, persone mai valutate al 9-box |

## Organizzazione

### Organigramma e team

- **Organigramma** (`/org`): albero dei team con persone, responsabile e diretti. **Nuovo team** (nome, team padre, responsabile) e **Modifica team**; ↑ ↓ cambiano solo l'ordine fra team fratelli.
- Un team si **elimina** (✕) solo se è vuoto e senza storia. Se ha solo storia si **archivia**: sparisce da organigramma e liste, ma lo storico resta e si può **Ripristinare** da «Team archiviati».
- Il team «Da collocare» non si elimina: sparisce da solo quando è vuoto.
- **Linee di riporto →** mostra il grafico per ruolo, con filtro per reparti, posizioni aperte ed **Esporta PDF**.
- La scheda team (clic sul nome) è in lettura: membri con retribuzione, contratto, benefit e 9-box, posizioni aperte, obiettivi del team.

### Riporti

Il riporto diretto **si calcola, non si sceglie**. Dal team della persona si risale ai team padre e si prende il ruolo superiore più vicino: Specialist → TL → Manager → Director. Solo da TL in su si hanno riporti.

Quando un cambio di team, ruolo o responsabile rende un riporto incoerente, l'app porta a **Verifica riporti** (anche dal pulsante in Organigramma). Lì spunti le righe da aggiornare e scegli:
- **Correzione**: sovrascrive l'assegnazione corrente, perché il riporto era sbagliato;
- **Cambiamento reale dal [data]**: crea una nuova assegnazione e conserva lo storico.

Chi resta non spuntato ricompare alla verifica successiva.

### Persone e scheda persona

La lista mostra le tue persone. Le persone nuove le censisce HR: tu le trovi qui e le collochi nei tuoi team dalla scheda.

Nella scheda persona:
- **Nuova assegnazione (team/ruolo)**: il cambiamento reale (promozione, cambio team) da una data. L'assegnazione precedente si chiude il giorno prima. È anche il modo di collocare chi è «Da collocare».
- **Correggi assegnazione corrente**: un errore di inserimento, sovrascritto senza storico.
- **Anagrafica**: nome, date, email, note si correggono in place.
- **In sola lettura**: situazione contrattuale, RAL (timeline e proposte a piano), benefit e incentivi.
- **Valutazioni 9-box, obiettivi e review, note e azioni, allegati.**
- **Eliminazione definitiva**: solo per una persona inserita per errore e senza altri dati collegati. Per chi esce si usa la cessazione, che registra HR.

### Cessazione e sostituzione

Quando HR registra un'uscita, la persona compare in **Cessazioni da decidere**:
- **Pianifica sostituzione →** crea una posizione nel budget assunzioni (titolo, team, ruolo, RAL prevista, inizio). Può anche aggiungere la RAL liberata al tetto del budget di destinazione.
- **Non sostituire** registra la decisione, con un motivo facoltativo. Si può annullare dalla scheda.

### Assunzioni

**Budget assunzioni** per periodo, con tetto, riporto dall'anno precedente, applicato, impegnato e residuo.
- **+ Nuova posizione**: titolo, team, ruolo, RAL prevista, inizio previsto e tipo: **+1 al team** oppure **sostituisce** una persona cessata.
- Stati della posizione: Pianificata → In selezione (**Avvia selezione**) → Assunta (scegli la persona censita da HR e premi **Assunta**), oppure Annullata.
- **Chiudi e riporta →**: trasferisce il residuo e le posizioni aperte a un altro budget, o a uno nuovo.
- Un budget senza posizioni si elimina; con posizioni si chiude e resta nello storico.

### Simulazioni di riorganizzazione

Da **Simulazioni** (in Organigramma): **Nuova simulazione**, poi in bozza:
- modifichi team (nuovi, spostati, tolti);
- sposti persone di team o ruolo, o le segni «esce»;
- aggiungi posizioni ipotetiche (nuove assunzioni, o una figura interna da un altro team);
- sposti le posizioni aperte del budget.

La simulazione salva solo le differenze dalla realtà. I riporti si ricalcolano da soli.
- **Confronta con l'attuale** o **Confronta 1:1** fra due simulazioni; **Duplica come variante**.
- **Approva** → **Applica dal [data]**: team creati o aggiornati, spostamenti registrati come nuove assegnazioni da quella data, posizioni del budget aggiornate se ancora aperte, poi verifica dei riporti.
- Chi è segnato «esce» non viene toccato: l'uscita la registra HR. Le posizioni ipotetiche non entrano nel budget: si aprono da Assunzioni.

## Retribuzione

### Analisi salary → Piano aumenti

1. In **Analisi salary** scegli il budget e indichi l'aumento (in € o %), il nuovo livello e la decorrenza. L'anteprima mostra il totale delle nuove proposte, quanto è già impegnato e il residuo, e avvisa se il budget sfora.
2. **Salva nel piano →**: le proposte nascono **in bozza**. Non sono ancora aumenti.
3. Nel **Piano aumenti** ogni proposta segue il percorso **Bozza → Proposta a HR → Approvata → Applicata** (oppure **Respinta**). Solo l'applicazione tocca la RAL reale.
   - **Invia a HR**; **📄 Report per HR** genera il prospetto da comunicare (stampa/PDF o Excel).
   - Modifichi l'importo solo in bozza: una proposta inviata si riporta in bozza (**↩ bozza**) per cambiarla. Nel piano confermi la **nuova RAL**, e lo scarto dalla RAL attuale è ciò che consuma il budget.
   - **Approva** e **Applica** li fa chi arriva prima fra te e HR. **Applica le N approvate →** le applica tutte in ordine di decorrenza.

### Budget aumenti

Ogni budget ha un tetto, fisso oppure in % sul monte RAL della platea. Il **residuo** è il tetto meno l'applicato meno l'impegnato (le proposte non ancora applicate).
- Nei budget in %, la platea si gestisce con **Includi** / **Escludi**: sono esclusi in partenza gli assunti nell'anno e chi non ha RAL.
- Un budget senza movimenti si elimina, anche se chiuso; con movimenti si chiude e resta nello storico (**Riapri**).

### Montepremi

**Il tuo montepremi** (peso composito):
- Si crea con un tetto fisso o una cifra a testa. **Genera proposte →** distribuisce il tetto.
- Il peso è il prodotto di casella 9-box × ruolo × rating della review × obiettivi; ogni fattore si accende o si spegne per montepremi.
- Puoi escludere persone, una per una o in blocco (assunti nell'ultimo anno, non operativi da almeno 6 mesi).
- I «Finale €» ritoccati a mano restano quando rigeneri. **Chiudi montepremi** quando è definitivo.

**Premio di ruolo di HR**: quando HR lo invia, compare in «Premi di ruolo di HR — le tue persone» e in dashboard.
- Vedi solo le tue persone e puoi cambiarne il «Ruolo per il premio»: il proposto è il ruolo prevalente nell'anno di competenza. Il peso si ricalcola su tutta la platea.
- **Approva la mia parte →** chiude le tue modifiche. Se poi serve un cambio, chiedi a HR di richiamare il premio.

### Listino

Costo giornaliero per codice, team e persona, calcolato dai parametri aziendali che fissa HR. Nella card **Codice di listino e produttività per persona** imposti, per le tue persone, il codice e le percentuali di formazione, attività interne e saturazione (vuoto = valore aziendale). Il salvataggio è immediato. Un cambio reale di codice si registra con una nuova assegnazione dalla scheda.

## Valutazione

### 9-Box

- Dalla griglia: **Valuta** chi non è mai stato valutato, **Rivaluta** gli altri. La nuova valutazione si aggiunge e la precedente resta.
- Il questionario parte dal contesto (livello di responsabilità, anzianità nel ruolo), che applica gli aggiustamenti configurati. Poi una domanda alla volta, fino a **Calcola e salva →**.
- L'esito mostra la casella, il calcolo, le risposte e il movimento nella griglia. **Annulla questa valutazione** è solo per un errore di inserimento.
- Ogni valutazione conserva il questionario con cui è stata fatta: cambiarlo dopo non riscrive la storia.

### Cicli & obiettivi

- **Nuovo ciclo** (nome, anno); dal ciclo apri ogni persona.
- **1.1 Valutazione obiettivi** dell'anno precedente: punteggi 1–5 dell'interessato (auto) e del TL.
- **Valutazione complessiva**: rating, data dell'1:1, commenti, crescita personale, sintesi. Si salva in bozza e poi si **Finalizza**. Riportarla in bozza la toglie dal calcolo del montepremi.
- **1.2 Obiettivi per l'anno successivo**: i pesi arrivano al **100% per categoria**, separatamente per professionali e personali, mai sommati insieme.
- **Benessere sul lavoro**: carico, soddisfazione, work-life balance, commento di chiusura.
- **Chiudi ciclo** / **Riapri ciclo**.

## Note 1:1 e azioni

Note e azioni sono **solo tue**: HR e gli altri director non le leggono.
- **Nuova nota**: persona, data, tipo, titolo, testo, eventuale azione collegata con scadenza.
- **Modifica** corregge una nota esistente; per un altro incontro si crea una nota nuova.
- Ricerca full-text, archiviazione, **Report** stampabile, globale o per persona.
- Se una persona passa a un altro director, le note restano tue in sola lettura, e le sue azioni si possono ancora chiudere.

## Report

Addetti e monte RAL nel tempo, per tutta l'area o per team (con la serie per team), con i dati anche in tabella. Puoi escludere dal report chi non ha uno storico utilizzabile (**Salva le esclusioni**).

## Configurazione

La tua configurazione personale: un director nuovo parte da quella predefinita.

| Tab | Contenuto |
| --- | --- |
| Generale | Soglie in anni per evidenziare in arancio o in rosso l'ultima variazione di RAL |
| 9-box | Il questionario (domande con asse, peso, risposte con punteggio 1–3, note per ruolo e anzianità), le 9 caselle, gli aggiustamenti ruolo × anzianità e il peso premio per casella |
| Premi | Moltiplicatori del montepremi per ruolo e per rating della review |

Liste valori, benefit, CCNL e listino sono aziendali: li gestisce HR.
