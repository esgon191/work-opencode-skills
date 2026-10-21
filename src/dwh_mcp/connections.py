"""Доступ к контурам DWH.

Топология  -> connections.yaml (в git)
Логин      -> connections.local.yaml (локальный, в .gitignore)
Пароль     -> системный keyring, на диск не пишется

CLI:
    dwh-connections                         список контуров
    dwh-connections set-password gp_prod    сохранить пароль
    dwh-connections check gp_prod           проверить соединение
"""
import getpass
import os
import pathlib
import sys

import keyring
import yaml
import psycopg2


class DwhError(Exception):
    """Понятная пользователю ошибка: сервер отдаёт её текст модели как есть."""


def _root() -> pathlib.Path:
    """Каталог с connections.yaml: $DWH_MCP_CONFIG_DIR, корень репозитория
    или ~/.config/opencode."""
    env = os.environ.get("DWH_MCP_CONFIG_DIR")
    candidates = [pathlib.Path(env).expanduser()] if env else []
    candidates += list(pathlib.Path(__file__).resolve().parents)
    candidates.append(pathlib.Path.home() / ".config" / "opencode")
    for d in candidates:
        if (d / "connections.yaml").exists():
            return d
    raise DwhError(
        "connections.yaml не найден ни в $DWH_MCP_CONFIG_DIR, ни в репозитории, "
        "ни в ~/.config/opencode/"
    )


def _read(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _cfg() -> dict:
    return _read(_root() / "connections.yaml")


def _local() -> dict:
    return _read(_root() / "connections.local.yaml")


def targets() -> dict:
    """Все контуры из общего конфига."""
    return _cfg().get("databases", {})


def resolve(alias: str | None = None, kind: str | None = None) -> dict:
    """Параметры подключения без пароля. Без alias — первый контур нужного
    kind (или глобальный default)."""
    base = _cfg()
    local = _local()
    dbs = base.get("databases", {})

    if alias is None and kind is not None:
        alias = next(
            (n for n, d in dbs.items() if d.get("kind", "greenplum") == kind), None
        )
        if alias is None:
            raise DwhError(f"в connections.yaml нет контура типа {kind}")
    alias = alias or base.get("default")
    if alias not in dbs:
        raise DwhError(f"неизвестный контур {alias!r}; доступны: {', '.join(dbs)}")

    user = local.get("databases", {}).get(alias, {}).get("user") or local.get("user")
    if not user:
        raise DwhError(
            f"логин не задан. Скопируй connections.local.yaml.example в "
            f"{_root() / 'connections.local.yaml'} и укажи в нём user"
        )

    cfg = dict(dbs[alias])
    k = cfg.get("kind", "greenplum")
    if kind is not None and k != kind:
        raise DwhError(f"контур {alias!r} — {k}, а не {kind}")
    return cfg | {
        "alias": alias,
        "user": user,
        "service": f"opencode/{alias}",
        "kind": k,
    }


def password(alias: str | None = None) -> str:
    d = resolve(alias)
    pw = keyring.get_password(d["service"], d["user"])
    if not pw:
        raise DwhError(
            f"пароля для {d['user']}@{d['alias']} нет в keyring. Пользователь должен "
            f"сам выполнить в терминале (команда интерактивная):\n"
            f"    uv run --directory {_root()} dwh-connections set-password {d['alias']}"
        )
    return pw


def connect(alias: str | None = None, kind: str | None = None, retries: int = 0):
    """Соединение с контуром: psycopg2 (greenplum) или clickhouse_connect."""

    d = resolve(alias, kind)
    if d["kind"] == "clickhouse":
        return _connect_ch(d)

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
        if "LDAP auth failed: unknown error" in str(e) and retries < 1:
            return connect(alias, kind, retries=1)

        else:
            raise


def _connect_ch(d: dict):
    """Клиент clickhouse_connect для контура ClickHouse."""
    import clickhouse_connect

    return clickhouse_connect.get_client(
        host=d["host"],
        port=d["port"],
        username=d["user"],
        password=password(d["alias"]),
        database=d.get("dbname", "default"),
        send_receive_timeout=300,
    )


def describe(kind: str | None = None) -> str:
    """Список контуров (с фильтром по kind): база, RO/RW, логин, наличие пароля."""
    local = _local()
    default = _cfg().get("default")
    lines = []
    for name, d in targets().items():
        if kind and d.get("kind", "greenplum") != kind:
            continue
        user = local.get("databases", {}).get(name, {}).get("user") or local.get("user")
        has_pw = bool(keyring.get_password(f"opencode/{name}", user)) if user else False
        lines.append(
            f"{name:<10} {d['dbname']:<10} {'RO' if d.get('readonly') else 'RW':<3}"
            f" {user or '— логин не задан':<16}"
            f" {'пароль: ok' if has_pw else 'пароль: нет':<12}"
            f"{' (default)' if name == default else ''}"
        )
    return "\n".join(lines)


# --- CLI --------------------------------------------------------------------

def _cmd_set_password(alias: str | None) -> None:
    d = resolve(alias)
    pw = getpass.getpass(f"пароль {d['user']}@{d['alias']}: ")
    keyring.set_password(d["service"], d["user"], pw)
    print(f"сохранено в {keyring.get_keyring().__class__.__name__}")


def _cmd_check(alias: str | None) -> None:
    d = resolve(alias)
    if d["kind"] == "clickhouse":
        client = connect(alias)
        try:
            user, dbname, ver = client.query(
                "select currentUser(), currentDatabase(), version()"
            ).result_rows[0]
        finally:
            client.close()
        print(f"ok: {user}@{d['host']}/{dbname}\nClickHouse {ver}")
        return
    with connect(alias) as conn, conn.cursor() as cur:
        cur.execute("select current_user, current_database(), version()")
        user, dbname, ver = cur.fetchone()
        print(f"ok: {user}@{d['host']}/{dbname}\n{ver.split(',')[0]}")


def main() -> None:
    args = sys.argv[1:]
    cmd = args[0] if args else "list"
    arg = args[1] if len(args) > 1 else None
    try:
        if cmd == "set-password":
            _cmd_set_password(arg)
        elif cmd == "check":
            _cmd_check(arg)
        elif cmd == "list":
            print(describe())
        else:
            sys.exit(f"неизвестная команда {cmd!r}: list | set-password | check")
    except DwhError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
