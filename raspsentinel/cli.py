from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Callable, List, Optional

import typer
import yaml

from .store import Store

app = typer.Typer(add_completion=False, help="Herramientas para instalar y operar Raspsentinel.")
config_app = typer.Typer(add_completion=False, help="Operaciones sobre la configuración.")
devices_app = typer.Typer(add_completion=False, help="Consulta y gestión de dispositivos.")

app.add_typer(config_app, name="config")
app.add_typer(devices_app, name="devices")

CONF_PATH = "/etc/raspsentinel/config.yaml"
SERVICE_NAME = "raspsentinel.service"
COMMAND_OVERVIEW = """Comandos principales:
  setup                   Asistente interactivo de configuración.
  start                   Inicia el servicio systemd.
  stop                    Detiene el servicio systemd.
  restart                 Reinicia el servicio.
  enable                  Habilita el inicio automático en systemd.
  disable                 Deshabilita el inicio automático en systemd.
  status                  Muestra el estado del servicio.
  logs [--lines N]        Muestra los logs recientes (usar --follow para seguir).
  allowlist [--manage]    Lista dispositivos permitidos y permite editarlos.
  blocklist [--manage]    Lista dispositivos bloqueados y permite editarlos.
  devices list            Lista dispositivos vistos (usar -s para filtrar).
  devices info MAC        Muestra detalles de un dispositivo.
  devices allow MAC       Añade un dispositivo a la allowlist.
  devices block MAC       Añade un dispositivo a la blocklist.
  devices unblock MAC     Quita un dispositivo de la blocklist.
  devices name MAC NAME   Asigna un nombre amigable.
  config show             Muestra la configuración actual.
  config get CLAVE        Obtiene una clave (ej. network.interface).
  config set CLAVE VALOR  Actualiza una clave.
  config wizard           Repite el asistente interactivo.

Ejemplo:
  sudo raspsentinel setup
"""


@app.command()
def setup() -> None:
    """Asistente interactivo de configuración."""
    _ensure_conf_dir()
    data = _load_config()
    data.setdefault("telegram", {})
    data.setdefault("network", {})
    data.setdefault("block", {})
    data.setdefault("app", {})

    gw_guess, iface_guess = _detect_default_routes()
    interfaces = _list_interfaces()

    if interfaces:
        typer.echo(f"Interfaces detectadas: {', '.join(interfaces)}")
    if iface_guess:
        typer.echo(f"Sugerencia: {iface_guess} parece ser la interfaz activa.")
    if gw_guess:
        typer.echo(f"Sugerencia: {gw_guess} podría ser tu gateway.")

    typer.echo("\nIntroduce los datos del bot de Telegram y la red a vigilar:")
    data["telegram"]["bot_token"] = typer.prompt(
        "Telegram bot token", default=data["telegram"].get("bot_token", "")
    )
    data["telegram"]["chat_id"] = _prompt_int(
        "Telegram chat_id", default=data["telegram"].get("chat_id")
    )
    data["network"]["interface"] = typer.prompt(
        "Interfaz de red a vigilar",
        default=data["network"].get("interface", iface_guess or "wlan0"),
    )
    data["network"]["gateway_ip"] = typer.prompt(
        "IP del gateway/router",
        default=data["network"].get("gateway_ip", gw_guess or ""),
    )
    data["network"]["scan_interval_sec"] = _prompt_int(
        "Intervalo de escaneo (segundos)",
        default=data["network"].get("scan_interval_sec", 60),
    )

    enable_block = typer.confirm(
        "¿Habilitar bloqueo por ARP spoofing?",
        default=bool(data["block"].get("enable", False)),
    )
    data["block"]["enable"] = enable_block
    if enable_block:
        data["block"]["gateway_ip"] = typer.prompt(
            "Gateway para ARP spoof",
            default=data["block"].get("gateway_ip", data["network"]["gateway_ip"]),
        )
        data["block"]["arp_interval_sec"] = _prompt_float(
            "Intervalo de reenvío ARP (segundos)",
            default=data["block"].get("arp_interval_sec", 2.0),
        )
    else:
        data["block"]["gateway_ip"] = data["block"].get(
            "gateway_ip", data["network"].get("gateway_ip", "")
        )

    data["app"].setdefault("data_dir", "/var/lib/raspsentinel")

    _save_config(data)
    typer.echo(f"\nConfiguración guardada en {CONF_PATH}")


