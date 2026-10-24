"""Amministrazione da shell, per l'IT: `python -m app.admin_cli <comando>`.

In produzione si usa il wrapper `teamer-admin` (deploy/install/), che crea la chiave
come root e poi lancia questi comandi come utente `teamer`. Comandi:

    init [--admin NOME]         chiave di sistema (se manca) + primo site admin
    create-admin NOME           nuovo site admin con password provvisoria
    create-user NOME --role R [--person "Nome Cognome"]
                                nuovo utente (admin | director | hr) con password provvisoria;
                                un director si collega alla persona Director+ che lo rappresenta
    link-person NOME "Nome Cognome" / unlink-person NOME
                                collega o scollega la persona di un utente director
    reset-password NOME         password provvisoria, da cambiare al primo accesso
    unlock NOME                 toglie il blocco per troppi tentativi
    enable NOME / disable NOME  riattiva / disattiva
    list-users
    assign-unassigned NOME      assegna al director NOME i dati senza proprietario
    list-teams                  albero dei team con il titolare
    restore FILE [--source-key | --password]
                                sostituisce i dati con quelli del file (utenti e audit restano);
                                chiave dell'altra istanza o password ≤ 0.29 chieste a prompt.
                                Il wrapper ferma il servizio durante lo scambio.

Ogni azione finisce nell'audit come utente `cli`.
"""
import argparse
import getpass
import sys
from pathlib import Path

from app import config, db, perimeter, session, users


def _fail(msg: str) -> int:
    print(f"errore: {msg}", file=sys.stderr)
    return 1


def _open() -> str:
    state = db.startup()
    if state == "chiave_mancante":
        print(f"Manca la chiave di sistema ({config.DB_KEY_FILE}): esegui prima `init`.", file=sys.stderr)
    elif state == "legacy":
        print("Il database è ancora cifrato con la password della versione precedente: "
              "chi la conosce apre Teamer dal browser e lo aggiorna (diventa il primo Director). "
              "Poi rilancia questo comando.", file=sys.stderr)
    return state


def _user(name: str):
    u = users.by_username(name)
    if u is None:
        raise SystemExit(_fail(f"utente {name} inesistente"))
    return u


def _print_temp(username: str, temp: str) -> None:
    print(f"Utente: {username}\nPassword provvisoria: {temp}\n(da cambiare al primo accesso)")


def _person_id(name: str | None, keep: int | None = None) -> int | None:
    """La persona Director+ collegabile con quel nome (esatto, senza maiuscole); errore se non c'è."""
    if not name:
        return None
    for p in users.linkable_people(keep):
        if p["full_name"].strip().lower() == name.strip().lower():
            return p["id"]
    raise users.UserError(f"persona «{name}» non collegabile: dev'essere attiva, Director+ e senza utente "
                          "(nomi disponibili: " + ", ".join(p["full_name"] for p in users.linkable_people(keep)) + ")")


def _create(username: str, role: str, person: str | None = None) -> int:
    temp = users.temporary_password()
    try:
        if role == "director" and not person and users.linkable_people():
            raise users.UserError("un utente director si collega alla persona che lo rappresenta: --person \"Nome Cognome\" "
                                  "(disponibili: " + ", ".join(p["full_name"] for p in users.linkable_people()) + ")")
        users.create(username, role, temp, must_change=True, person_id=_person_id(person))
        if role == "director" and not person:
            print("Nessuna persona Director+ da collegare: quando HR la censisce, link-person.")
    except users.UserError as exc:
        return _fail(str(exc))
    _print_temp(username, temp)
    return 0


def _link(username: str, person: str | None) -> int:
    u = _user(username)
    try:
        users.link_person(u["id"], _person_id(person, keep=u["person_id"]) if person else None)
    except users.UserError as exc:
        return _fail(str(exc))
    print(f"{u['username']}: " + (f"collegato a {person}" if person else "scollegato"))
    return 0


