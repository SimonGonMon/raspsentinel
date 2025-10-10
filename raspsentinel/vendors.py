from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, Optional


IEEE_OUI_PATHS = (
    "/usr/share/arp-scan/ieee-oui.txt",
    "/usr/share/misc/ieee-oui.txt",
)
IEEE_IAB_PATHS = (
    "/usr/share/arp-scan/ieee-iab.txt",
    "/usr/share/misc/ieee-iab.txt",
)


class VendorLookup:
    """Resuelve fabricantes a partir de los ficheros OUI/IAB instalados por arp-scan."""

    def __init__(self) -> None:
        self._map6: Dict[str, str] = {}
        self._map9: Dict[str, str] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        for path in IEEE_OUI_PATHS:
            self._parse_file(path, self._map6)
        for path in IEEE_IAB_PATHS:
            self._parse_file(path, self._map9)
        self._loaded = True

    def _parse_file(self, path: str, target: Dict[str, str]) -> None:
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if "(base 16)" in line or "(base 36)" in line:
                        prefix, _, vendor = line.partition("(base")
                        prefix = prefix.strip().replace("-", "").replace(":", "").upper()
                        vendor = vendor.split(")", 1)[-1].strip()
                        if prefix and vendor:
                            target[prefix] = vendor
        except OSError:
            return

    @lru_cache(maxsize=256)
    def lookup(self, mac: str) -> Optional[str]:
        self._load()
        clean = mac.upper().replace(":", "").replace("-", "")
        if not clean:
            return None
        if len(clean) >= 9:
            vendor = self._map9.get(clean[:9])
            if vendor:
                return vendor
        return self._map6.get(clean[:6])


VENDOR_LOOKUP = VendorLookup()
