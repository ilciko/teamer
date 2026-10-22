import os
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp())
os.environ["TEAMER_DB_PATH"] = str(_tmp / "test.db")
os.environ["TEAMER_DB_KEY_FILE"] = str(_tmp / "test.key")
# TestClient fuori da un `with` non avvia il lifespan, quindi il reaper non parte
# comunque: questo lo blinda anche se un domani si passasse al context manager.
os.environ["TEAMER_AUTOLOCK"] = "0"

from app import config, db, session, users  # noqa: E402

config.DB_PATH = Path(os.environ["TEAMER_DB_PATH"])
config.DB_KEY_FILE = Path(os.environ["TEAMER_DB_KEY_FILE"])
db.write_key()
TEST_KEY = db.load_key()
PASSWORD = "password-di-prova"


@pytest.fixture()
def fresh_db(tmp_path):
    """DB cifrato pulito e migrato, chiuso a fine test."""
    path = tmp_path / "t.db"
    db.close_db()
    db.open_db(TEST_KEY, db_path=path)
    yield path
    db.close_db()


def login(c, username: str, password: str = PASSWORD):
    r = c.post("/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r


@pytest.fixture()
def app_db(tmp_path):
    """DB nuovo aperto come all'avvio del servizio, con un director e un site admin."""
    path = tmp_path / "e2e.db"
    config.DB_PATH = path
    session.reset()
    db.close_db()
    assert db.startup() == "pronto"
    users.create("coo", "director", PASSWORD)
    users.create("it", "admin", PASSWORD)
    yield path
    session.reset()
    db.close_db()


@pytest.fixture()
def client(app_db):
    """TestClient loggato come director."""
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    assert login(c, "coo").url.path == "/"
    yield c


@pytest.fixture()
def admin_client(app_db):
    """TestClient loggato come site admin."""
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    assert login(c, "it").url.path == "/admin"
    yield c