def _restore(args) -> int:
    if not args.file.is_file():
        return _fail(f"file {args.file} non trovato")
    source_key = getpass.getpass("Chiave dell'istanza di origine: ") if args.source_key else None
    password = getpass.getpass("Password del DB (≤ 0.29): ") if args.password else None
    try:
        stats = db.restore(args.file, source_key=source_key, password=password)
    except db.WrongPassword:
        return _fail("il file non si apre con la chiave o la password indicate")
    except db.RestoreError as exc:
        return _fail(str(exc))
    users.audit("restore", f"{args.file.name} (schema {stats['from_version']}, da shell): "
                           f"{stats['summary']}; copia precedente {stats['backup']}")
    print(f"Ripristino completato: {stats['summary']} "
          f"(schema di origine {stats['from_version']}).\n"
          f"Il database precedente è in data/backups/{stats['backup']}. Utenti e audit sono quelli di prima.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="teamer-admin", description="Amministrazione di Teamer da shell (IT).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="chiave di sistema (se manca) e primo site admin")
    p.add_argument("--admin", default="admin")
    sub.add_parser("create-admin").add_argument("username")
    p = sub.add_parser("create-user")
    p.add_argument("username")
    p.add_argument("--role", choices=sorted(users.ROLES), required=True)
    p.add_argument("--person", help="per un director: la persona Director+ che lo rappresenta (nome e cognome)")
    p = sub.add_parser("link-person", help="collega un utente director alla sua persona")
    p.add_argument("username")
    p.add_argument("person")
    sub.add_parser("unlink-person", help="scollega la persona di un utente director").add_argument("username")
    for cmd in ("reset-password", "unlock", "enable", "disable"):
        sub.add_parser(cmd).add_argument("username")
    sub.add_parser("list-users")
    sub.add_parser("assign-unassigned", help="assegna a un director i dati senza proprietario").add_argument("username")
    sub.add_parser("list-teams", help="albero dei team con il titolare")
    p = sub.add_parser("restore", help="sostituisce i dati con quelli di un backup o di un DB della 0.29")
    p.add_argument("file", type=Path)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--source-key", action="store_true", help="chiede la chiave dell'istanza di origine")
    g.add_argument("--password", action="store_true", help="chiede la password del DB (versioni ≤ 0.29)")
    args = ap.parse_args(argv)

    if args.cmd == "init" and not config.DB_KEY_FILE.exists():
        db.write_key()
        print(f"Chiave di sistema creata in {config.DB_KEY_FILE}.\n"
              "CONSERVANE UNA COPIA FUORI DAL SERVER: senza chiave il database non si apre più.")
    if _open() != "pronto":
        return 0 if args.cmd == "init" else 1
    token = session.bind(session.Session(user_id=None, username="cli", role="admin", ip="shell"))
    try:
        if args.cmd == "init":
            if users.active_admins():
                print("Esiste già un site admin attivo: niente da fare.")
                return 0
            return _create(args.admin, "admin")
        if args.cmd == "create-admin":
            return _create(args.username, "admin")
        if args.cmd == "create-user":
            return _create(args.username, args.role, args.person)
        if args.cmd == "link-person":
            return _link(args.username, args.person)
        if args.cmd == "unlink-person":
            return _link(args.username, None)
        if args.cmd == "list-users":
            linked = {u["id"]: name for u, name in ((u, next((p["full_name"] for p in users.linkable_people(keep=u["person_id"])
                                                              if p["id"] == u["person_id"]), None))
                                                    for u in users.all_users() if u["person_id"]) if name}
            for u in users.all_users():
                stato = "attivo" if u["active"] else "disattivato"
                if u["locked_until"]:
                    stato += f", bloccato fino a {u['locked_until']}"
                persona = f" persona: {linked[u['id']]}" if u["id"] in linked else (" persona: da collegare" if u["role"] == "director" else "")
                print(f"{u['username']:<20} {users.ROLES[u['role']]:<12} {stato:<12} "
                      f"ultimo accesso: {u['last_login_at'] or 'mai'}{persona}")
            return 0
        if args.cmd == "restore":
            return _restore(args)
        if args.cmd == "list-teams":
            for t in perimeter.team_tree():
                print(f"{'  ' * t['depth']}{t['name']:<{40 - 2 * t['depth']}} {t['owner'] or '(da assegnare)'}"
                      f"{'  [archiviato]' if t['archived_at'] else ''}")
            return 0
        u = _user(args.username)
        if args.cmd == "assign-unassigned":
            if u["role"] != "director" or not u["active"]:
                return _fail(f"{u['username']} non è un director attivo")
            counts = perimeter.assign_unassigned(u["id"])
            users.audit("assign_unassigned", f"a {u['username']} (da shell)")
            print(f"Assegnati a {u['username']}: " + (", ".join(
                f"{label} {counts[t]}" for t, label, _ in perimeter.UNASSIGNED_GROUPS if counts.get(t))
                or "solo configurazione") + ".")
            return 0
        if args.cmd == "reset-password":
            _print_temp(u["username"], users.reset_password(u["id"]))
        elif args.cmd == "unlock":
            users.unlock(u["id"])
            print(f"{u['username']} sbloccato.")
        elif args.cmd in ("enable", "disable"):
            try:
                users.set_active(u["id"], args.cmd == "enable")
            except users.UserError as exc:
                return _fail(str(exc))
            print(f"{u['username']} {'riattivato' if args.cmd == 'enable' else 'disattivato'}.")
        return 0
    finally:
        session.unbind(token)
        db.close_db()


if __name__ == "__main__":
    sys.exit(main())
