from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Optional

import typer
import yaml

app = typer.Typer(add_completion=False, help="Herramientas para instalar y operar Raspsentinel.")
config_app = typer.Typer(add_completion=False, help="Operaciones sobre el archivo de configuración.")
app.add_typer(config_app, name="config")

CONF_PATH = "/etc/raspsentinel/config.yaml"
SERVICE_NAME = "raspsentinel.service"


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
    app()