@app.command()
def start() -> None:
    """Inicia el servicio systemd."""
    _systemctl("start")


@app.command()
def stop() -> None:
    """Detiene el servicio systemd."""
    _systemctl("stop")


@app.command()
def restart() -> None:
    """Reinicia el servicio."""
    _systemctl("restart")


@app.command()
def enable() -> None:
    """Habilita el servicio para iniciar con el sistema."""
    _systemctl("enable")


@app.command()
def disable() -> None:
    """Deshabilita el servicio en el arranque."""
    _systemctl("disable")


@app.command()
def status() -> None:
    """Muestra el estado del servicio."""
    subprocess.call(["systemctl", "status", SERVICE_NAME])


@app.command()
def logs(
    lines: int = typer.Option(200, "--lines", help="Número de líneas recientes a mostrar."),
    follow: bool = typer.Option(False, "--follow", help="Seguir los logs en vivo."),
) -> None:
    """Muestra los logs recientes del servicio."""
    cmd = ["journalctl", "-u", SERVICE_NAME, "-n", str(lines)]
    if follow:
        cmd.append("-f")
    subprocess.call(cmd)


@app.command()
def allowlist(manage: bool = typer.Option(False, "--manage", "-m", help="Abrir asistente para quitar entradas.")) -> None:
    """Muestra la allowlist y opcionalmente permite editarla."""
    cfg = _load_config()
    store = _store_from_config(cfg)
    allow = _collect_devices(store, lambda d: d.get("allow"))
    if not allow:
        typer.echo("Allowlist vacía.")
        return
    _print_table(allow, title="Allowlist actual")
    if manage:
        _interactive_toggle(store, allow, action="unallow")


@app.command()
def blocklist(manage: bool = typer.Option(False, "--manage", "-m", help="Abrir asistente para desbloquear dispositivos.")) -> None:
    """Muestra la blocklist y permite desbloquear dispositivos."""
    cfg = _load_config()
    store = _store_from_config(cfg)
    blocked = _collect_devices(store, lambda d: d.get("block"))
    if not blocked:
        typer.echo("Blocklist vacía.")
        return
    _print_table(blocked, title="Blocklist actual")
    if manage:
        _interactive_toggle(store, blocked, action="unblock")


@devices_app.command("list")
def devices_list(
    status: str = typer.Option("all", "--status", "-s", help="Filtro: all|allow|block|new"),
) -> None:
    """Lista los dispositivos vistos con filtros sencillos."""
    cfg = _load_config()
    store = _store_from_config(cfg)
    devices = store.list_devices()
    rows = []
    status = status.lower()
    for mac, info in devices.items():
        status_flag = _device_status(info)
        if status != "all" and status_flag.lower() != status:
            continue
        rows.append(
            {
                "mac": mac,
                "status": status_flag,
                "ip": info.get("ip") or "?",
                "name": info.get("name") or "—",
                "vendor": info.get("vendor") or "?",
            }
        )
    if not rows:
        typer.echo("Sin resultados.")
        return
    _print_table(rows, title="Dispositivos")


