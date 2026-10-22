"""Barra laterale: gruppi a fisarmonica (uno solo aperto), firma con versione, modalità pubblica."""
import re


def _nav(html):
    return html.split('class="sidebar"')[1].split("</nav>")[0]


def _groups(html):
    """[(titolo, aperto)] dei gruppi della barra."""
    return [(t, bool(o)) for o, t in re.findall(
        r'<details class="nav-group" name="nav-groups"( open)?>\s*<summary>([^<]+)</summary>', _nav(html))]


def test_tutti_chiusi_sulla_dashboard(client):
    groups = _groups(client.get("/").text)
    assert [t for t, _ in groups] == ["Organizzazione", "Retribuzione", "Valutazione", "Interazioni", "Sistema"]
    assert not any(o for _, o in groups)


def test_aperto_solo_il_gruppo_della_pagina(client):
    for path, group in [("/people", "Organizzazione"), ("/comp/hiring", "Organizzazione"),
                        ("/org/chart", "Organizzazione"), ("/comp/listino", "Retribuzione"),
                        ("/cycles", "Valutazione"), ("/notes", "Interazioni"), ("/settings", "Sistema")]:
        opened = [t for t, o in _groups(client.get(path).text) if o]
        assert opened == [group], (path, opened)
    nav = _nav(client.get("/comp/hiring").text)
    org = nav.split("<summary>Organizzazione</summary>")[1].split("</details>")[0]
    assert 'href="/comp/hiring"' in org and 'class="nav-link active" href="/comp/hiring"' in org


def test_firma_con_versione(client):
    from app import config

    assert f"by ilciko.lab @ v{config.APP_VERSION}" in _nav(client.get("/org").text)


def test_modalita_pubblica_nasconde_gruppi_vuoti(client):
    client.post("/public-mode", data={"next": "/org"})
    groups = _groups(client.get("/org").text)
    assert [t for t, _ in groups] == ["Organizzazione", "Retribuzione"]
    retr = _nav(client.get("/org").text).split("<summary>Retribuzione</summary>")[1].split("</details>")[0]
    assert retr.count('class="nav-link') == 1 and 'href="/comp/listino"' in retr
