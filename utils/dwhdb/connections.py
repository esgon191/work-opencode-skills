"""Доступ к контурам DWH.

Топология  -> connections.yaml (в git)
Логин      -> connections.local.yaml (локальный, в .gitignore)
Пароль     -> системный keyring, на диск не пишется

CLI:
    python utils/dwhdb/connections.py                     список контуров
    python utils/dwhdb/connections.py set-password gp_prod  сохранить пароль
    python utils/dwhdb/connections.py check gp_prod         проверить соединение
"""
import getpass
import pathlib
import sys

import keyring
import yaml
import psycopg2


def _root() -> pathlib.Path:
    """Корень репозитория скилов — ближайший предок с connections.yaml."""
    for d in pathlib.Path(__file__).resolve().parents:
        if (d / "connections.yaml").exists():
            return d
    fallback = pathlib.Path.home() / ".config" / "opencode"
    if (fallback / "connections.yaml").exists():
        return fallback
    sys.exit("connections.yaml не найден ни в репозитории, ни в ~/.config/opencode/")


ROOT = _root()
CFG = ROOT / "connections.yaml"
LOCAL = ROOT / "connections.local.yaml"


def _read(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def targets() -> dict:
    """Все контуры из общего конфига."""
    return _read(CFG).get("databases", {})


def resolve(alias: str | None = None) -> dict:
    """Параметры подключения без пароля."""
    base = _read(CFG)
    local = _read(LOCAL)
    dbs = base.get("databases", {})

    alias = alias or base.get("default")
    if alias not in dbs:
        sys.exit(f"неизвестный контур {alias!r}; доступны: {', '.join(dbs)}")

    user = local.get("databases", {}).get(alias, {}).get("user") or local.get("user")
    if not user:
        sys.exit(
            f"логин не задан. Скопируй {LOCAL.name}.example в {LOCAL.name} "
            f"и укажи в нём user"
        )

    return dict(dbs[alias]) | {
        "alias": alias,
        "user": user,
        "service": f"opencode/{alias}",
    }


def password(alias: str | None = None) -> str:
    d = resolve(alias)
    pw = keyring.get_password(d["service"], d["user"])
    if not pw:
        sys.exit(
            f"пароля для {d['user']}@{d['alias']} нет в keyring. Выполни:\n"
            f"    python utils/dwhdb/connections.py set-password {d['alias']}"
        )
    return pw


def connect(alias: str | None = None, retries = 0):
    """psycopg2-соединение с выбранным контуром."""

    d = resolve(alias)
    # Иногда не получается подключиться по неизвестной ошибке (обычно первый раз в сессии
    # для этого одна попытка реконнекта по этой конкретной причине
    try: 
        return psycopg2.connect(
            host=d["host"],
            port=d["port"],
            dbname=d["dbname"],
            user=d["user"],
            password=password(alias),
            sslmode=d.get("sslmode", "prefer"),
            application_name=f"opencode/{d['alias']}",
        )
    except psycopg2.OperationalError as e:
        if "LDAP auth failed: unknown error" in e.message and retries < 1:
            return connect(alias, retries=1)

        else:
            raise 


# --- CLI --------------------------------------------------------------------

def _cmd_list() -> None:
    local = _read(LOCAL)
    default = _read(CFG).get("default")
    for name, d in targets().items():
        user = local.get("databases", {}).get(name, {}).get("user") or local.get("user")
        has_pw = bool(keyring.get_password(f"opencode/{name}", user)) if user else False
        print(
            f"{name:<10} {d['dbname']:<10} {'RO' if d.get('readonly') else 'RW':<3}"
            f" {user or '— логин не задан':<16}"
            f" {'пароль: ok' if has_pw else 'пароль: нет':<12}"
            f"{' (default)' if name == default else ''}"
        )


def _cmd_set_password(alias: str | None) -> None:
    d = resolve(alias)
    pw = getpass.getpass(f"пароль {d['user']}@{d['alias']}: ")
    keyring.set_password(d["service"], d["user"], pw)
    print(f"сохранено в {keyring.get_keyring().__class__.__name__}")


def _cmd_check(alias: str | None) -> None:
    d = resolve(alias)
    with connect(alias) as conn, conn.cursor() as cur:
        cur.execute("select current_user, current_database(), version()")
        user, dbname, ver = cur.fetchone()
        print(f"ok: {user}@{d['host']}/{dbname}\n{ver.split(',')[0]}")


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "list"
    arg = args[1] if len(args) > 1 else None
    if cmd == "set-password":
        _cmd_set_password(arg)
    elif cmd == "check":
        _cmd_check(arg)
    elif cmd == "list":
        _cmd_list()
    else:
        sys.exit(f"неизвестная команда {cmd!r}: list | set-password | check")
