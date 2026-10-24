"""Popola il DB di sviluppo con dati finti. Uso: make seed (utenti coo / admin, password demo12345678)."""
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db, session, users  # noqa: E402
from app.services.ninebox_defaults import DEFAULT_NINEBOX_CONFIG  # noqa: E402
from app.services import ninebox_calc  # noqa: E402

random.seed(42)
DEMO_PASSWORD = "demo12345678"

# (nome, ruolo, team, RAL, codice di listino: None = fuori listino)
PEOPLE = [
    ("Francesco Landini", "mgr", "Logistica", 38000, None),
    ("Giulia Ferrari", "ic", "Logistica", 27000, "PS010"),
    ("Marco Bertolini", "ic", "Logistica", 26000, "PS010"),
    ("Sara Malagoli", "tl", "Produzione", 32000, None),
    ("Luca Prandini", "ic", "Produzione", 25500, None),
    ("Elena Vezzani", "ic", "Produzione", 24500, None),
    ("Andrea Costi", "ic", "Produzione", 26500, None),
    ("Chiara Zanni", "tl", "Ufficio Tecnico", 34000, "GE040"),
    ("Davide Montanari", "ic", "Ufficio Tecnico", 30000, "PS020"),
    ("Federica Ruini", "ic", "Amministrazione", 28000, None),
]
LISTINO = [("GE040", "Consultant PM", 10, 450), ("PS010", "Professional Service", 20, 320),
           ("PS020", "Senior Professional Service", 30, None)]


