from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict

try:
    from scapy.all import ARP, Ether, sendp, get_if_hwaddr, conf  # type: ignore
except ImportError:  # pragma: no cover - runtime guard
    ARP = Ether = sendp = get_if_hwaddr = conf = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class _TaskEntry:
    task: asyncio.Task
    stop_event: asyncio.Event


class ArpSpoofBlocker:
    """Mantiene sesiones de ARP spoofing para bloquear dispositivos."""

    def __init__(self, iface: str, gateway_ip: str, interval: float = 2.0):
        if ARP is None or get_if_hwaddr is None or sendp is None:
            raise RuntimeError("scapy no está instalado; bloqueo por ARP no disponible.")
        if not gateway_ip:
            raise ValueError("Se requiere gateway_ip para el bloqueo por ARP.")
        self.iface = iface
        self.gateway_ip = gateway_ip
        self.interval = interval
        self._entries: Dict[str, _TaskEntry] = {}
        self._my_mac = get_if_hwaddr(self.iface)
        conf.iface = self.iface  # type: ignore[attr-defined]
        logger.info("ARP spoof listo en %s (MAC %s)", self.iface, self._my_mac)

    async def block(self, mac: str, ip: str):
        mac = mac.upper()
        if not ip:
            raise ValueError(f"No hay IP conocida para {mac}, no se puede bloquear.")
        if mac in self._entries:
            return
        stop_event = asyncio.Event()
        task = asyncio.create_task(self._spoof_loop(mac, ip, stop_event))
        self._entries[mac] = _TaskEntry(task=task, stop_event=stop_event)
        logger.info("Iniciando bloqueo ARP para %s (%s)", mac, ip)

    async def unblock(self, mac: str):
        mac = mac.upper()
        entry = self._entries.pop(mac, None)
        if not entry:
            return
        entry.stop_event.set()
        entry.task.cancel()
        try:
            await entry.task
        except asyncio.CancelledError:
            pass
        logger.info("Bloqueo ARP detenido para %s", mac)

    async def shutdown(self):
        for mac in list(self._entries.keys()):
            await self.unblock(mac)

    async def _spoof_loop(self, mac: str, ip: str, stop_event: asyncio.Event):
        while True:
            try:
                await asyncio.to_thread(self._send_packet, mac, ip)
            except Exception as exc:  # pragma: no cover - runtime safety
                logger.error("Error al enviar paquete ARP para %s: %s", mac, exc)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.interval)
                break
            except asyncio.TimeoutError:
                continue

    def _send_packet(self, target_mac: str, target_ip: str):
        ether = Ether()  # type: ignore[call-arg]
        ether.src = self._my_mac
        ether.dst = target_mac

        arp = ARP()  # type: ignore[call-arg]
        arp.psrc = self.gateway_ip
        arp.hwsrc = self._my_mac
        arp.pdst = target_ip
        arp.hwdst = target_mac
        arp.op = 2

        packet = ether / arp  # type: ignore[operator]
        sendp(packet, iface=self.iface, verbose=False)  # type: ignore[arg-type]
