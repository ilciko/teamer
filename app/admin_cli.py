"""Amministrazione da shell, per l'IT: `python -m app.admin_cli <comando>`.

In produzione si usa il wrapper `teamer-admin` (deploy/install/), che crea la chiave
come root e poi lancia questi comandi come utente `teamer`. Comandi:

    init [--admin NOME]         chiave di sistema (se manca) + primo site admin
    create-admin NOME           nuovo site admin con password provvisoria
    create-user NOME --role R   nuovo utente (admin | director) con password provvisoria
    reset-password NOME         password provvisoria, da cambiare al primo accesso
    unlock NOME                 toglie il blocco per troppi tentativi
    enable NOME / disable NOME  riattiva / disattiva
    list-users

Ogni azione finisce nell'audit come utente `cli`.
"""
import argparse
import sys

from app import config, db, session, users


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


def _create(username: str, role: str) -> int:
    temp = users.temporary_password()
    try:
        users.create(username, role, temp, must_change=True)
    except users.UserError as exc:
        return _fail(str(exc))
    _print_temp(username, temp)
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
    for cmd in ("reset-password", "unlock", "enable", "disable"):
        sub.add_parser(cmd).add_argument("username")
    sub.add_parser("list-users")
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
            return _create(args.username, args.role)
        if args.cmd == "list-users":
            for u in users.all_users():
                stato = "attivo" if u["active"] else "disattivato"
                if u["locked_until"]:
                    stato += f", bloccato fino a {u['locked_until']}"
                print(f"{u['username']:<20} {users.ROLES[u['role']]:<12} {stato:<12} "
                      f"ultimo accesso: {u['last_login_at'] or 'mai'}")
            return 0
        u = _user(args.username)
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