@devices_app.command("info")
def devices_info(mac: str) -> None:
    """Muestra la ficha completa de un dispositivo."""
    cfg = _load_config()
    store = _store_from_config(cfg)
    mac = mac.upper()
    device = store.list_devices().get(mac)
    if not device:
        typer.echo(f"No se encontraron datos para {mac}")
        raise typer.Exit(code=1)
    typer.echo(f"MAC:    {mac}")
    typer.echo(f"Nombre: {device.get('name') or '—'}")
    typer.echo(f"Estado: {_device_status(device)}")
    typer.echo(f"IP:     {device.get('ip') or '?'}")
    typer.echo(f"Vendor: {device.get('vendor') or '?'}")
    typer.echo(f"Primer visto: {device.get('first_seen')}")
    typer.echo(f"Último visto: {device.get('last_seen')}")
    if notes := device.get("notes"):
        typer.echo(f"Notas:  {notes}")


@devices_app.command("allow")
def devices_allow(mac: str, name: Optional[str] = typer.Option(None, "--name", "-n", help="Nombre opcional.")) -> None:
    """Añade un dispositivo a la allowlist."""
    cfg = _load_config()
    store = _store_from_config(cfg)
    store.mark_allow(mac, name)
    typer.echo(f"{mac.upper()} añadido a allowlist.")


