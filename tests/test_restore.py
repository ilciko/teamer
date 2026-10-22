"""Ripristino e import: i dati arrivano dal file, utenti e audit restano quelli dell'istanza."""
import pytest

from app import config, db, users
from tests.conftest import PASSWORD, TEST_KEY, make_legacy_db


def _people():
    return [r["full_name"] for r in db.query("SELECT full_name FROM person ORDER BY id")]


def test_backup_della_stessa_istanza(app_db, tmp_path):
    db.execute("INSERT INTO person (full_name) VALUES ('Prima')")
    bk = tmp_path / "bk.db"
    db.backup_to(bk)
    db.execute("INSERT INTO person (full_name) VALUES ('Dopo')")
    users.create("nuovo", "director", PASSWORD)          # creato dopo il backup: deve restare
    stats = db.restore(bk)
    assert _people() == ["Prima"] and stats["people"] == 1
    assert users.by_username("nuovo") and users.by_username("it")
    assert (app_db.parent / "backups" / stats["backup"]).exists()
    assert db.state() == "pronto"
    db.close_db()
    db.open_db(TEST_KEY, app_db)                          # il file al suo posto si apre con la chiave
    assert _people() == ["Prima"]


def test_import_da_un_altra_istanza(app_db, tmp_path):
    other = db.generate_key()
    src = tmp_path / "altra.db"
    conn = db._connect(src, db._raw(other))
    db._migrate(conn)
    conn.execute("INSERT INTO person (full_name) VALUES ('Da casa')")
    conn.commit()
    conn.close()
    with pytest.raises(db.WrongPassword):
        db.restore(src)                                   # senza la chiave giusta non si apre
    assert _people() == []                                # e niente è cambiato
    db.restore(src, source_key=other.upper())
    assert _people() == ["Da casa"]


def test_import_di_un_db_della_029(app_db, tmp_path):
    src = tmp_path / "casa.db"
    make_legacy_db(src, "vecchia-pw", people=["Anna", "Bruno"])
    with pytest.raises(db.WrongPassword):
        db.restore(src, password="sbagliata")
    stats = db.restore(src, password="vecchia-pw")
    assert stats["from_version"] == 25 and _people() == ["Anna", "Bruno"]
    assert db.schema_version() == db.latest_migration()
    assert db.get_meta("public_mode", "assente") == "assente"
    assert {u["username"] for u in users.all_users()} == {"coo", "it"}


def test_file_non_valido(app_db, tmp_path):
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"non sono un database" * 100)
    with pytest.raises(db.WrongPassword):
        db.restore(junk)
    foreign = tmp_path / "foreign.db"
    conn = db._connect(foreign, db._raw(TEST_KEY))
    conn.execute("CREATE TABLE x (a)")
    conn.commit()
    conn.close()
    with pytest.raises(db.RestoreError, match="non è un database di Teamer"):
        db.restore(foreign)
    with pytest.raises(db.RestoreError, match="64 caratteri"):
        db.restore(foreign, source_key="corta")


def test_versione_piu_recente_rifiutata(app_db, tmp_path):
    db.execute("UPDATE app_meta SET value='999' WHERE key='schema_version'")
    bk = tmp_path / "futuro.db"
    db.backup_to(bk)
    db.execute(f"UPDATE app_meta SET value='{db.latest_migration()}' WHERE key='schema_version'")
    with pytest.raises(db.RestoreError, match="più recente"):
        db.restore(bk)


def test_ripristino_dal_pannello(admin_client, client, tmp_path):
    src = tmp_path / "casa.db"
    make_legacy_db(src, "vecchia-pw", people=["Carla"])
    files = {"file": ("casa.db", src.read_bytes(), "application/octet-stream")}
    r = admin_client.post("/admin/restore", files=files, data={"password": "vecchia-pw", "confirm": "no"})
    assert "SOSTITUISCI" in r.text and _people() == []
    r = admin_client.post("/admin/restore", files=files, data={"password": "sbagliata", "confirm": "SOSTITUISCI"})
    assert "non si apre" in r.text
    r = admin_client.post("/admin/restore", files=files, data={"password": "vecchia-pw", "confirm": "SOSTITUISCI"})
    assert "Ripristino completato: 1 persona" in r.text and _people() == ["Carla"]
    assert client.get("/people").status_code == 200                # le sessioni restano valide
    assert "Carla" in client.get("/people").text
    row = db.one("SELECT * FROM audit_event WHERE event='restore'")
    assert row["username"] == "it" and "password 0.29" in row["detail"]
    assert client.post("/admin/restore", files=files, data={"confirm": "SOSTITUISCI"}).status_code == 403
    assert not list((config.DB_PATH.parent / "restore").glob("*.db"))   # nessun file lasciato in giro


def test_restore_da_shell(app_db, tmp_path, monkeypatch, capsys):
    from app import admin_cli

    src = tmp_path / "casa.db"
    make_legacy_db(src, "vecchia-pw", people=["Dario"])
    monkeypatch.setattr(admin_cli.getpass, "getpass", lambda prompt: "vecchia-pw")
    db.close_db()                                          # il servizio è fermo (lo ferma il wrapper)
    assert admin_cli.main(["restore", str(src), "--password"]) == 0
    assert "1 persona" in capsys.readouterr().out
    db.startup()
    assert _people() == ["Dario"]
    assert db.one("SELECT username FROM audit_event WHERE event='restore'")["username"] == "cli"
