from __future__ import annotations
import json, os, threading
from typing import Dict, Any
from datetime import datetime, timezone


class Store:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.path = os.path.join(self.data_dir, "devices.json")
        self._lock = threading.Lock()
        if not os.path.exists(self.path):
            self._write({"devices": {}, "block_applied": []})

    def _read(self) -> Dict[str, Any]:
        with self._lock:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)

    def _write(self, data: Dict[str, Any]):
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)

    def _ensure(self):
        if not os.path.exists(self.path):
            self._write({"devices": {}, "block_applied": []})

    def upsert_device(self, mac: str, ip: str | None, vendor: str | None):
        d = self._read()
        dev = d["devices"].get(mac.upper(), {
            "name": None,
            "first_seen": datetime.now(timezone.utc).isoformat(),
            "allow": False,
            "block": False,
            "vendor": vendor,
            "notes": None,
        })
        dev["ip"] = ip
        dev["vendor"] = vendor or dev.get("vendor")
        dev["last_seen"] = datetime.now(timezone.utc).isoformat()
        d["devices"][mac.upper()] = dev
        self._write(d)

    def mark_allow(self, mac: str, name: str | None = None):
        d = self._read()
        m = mac.upper()
        if m not in d["devices"]:
            d["devices"][m] = {"name": name, "allow": True, "block": False}
        else:
            d["devices"][m]["allow"] = True
            d["devices"][m]["block"] = False
            if name:
                d["devices"][m]["name"] = name
        self._write(d)

    def mark_block(self, mac: str, reason: str | None = None):
        d = self._read()
        m = mac.upper()
        if m not in d["devices"]:
            d["devices"][m] = {"name": None, "allow": False, "block": True}
        else:
            d["devices"][m]["block"] = True
            d["devices"][m]["allow"] = False
        if reason:
            d["devices"][m]["notes"] = reason
        self._write(d)

    def unallow(self, mac: str):
        d = self._read()
        m = mac.upper()
        if m in d["devices"]:
            d["devices"][m]["allow"] = False
            self._write(d)

    def unblock(self, mac: str):
        d = self._read()
        m = mac.upper()
        if m in d["devices"]:
            d["devices"][m]["block"] = False
            self._write(d)

    def set_name(self, mac: str, name: str):
        d = self._read()
        m = mac.upper()
        if m in d["devices"]:
            d["devices"][m]["name"] = name
            self._write(d)

    def list_devices(self) -> Dict[str, Any]:
        return self._read()["devices"]
