"""Questionario 9-box del director: editor leggibile, struttura libera, storia che non si riscrive."""
import json

from app import db
from tests.conftest import as_user


def _form(model):
    """Il form dell'editor ricostruito da un questionario."""
    data = {"nq": str(len(model["questions"]))}
    for i, q in enumerate(model["questions"]):
        data.update({f"q{i}_type": q["type"], f"q{i}_label": q["label"], f"q{i}_weight": str(q["weight"]),
                     f"q{i}_text": q["text"], f"q{i}_no": str(len(q["options"]))})
        for j, o in enumerate(q["options"]):
            data[f"q{i}_o{j}_text"] = o["text"]
            data[f"q{i}_o{j}_value"] = str(o["value"])
        for k, v in q.get("ctx_notes", {}).items():
            data[f"q{i}_ctx_{k}"] = v
    for k, b in model["boxes"].items():
        data[f"box_{k}_label"] = b["label"]
        data[f"box_{k}_desc"] = b.get("desc", "")
    return data


def _model():
    from app.routers.settings import _ninebox_model

    with as_user("coo"):
        return _ninebox_model()[1]


def _persona(client):
    t = db.execute("INSERT INTO team (name) VALUES ('Squadra')")
    pid = db.execute("INSERT INTO person (full_name) VALUES ('Valutata')")
    client.post(f"/people/{pid}/assignment", data={"team_id": t, "role_type": "ic", "start_date": "2024-01-01"})
    return pid


def test_editor_leggibile_senza_json_e_senza_scheda_modelli(client):
    html = client.get("/settings?tab=ninebox").text
    assert 'name="config_json"' not in html and 'href="/settings?tab=models"' not in html
    assert "Come valuti il raggiungimento degli obiettivi" in html          # testo della domanda in chiaro
    assert 'name="q0_o0_value"' in html and "Prestazione · 1" in html
    assert "Aggiustamenti dinamici" in html and "Peso premio per casella" in html
    assert "Moltiplicatori premio" not in html
    assert "Moltiplicatori premio" in client.get("/settings?tab=premi").text


def test_pulsanti_strutturali_non_salvano(client):
    data = _form(_model())
    r = client.post("/settings/ninebox-model", data={**data, "op": "add_q"})
    assert "Modifiche non ancora salvate" in r.text and 'name="q6_text"' in r.text
    assert len(_model()["questions"]) == 6
    r = client.post("/settings/ninebox-model", data={**data, "op": "del_o-0-2"})
    assert 'name="q0_o2_text"' not in r.text and 'name="q1_o2_text"' in r.text


def test_questionario_non_valido_non_si_salva(client):
    m = _model()
    m["questions"] = [q for q in m["questions"] if q["type"] == "perf"]     # niente potenziale
    m["questions"][0]["options"][0]["value"] = 5
    r = client.post("/settings/ninebox-model", data={**_form(m), "op": "save"})
    assert "Serve almeno una domanda di potenziale" in r.text and "il punteggio va da 1 a 3" in r.text
    assert len(_model()["questions"]) == 6


def test_struttura_libera_media_pesata_e_storia_ferma(client):
    m = _model()
    perf = [q for q in m["questions"] if q["type"] == "perf"]
    pot = [q for q in m["questions"] if q["type"] == "pot"][:1]
    perf[0]["weight"] = 3.0                                               # la prima domanda pesa il triplo
    m["questions"] = perf + pot                                           # 3 + 1 domande
    assert client.post("/settings/ninebox-model", data={**_form(m), "op": "save"}).status_code == 200
    assert len(_model()["questions"]) == 4
    pid = _persona(client)
    html = client.get(f"/ninebox/start/{pid}").text
    assert "0 / 4" in html
    # risposte: 3 (peso 3), 1, 1 → prestazione (9+1+1)/5 = 2.2; potenziale 3
    r = client.post("/ninebox/save", data={"person_id": pid, "role_type": "ic", "seniority": "mid",
                                           "answers": "2,0,0,2"})
    aid = int(r.url.path.rsplit("/", 1)[1])
    a = db.one("SELECT raw_perf, raw_pot, answers, model_snapshot FROM ninebox_assessment WHERE id=?", (aid,))
    assert round(a["raw_perf"], 2) == 2.2 and a["raw_pot"] == 3
    assert json.loads(a["answers"]) == [3, 1, 1, 3]
    # il questionario cambia dopo: la valutazione mostra i testi di allora
    old_text = m["questions"][0]["options"][2]["text"]
    m["questions"][0]["options"][2]["text"] = "Testo cambiato dopo"
    client.post("/settings/ninebox-model", data={**_form(m), "op": "save"})
    html = client.get(f"/ninebox/result/{aid}").text
    assert old_text in html and "Testo cambiato dopo" not in html


def test_ogni_director_ha_il_suo_questionario(client, client2):
    m = _model()
    m["questions"][0]["text"] = "Domanda solo di coo"
    client.post("/settings/ninebox-model", data={**_form(m), "op": "save"})
    assert "Domanda solo di coo" not in client2.get("/settings?tab=ninebox").text


def test_aggiustamenti_e_moltiplicatori_seguono_le_liste_aziendali(client, hr_client):
    hr_client.post("/azienda/liste", data={"category": "role_type", "code": "dir", "label": "Direttore",
                                              "sort_order": 50})
    html = client.get("/settings?tab=ninebox").text
    assert 'name="p|dir|new"' in html                                       # riga nuova, valore neutro
    client.post("/settings/ninebox-weights", data={"p|dir|new": "0.2", "q|dir|new": "0.1"})
    assert db.one("SELECT perf_adj FROM ninebox_weight WHERE role_type='dir' AND seniority='new'")["perf_adj"] == 0.2
    html = client.get("/settings?tab=premi").text
    assert "Direttore" in html and 'name="role|dir" value="1.0"' in html
    client.post("/settings/bonus-factors", data={"role|dir": "1.5"})
    assert db.one("SELECT factor FROM bonus_factor WHERE kind='role' AND code='dir'")["factor"] == 1.5
