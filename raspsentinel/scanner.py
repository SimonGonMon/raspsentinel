from __future__ import annotations

import re
from typing import Dict, List

from .utils import has_cmd, run


ARP_RE = re.compile(r"^(?P<ip>\d+\.\d+\.\d+\.\d+)\s+(?P<mac>[0-9a-f:]{17})\s+(?P<vendor>.+)$", re.I)
IPN_RE = re.compile(r"^(?P<ip>\d+\.\d+\.\d+\.\d+) dev \S+ lladdr (?P<mac>[0-9a-f:]{17}) ")


class Scanner:
    def __init__(self, iface: str):
        self.iface = iface

    def scan(self) -> List[Dict[str, str]]:
        if has_cmd("arp-scan"):
            return self._scan_arp_scan()
        else:
            return self._scan_ip_neigh()

    def _scan_arp_scan(self) -> List[Dict[str, str]]:
        out = run(["arp-scan", "--interface", self.iface, "--localnet", "--plain", "--ignoredups"])
        res = []
        for line in out.splitlines():
            m = ARP_RE.match(line.strip())
            if m:
                res.append({"ip": m.group("ip"), "mac": m.group("mac").upper(), "vendor": m.group("vendor").strip()})
        return res

    def _scan_ip_neigh(self) -> List[Dict[str, str]]:
        out = run(["ip", "neigh", "show", "dev", self.iface])
        res = []
        for line in out.splitlines():
            m = IPN_RE.match(line.strip())
            if m:
                res.append({"ip": m.group("ip"), "mac": m.group("mac").upper(), "vendor": None})
        return res
