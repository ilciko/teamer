"""Import persone da Excel: censimento dello stato attuale (team, contratto, RAL)."""
import io
from datetime import date, datetime

from openpyxl import Workbook, load_workbook

from app import db

COLUMNS = [
    ("nome", "Nome e cognome (obbligatorio)"),
    ("email", "Email"),
    ("data_assunzione", "Data assunzione (GG/MM/AAAA)"),
    ("data_nascita", "Data nascita (GG/MM/AAAA)"),
    ("team", "Team (creato se non esiste)"),
    ("ruolo", "Ruolo: ic / tl / mgr / sr"),
    ("manager", "Manager (nome e cognome)"),
    ("livello", "Livello (numero)"),
    ("ccnl", "CCNL"),
    ("contratto", "Contratto: indeterminato / determinato / apprendistato / collaborazione"),
    ("scadenza_contratto", "Scadenza contratto se a termine (GG/MM/AAAA)"),
    ("smartwork", "Smart working: no / parziale / full"),
    ("timbratura", "Timbratura: esente / 4_timbrate / solo_presenza"),
    ("part_time_pct", "Part-time % (100 = full time)"),
    ("ral", "RAL attuale €"),
    ("note", "Note"),
]


def build_template() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Persone"
    for col, (key, _) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col, value=key)
        cell.font = cell.font.copy(bold=True)
        ws.column_dimensions[cell.column_letter].width = max(14, len(key) + 4)
    info = wb.create_sheet("Istruzioni")
    info.column_dimensions["A"].width = 30
    info.column_dimensions["B"].width = 70
    info.append(["Colonna", "Descrizione"])
    for key, desc in COLUMNS:
        info.append([key, desc])
    info.append([])
    info.append(["Note", "Una riga per persona. Solo 'nome' è obbligatorio; le altre colonne possono restare vuote."])
    info.append(["", "Le date valgono sia come data Excel sia come testo GG/MM/AAAA o AAAA-MM-GG."])
    info.append(["", "L'import è un censimento: crea lo stato attuale (assegnazione, contratto, RAL con tipo 'censimento')."])
    info.append(["", "Persone già presenti con lo stesso nome vengono saltate."])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _parse_date(v) -> str | None:
    if v in (None, ""):
        return None
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"data non riconosciuta: {s!r}")


def _norm(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _ensure_lookup(category: str, code: str) -> None:
    if not db.one("SELECT 1 FROM lookup WHERE category=? AND code=?", (category, code)):
        db.execute(
            "INSERT INTO lookup (category, code, label, sort_order) VALUES (?,?,?,99)",
            (category, code, code))


def import_workbook(content: bytes, ref_date: str) -> dict:
    """Importa il foglio 'Persone'. Ritorna {created, skipped, errors: [(riga, msg)]}."""
    wb = load_workbook(io.BytesIO(content), data_only=True)
    ws = wb["Persone"] if "Persone" in wb.sheetnames else wb.active
    headers = [(_norm(c.value) or "").lower() for c in ws[1]]

    def col(row, key):
        try:
            return row[headers.index(key)]
        except ValueError:
            return None

    created, skipped, errors = [], [], []
    pending_managers = []  # (person_id, manager_name)

    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        name = _norm(col(row, "nome"))
        if not name:
            continue
        try:
            if db.one("SELECT id FROM person WHERE lower(full_name)=lower(?)", (name,)):
                skipped.append(name)
                continue
            hire = _parse_date(col(row, "data_assunzione"))
            birth = _parse_date(col(row, "data_nascita"))
            pid = db.execute(
                "INSERT INTO person (full_name, email, hire_date, birth_date, notes) VALUES (?,?,?,?,?)",
                (name, _norm(col(row, "email")), hire, birth, _norm(col(row, "note"))))

            start = hire or ref_date
            team_name = _norm(col(row, "team"))
            if team_name:
                # mai in un team archiviato: se c'è solo quello, se ne crea uno nuovo
                t = db.one("SELECT id FROM team WHERE lower(name)=lower(?) AND archived_at IS NULL",
                           (team_name,))
                team_id = t["id"] if t else db.execute(
                    "INSERT INTO team (name) VALUES (?)", (team_name,))
                role = (_norm(col(row, "ruolo")) or "ic").lower()
                db.execute(
                    "INSERT INTO person_assignment (person_id, team_id, role_type, start_date) "
                    "VALUES (?,?,?,?)", (pid, team_id, role, start))
                mgr = _norm(col(row, "manager"))
                if mgr:
                    pending_managers.append((pid, mgr))

            livello = _norm(col(row, "livello"))
            if livello:
                if livello.endswith(".0"):
                    livello = livello[:-2]
                _ensure_lookup("livello", livello)
            contratto = (_norm(col(row, "contratto")) or "").lower() or None
            if any([livello, contratto, _norm(col(row, "ccnl")), _norm(col(row, "smartwork"))]):
                pt = col(row, "part_time_pct")
                ccnl = _norm(col(row, "ccnl")) or db.get_meta("default_ccnl") or None
                db.execute(
                    "INSERT INTO employment (person_id, livello, ccnl, tipo_contratto, smartwork, "
                    "timbratura_scheme, part_time_pct, start_date, end_date) VALUES (?,?,?,?,?,?,?,?,?)",
                    (pid, livello, ccnl, contratto,
                     (_norm(col(row, "smartwork")) or "").lower() or None,
                     (_norm(col(row, "timbratura")) or "").lower() or None,
                     float(pt) if pt not in (None, "") else 100.0,
                     start, _parse_date(col(row, "scadenza_contratto"))))

            ral = col(row, "ral")
            if ral not in (None, ""):
                # chi è assunto dopo il censimento parte dalla sua assunzione,
                # non dalla data di riferimento dell'import
                db.execute(
                    "INSERT INTO ral_event (person_id, effective_date, amount, delta, change_type, reason) "
                    "VALUES (?,?,?,0,'censimento','import Excel')",
                    (pid, max(hire, ref_date) if hire else ref_date, float(ral)))
            created.append(name)
        except Exception as exc:  # riga malformata: si salta, le altre proseguono
            errors.append((i, f"{name}: {exc}"))

    for pid, mgr_name in pending_managers:
        m = db.one("SELECT id FROM person WHERE lower(full_name)=lower(?)", (mgr_name,))
        if m:
            db.execute(
                "UPDATE person_assignment SET manager_person_id=? "
                "WHERE person_id=? AND end_date IS NULL AND voided=0", (m["id"], pid))
        else:
            errors.append((0, f"manager '{mgr_name}' non trovato (persona id {pid}): riporto non impostato"))

    return {"created": created, "skipped": skipped, "errors": errors}
