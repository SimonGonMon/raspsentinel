from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Optional

import yaml

from .blocker import ArpSpoofBlocker
from .scanner import Scanner
from .store import Store
from .telegram_bot import TelegramBot

logger = logging.getLogger(__name__)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="/etc/raspsentinel/config.yaml")
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    data_dir = cfg.get("app", {}).get("data_dir", "/var/lib/raspsentinel")
    store = Store(data_dir)
    iface = cfg["network"]["interface"]
    scanner = Scanner(iface)

    block_cfg = cfg.get("block", {})
    block_enable = bool(block_cfg.get("enable", False))
    gateway_ip = block_cfg.get("gateway_ip") or cfg.get("network", {}).get("gateway_ip")
    arp_interval = float(block_cfg.get("arp_interval_sec", 2.0))

    blocker: Optional[ArpSpoofBlocker] = None
    if block_enable:
        try:
            blocker = ArpSpoofBlocker(iface=iface, gateway_ip=gateway_ip, interval=arp_interval)
        except Exception as exc:
            logger.error("No se pudo inicializar el bloqueo ARP: %s", exc)
            block_enable = False

    async def _apply(mac: str):
        if not block_enable or blocker is None:
            return
        device = store.list_devices().get(mac.upper())
        if not device:
            logger.warning("No hay datos para %s, no se puede bloquear.", mac)
            return
        ip = device.get("ip")
        try:
            await blocker.block(mac, ip)
        except Exception as exc:
            logger.error("Error al aplicar bloqueo a %s: %s", mac, exc)

    async def _remove(mac: str):
        if not block_enable or blocker is None:
            return
        try:
            await blocker.unblock(mac)
        except Exception as exc:
            logger.error("Error al quitar bloqueo a %s: %s", mac, exc)

    bot = TelegramBot(
        token=cfg["telegram"]["bot_token"],
        chat_id=int(cfg["telegram"]["chat_id"]),
        store=store,
        block_apply_cb=_apply,
        block_remove_cb=_remove,
    )

    scan_interval = int(cfg["network"].get("scan_interval_sec", 60))

    async def scan_loop():
        while True:
            try:
                seen = scanner.scan()
                devices = store.list_devices()
                known_allow = {m for m, d in devices.items() if d.get("allow")}
                known_block = {m for m, d in devices.items() if d.get("block")}

                for dev in seen:
                    mac = dev["mac"].upper()
                    store.upsert_device(mac, dev.get("ip"), dev.get("vendor"))
                    if mac not in known_allow and mac not in known_block:
                        await bot.notify_new(dev)
                # opcional: purga de "online" es solo a efectos de presentación
            except Exception as e:
                # registro mínimo a stdout
                logger.exception("scan error: %s", e)
            await asyncio.sleep(scan_interval)

    async def bot_loop():
        await bot.run()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            pass

    try:
        await asyncio.gather(bot_loop(), scan_loop())
    finally:
        if block_enable and blocker is not None:
            await blocker.shutdown()
        try:
            await bot.stop()
        except Exception as exc:  # pragma: no cover - cleanup best-effort
            logger.debug("Error al detener el bot: %s", exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
