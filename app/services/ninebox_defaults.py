"""Config predefinita del modello 9-box, portata dall'artefatto HTML.

Vive in evaluation_model.config (JSON): domande, note contestuali e caselle
si modificano dalla UI di configurazione, non nel codice.
"""

DEFAULT_NINEBOX_CONFIG = {
    "questions": [
        {
            "id": 0,
            "type": "perf",
            "tag": "Prestazione · 1",
            "text": "Come valuti il raggiungimento degli obiettivi e dei KPI?",
            "ctx_notes": {
                "mgr": "Per un manager considera obiettivi di team e business, non solo individuali.",
                "sr": "Valuta risultati su scala funzionale o organizzativa ampia.",
            },
            "options": [
                {"text": "Non raggiunge gli obiettivi prefissati, risultati sotto le aspettative", "value": 1},
                {"text": "Raggiunge la maggior parte degli obiettivi, qualche gap occasionale", "value": 2},
                {"text": "Raggiunge costantemente tutti gli obiettivi, spesso supera le aspettative", "value": 3},
            ],
        },
        {
            "id": 1,
            "type": "perf",
            "tag": "Prestazione · 2",
            "text": "Come descriveresti la qualità e la consistenza del lavoro nel tempo?",
            "ctx_notes": {},
            "options": [
                {"text": "Qualità variabile, risultati discontinui o incoerenti", "value": 1},
                {"text": "Qualità buona ma non sempre costante", "value": 2},
                {"text": "Qualità eccellente e consistente, alta affidabilità", "value": 3},
            ],
        },
        {
            "id": 2,
            "type": "perf",
            "tag": "Prestazione · 3",
            "text": "Come valuti la padronanza tecnica/funzionale nel ruolo attuale?",
            "ctx_notes": {
                "tl": "Considera anche la capacità di guidare tecnicamente il team.",
                "mgr": "Considera anche la competenza nella gestione delle persone e dei processi.",
                "sr": "Considera vision strategica e capacità di influenza cross-funzionale.",
            },
            "options": [
                {"text": "Competenze di base, necessita supporto frequente", "value": 1},
                {"text": "Buona competenza, autonomia nella maggior parte dei compiti", "value": 2},
                {"text": "Expertise elevata, punto di riferimento per il team o l'organizzazione", "value": 3},
            ],
        },
        {
            "id": 3,
            "type": "pot",
            "tag": "Potenziale · 4",
            "text": "Come si comporta di fronte a situazioni nuove o fuori dalla sua area di comfort?",
            "ctx_notes": {
                "mgr": "Per chi già gestisce un team, l'adattabilità deve manifestarsi su sfide organizzative complesse.",
                "sr": "A questo livello ci si aspetta leadership in contesti altamente ambigui.",
                "new": "Per chi è nuovo, anche segnali precoci di adattamento rapido sono indicatori potenti.",
            },
            "options": [
                {"text": "Difficoltà ad adattarsi, preferisce ambienti e compiti noti", "value": 1},
                {"text": "Si adatta se necessario, ma richiede tempo e supporto", "value": 2},
                {"text": "Si adatta rapidamente ed efficacemente a nuovi contesti", "value": 3},
            ],
        },
        {
            "id": 4,
            "type": "pot",
            "tag": "Potenziale · 5",
            "text": "Con quale velocità acquisisce nuove competenze o si aggiorna?",
            "ctx_notes": {
                "new": "Per chi è nuovo nel ruolo, segnali precoci di apprendimento rapido sono particolarmente significativi.",
            },
            "options": [
                {"text": "Lentamente, fatica a trasferire gli apprendimenti in pratica", "value": 1},
                {"text": "A un ritmo nella media, con applicazione graduale", "value": 2},
                {"text": "Rapidamente, trasferisce subito l'apprendimento in azione concreta", "value": 3},
            ],
        },
        {
            "id": 5,
            "type": "pot",
            "tag": "Potenziale · 6",
            "text": "Qual è la tua valutazione del suo potenziale di crescita futuro?",
            "ctx_notes": {
                "mgr": "Già in un ruolo di responsabilità: il potenziale si misura sulla capacità di gestire perimetri più ampi o ruoli di direzione.",
                "sr": "A questo livello il potenziale riguarda C-suite, board advisory o leadership di business unit complesse.",
            },
            "options": [
                {"text": "Potenziale limitato all'area attuale, crescita verticale improbabile", "value": 1},
                {"text": "Promuovibile di un livello o capace di muoversi lateralmente", "value": 2},
                {"text": "Alto potenziale, promuovibile in più aree o ruoli di maggiore responsabilità", "value": 3},
            ],
        },
    ],
    "labels": [
        "Obiettivi e KPI",
        "Qualità e consistenza",
        "Expertise tecnica",
        "Adattabilità",
        "Velocità apprendimento",
        "Potenziale crescita",
    ],
    "boxes": {
        "low-low": {"n": 1, "label": "Low Performer", "zone": "r",
                    "desc": "Richiede interventi di sviluppo e supporto. Valuta un piano di miglioramento strutturato o una ricollocazione nel ruolo più adatto."},
        "med-low": {"n": 2, "label": "Solid Professional", "zone": "a",
                    "desc": "Professionista affidabile nel ruolo attuale. Valorizzalo dove si trova e riconosci il suo contributo stabile."},
        "high-low": {"n": 4, "label": "High Professional", "zone": "a",
                     "desc": "Eccellente nei risultati e nella competenza tecnica, ma bassa versatilità. Prezioso dove si trova, cresce verticalmente nell'area."},
        "low-med": {"n": 3, "label": "Inconsistent Performer", "zone": "a",
                    "desc": "Potenziale non ancora espresso. Potrebbe essere nel ruolo sbagliato. Valuta riposizionamento e coaching mirato."},
        "med-med": {"n": 5, "label": "Key Performer", "zone": "a",
                    "desc": "Solido e affidabile, capace di crescere di un livello o muoversi lateralmente. Risorsa stabile e importante per il team."},
        "high-med": {"n": 7, "label": "High Professional Plus", "zone": "g",
                     "desc": "Ottimi risultati e buona adattabilità. Promuovibile in più aree funzionali. Considera percorsi di sviluppo manageriale o trasversale."},
        "low-high": {"n": 6, "label": "Diamond in the Rough", "zone": "g",
                     "desc": "Alto potenziale ancora inespresso. Potrebbe essere nel ruolo sbagliato o mancare di opportunità. Investi con coaching e incarichi sfidanti."},
        "med-high": {"n": 8, "label": "Future Star", "zone": "g",
                     "desc": "Alto potenziale con buona prestazione. In crescita accelerata. Assegna incarichi sfidanti per confermare il percorso."},
        "high-high": {"n": 9, "label": "Consistent Star", "zone": "gg",
                      "desc": "Il meglio dell'organizzazione. Trattienilo con piani di sviluppo ambiziosi, visibilità e riconoscimenti concreti."},
    },
}


def ensure_default_model() -> None:
    """Crea il modello 9-box predefinito se non esiste (idempotente)."""
    import json

    from app import db

    row = db.one("SELECT id FROM evaluation_model WHERE type='nine_box' AND active=1")
    if row is None:
        db.execute(
            "INSERT INTO evaluation_model (name, type, config) VALUES (?,?,?)",
            ("9-Box Talent Matrix", "nine_box", json.dumps(DEFAULT_NINEBOX_CONFIG, ensure_ascii=False)),
        )
