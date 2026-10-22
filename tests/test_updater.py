"""Aggiornamenti dall'app: confronto versioni, controllo release, richiesta all'updater di sistema."""
import json

import pytest

from app.services import updater


def test_versioni():
    assert updater.parse_version("v0.29.0") == (0, 29, 0) == updater.parse_version("0.29.0")
    assert updater.parse_version("dev") is None and updater.parse_version("main-202610221200") is None
    assert updater.is_newer("v0.29.0", "0.28.2") and updater.is_newer("v1.0.0", "0.99.9")
    assert not updater.is_newer("v0.28.2", "0.28.2") and not updater.is_newer("v0.29.0", "dev")


def test_parse_release():
    ok = updater.parse_release({"tag_name": "v0.29.0", "html_url": "u", "name": "", "published_at": "x"})
    assert ok == {"tag": "v0.29.0", "url": "u", "name": "v0.29.0", "published_at": "x"}
    assert updater.parse_release({"tag_name": "v0.29.0", "prerelease": True}) is None
    assert updater.parse_release({"tag_name": "nightly"}) is None
    assert updater.parse_release(["boh"]) is None


@pytest.fixture()
def upd_dir(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "teamer.db")
    monkeypatch.setattr(config, "APP_VERSION", "0.28.2")
    return tmp_path / "update"


def test_check_salva_e_in_errore_tiene_l_ultima(upd_dir):
    r = updater.check(fetch=lambda url: {"tag_name": "v0.29.0", "html_url": "https://x/rel"})
    assert r["tag"] == "v0.29.0" and json.loads((upd_dir / "latest.json").read_text())["tag"] == "v0.29.0"
    assert updater.available()["tag"] == "v0.29.0"

    def boom(url):
        raise OSError("rete assente")

    r = updater.check(fetch=boom)
    assert r["tag"] == "v0.29.0" and "rete assente" in r["error"]          # l'ultima nota resta
    updater.check(fetch=lambda url: {"tag_name": "v0.28.2"})
    assert updater.available() is None                                      # già installata


def test_file_corrotti_o_assenti(upd_dir):
    assert updater.latest() is None and updater.state() is None and updater.log_tail() == ""
    upd_dir.mkdir()
    (upd_dir / "state.json").write_text("{non json")
    assert updater.state() is None and not updater.pending()


def test_richiesta_solo_con_la_path_unit(upd_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "UNIT_FILE", tmp_path / "manca.path")
    assert not updater.can_request() and not updater.request_update()
    unit = tmp_path / "teamer-update.path"
    unit.write_text("[Path]")
    monkeypatch.setattr(updater, "UNIT_FILE", unit)
    assert updater.request_update() and (upd_dir / "request").exists()
    assert updater.pending() and not updater.request_update()             # niente doppie richieste


def test_tab_aggiornamenti_e_avviso(client, tmp_path, monkeypatch):
    from app import config, db

    monkeypatch.setattr(config, "APP_VERSION", "0.28.2")
    html = client.get("/settings?tab=update").text
    assert "Installata" in html and "0.28.2" in html and "non è disponibile qui" in html
    assert "update-badge" not in client.get("/org").text
    updater.check(fetch=lambda url: {"tag_name": "v0.29.0", "html_url": "https://x/rel"})
    assert "↑ Aggiornamento v0.29.0" in client.get("/org").text
    unit = tmp_path / "teamer-update.path"
    unit.write_text("[Path]")
    monkeypatch.setattr(updater, "UNIT_FILE", unit)
    assert "Aggiorna a v0.29.0" in client.get("/settings?tab=update").text
    r = client.post("/settings/update/run", follow_redirects=False)
    assert r.headers["location"] == "/settings?tab=update&saved=avviato"
    assert (updater.update_dir() / "request").exists()
    assert 'id="upd-wait"' in client.get("/settings?tab=update").text
    # modalità pubblica: niente avviso, la tab è chiusa
    client.post("/public-mode", data={"next": "/org"})
    assert "update-badge" not in client.get("/org").text
    assert client.get("/settings?tab=update").status_code == 403
    assert db.get_meta("public_mode") == "1"


def test_backup_elencati(upd_dir, tmp_path):
    assert updater.backups() == []
    bk = tmp_path / "backups"
    bk.mkdir()
    (bk / "teamer-v0.28.2-20261022.db").write_bytes(b"x" * 2048)
    (bk / "altro.txt").write_text("no")
    assert [b["name"] for b in updater.backups()] == ["teamer-v0.28.2-20261022.db"]
    assert updater.backups()[0]["size_kb"] == 2
