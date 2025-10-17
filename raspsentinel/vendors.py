from __future__ import annotations

import os
import logging
from functools import lru_cache
from typing import Dict, Optional

try:
    from mac_vendor_lookup import MacLookup  # type: ignore
except ImportError:  # pragma: no cover - optional dependency at runtime
    MacLookup = None

logger = logging.getLogger(__name__)

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
        self._mac_lookup: Optional["MacLookup"] = None
        self._mac_lookup_failed = False

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

    def _ensure_mac_lookup(self) -> Optional["MacLookup"]:
        if self._mac_lookup_failed:
            return None
        if self._mac_lookup is not None:
            return self._mac_lookup
        if MacLookup is None:
            self._mac_lookup_failed = True
            return None
        try:
            lookup = MacLookup()
            try:
                lookup.load_vendors()
            except FileNotFoundError:
                lookup.update_vendors()
                lookup.load_vendors()
            self._mac_lookup = lookup
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.debug("Mac vendor lookup unavailable: %s", exc)
            self._mac_lookup_failed = True
        return self._mac_lookup

    def _lookup_mac_lookup(self, mac: str, clean: str) -> Optional[str]:
        lookup = self._ensure_mac_lookup()
        if lookup is None or not clean:
            return None
        normalized = mac.upper()
        if ":" not in normalized and "-" not in normalized and len(clean) >= 12:
            normalized = ":".join(clean[i : i + 2] for i in range(0, 12, 2))
        try:
            return lookup.lookup(normalized)
        except Exception:  # pragma: no cover - fall back to local tables
            return None

    @lru_cache(maxsize=256)
    def lookup(self, mac: str) -> Optional[str]:
        self._load()
        clean = mac.upper().replace(":", "").replace("-", "")
        if not clean:
            return None
        vendor = self._lookup_mac_lookup(mac, clean)
        if vendor:
            return vendor
        if len(clean) >= 9:
            vendor = self._map9.get(clean[:9])
            if vendor:
                return vendor
        return self._map6.get(clean[:6])


VENDOR_LOOKUP = VendorLookup()
