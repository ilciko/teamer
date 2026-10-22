# Tool Gestione Team — Schema Dati

App web per il COO (ruolo *director*) con un site admin IT (ruolo *admin*). Python (FastAPI) + SQLite cifrato via SQLCipher con una **chiave di sistema** grezza (`PRAGMA key = "x'…'"`, 32 byte casuali in un file noto solo all'IT, `TEAMER_DB_KEY_FILE`); le password degli utenti non cifrano nulla, ne sta solo l'hash in `app_user`. Fino alla 0.29 la chiave era la password del COO (modalità passphrase): la migrazione la ricifra con `PRAGMA rekey`. Tabelle in 5 aree.

## Principi di schema

- **Storicizzazione append-only.** Tutto ciò che evolve nel tempo (RAL, benefit, organigramma, valutazioni, 9-box, obiettivi) non si sovrascrive: si aggiunge un record. Lo "stato attuale" è l'ultimo record valido; lo storico è la serie completa. Niente `UPDATE` distruttivi sui dati sensibili: gli errori si correggono annullando l'evento (flag `voided` + `void_reason`) e inserendone uno nuovo.
- **Audit su ogni evento.** Tutte le tabelle a eventi hanno `created_at DATETIME`, `voided BOOLEAN` e `void_reason TEXT` (omessi dalle tabelle qui sotto per brevità): la data di validità (`effective_date`/`eval_date`) e la data di registrazione sono cose diverse. Le viste "stato attuale" filtrano `voided = 0`.
- **Ciclo di valutazione come entità.** I periodi non sono testo libero: `review_cycle` lega obiettivi, review annuali, valutazioni e montepremi allo stesso ciclo (es. "Review 2026").
- **Config editabile, non hardcoded.** I pesi dinamici del 9-box, la mappatura casella→peso premio, i tipi di benefit e i modelli di valutazione vivono in tabelle, non nel codice. Li modifichi dalla UI.
- **Benefit tipizzati.** I benefit sono eterogenei (enum, booleano, importo): un catalogo (`benefit_type`) + assegnazioni storicizzate, così ne aggiungi di nuovi senza toccare lo schema.
- **Report = viste.** Nessuna tabella report: sono query di aggregazione sulle tabelle a eventi.
- **Cifratura trasparente.** SQLCipher cifra l'intero file; a valle del login lo schema è un normale SQLite, quindi query e viste non cambiano. Backup: export del file cifrato con rotazione, dal menu dell'app. Anche gli allegati stanno nel DB (`attachment`), così nulla resta in chiaro sul disco.

---

## Area 1 — Core / Organigramma

### `person` — anagrafica stabile
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| full_name | TEXT | |
| avatar | BLOB | immagine profilo per la vista organigramma |
| hire_date | DATE | |
| birth_date | DATE | opzionale (dato personale) |
| email | TEXT | opzionale |
| status | TEXT | `attivo` / `cessato` |
| report_excluded | BOOLEAN | fuori dalle serie del report (entrambe: addetti e monte RAL) |
| end_date | DATE | data cessazione, se applicabile |
| notes | TEXT | note libere anagrafiche |

### `team` — nodi dell'organigramma (albero)
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT | |
| parent_team_id | INTEGER FK→team.id | gerarchia; NULL = radice |
| lead_person_id | INTEGER FK→person.id | responsabile del team |
| description | TEXT | |
| sort_order | INTEGER | ordine tra fratelli (stesso padre), poi nome; si cambia con "sposta su/giù" in /org, che non cambia mai il padre *(0020)* |
| archived_at | DATETIME | NULL = attivo; valorizzato = archiviato: team vuoto ma con storico, fuori da organigramma, grafico, simulazioni e menu (si ripristina da /org) *(0022)* |

### `person_assignment` — appartenenza/ruolo nel tempo *(storicizzata)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| person_id | INTEGER FK→person.id | |
| team_id | INTEGER FK→team.id | |
| manager_person_id | INTEGER FK→person.id | riporto diretto, **derivato** da team e ruolo (`org_tree.expected_manager`), non si sceglie; NULL = vertice |
| role_type | TEXT | `ic` / `tl` / `mgr` / `sr` (coerente col 9-box) |
| start_date | DATE | |
| end_date | DATE | NULL = assegnazione corrente |
| listino_profile_id | INTEGER FK→listino_profile.id | codice di listino di vendita; NULL = fuori listino |

> L'organigramma corrente = `person_assignment` con `end_date IS NULL`. I movimenti (cambio team, promozione) sono nuovi record. Il **responsabile diretto** è `manager_person_id`, non duplicato altrove. Il **codice di listino** segue la stessa storia: cambia con una nuova assegnazione, si corregge in place (anche dalla pagina Listino); la platea del listino è «assegnazioni correnti con codice».

### `employment` — situazione contrattuale nel tempo *(storicizzata)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| person_id | INTEGER FK→person.id | |
| livello | TEXT | inquadramento; codice da `lookup` (categoria `livello`) |
| ccnl | TEXT | contratto collettivo applicato |
| tipo_contratto | TEXT | `indeterminato`/`determinato`/`apprendistato`/… (da `lookup`) |
| smartwork | TEXT | codice da `lookup` (categoria `smartwork`) |
| timbratura_scheme | TEXT | `esente`/`4_timbrate`/`solo_presenza`/… (da `lookup`) |
| part_time_pct | REAL | 100 = full time |
| weekly_hours | REAL | ore settimanali contrattuali |
| start_date | DATE | |
| end_date | DATE | NULL = situazione corrente |
| note | TEXT | |

> Separata da `person_assignment`: org-move e cambio-contratto evolvono a cadenze diverse, ciascuno col proprio storico. Situazione corrente = `end_date IS NULL`.

### `lookup` — liste di valori editabili *(config)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| category | TEXT | `livello` / `smartwork` / `timbratura` / `change_type` / `meeting_type` / `goal_category` / `workload` / `satisfaction` / `overall_rating` / … |
| code | TEXT | valore memorizzato (es. `4_timbrate`) |
| label | TEXT | etichetta mostrata (es. "4 timbrate") |
| sort_order | INTEGER | ordinamento in UI |
| active | BOOLEAN | |

> Unica tabella per tutte le pick-list configurabili: aggiungi/rinomini una voce dalla UI senza toccare lo schema. Chiave logica: (`category`, `code`).

### `app_meta` — configurazione di sistema
| Campo | Tipo | Note |
|---|---|---|
| key | TEXT PK | |
| value | TEXT | schema_version, impostazioni globali |

> La chiave del DB **non** sta qui (né da nessuna parte nel DB): sta nel file di sistema letto all'avvio. `public_mode` non è più qui dalla 0026: è per utente (`app_user.public_mode`).

Chiavi impostate da Configurazione → Generale: `default_ccnl`, `ral_stale_amber_years` e `ral_stale_red_years` (anni oltre i quali l'analisi salary evidenzia in arancio e in rosso la data dell'ultima variazione di RAL).

Chiavi del listino (pagina Listino → «Salva come predefiniti»): `listino_oneri_mult` (oneri × RAL: INPS, INAIL, TFR), `listino_premi_pct` (premi attesi % RAL, soggetti a oneri), `listino_altri_costi` (€ annui a persona), `listino_festivita_gg` (festività feriali; `''` = dal calendario dell'anno), `listino_festivita_extra_gg` (patrono/chiusure), `listino_ferie_gg`, `listino_malattia_gg`, `listino_formazione_pct`, `listino_interne_pct`, `listino_saturazione_pct`. Il calcolo è in `app/services/listino.py`.

### `reorg_scenario`, `reorg_team`, `reorg_move`, `reorg_position` — simulazioni di riorganizzazione *(0021)*
Prove di organigramma da confrontare, approvare e applicare (`/org/sim`, `app/services/reorg.py`). Una simulazione **non copia** l'organigramma: salva solo le differenze, e lo stato simulato = realtà di oggi + differenze (i riporti si ricalcolano con `org_tree.expected_manager`).

| Tabella | Contenuto |
|---|---|
| `reorg_scenario` | nome, descrizione, `status` (bozza → approvata → applicata \| scartata, lookup `reorg_status`), `effective_date` di applicazione, `approved_at`, `applied_at` |
| `reorg_team` | `team_id` NULL = team nuovo (riferito come `-reorg_team.id`), altrimenti override completo di un team reale (`name`, `parent_ref`, `lead_person_id`, `sort_order`, `removed`) |
| `reorg_move` | PK (scenario, persona): `team_ref` e `role_type` di chi cambia rispetto alla realtà; `hidden` = nella simulazione esce, applicando resta *(0025)* |
| `reorg_position` | posizioni ipotetiche (`title`, `team_ref`, `role_type`), non entrano nel budget assunzioni; `internal` = figura interna di un altro team (titolo = nome della persona) *(0025)* |
| `reorg_position_move` | PK (scenario, `position_id` → `hiring_position`, ON DELETE CASCADE): `team_ref` e `role_type` di una posizione aperta del budget spostata; applicando si aggiorna la posizione in place *(0023)*; `hidden` = nella simulazione la posizione non c'è, applicando resta nel budget com'è *(0024)* |

`parent_ref`/`team_ref`: > 0 team reale, < 0 team nuovo della simulazione, NULL radice/nessuno; niente FK, un riferimento che non esiste più si ignora. Applicare (solo da `approvata`, con data) crea/aggiorna i team e registra gli spostamenti come nuove `person_assignment`.

---

## Area 2 — Valutazioni e Obiettivi

### `review_cycle` — ciclo di valutazione annuale
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT | es. "Review 2026" |
| year | INTEGER | anno di riferimento |
| status | TEXT | `aperto` / `chiuso` |
| note | TEXT | |

> Entità periodo condivisa: obiettivi, review annuali, valutazioni e montepremi si agganciano qui via `cycle_id`, rendendo banali i report "tutto il ciclo 2026".

### `evaluation_model` — modello/strumento di valutazione *(pluggable)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT | |
| type | TEXT | `competency` / `nine_box` / … |
| config | JSON | competenze, scale, pesi del modello |
| active | BOOLEAN | |

> Per il modello `nine_box`, `config` contiene le 6 domande con opzioni di risposta, le note contestuali per ruolo/anzianità e le etichette/descrizioni delle 9 caselle: modificare una domanda = editare il modello dalla UI, senza toccare il codice.

### `ninebox_assessment` — esito 9-box *(storicizzato)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| person_id | INTEGER FK→person.id | |
| eval_date | DATE | |
| role_type | TEXT | contesto: `ic`/`tl`/`mgr`/`sr` |
| seniority | TEXT | contesto: `new`/`mid`/`sen` |
| raw_perf, raw_pot | REAL | medie grezze (scala 1–3) |
| adj_perf, adj_pot | REAL | dopo aggiustamento pesi |
| perf_level, pot_level | TEXT | `low`/`med`/`high` |
| box_number | INTEGER | 1–9 |
| weights_snapshot | JSON | pesi usati → risultato riproducibile a posteriori |
| answers | JSON | le 6 risposte (o tabella figlia se preferisci) |

> Lo storico di `box_number` per persona = il **movimento nella griglia** nel tempo.

### `ninebox_weight` — aggiustamenti dinamici del 9-box *(config editabile)*
| Campo | Tipo | Note |
|---|---|---|
| role_type | TEXT PK | `ic`/`tl`/`mgr`/`sr` |
| seniority | TEXT PK | `new`/`mid`/`sen` — PK composita |
| perf_adj | REAL | aggiustamento prestazione, segno incluso (es. `new` negativo, `mid` 0, `sen` −0.10) |
| pot_adj | REAL | aggiustamento potenziale |

> 12 righe seed che riproducono l'artefatto HTML, ma **tutto** configurabile: nell'artefatto l'aggiustamento dei "consolidati" (−0.10/−0.10) era hardcoded. `weights_snapshot` in `ninebox_assessment` garantisce comunque la riproducibilità a posteriori.

### `weight_mapping` — mappatura casella → peso premio *(config editabile)*
| Campo | Tipo | Note |
|---|---|---|
| box_number | INTEGER PK | 1–9 |
| weight | REAL | es. box 9 = peso alto, box 1 = 0 |

### `goal` — obiettivo definito *(storicizzato)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| person_id | INTEGER FK→person.id | |
| cycle_id | INTEGER FK→review_cycle.id | ciclo in cui l'obiettivo è stato **definito** |
| category | TEXT | `professionale` / `personale` (da `lookup`, categoria `goal_category`) |
| description | TEXT | |
| weight_pct | REAL | peso % dell'obiettivo |
| note | TEXT | note in fase di definizione |
| status | TEXT | `attivo` / `annullato` |

> Definiti durante la review dell'anno N per l'anno N+1, come nel modulo annuale. Vincolo logico (validato in UI): Σ `weight_pct` = 100 per persona/ciclo/categoria.

### `goal_review` — valutazione dell'obiettivo *(nel ciclo successivo)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| goal_id | INTEGER FK→goal.id | |
| review_id | INTEGER FK→performance_review.id | la review in cui l'obiettivo viene valutato |
| self_score | REAL | autovalutazione dipendente, scala 1–5 |
| tl_score | REAL | valutazione Team Leader, scala 1–5 |
| note | TEXT | |

> Punteggio complessivo prestazioni = Σ (`goal.weight_pct` × `tl_score`) / 100.

### `performance_review` — la review annuale di una persona
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| person_id | INTEGER FK→person.id | |
| cycle_id | INTEGER FK→review_cycle.id | |
| review_date | DATE | data dell'1:1 |
| overall_rating | INTEGER | scala 1–5 ("Serve un forte miglioramento" → "Eccezionale", etichette da `lookup`) |
| overall_employee_comment | TEXT | commento del dipendente sulla valutazione complessiva |
| overall_tl_comment | TEXT | commento del Team Leader |
| growth_self_comment | TEXT | crescita personale, self-assessment |
| growth_tl_comment | TEXT | crescita personale, commento TL |
| synthesis_employee_comment | TEXT | commenti generali dipendente (sintesi) |
| synthesis_tl_comment | TEXT | commenti generali TL (sintesi) |
| status | TEXT | `bozza` / `finalizzata` |

> Contenitore che raggruppa `goal_review` e `wellbeing_entry` di un ciclo. Il modulo cartaceo/docx resta fuori dal tool: dopo l'1:1 il COO inserisce qui punteggi e commenti; il documento compilato si conserva in `attachment`.

> Unicità: indice **parziale** `UNIQUE(person_id, cycle_id) WHERE voided = 0` (migrazione 0012): una sola review viva per persona/ciclo, ma quelle annullate non impediscono di ricominciare. Il vincolo di tabella originale, che non guardava `voided`, rendeva il void di fatto irreversibile.

### `wellbeing_entry` — rilevazione benessere *(1:1 con la review)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| review_id | INTEGER FK→performance_review.id | UNIQUE: una rilevazione per review |
| workload_rating | TEXT | da `lookup` (categoria `workload`): `molto_inferiore`/`inferiore`/`in_linea`/`superiore` |
| workload_employee_comment | TEXT | |
| workload_tl_comment | TEXT | |
| satisfaction_rating | TEXT | da `lookup` (categoria `satisfaction`): `per_nulla`/`poco`/`soddisfatto`/`molto` |
| satisfaction_employee_comment | TEXT | |
| satisfaction_tl_comment | TEXT | |
| wlb_resources | BOOLEAN | "Hai accesso alle risorse necessarie?" |
| wlb_resources_note | TEXT | |
| wlb_time_difficulty | BOOLEAN | "Hai difficoltà nella gestione del tempo?" |
| wlb_time_note | TEXT | |
| wlb_balance | BOOLEAN | "Equilibrio sano vita privata/lavoro?" |
| wlb_balance_note | TEXT | |
| tl_comment | TEXT | commento TL di chiusura capitolo |

> Domande fisse del modulo → colonne strutturate, non JSON: trend soddisfazione/carico per persona anno su anno, heatmap benessere per team, incrocio benessere × 9-box (es. Consistent Star con carico "superiore" = rischio retention).

---

## Area 3 — Retribuzione (modello a livelli)

### `ral_event` — RAL *(storicizzata, a eventi)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| person_id | INTEGER FK→person.id | |
| budget_id | INTEGER FK→ral_budget.id | NULL se fuori budget |
| effective_date | DATE | per il `censimento`: la data di riferimento, o quella di assunzione se successiva |
| amount | REAL | nuova RAL |
| delta | REAL | **calcolato all'inserimento** dall'ultimo evento non annullato — mai digitato |
| change_type | TEXT | `censimento`/`assunzione`/`aumento`/`promozione`/`adeguamento` |
| reason | TEXT | motivazione |

### `ral_budget` — tetto budget aumenti *(top-down)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| period | TEXT | es. anno (etichetta) |
| cycle_id | INTEGER FK→review_cycle.id | NULL ammesso — aggancio al ciclo |
| total_cap | REAL | tetto |
| description | TEXT | |

> Residuo = `total_cap − Σ delta` degli `ral_event` legati al budget. Allocato vs tetto sempre visibile.

### `ral_proposal` — piano aumenti *(proposte con ciclo di vita)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| person_id | INTEGER FK→person.id | |
| budget_id | INTEGER FK→ral_budget.id | budget su cui grava |
| amount | REAL | delta proposto (0 ammesso: solo cambio livello) |
| effective_date | DATE | decorrenza **prevista**, propria della riga |
| new_livello | TEXT | eventuale passaggio di livello |
| status | TEXT | `bozza`/`proposta`/`approvata`/`applicata`/`respinta` |
| note | TEXT | |
| proposed_at | DATE | invio a HR |
| decided_at | DATE | approvazione o rifiuto |
| ral_event_id | INTEGER FK→ral_event.id | valorizzato all'applicazione |

> Lo stadio intermedio fra simulazione e realtà. Un aumento passa da HR prima di esistere: solo l'ultimo passaggio (`applicata`) genera il `ral_event` e, se il livello cambia, la nuova `employment`. La decorrenza è di riga — in genere comune, ma può variare per persona — e non coincide con la data di registrazione. Più righe per persona/budget = **più step** (tranche): applicandole in ordine di decorrenza, la seconda parte dalla RAL aggiornata dalla prima.

> **Budget applicato vs impegnato**: `applicato` = Σ delta degli `ral_event` legati al budget; `impegnato` = Σ `amount` delle proposte in `bozza`/`proposta`/`approvata`; residuo = tetto − applicato − impegnato. Così il secondo step non riusa denaro già promesso.

### `hiring_budget` — tetto budget assunzioni *(top-down)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| period | TEXT | etichetta, es. "Assunzioni 2026" |
| year | INTEGER | |
| total_cap | REAL | tetto **proprio** dell'anno, senza il riporto |
| status | TEXT | `aperto`/`chiuso` — i chiusi escono da selezioni e cose aperte |
| note | TEXT | |

### `hiring_position` — posizione a budget *(ciclo di vita)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| budget_id | INTEGER FK→hiring_budget.id | budget di imputazione |
| title | TEXT | |
| team_id | INTEGER FK→team.id | |
| role_type | TEXT | |
| expected_ral | REAL | RAL prevista: è ciò che impegna il tetto finché la posizione è aperta |
| expected_start | DATE | |
| status | TEXT | `pianificata`/`in_selezione`/`assunta`/`annullata` |
| person_id | INTEGER FK→person.id | valorizzato all'assunzione |
| replaces_person_id | INTEGER FK→person.id | posizione nata da una cessazione |
| transfer_id | INTEGER FK→hiring_transfer.id | arrivata con un riporto |
| note | TEXT | |

> **Applicato vs impegnato**: `applicato` = RAL **reale** di chi è stato assunto (la `expected_ral` non conta più); `impegnato` = Σ `expected_ral` delle posizioni `pianificata`/`in_selezione`; residuo = tetto − applicato − impegnato.

### `hiring_transfer` — riporto fra budget assunzioni *(a eventi)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| from_budget_id | INTEGER FK→hiring_budget.id | budget chiuso |
| to_budget_id | INTEGER FK→hiring_budget.id | esistente o creato dal trasferimento |
| amount | REAL | quota di tetto riportata (proposta = residuo dell'origine) |
| note | TEXT | |

> Il riporto **non** viene sommato dentro `total_cap`: il tetto mostrato è `total_cap + Σ amount` dei trasferimenti entranti non annullati, e il "riporto AP" resta un badge a sé. Così un trasferimento sbagliato si annulla (`voided=1`) senza ricalcolare i tetti a mano: torna indietro il denaro e con lui le posizioni ancora aperte, mentre chi è già stato assunto resta dov'è.

### `listino_profile` — codici di listino di vendita *(config)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| code | TEXT UNIQUE | es. `GE040`, `PS010`: stabile |
| description | TEXT | es. Consultant PM, Professional Service: si rinomina e si propaga |
| active | BOOLEAN | disattivato = non si propone più, resta dove è usato |
| sort_order | INTEGER | ordine nel listino |
| day_rate | REAL | tariffa €/giorno del listino commerciale corrente; NULL = non definita, nessun confronto |

> È la categoria d'offerta commerciale, più larga del ruolo e mai riconciliabile con livello o `role_type`: un junior dev e un senior hardware possono stare nello stesso codice. La pagina Listino divide il costo azienda annuo (RAL × oneri × premi + benefit a costo + altri costi) per i giorni fatturabili dell'anno (calendario reale − ferie − malattia − formazione − attività interne, × saturazione × part-time) e aggrega per codice, team e ruolo (min, media, blended = Σcosti/Σgiorni, max) e, dove c'è `day_rate`, mostra lo scostamento tariffa − costo (per codice contro il blended, per persona contro il suo costo/gg). Mai cancellare un codice: le assegnazioni storiche lo citano.

### `listino_person_param` — produttività per persona nel listino *(config)*
| Campo | Tipo | Note |
|---|---|---|
| person_id | INTEGER PK FK→person.id | |
| formazione_pct | REAL | NULL = predefinito globale (`listino_formazione_pct`) |
| interne_pct | REAL | NULL = predefinito globale |
| saturazione_pct | REAL | NULL = predefinito globale |

> Overlay di parametri di calcolo, non stato storicizzato: si corregge in place dalla pagina Listino; la riga sparisce quando tutti e tre tornano NULL. Ferie, malattia e costi restano globali; il part-time viene da `employment`.

### `benefit_type` — catalogo componenti benefit *(config)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT | Auto, Rimborso pasto, MLO, Reperibilità H24… |
| value_kind | TEXT | `boolean` / `enum` / `amount` |
| enum_options | JSON | es. Auto → `["si","no","addebito"]` |
| is_cost | BOOLEAN | concorre al costo totale |
| active | BOOLEAN | |

### `benefit_assignment` — benefit assegnato *(storicizzato)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| person_id | INTEGER FK→person.id | |
| benefit_type_id | INTEGER FK→benefit_type.id | |
| value | TEXT | interpretato secondo `value_kind` |
| effective_date | DATE | |
| end_date | DATE | NULL = attivo |
| reason | TEXT | |

### `incentive` — incentivi one-shot *(ripetibili)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| person_id | INTEGER FK→person.id | |
| inc_date | DATE | |
| amount | REAL | |
| reason | TEXT | attività spot |

### `bonus_pool` — montepremi *(tetto, top-down)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| period | TEXT | etichetta |
| cycle_id | INTEGER FK→review_cycle.id | NULL ammesso — aggancio al ciclo |
| total_cap | REAL | tetto montepremi |
| status | TEXT | `bozza`/`chiuso` |

### `bonus_allocation` — distribuzione premio per persona
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| pool_id | INTEGER FK→bonus_pool.id | |
| person_id | INTEGER FK→person.id | |
| weight | REAL | da `weight_mapping` (ultimo box) — editabile |
| proposed_amount | REAL | `weight` normalizzato × `total_cap` |
| final_amount | REAL | override manuale (bottom-up) |
| note | TEXT | |

> Σ `final_amount` ≤ `total_cap`: residuo/sforamento mostrato in tempo reale.

---

## Area 4 — Interazioni e Documenti

### `meeting_note` — nota meeting
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| person_id | INTEGER FK→person.id | |
| note_date | DATE | |
| type | TEXT | `1:1`/`review`/`feedback`/`altro` |
| title | TEXT | |
| body | TEXT | testo libero |
| created_at | DATETIME | |
| updated_at | DATETIME | NULL = mai modificata |
| archived_at | DATETIME | NULL = attiva; valorizzata = archiviata |

> La ricerca è per parole (`LIKE` su titolo e testo, tutte le parole devono comparire). Fino alla 0.30 c'era un indice FTS5: eliminato nella 0027 perché un indice full-text non si filtra per perimetro (chi lo interroga legge le note di tutti).

> Unica eccezione all'append-only: la nota è un **documento**, non un evento — nessuna query di stato la legge. Il "cambiamento reale" è una nota nuova, la "correzione" è la modifica in place. Si cancella davvero, e cancellandola le `action_item` collegate sopravvivono con `meeting_note_id = NULL`: l'impegno preso non muore col testo.

> Archiviare (`archived_at`) toglie la nota di mezzo — lista, ricerca, dashboard, scheda persona — senza cancellarla: in Note un toggle la fa ricomparire e da lì si ripristina. È uno stato reversibile, non una correzione, quindi non tocca `updated_at`. Il report stampabile (`/notes/report`, globale o per persona) segue lo stesso toggle e marca le archiviate.

### `action_item` — impegno/azione tracciata
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| meeting_note_id | INTEGER FK→meeting_note.id | NULL se standalone |
| person_id | INTEGER FK→person.id | responsabile |
| description | TEXT | |
| due_date | DATE | scadenza |
| status | TEXT | `aperto`/`in corso`/`chiuso` |
| closed_date | DATE | |

### `attachment` — allegati documentali
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| person_id | INTEGER FK→person.id | |
| review_id | INTEGER FK→performance_review.id | NULL se allegato generico di persona |
| filename | TEXT | |
| mime | TEXT | |
| content | BLOB | dentro il DB → cifrato con tutto il resto |
| note | TEXT | |

> Caso d'uso principale: il docx/PDF compilato della review annuale accanto ai dati strutturati, senza file sparsi in chiaro sul disco.

---

## Proprietari *(0028)*

Configurazione (`lookup`, `ninebox_weight`, `weight_mapping`, `evaluation_model`, `bonus_factor`, `benefit_type`, `listino_profile`), contenitori (`review_cycle`, `ral_budget`, `bonus_pool`, `hiring_budget`, `hiring_transfer`, `reorg_scenario`), i loro figli senza persona (`hiring_position`, `reorg_team`, `reorg_move`, `reorg_position`, `reorg_position_move`) e `team` hanno `owner_user_id INTEGER DEFAULT (teamer_owner()) FK→app_user.id`: il director a cui appartengono, NULL = da assegnare. Le UNIQUE della configurazione includono il proprietario (`ninebox_weight`, `weight_mapping`, `bonus_factor` hanno ora un `id` e una UNIQUE con il proprietario al posto della chiave primaria naturale). `bonus_allocation.pool_id` è facoltativo (una riga staccata dal montepremi resta nello storico della persona). Dalla 0029 anche `person` ha `owner_user_id`: conta solo per chi non ha ancora un'assegnazione (resta del director che l'ha creata); per gli altri il perimetro lo decide il team dell'ultima assegnazione. Vedi `docs/perimetri.md`.

### `user_meta` — configurazione per director *(0028)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| key | TEXT | `default_ccnl`, `ral_stale_amber_years`, `ral_stale_red_years`, `listino_*` (stavano in `app_meta`) |
| value | TEXT | |
| owner_user_id | INTEGER FK→app_user.id | UNIQUE(owner_user_id, key) |

Dalla 0030 `lookup` e `benefit_type` tornano **aziendali** (senza `owner_user_id`, UNIQUE(category, code)) e `default_ccnl` torna in `app_meta`: la migrazione ha fuso le copie per director (vince quella di un director, la più vecchia) ripuntando le assegnazioni dei benefit. `ninebox_assessment.model_snapshot` (0030, JSON): il questionario e le caselle usati in quella valutazione, con gli indici delle risposte scelte; la storia non dipende dal questionario attuale.

In `app_meta` restano `schema_version`, `instance_id` e `default_ccnl` (identifica l'istanza: un ripristino da un'altra istanza rende i dati «da assegnare»).

## Area 5 — Utenti e audit *(0026)*

### `app_user` — utenti dell'app *(config: si corregge in place, si disattiva)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| username | TEXT UNIQUE NOCASE | si digita al login, niente elenco |
| display_name | TEXT | |
| role | TEXT | `admin` (site admin IT: utenti, audit, backup, aggiornamenti; nessun dato del personale) / `director` (il COO: tutto il resto) |
| password_hash | TEXT | `scrypt$n$r$p$salt$hash` (min 12 caratteri) |
| must_change_password | BOOLEAN | password provvisoria (creazione, reset): ogni pagina rimanda ad `/account` |
| active | BOOLEAN | disattivato = sessioni chiuse subito, login rifiutato. Mai cancellato: l'audit punta qui |
| public_mode | BOOLEAN | modalità pubblica dell'utente (persistente) |
| failed_logins | INTEGER | errori consecutivi; dopo 5 → `locked_until` crescente |
| locked_until | DATETIME | blocco per troppi tentativi (lo toglie l'admin) |
| last_login_at, password_changed_at, created_at | DATETIME | ora locale |

> Deve restare almeno un `admin` attivo. Il ruolo cambia le pagine visibili: cambiarlo chiude le sessioni dell'utente.

### `audit_event` — registro di audit *(append-only)*
| Campo | Tipo | Note |
|---|---|---|
| id | INTEGER PK | |
| at | DATETIME | ora locale |
| user_id | INTEGER FK→app_user.id | NULL per tentativi con un nome inesistente |
| username | TEXT | copiato (resta leggibile anche senza utente; `cli` per `teamer-admin`) |
| event | TEXT | `login_ok`/`login_ko`/`logout`/`lock`/`unlock`, `password_change`/`password_reset`, `user_create`/`user_update`/`user_disable`/`user_enable`/`user_unlock`, `sessions_close`, `backup`, `restore`, `assign_unassigned`, `team_transfer`, `update_request`, `migrazione_chiave`, `azione` |
| detail | TEXT | per `azione`: metodo, path ed esito della richiesta — **mai il contenuto** |
| ip | TEXT | |

> Nessuna route aggiorna o cancella righe. Le anteprime htmx (`*/simulate`) non sono azioni e non si registrano. `app_user` e `audit_event` sono dell'**istanza**: un ripristino sostituisce i dati ma ricopia queste due tabelle da quelle correnti.

---

## Come si legano i moduli

- **Ciclo annuale**: `review_cycle` → durante la review dell'anno N si valutano i `goal` definiti nel ciclo N−1 (`goal_review`, doppio punteggio self/TL) e si definiscono i `goal` del ciclo N+1; `performance_review` raggruppa punteggi, commenti e `wellbeing_entry`.
- **9-box/valutazione → premi**: l'ultimo `ninebox_assessment.box_number` → `weight_mapping.weight` → `bonus_allocation.weight` (poi override manuale).
- **Costo totale persona** (report): `ral_event` (ultimo) + `benefit_assignment` attivi con `is_cost` + `incentive` del periodo + `bonus_allocation.final_amount`.
- **Scheda individuale**: anagrafica + situazione contrattuale (`employment`: livello, smartwork, timbratura) + timeline RAL + benefit attivi + storico valutazioni/9-box + obiettivi e review + note, azioni aperte e allegati.
- **Report aggregati**: per team (via `person_assignment`), per casella 9-box, per centro di costo, budget vs allocato, trend benessere (per persona e per team), gap autovalutazione vs valutazione TL.
- **Dashboard scadenze** (vista): contratti a termine in scadenza (`employment.tipo_contratto = 'determinato'` + `end_date`), `action_item` aperti oltre `due_date`, cicli di review `aperti`, benefit con `end_date` imminente.

Lo stile UI dell'app segue i design token dell'artefatto 9-box (palette, font, componenti): vedi la sezione "Design System" in `proposte_integrazioni_schema.md`.

Il diagramma ER completo è nel file `schema_team_tool_ER.mermaid`.

Tabelle eliminate nella 0027 perché mai usate dall'app: `evaluation`, `evaluation_item` (valutazioni per competenza) e `ral_projection` (proiezioni di crescita); `ninebox_assessment` ha perso `evaluation_id`.
