import os
import tempfile
from pathlib import Path

import pytest

os.environ["TEAMER_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "test.db")
# TestClient fuori da un `with` non avvia il lifespan, quindi il reaper non parte
# comunque: questo lo blinda anche se un domani si passasse al context manager.
os.environ["TEAMER_AUTOLOCK"] = "0"

from app import config, db, session  # noqa: E402

config.DB_PATH = Path(os.environ["TEAMER_DB_PATH"])


@pytest.fixture()
def fresh_db(tmp_path):
    """DB cifrato pulito e migrato, chiuso a fine test."""
    path = tmp_path / "t.db"
    db.close_db()
    db.open_db("password-test", db_path=path)
    yield path
    db.close_db()


@pytest.fixture()
def client(tmp_path):
    """TestClient loggato su un DB temporaneo (primo avvio = creazione)."""
    from fastapi.testclient import TestClient

    from app.main import app

    path = tmp_path / "e2e.db"
    config.DB_PATH = path
    db.close_db()
    session.reset()
    c = TestClient(app)
    r = c.post("/login", data={"password": "password-test", "password_confirm": "password-test"})
    assert r.status_code == 200 and r.url.path == "/"
    yield c
    db.close_db()
