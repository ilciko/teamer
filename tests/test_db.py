"""Test su cifratura, migrazioni e regole a eventi."""
import pytest

from app import db
from tests.conftest import TEST_KEY


def test_migrations_applied(fresh_db):
    assert db.schema_version() >= 2
    tables = {r["name"] for r in db.query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "AND name NOT LIKE 'meeting_note_fts%'")}
    expected = {
        "person", "team", "person_assignment", "employment", "lookup", "app_meta",
        "review_cycle", "evaluation_model", "evaluation", "evaluation_item",
        "ninebox_assessment", "ninebox_weight", "weight_mapping",
        "goal", "goal_review", "performance_review", "wellbeing_entry",
        "ral_budget", "ral_event", "ral_projection", "benefit_type",
        "benefit_assignment", "incentive", "bonus_pool", "bonus_allocation",
        "meeting_note", "action_item", "attachment",
    }
    assert expected <= tables
    assert len(expected) == 28


def test_seed_config(fresh_db):
    assert len(db.query("SELECT * FROM ninebox_weight")) == 12
    assert len(db.query("SELECT * FROM weight_mapping")) == 9
    assert db.one("SELECT COUNT(*) AS n FROM lookup")["n"] > 30


def test_wrong_key(fresh_db):
    db.close_db()
    with pytest.raises(db.WrongPassword):
        db.open_db(db.generate_key(), db_path=fresh_db)
    # e con quella giusta riapre
    db.open_db(TEST_KEY, db_path=fresh_db)
    assert db.schema_version() >= 2


def test_file_cifrato_con_la_chiave_grezza(fresh_db):
    assert fresh_db.read_bytes()[:16] != b"SQLite format 3\x00"


def test_chiave_mancante_o_malformata(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "DB_KEY_FILE", tmp_path / "nessuna.key")
    with pytest.raises(db.KeyMissing):
        db.load_key()
    assert db.startup() == "chiave_mancante" and not db.is_open()
    (tmp_path / "nessuna.key").write_text("corta")
    with pytest.raises(db.KeyMissing, match="non valida"):
        db.load_key()


def test_write_key_non_sovrascrive(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "DB_KEY_FILE", tmp_path / "k")
    key = db.write_key()
    assert db.load_key() == key and oct((tmp_path / "k").stat().st_mode)[-3:] == "640"
    with pytest.raises(FileExistsError):
        db.write_key()
    assert db.load_key() == key


def test_migrazione_dal_db_cifrato_con_la_password(tmp_path, monkeypatch):
    """Le versioni mono-utente cifravano con la password del COO: si ricifra sulla chiave."""
    from app import config

    path = tmp_path / "legacy.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    db.close_db()
    conn = db._connect(path, "'vecchia-password'")
    conn.execute("CREATE TABLE x (a)")
    conn.execute("INSERT INTO x VALUES (42)")
    conn.commit()
    conn.close()
    assert db.startup() == "legacy" and not db.is_open()
    with pytest.raises(db.WrongPassword):
        db.migrate_legacy("sbagliata")
    db.migrate_legacy("vecchia-password")
    assert db.state() == "pronto" and db.one("SELECT a FROM x")["a"] == 42
    assert db.schema_version() >= 26
    db.close_db()
    with pytest.raises(db.WrongPassword):
        db._connect(path, "'vecchia-password'")
    assert db.startup() == "pronto"
    db.close_db()


def test_fts_search(fresh_db):
    pid = db.execute("INSERT INTO person (full_name) VALUES ('Test Persona')")
    db.execute(
        "INSERT INTO meeting_note (person_id, note_date, title, body) "
        "VALUES (?, '2026-01-01', 'Registro Rentri', 'gestione del magazzino a Rubiera')",
        (pid,))
    hits = db.query(
        "SELECT rowid FROM meeting_note_fts WHERE meeting_note_fts MATCH 'rubiera'")
    assert len(hits) == 1


