"""Tutte le scritture SQL dell'app passano da db.qualify() e hanno un bersaglio noto.

Sotto le viste dei perimetri una scrittura senza `main.` fallirebbe sulla vista omonima:
db.py la qualifica da sé, purché la tabella sia scritta per nome. Questo test legge il
sorgente (AST) e pretende che ogni INSERT/UPDATE/DELETE abbia un bersaglio letterale,
esistente nello schema, con ON CONFLICT coerenti con le UNIQUE della tabella; e che nel
codice dell'app non compaiano schemi espliciti né comandi che scavalcano le viste.
"""
import ast
import re
from pathlib import Path

import pytest

from app import db

APP = Path(__file__).resolve().parent.parent / "app"
WRITE = re.compile(r"^\s*(INSERT|UPDATE|DELETE)\b", re.IGNORECASE)
FORBIDDEN = re.compile(r"\b(main|temp)\.\w|\bATTACH\b|\bVACUUM\b|\bRETURNING\b|\bREPLACE\s+INTO\b|\bexecutescript\b",
                       re.IGNORECASE)


def _strings(path: Path):
    """Stringhe SQL del file; nelle f-string i valori diventano {}."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value
        elif isinstance(node, ast.JoinedStr):
            parts = [v.value if isinstance(v, ast.Constant) else "{}" for v in node.values]
            yield node.lineno, "".join(parts)


def _sql_writes():
    out = []
    for path in sorted(APP.rglob("*.py")):
        if path.name == "db.py":
            continue
        for line, text in _strings(path):
            if WRITE.match(text) and re.search(r"\b(INTO|SET|FROM)\b", text, re.IGNORECASE):
                out.append((f"{path.relative_to(APP.parent)}:{line}", text))
    return out


WRITES = _sql_writes()


@pytest.fixture(scope="module")
def schema(tmp_path_factory):
    from tests.conftest import TEST_KEY

    db.close_db()
    db.open_db(TEST_KEY, tmp_path_factory.mktemp("schema") / "s.db")
    tables = {r["name"] for r in db.sys.query("SELECT name FROM sqlite_master WHERE type='table'")}
    uniques = {}
    for t in tables:
        sets = []
        pk = [r["name"] for r in sorted(db.sys.query(f"PRAGMA table_info({t})"), key=lambda r: r["pk"]) if r["pk"]]
        if pk:
            sets.append(set(pk))
        for idx in db.sys.query(f"PRAGMA index_list({t})"):
            if idx["unique"]:
                sets.append({r["name"] for r in db.sys.query(f"PRAGMA index_info({idx['name']})")})
        uniques[t] = sets
    yield tables, uniques
    db.close_db()


def test_ci_sono_scritture_da_controllare():
    assert len(WRITES) > 150


def test_qualify():
    assert db.qualify("INSERT INTO lookup (a) VALUES (?)") == "INSERT INTO main.lookup (a) VALUES (?)"
    assert db.qualify("  insert or ignore into goal_review (x) VALUES (?)").startswith("  insert or ignore into main.goal_review")
    assert db.qualify("UPDATE person SET full_name=? WHERE id=?") == "UPDATE main.person SET full_name=? WHERE id=?"
    assert db.qualify("DELETE FROM goal WHERE id IN (SELECT id FROM goal)") == \
        "DELETE FROM main.goal WHERE id IN (SELECT id FROM goal)"           # le sottoquery leggono le viste
    assert db.qualify("SELECT * FROM person") == "SELECT * FROM person"
    assert db.qualify("UPDATE main.person SET x=1") == "UPDATE main.person SET x=1"


@pytest.mark.parametrize("where,sql", WRITES, ids=[w for w, _ in WRITES])
def test_ogni_scrittura_ha_un_bersaglio_noto(schema, where, sql):
    tables, uniques = schema
    target = db.write_target(sql)
    assert target, f"{where}: bersaglio non letterale"
    assert target in tables, f"{where}: tabella {target} inesistente"
    m = re.search(r"ON\s+CONFLICT\s*\(([^)]*)\)", sql, re.IGNORECASE)
    if m:
        cols = {c.strip() for c in m.group(1).split(",")}
        assert cols in uniques[target], f"{where}: ON CONFLICT({m.group(1)}) non è una UNIQUE di {target}"


def test_nessuno_schema_esplicito_nel_codice():
    bad = []
    for path in sorted(APP.rglob("*.py")):
        if path.name == "db.py":
            continue
        for line, text in _strings(path):
            if re.search(r"\b(SELECT|INSERT|UPDATE|DELETE)\b", text) and FORBIDDEN.search(text):
                bad.append(f"{path.relative_to(APP.parent)}:{line}")
    assert bad == []


def test_nessun_executescript_nell_app():
    """executescript esegue più statement senza passare da qualify(): solo le migrazioni in db.py."""
    for path in sorted(APP.rglob("*.py")):
        if path.name == "db.py":
            continue
        tree = ast.parse(path.read_text())
        calls = [n.lineno for n in ast.walk(tree)
                 if isinstance(n, ast.Attribute) and n.attr in ("executescript", "_conn", "_sys")]
        assert calls == [], f"{path.name}: {calls}"