@devices_app.command("block")
def devices_block(mac: str, notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Motivo/nota opcional.")) -> None:
    """Añade un dispositivo a la blocklist."""
    cfg = _load_config()
    store = _store_from_config(cfg)
    store.mark_block(mac, notes)
    typer.echo(f"{mac.upper()} añadido a blocklist.")


@devices_app.command("unblock")
def devices_unblock(mac: str) -> None:
    """Quita un dispositivo de la blocklist."""
    cfg = _load_config()
    store = _store_from_config(cfg)
    store.unblock(mac)
    typer.echo(f"{mac.upper()} desbloqueado.")


@devices_app.command("name")
def devices_name(mac: str, name: str) -> None:
    """Asignar o actualizar el nombre amigable."""
    cfg = _load_config()
    store = _store_from_config(cfg)
    store.set_name(mac, name)
    typer.echo(f"{mac.upper()} ahora se llama '{name}'.")

@config_app.command("show")
def config_show(
    yaml_output: bool = typer.Option(False, "--yaml", help="Imprimir la configuración en YAML."),
) -> None:
    """Muestra la configuración actual."""
    data = _load_config()
    if yaml_output:
        typer.echo(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    else:
        typer.echo(json.dumps(data, indent=2, ensure_ascii=False))


@config_app.command("get")
def config_get(key: str) -> None:
    """Obtiene una clave usando notación punto (ej: network.interface)."""
    data = _load_config()
    try:
        typer.echo(_get_nested(data, key))
    except KeyError as exc:
        raise typer.BadParameter(f"No existe la clave '{key}'") from exc


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    """Actualiza una clave usando notación punto."""
    data = _load_config()
    _set_nested(data, key, value)
    _save_config(data)
    typer.echo("Configuración actualizada.")


@config_app.command("wizard")
def config_wizard() -> None:
    """Repite el asistente interactivo."""
    setup()


def _systemctl(action: str) -> None:
    subprocess.check_call(["systemctl", action, SERVICE_NAME])


def _ensure_conf_dir() -> None:
    os.makedirs(os.path.dirname(CONF_PATH), exist_ok=True)


def _load_config() -> dict[str, Any]:
    if os.path.exists(CONF_PATH):
        with open(CONF_PATH, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    return {}


def _save_config(data: dict[str, Any]) -> None:
    with open(CONF_PATH, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def _store_from_config(cfg: dict[str, Any]) -> Store:
    data_dir = cfg.get("app", {}).get("data_dir", "/var/lib/raspsentinel")
    return Store(data_dir)


def _collect_devices(store: Store, predicate: Callable[[dict[str, Any]], bool]) -> List[dict[str, Any]]:
    devices = store.list_devices()
    rows: List[dict[str, Any]] = []
    for mac, info in sorted(devices.items()):
        if predicate(info):
            rows.append(
                {
                    "mac": mac,
                    "ip": info.get("ip") or "?",
                    "name": info.get("name") or "—",
                    "vendor": info.get("vendor") or "?",
                    "status": _device_status(info),
                }
            )
    return rows


def _print_table(rows: List[dict[str, Any]], title: str) -> None:
    typer.echo(f"\n{title}")
    typer.echo("-" * len(title))
    for idx, row in enumerate(rows, start=1):
        typer.echo(
            f"{idx:>2}. {row['mac']} [{row['status']}]  IP {row['ip']}  "
            f"{row['name']}  {row['vendor']}"
        )


def _interactive_toggle(store: Store, rows: List[dict[str, Any]], action: str) -> None:
    actions = {
        "unblock": store.unblock,
        "unallow": store.unallow,
    }
    action_fn = actions.get(action)
    if action_fn is None:
        return
    label = "desbloquear" if action == "unblock" else "quitar de allowlist"
    while rows:
        typer.echo("\nIntroduce el número a " + label + " (ENTER para salir).")
        choice = typer.prompt("Número", default="")
        if not choice.strip():
            break
        try:
            idx = int(choice)
        except ValueError:
            typer.echo("Introduce un número válido.")
            continue
        if idx < 1 or idx > len(rows):
            typer.echo("Fuera de rango.")
            continue
        mac = rows.pop(idx - 1)["mac"]
        action_fn(mac)
        typer.echo(f"{mac} actualizado.")
        if rows:
            _print_table(rows, "Estado actualizado")
        else:
            typer.echo("No quedan entradas.")


def _device_status(data: dict[str, Any]) -> str:
    if data.get("block"):
        return "BLOCK"
    if data.get("allow"):
        return "ALLOW"
    return "NEW"


def _prompt_int(message: str, default: Optional[int] = None) -> int:
    while True:
        default_text = "" if default is None else str(default)
        text = typer.prompt(message, default=default_text)
        try:
            return int(text)
        except ValueError:
            typer.echo("Introduce un número válido.")


def _prompt_float(message: str, default: Optional[float] = None) -> float:
    while True:
        default_text = "" if default is None else str(default)
        text = typer.prompt(message, default=default_text)
        try:
            return float(text)
        except ValueError:
            typer.echo("Introduce un número válido (usa punto decimal).")


def _set_nested(data: dict[str, Any], dotted_key: str, value: str) -> None:
    parts = dotted_key.split(".")
    current: dict[str, Any] = data
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = _auto_cast(value)


def _get_nested(data: dict[str, Any], dotted_key: str) -> Any:
    current: Any = data
    for part in dotted_key.split("."):
        current = current[part]
    return current


def _auto_cast(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _detect_default_routes() -> tuple[Optional[str], Optional[str]]:
    try:
        output = subprocess.check_output(
            ["ip", "route", "show", "default"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None, None

    for line in output.splitlines():
        tokens = line.split()
        if "via" in tokens and "dev" in tokens:
            try:
                gw = tokens[tokens.index("via") + 1]
                iface = tokens[tokens.index("dev") + 1]
                return gw, iface
            except (IndexError, ValueError):
                continue
    return None, None


def _list_interfaces() -> list[str]:
    try:
        output = subprocess.check_output(
            ["ip", "-o", "link", "show"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []

    interfaces: list[str] = []
    for line in output.splitlines():
        try:
            _, name_part, *_ = line.split(":", 2)
        except ValueError:
            continue
        name = name_part.strip().split("@", 1)[0]
        if name and name != "lo":
            interfaces.append(name)
    return interfaces


if __name__ == "__main__":
    if os.geteuid() != 0:
        typer.echo("Este comando requiere privilegios de superusuario. Ejecuta 'sudo raspsentinel'.")
        raise SystemExit(1)
    if len(sys.argv) == 1:
        typer.echo(COMMAND_OVERVIEW.rstrip())
        raise SystemExit(0)
    app()
