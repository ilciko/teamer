"""Utenti: hash delle password, backoff, regole su admin e audit."""
import pytest

from app import db, session, users


@pytest.fixture()
def u(fresh_db):
    session.reset()
    uid = users.create("coo", "director", "password-lunga-1")
    yield uid
    session.reset()


def test_hash_scrypt_con_sale():
    h1, h2 = users.hash_password("segreta-segreta"), users.hash_password("segreta-segreta")
    assert h1.startswith("scrypt$") and h1 != h2
    assert users.verify_password("segreta-segreta", h1)
    assert not users.verify_password("segreta-segretA", h1)
    assert not users.verify_password("x", "rotto") and not users.verify_password("x", "bcrypt$1$2$3$aa$bb")


def test_regole_della_password():
    assert users.password_error("corta") and users.password_error("a" * 12, "b" * 12)
    assert users.password_error("a" * 12, "a" * 12) is None


def test_login_e_nome_utente_senza_maiuscole(u):
    user, err = users.authenticate("COO", "password-lunga-1")
    assert err is None and user["id"] == u and user["last_login_at"]


def test_backoff_dopo_troppi_errori(u):
    for _ in range(users.MAX_FAILED):
        assert users.authenticate("coo", "sbagliata")[1] == users.GENERIC_ERROR
    user, err = users.authenticate("coo", "password-lunga-1")     # giusta, ma bloccato
    assert user is None and "Troppi tentativi" in err
    users.unlock(u)
    assert users.authenticate("coo", "password-lunga-1")[1] is None
    assert users.get(u)["failed_logins"] == 0


def test_utente_inesistente_stesso_messaggio_e_audit(u):
    assert users.authenticate("nessuno", "x")[1] == users.GENERIC_ERROR
    row = db.one("SELECT * FROM audit_event WHERE event='login_ko' ORDER BY id DESC")
    assert row["username"] == "nessuno" and row["user_id"] is None


def test_disattivato_non_entra_e_perde_le_sessioni(u):
    s = session.create(u, "coo", "director")
    users.set_active(u, False)
    assert session.get(s.id) is None
    assert "disattivato" in users.authenticate("coo", "password-lunga-1")[1]


def test_reset_password_provvisoria_da_cambiare(u):
    s = session.create(u, "coo", "director")
    temp = users.reset_password(u)
    assert len(temp) >= users.MIN_PASSWORD and session.get(s.id) is None
    user, err = users.authenticate("coo", temp)
    assert err is None and user["must_change_password"] == 1
    users.set_password(u, "nuova-password-1")
    assert users.get(u)["must_change_password"] == 0


def test_resta_sempre_un_admin(u):
    a = users.create("it", "admin", "password-lunga-1")
    with pytest.raises(users.UserError):
        users.set_active(a, False)
    with pytest.raises(users.UserError):
        users.update(a, None, "director")
    b = users.create("it2", "admin", "password-lunga-1")
    users.set_active(a, False)
    assert users.active_admins() == 1 and users.get(b)["active"]


def test_nomi_utente_unici_e_validi(u):
    with pytest.raises(users.UserError, match="esiste già"):
        users.create("Coo", "director", "password-lunga-1")
    with pytest.raises(users.UserError):
        users.create("con spazio", "director", "password-lunga-1")
    with pytest.raises(users.UserError):
        users.create("x", "manager", "password-lunga-1")


def test_cambio_ruolo_chiude_le_sessioni(u):
    users.create("it", "admin", "password-lunga-1")
    s = session.create(u, "coo", "director")
    users.update(u, "Il COO", "admin")
    assert session.get(s.id) is None and users.get(u)["display_name"] == "Il COO"
