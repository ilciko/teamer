# Esclusioni per l'analisi di sicurezza

Questo file dice al sistema di verifica quali reperti degli scanner statici (semgrep, bandit, ruff) sono già stati esaminati: per ciascuno indica perché non è sfruttabile o dove è mitigato. Ultima revisione: **v0.47.7** (2026-10-24).

Regole per chi lo legge:

- Un reperto si esclude solo se rientra **per intero** in una voce: regola, percorso e condizione. Se una condizione non è più vera, il reperto torna da segnalare.
- Un reperto nuovo (regola, file o punto non elencati) si segnala sempre.
- Ogni esclusione va riconfermata quando cambia il codice che la giustifica, e questo file si aggiorna nello stesso commit.

Stack: FastAPI + Jinja2 + htmx, SQLite/SQLCipher con il driver `sqlcipher3` (DB-API, segnaposto `?`). **Non è Django né SQLAlchemy**: le regole `python.django.*` e `python.sqlalchemy.*` colpiscono forme simili ma non le API che descrivono.

```yaml
exclusions:
  - id: csrf-origin-guard
    cwe: CWE-352
    rules:
      - python.django.security.django-no-csrf-token.django-no-csrf-token
    paths: ["app/templates/**/*.html"]
    status: mitigato (0.47.5)
    reason: >
      I template sono Jinja2, dove {% csrf_token %} non esiste. La protezione è il middleware
      origin_guard in app/main.py: rifiuta con 403 ogni richiesta non-GET di un'altra origine,
      login e battito compresi (Sec-Fetch-Site in HTTPS, Origin contro Host/X-Forwarded-Host in
      HTTP). Si aggiunge al cookie di sessione SameSite=Lax. Test: tests/test_csrf.py.
    valid_while:
      - "app/main.py contiene origin_guard ed è il middleware più esterno (registrato dopo auth_guard)"
      - "SAFE_METHODS contiene solo GET, HEAD, OPTIONS e nessuna route GET modifica dati"
      - "tests/test_csrf.py esiste e passa"

  - id: sql-identificatori-interni
    cwe: CWE-89
    rules:
      - B608                       # bandit hardcoded_sql_expressions
      - python.lang.security.audit.formatted-sql-query.formatted-sql-query
      - python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
      - python.django.security.injection.tainted-sql-string.tainted-sql-string
    paths:
      - app/perimeter.py
      - app/db.py
      - app/routers/admin.py
      - app/routers/compensation.py
      - app/routers/interactions.py
      - app/routers/listino.py
      - app/routers/ninebox.py
      - app/routers/org.py
      - app/routers/reorg.py
      - app/routers/reports.py
      - app/routers/review.py
    status: falso positivo (verificato punto per punto)
    reason: >
      Nelle f-string SQL entrano solo: nomi di tabelle e colonne da costanti del codice
      (perimeter.OWNED/TEAM/CONFIG/AUTHORED/OWNER_COL/CATALOG_REFS/NATURAL_KEYS, db.INSTANCE_TABLES,
      admin.AUDIT_COLS, listino.PROD_KEYS) o lette da PRAGMA table_info / sqlite_master;
      interi già convertiti (int(uid), int(src), id dal DB); frammenti costanti
      (perimeter.IN_PERSON, interactions._PERSON_JOIN/_PERSON_NAME, reports.director_of/person_join,
      org «current», ninebox team_join/conds, admin _audit_where con soli «colonna = ?»);
      liste di segnaposto ",".join("?" * n). Tutti i valori dell'utente passano come parametri.
      review.py: la colonna viene dal dizionario fisso {"self","tl","note"} (un campo diverso dà
      KeyError). listino.py: le chiavi vengono da listino.parse_prod, che restituisce solo PROD_KEYS.
    valid_while:
      - "nessun valore di Request/Form/Query/form.get finisce in una f-string SQL, se non convertito a int o scelto da un insieme fisso"
      - "le scritture dell'app passano l'analisi AST di tests/test_sql_scritture.py"

  - id: sqlcipher-pragma-key
    cwe: CWE-89
    rules:
      - python.lang.security.audit.formatted-sql-query.formatted-sql-query
      - B608
    paths: ["app/db.py"]
    status: falso positivo, irrobustito (0.47.6)
    reason: >
      PRAGMA key/rekey non accettano parametri, quindi il letterale si scrive per forza nel testo.
      db._raw accetta solo 64 cifre esadecimali (ValueError altrimenti); load_key e il ripristino
      con source_key le validano anche prima. La password legacy ≤ 0.29 (_quote_key) è un
      letterale SQL con gli apici raddoppiati. Test: tests/test_db.py::test_raw_accetta_solo_chiavi_esadecimali.
    valid_while:
      - "ogni PRAGMA key/rekey usa db._raw(...) o un letterale prodotto da db._quote_key(...)"

  - id: updater-url-fisso
    cwe: CWE-939
    rules:
      - python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
    paths: ["app/services/updater.py"]
    status: falso positivo
    reason: >
      updater._fetch apre solo https://api.github.com/repos/{REPO}/releases/latest o /tags, con
      REPO dalla variabile d'ambiente del server TEAMER_UPDATE_REPO (predefinita ilciko/teamer).
      Nessun URL arriva da una richiesta.
    valid_while:
      - "gli URL passati a _fetch sono costruiti solo da REPO e da percorsi costanti"

  - id: vendored-js
    rules:
      - javascript.lang.security.audit.prototype-pollution.prototype-pollution-loop.prototype-pollution-loop
    paths: ["app/static/js/chart.umd.js", "app/static/js/htmx.min.js"]
    status: libreria di terze parti
    reason: >
      Chart.js e htmx minificati, inclusi nel repo per il funzionamento offline. Non sono codice
      dell'app: le loro vulnerabilità si seguono per versione (avvisi del progetto), non per regola.
    valid_while:
      - "il file è la build ufficiale della libreria, non modificata"

  - id: test-e-seed
    rules: [B101, B105, B106, B107, B311]
    paths: ["tests/**", "scripts/seed_demo.py"]
    status: non pertinente
    reason: >
      assert e password di prova nei test; random e password demo nel generatore del DB di
      esempio (make seed), che non gira in produzione.

  - id: reaper-sessioni
    rules: [B110]
    paths: ["app/session.py"]
    status: voluto
    reason: >
      try/except/pass dentro il while del reaper (session.reaper), che blocca le sessioni
      abbandonate: un errore in un giro (blocco o audit) non deve uccidere il task, altrimenti
      nessuna sessione si bloccherebbe più fino al riavvio. Il giro dopo riprova.
    valid_while:
      - "l'except Exception: pass resta dentro il ciclo di session.reaper e non altrove"

  - id: fastapi-query-default
    rules: [B008]
    paths: ["app/routers/ninebox.py", "app/routers/org.py"]
    status: idioma del framework
    reason: >
      Query(...) come valore predefinito di un parametro è il modo documentato di FastAPI per i
      parametri ripetuti (?team=1&team=2): il framework lo legge, non viene chiamato una volta sola.
```

## Mitigazioni che gli scanner non vedono

| Rischio | Dove | Da |
| --- | --- | --- |
| CSRF | `app/main.py` → `origin_guard` | 0.47.5 |
| Clickjacking, script e connessioni verso altri host | `app/main.py` → `SECURITY_HEADERS` (CSP con `frame-ancestors 'none'`, `X-Frame-Options`, `nosniff`, `Referrer-Policy`) | 0.47.7 |
| Cookie in chiaro dietro un proxy HTTPS | `app/main.py` → `Secure` su ogni `Set-Cookie` in HTTPS | 0.47.7 |
| Accesso a dati fuori perimetro | `app/perimeter.py`: viste temporanee, guardie e authorizer SQLite sulla connessione di sessione | 0.32 |