def main() -> None:
    if db.db_exists():
        print(f"DB già esistente in {config.DB_PATH}: seed annullato per non sporcarlo.")
        print("Cancella il file (rm data/teamer.db) e rilancia.")
        return
    if not config.DB_KEY_FILE.exists():
        db.write_key()
        print(f"Chiave di sviluppo creata in {config.DB_KEY_FILE}")
    db.open_db(db.load_key())
    coo = users.create("coo", "director", DEMO_PASSWORD, "COO demo")   # riceve la configurazione di default
    users.create("admin", "admin", DEMO_PASSWORD, "Site admin demo")
    print(f"DB creato in {config.DB_PATH} (utenti: coo = Director, admin = Site admin; password: {DEMO_PASSWORD})")
    # i dati demo li crea coo, nella sua sessione: sono suoi (configurazione, team, cicli, budget)
    session.bind(session.Session(user_id=coo, username="coo", role="director"))

    teams = {}
    for name, parent in [("Operations", None), ("Logistica", "Operations"),
                         ("Produzione", "Operations"), ("Ufficio Tecnico", None),
                         ("Amministrazione", None)]:
        teams[name] = db.execute(
            "INSERT INTO team (name, parent_team_id) VALUES (?,?)",
            (name, teams.get(parent)))

    boxes = DEFAULT_NINEBOX_CONFIG["boxes"]
    weights = {(r["role_type"], r["seniority"]): (r["perf_adj"], r["pot_adj"])
               for r in db.query("SELECT * FROM ninebox_weight")}

    cycle_prev = db.execute(
        "INSERT INTO review_cycle (name, year, status) VALUES ('Review 2025', 2025, 'chiuso')")
    db.execute(
        "INSERT INTO review_cycle (name, year) VALUES ('Review 2026', 2026)")

    # catalogo benefit: aziendale, lo scrive la connessione di sistema
    mensa = db.sys.execute(
        "INSERT INTO benefit_type (name, value_kind, is_cost) VALUES ('Rimborso pasto', 'amount', 1)")
    db.sys.execute(
        "INSERT INTO benefit_type (name, value_kind, enum_options, is_cost) "
        "VALUES ('Auto aziendale', 'enum', '[\"si\",\"no\",\"addebito\"]', 1)")

    listino = {}   # codici di listino: aziendali (0.41), li scrive la connessione di sistema
    for code, description, order, rate in LISTINO:
        listino[code] = db.sys.execute(
            "INSERT INTO listino_profile (code, description, sort_order, day_rate) VALUES (?,?,?,?)",
            (code, description, order, rate))

    for full_name, role, team, ral, codice in PEOPLE:
        hire = date.today() - timedelta(days=random.randint(400, 3000))
        pid = db.execute(
            "INSERT INTO person (full_name, hire_date, email) VALUES (?,?,?)",
            (full_name, hire.isoformat(),
             full_name.lower().replace(" ", ".") + "@azienda.it"))
        db.execute(
            "INSERT INTO person_assignment (person_id, team_id, role_type, start_date, listino_profile_id) "
            "VALUES (?,?,?,?,?)",
            (pid, teams[team], role, hire.isoformat(), listino.get(codice)))
        db.execute(
            "INSERT INTO employment (person_id, livello, tipo_contratto, smartwork, "
            "timbratura_scheme, start_date, part_time_pct) VALUES (?,?,?,?,?,?,?)",
            (pid, "quadro" if role in ("mgr", "sr") else "impiegato",
             "indeterminato" if random.random() > 0.2 else "determinato",
             random.choice(["no", "parziale"]), "4_timbrate", hire.isoformat(),
             50 if full_name == "Marco Bertolini" else 100))
        # storia RAL: assunzione + eventuale aumento
        db.execute(
            "INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type) "
            "VALUES (?,?,?,?, 'assunzione')",
            (pid, hire.isoformat(), ral - 2000, 0))
        db.execute(
            "INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type, reason) "
            "VALUES (?,?,?,?, 'aumento', 'revisione annuale')",
            (pid, (date.today() - timedelta(days=200)).isoformat(), ral, 2000))
        if random.random() > 0.5:
            db.execute(
                "INSERT INTO benefit_assignment (person_id, benefit_type_id, value, effective_date) "
                "VALUES (?,?,?,?)",
                (pid, mensa, "1200", hire.isoformat()))
        # valutazione 9-box
        sen = "sen" if (date.today() - hire).days > 3 * 365 else "mid"
        answers = [random.randint(1, 3) for _ in range(6)]
        w = weights[(role, sen)]
        r = ninebox_calc.compute(answers, w[0], w[1], boxes)
        db.execute(
            "INSERT INTO ninebox_assessment (person_id, eval_date, role_type, seniority, "
            "raw_perf, raw_pot, adj_perf, adj_pot, perf_level, pot_level, box_number, "
            "weights_snapshot, answers) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, (date.today() - timedelta(days=random.randint(10, 120))).isoformat(),
             role, sen, r["raw_perf"], r["raw_pot"], r["adj_perf"], r["adj_pot"],
             r["perf_level"], r["pot_level"], r["box_number"],
             json.dumps({"perf_adj": w[0], "pot_adj": w[1]}), json.dumps(answers)))
        # obiettivi definiti nel ciclo 2025 (da valutare nel 2026)
        db.execute(
            "INSERT INTO goal (person_id, cycle_id, category, description, weight_pct) "
            "VALUES (?,?,?,?,?)",
            (pid, cycle_prev, "professionale", f"Obiettivo professionale di {full_name.split()[0]}", 100))
        db.execute(
            "INSERT INTO goal (person_id, cycle_id, category, description, weight_pct) "
            "VALUES (?,?,?,?,?)",
            (pid, cycle_prev, "personale", "Partecipare agli eventi extra lavorativi", 100))
        # note 1:1
        db.execute(
            "INSERT INTO meeting_note (person_id, note_date, type, title, body) VALUES (?,?,?,?,?)",
            (pid, (date.today() - timedelta(days=random.randint(5, 60))).isoformat(),
             "1:1", "Check mensile", f"Confronto con {full_name}: carico ok, nessun blocco."))

    # budget e azioni
    db.execute(
        "INSERT INTO ral_budget (period, total_cap, description) VALUES ('2026', 15000, 'Budget aumenti 2026')")
    people = db.query("SELECT id FROM person LIMIT 3")
    for i, p in enumerate(people):
        db.execute(
            "INSERT INTO action_item (person_id, description, due_date) VALUES (?,?,?)",
            (p["id"], f"Azione di prova {i+1}",
             (date.today() + timedelta(days=15 * (i - 1))).isoformat()))
    session.reset()
    db.close_db()
    print(f"Seed completato: {len(PEOPLE)} persone, 2 cicli, budget 2026, 9-box per tutti, "
          f"{len(LISTINO)} codici di listino.")


if __name__ == "__main__":
    main()