def test_voided_excluded_from_current_ral(fresh_db):
    from app.services import cost

    pid = db.execute("INSERT INTO person (full_name) VALUES ('X Y')")
    db.execute(
        "INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type) "
        "VALUES (?, '2025-01-01', 30000, 0, 'assunzione')", (pid,))
    bad = db.execute(
        "INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type) "
        "VALUES (?, '2026-01-01', 99000, 69000, 'aumento')", (pid,))
    db.execute("UPDATE ral_event SET voided=1 WHERE id=?", (bad,))
    assert cost.current_ral(pid)["amount"] == 30000


def test_backup_is_encrypted_copy(fresh_db, tmp_path):
    db.execute("INSERT INTO person (full_name) VALUES ('Backup Test')")
    dest = tmp_path / "bck.db"
    db.backup_to(dest)
    assert dest.exists() and dest.stat().st_size > 0
    # il backup si apre con la stessa chiave e contiene i dati
    db.close_db()
    db.open_db(TEST_KEY, db_path=dest)
    assert db.one("SELECT COUNT(*) AS n FROM person")["n"] == 1


def test_current_ral_a_una_data(fresh_db):
    """Un evento retrodatato si confronta col precedente, non con uno futuro."""
    from app.services import cost

    pid = db.execute("INSERT INTO person (full_name) VALUES ('Retro Datata')")
    for eff, amount in (("2021-01-01", 44000), ("2022-07-01", 48100)):
        db.execute(
            "INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type) "
            "VALUES (?,?,?,0,'aumento')", (pid, eff, amount))
    assert cost.current_ral(pid)["amount"] == 48100
    assert cost.current_ral(pid, on_date="2022-01-01")["amount"] == 44000


def test_last_ral_changes(fresh_db):
    """L'ultima variazione; per chi non ne ha, l'ultimo evento con importo 0."""
    from app.services import cost

    pid = db.execute("INSERT INTO person (full_name) VALUES ('Aumenti Vari')")
    eventi = [("2020-01-01", 39500, "assunzione"), ("2021-01-01", 44000, "promozione"),
              ("2022-01-01", 47500, "aumento")]
    for eff, amount, tipo in eventi:
        db.execute(
            "INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type) "
            "VALUES (?,?,?,0,?)", (pid, eff, amount, tipo))
    neo = db.execute("INSERT INTO person (full_name) VALUES ('Neo Assunto')")
    db.execute(
        "INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type) "
        "VALUES (?, '2026-03-01', 32000, 0, 'assunzione')", (neo,))

    changes = cost.last_ral_changes()
    assert changes[pid] == {"delta": 3500, "effective_date": "2022-01-01"}
    assert changes[neo] == {"delta": 0.0, "effective_date": "2026-03-01"}


def test_migrazione_censimento_allinea_alla_assunzione(fresh_db):
    """0013: il censimento di chi è assunto dopo prende la data di assunzione."""
    neo = db.execute("INSERT INTO person (full_name, hire_date) VALUES ('Neo', '2026-06-01')")
    vet = db.execute("INSERT INTO person (full_name, hire_date) VALUES ('Vet', '2010-03-01')")
    for pid in (neo, vet):
        db.execute(
            "INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type) "
            "VALUES (?, '2025-01-01', 40000, 0, 'censimento')", (pid,))
    # un aumento vero non va toccato, qualunque sia la data di assunzione
    db.execute("INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type) "
               "VALUES (?, '2020-01-01', 38000, 0, 'aumento')", (neo,))

    with db.transaction() as conn:
        conn.executescript((db.MIGRATIONS_DIR / "0013_ral_censimento_assunzione.sql").read_text())

    def eff(pid, tipo):
        return db.one("SELECT effective_date FROM ral_event WHERE person_id=? AND change_type=?",
                      (pid, tipo))["effective_date"]

    assert eff(neo, "censimento") == "2026-06-01"
    assert eff(vet, "censimento") == "2025-01-01"
    assert eff(neo, "aumento") == "2020-01-01"
