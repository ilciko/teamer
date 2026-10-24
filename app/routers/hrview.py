"""Viste trasversali di HR (0.38): nelle pagine dove HR vede righe di più director (assunzioni,
piano e budget aumenti, 9-box) ogni riga porta il suo director, c'è un filtro «Director» a scelta
multipla (`?director=ID&director=ID`) e un totale di ciò che il filtro mostra. I director non
vedono nulla di tutto questo: le loro pagine restano quelle di prima."""
from app import session, users


def context(request) -> dict:
    """`hr`, `directors` ({id: nome}, solo per HR; i nomi si leggono con `db.sys`), `dir_opts`
    (le stesse righe per il filtro, in ordine di nome) e `sel`, gli id scelti (vuoto = tutti)."""
    hr = session.current().role == "hr"
    directors = users.director_names() if hr else {}
    sel = {int(v) for v in request.query_params.getlist("director") if str(v).isdigit()} if hr else set()
    dir_opts = [{"id": k, "name": v} for k, v in sorted(directors.items(), key=lambda kv: kv[1].lower())]
    return {"hr": hr, "directors": directors, "dir_opts": dir_opts, "sel": sel}


def keep(ctx: dict, director_id) -> bool:
    """La riga passa il filtro Director (sempre, se non c'è filtro)."""
    return not ctx["sel"] or director_id in ctx["sel"]


def quarter(d) -> str | None:
    """«Q1 2027» da una data ISO: il trimestre di arrivo previsto di una posizione."""
    if not d:
        return None
    s = str(d)
    return f"Q{(int(s[5:7]) - 1) // 3 + 1} {s[:4]}"
