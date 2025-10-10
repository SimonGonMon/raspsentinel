from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Optional

import typer
import yaml

APP = typer.Typer(add_completion=False, help="Herramientas para operar Raspsentinel.")
CONF = "/etc/raspsentinel/config.yaml"

config_app = typer.Typer(add_completion=False, help="Comandos avanzados de configuración.")
APP.add_typer(config_app, name="config")


@APP.command()
def setup():
    """Asistente interactivo de configuración inicial."""
    _ensure_conf_dir()
    data = _load()
    data.setdefault("telegram", {})
    data.setdefault("network", {})
    data.setdefault("block", {})
    data.setdefault("app", {})

    gw_guess, iface_guess = _detect_default_gateway()
    iface_options = _list_interfaces()

    if iface_options:
        typer.echo(f"Detectamos interfaces disponibles: {', '.join(iface_options)}")
    if iface_guess:
        typer.echo(f"Sugerencia: {iface_guess} parece ser la interfaz activa.")
    if gw_guess:
        typer.echo(f"Sugerencia: {gw_guess} podría ser tu gateway actual.")

    typer.echo("Configura tu bot de Telegram y los parámetros de red:")
    data["telegram"]["bot_token"] = typer.prompt(
        "Telegram bot token", default=data["telegram"].get("bot_token", "")
    )
    chat_default = data["telegram"].get("chat_id")
    data["telegram"]["chat_id"] = _prompt_int(
        "Telegram chat_id", default=chat_default
    )
    data["network"]["interface"] = typer.prompt(
        "Interfaz de red a vigilar (wlan0/eth0)",
        default=data["network"].get("interface", iface_guess or "wlan0"),
    )
    data["network"]["gateway_ip"] = typer.prompt(
        "IP del gateway/router (para bloqueo ARP)",
        default=data["network"].get("gateway_ip", gw_guess or ""),
    )
    data["network"]["scan_interval_sec"] = _prompt_int(
        "Intervalo de escaneo en segundos",
        default=data["network"].get("scan_interval_sec", 60),
    )
    data["block"]["enable"] = typer.confirm(
        "¿Habilitar bloqueo por ARP spoofing?",
        default=bool(data["block"].get("enable", False)),
    )
    if data["block"]["enable"]:
        data["block"]["gateway_ip"] = typer.prompt(
            "Gateway para ARP spoof (enter para usar el de la red)",
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

    if not data["app"].get("data_dir"):
        data["app"]["data_dir"] = "/var/lib/raspsentinel"

    _save(data)
    typer.echo(f"Configuración guardada en {CONF}")


@APP.command()
def start():
    """Inicia el servicio systemd."""
    _systemctl("start")


@APP.command()
def stop():
    """Detiene el servicio systemd."""
    _systemctl("stop")


@APP.command()
def restart():
    """Reinicia el servicio."""
    _systemctl("restart")


@APP.command()
def enable():
    """Habilita el servicio para iniciar con el sistema."""
    _systemctl("enable")


@APP.command()
def disable():
    """Deshabilita el servicio en systemd."""
    _systemctl("disable")


@APP.command()
def status():
    """Muestra el estado del servicio."""
    subprocess.call(["systemctl", "status", "raspsentinel.service"])


@APP.command()
def logs(
    lines: int = typer.Option(
        200, "--lines", "-n", help="Número de líneas recientes a mostrar."
    ),
    follow: bool = typer.Option(
        True,
        "--follow",
        help="Mantener la salida siguiendo nuevos eventos (usa --no-follow para desactivar).",
    ),
):
    """Muestra los logs recientes."""
    cmd = ["journalctl", "-u", "raspsentinel.service", "-n", str(lines)]
    if follow:
        cmd.append("-f")
    subprocess.call(cmd)


@config_app.command("show")
def config_show(pretty: bool = typer.Option(True, "--pretty/--no-pretty")):
    """Muestra la configuración actual."""
    data = _load()
    if pretty:
        typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        typer.echo(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


@config_app.command("set")
def config_set(key: str, value: str):
    """Actualiza una clave usando notación punto."""
    data = _load()
    _set_key(data, key, value)
    _save(data)
    typer.echo("Actualizado.")


@config_app.command("get")
def config_get(key: str):
    """Obtiene una clave de la configuración."""
    data = _load()
    try:
        typer.echo(_get_key(data, key))
    except KeyError:
        raise typer.BadParameter(f"No existe la clave '{key}'")


@config_app.command("wizard")
def config_wizard():
    """Ejecuta nuevamente el asistente interactivo."""
    setup()


def _prompt_int(message: str, default: Optional[int] = None) -> int:
    while True:
        default_text = "" if default is None else str(default)
        value = typer.prompt(message, default=default_text)
        try:
            return int(value)
        except ValueError:
            typer.echo("Introduce un número válido.")


def _prompt_float(message: str, default: Optional[float] = None) -> float:
    while True:
        default_text = "" if default is None else str(default)
        value = typer.prompt(message, default=default_text)
        try:
            return float(value)
        except ValueError:
            typer.echo("Introduce un número válido.")


def _systemctl(action: str):
    subprocess.check_call(["systemctl", action, "raspsentinel.service"])


def _ensure_conf_dir():
    os.makedirs(os.path.dirname(CONF), exist_ok=True)


def _load() -> dict[str, Any]:
    if os.path.exists(CONF):
        with open(CONF, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    return {}


def _save(data: dict[str, Any]):
    with open(CONF, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def _set_key(data: dict[str, Any], dotted: str, value: str):
    keys = dotted.split(".")
    cur: dict[str, Any] = data
    for key in keys[:-1]:
        cur = cur.setdefault(key, {})
    cur[keys[-1]] = _auto_cast(value)


def _get_key(data: dict[str, Any], dotted: str):
    cur: Any = data
    for key in dotted.split("."):
        cur = cur[key]
    return cur


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


def _detect_default_gateway() -> tuple[Optional[str], Optional[str]]:
    try:
        out = subprocess.check_output(
            ["ip", "route", "show", "default"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None, None

    for line in out.splitlines():
        parts = line.split()
        if not parts:
            continue
        if "via" in parts and "dev" in parts:
            try:
                gw = parts[parts.index("via") + 1]
                iface = parts[parts.index("dev") + 1]
                return gw, iface
            except (ValueError, IndexError):
                continue
    return None, None


def _list_interfaces() -> list[str]:
    try:
        out = subprocess.check_output(
            ["ip", "-o", "link", "show"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []

    interfaces: list[str] = []
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) < 2:
            continue
        name = parts[1].strip().split("@", 1)[0]
        if name and name != "lo":
            interfaces.append(name)
    return interfaces


if __name__ == "__main__":
    APP()
