"""HR nelle pagine dei director (0.38 viste, 0.39 scritture).

Dove HR vede righe di più director (assunzioni, piano e budget aumenti, 9-box) ogni riga porta il
suo director, c'è un filtro «Director» a scelta multipla (`?director=ID&director=ID`) e un totale
di ciò che il filtro mostra. Per scrivere HR sceglie un director «in veste di» (`POST /hr/acting`,
nella sessione): da lì quelle pagine diventano le sue — i suoi budget, il suo piano, le sue persone
nell'analisi salary — con i form, e ciò che HR crea nasce intestato a lui (`owner()` nelle INSERT
delle tabelle con proprietario, `COALESCE(?, teamer_owner())`). Senza director scelto HR consulta
(`ro_hr`). I director non vedono nulla di tutto questo: le loro pagine restano quelle di prima.
"""
from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import RedirectResponse

from app import session, users

router = APIRouter()


def is_hr() -> bool:
    s = session.current()
    return s is not None and s.role == "hr"


def acting_id() -> int | None:
    """Il director «in veste di» della sessione di HR (None per i director e per HR senza scelta)."""
    s = session.current()
    return s.acting if s is not None and s.role == "hr" else None


def acting_name() -> str | None:
    a = acting_id()
    return users.director_names().get(a) if a else None


def owner() -> int | None:
    """Proprietario esplicito di una riga con `owner_user_id` creata ora: il director «in veste di»
    per HR, None per un director (resta il default `teamer_owner()`). Nelle INSERT:
    `owner_user_id = COALESCE(?, teamer_owner())`."""
    return acting_id()


def require_acting() -> int | None:
    """HR deve aver scelto il director prima di creare righe sue; per un director non serve."""
    a = acting_id()
    if is_hr() and not a:
        raise HTTPException(403, "Scegli prima il director per cui operi")
    return a


def context(request) -> dict:
    """`hr`; `directors` ({id: nome}, solo per HR; i nomi si leggono con `db.sys`); `dir_opts`
    (le stesse righe per i selettori, in ordine di nome); `acting`/`acting_name`; `sel` = director
    del filtro (con «in veste di» è solo lui); `ro_hr` = HR che consulta, niente form."""
    hr = is_hr()
    directors = users.director_names() if hr else {}
    acting = acting_id()
    if acting:
        sel = {acting}
    else:
        sel = {int(v) for v in request.query_params.getlist("director") if str(v).isdigit()} if hr else set()
    dir_opts = [{"id": k, "name": v} for k, v in sorted(directors.items(), key=lambda kv: kv[1].lower())]
    return {"hr": hr, "directors": directors, "dir_opts": dir_opts, "sel": sel,
            "acting": acting, "acting_name": directors.get(acting) if acting else None,
            "ro_hr": hr and not acting}


def keep(ctx: dict, director_id) -> bool:
    """La riga passa il filtro Director (sempre, se non c'è filtro)."""
    return not ctx["sel"] or director_id in ctx["sel"]


def quarter(d) -> str | None:
    """«Q1 2027» da una data ISO: il trimestre di arrivo previsto di una posizione."""
    if not d:
        return None
    s = str(d)
    return f"Q{(int(s[5:7]) - 1) // 3 + 1} {s[:4]}"


@router.post("/hr/acting")
def set_acting(director_id: str = Form(""), next: str = Form("/org")):
    """HR sceglie (o toglie) il director «in veste di»; vale per la sessione, fino all'uscita."""
    s = session.current()
    if s is None or s.role != "hr":
        raise HTTPException(403)
    did = int(director_id) if director_id.isdigit() else None
    s.acting = did if did in users.director_names() else None
    return RedirectResponse(next if next.startswith("/") else "/org", status_code=302)
