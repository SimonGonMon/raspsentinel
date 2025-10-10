from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)


class TelegramBot:
    PAGE_SIZE = 5

    def __init__(self, token: str, chat_id: int, store, block_apply_cb, block_remove_cb):
        self.token = token
        self.chat_id = int(chat_id)
        self.store = store
        self.block_apply_cb = block_apply_cb
        self.block_remove_cb = block_remove_cb
        self.app = Application.builder().token(self.token).build()
        self._register()

    def _register(self):
        self.app.add_handler(CommandHandler("start", self._start))
        self.app.add_handler(CommandHandler("id", self._id))
        self.app.add_handler(CommandHandler("settings", self._settings))
        self.app.add_handler(CommandHandler("connected", self._connected))
        self.app.add_handler(CommandHandler("allowlist", self._allowlist))
        self.app.add_handler(CommandHandler("blocklist", self._blocklist))
        self.app.add_handler(CommandHandler("add_allow", self._add_allow))
        self.app.add_handler(CommandHandler("rm_allow", self._rm_allow))
        self.app.add_handler(CommandHandler("add_block", self._add_block))
        self.app.add_handler(CommandHandler("rm_block", self._rm_block))
        self.app.add_handler(CallbackQueryHandler(self._buttons))

    async def run(self):
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)

    async def stop(self):
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()

    async def _authorized(self, update: Update) -> bool:
        return update.effective_chat and update.effective_chat.id == self.chat_id

    async def _reject(self, update: Update):
        if update.effective_chat:
            await update.effective_chat.send_message("No autorizado.")

    async def _start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._authorized(update):
            return await self._reject(update)
        await update.message.reply_text(
            "Raspsentinel listo. Usa /connected /allowlist /blocklist /settings"
        )

    async def _id(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        cid = update.effective_chat.id if update.effective_chat else None
        await update.message.reply_text(f"chat_id: {cid}")

    async def _settings(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._authorized(update):
            return await self._reject(update)
        await update.message.reply_text("Configuración en /etc/raspsentinel/config.yaml")

    async def _connected(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._authorized(update):
            return await self._reject(update)
        text, markup = self._render_connected_page(0)
        await update.message.reply_text(text, reply_markup=markup)

    async def _allowlist(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._authorized(update):
            return await self._reject(update)
        devs = self.store.list_devices()
        lines = [
            f"{m}  {d.get('name') or '—'}"
            for m, d in sorted(devs.items())
            if d.get("allow")
        ]
        await update.message.reply_text(
            "Allowlist:\n" + ("\n".join(lines) or "vacía")
        )

    async def _blocklist(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._authorized(update):
            return await self._reject(update)
        devs = self.store.list_devices()
        lines = [
            f"{m}  {d.get('name') or '—'}"
            for m, d in sorted(devs.items())
            if d.get("block")
        ]
        await update.message.reply_text(
            "Blocklist:\n" + ("\n".join(lines) or "vacía")
        )

    async def _add_allow(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._authorized(update):
            return await self._reject(update)
        if not ctx.args:
            return await update.message.reply_text("Uso: /add_allow <MAC> [nombre]")
        mac = ctx.args[0]
        name = " ".join(ctx.args[1:]) if len(ctx.args) > 1 else None
        self.store.mark_allow(mac, name)
        await update.message.reply_text(f"Permitido {mac}")

    async def _rm_allow(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._authorized(update):
            return await self._reject(update)
        if not ctx.args:
            return await update.message.reply_text("Uso: /rm_allow <MAC>")
        self.store.unallow(ctx.args[0])
        await update.message.reply_text(f"Quitado de allowlist {ctx.args[0]}")

    async def _add_block(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._authorized(update):
            return await self._reject(update)
        if not ctx.args:
            return await update.message.reply_text("Uso: /add_block <MAC> [motivo]")
        mac = ctx.args[0]
        reason = " ".join(ctx.args[1:]) if len(ctx.args) > 1 else None
        self.store.mark_block(mac, reason)
        await update.message.reply_text(f"Bloqueado {mac}")
        if self.block_apply_cb:
            await self.block_apply_cb(mac)

    async def _rm_block(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._authorized(update):
            return await self._reject(update)
        if not ctx.args:
            return await update.message.reply_text("Uso: /rm_block <MAC>")
        mac = ctx.args[0]
        self.store.unblock(mac)
        await update.message.reply_text(f"Desbloqueado {mac}")
        if self.block_remove_cb:
            await self.block_remove_cb(mac)

    async def _buttons(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        if update.effective_chat.id != self.chat_id:
            return
        data = q.data or ""
        if data.startswith("ALLOW|"):
            mac = data.split("|", 1)[1]
            self.store.mark_allow(mac)
            await q.edit_message_text(f"Permitido {mac}")
        elif data.startswith("BLOCK|"):
            mac = data.split("|", 1)[1]
            self.store.mark_block(mac, "bot decision")
            await q.edit_message_text(f"Bloqueado {mac}")
            if self.block_apply_cb:
                await self.block_apply_cb(mac)
        elif data.startswith("IGNORE|"):
            mac = data.split("|", 1)[1]
            await q.edit_message_text(f"Ignorado {mac}")
        elif data.startswith("CONNECTED|"):
            text, markup = self._handle_connected_callback(data)
            if text:
                await q.edit_message_text(text=text, reply_markup=markup)

    async def notify_new(self, device: Dict[str, Any]):
        mac = device.get("mac")
        ip = device.get("ip")
        vendor = device.get("vendor") or "?"
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(text="Permitir", callback_data=f"ALLOW|{mac}"),
                    InlineKeyboardButton(text="Bloquear", callback_data=f"BLOCK|{mac}"),
                    InlineKeyboardButton(text="Ignorar", callback_data=f"IGNORE|{mac}"),
                ]
            ]
        )
        text = (
            f"\nNuevo dispositivo visto:\nMAC: *{mac}*\nIP: `{ip}`\nVendor: _{vendor}_"
        )
        await self.app.bot.send_message(
            chat_id=self.chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb,
        )

    def _handle_connected_callback(
        self, data: str
    ) -> Tuple[Optional[str], Optional[InlineKeyboardMarkup]]:
        parts = data.split("|")
        if len(parts) < 2:
            return None, None
        action = parts[1]
        if action == "PAGE" and len(parts) >= 3:
            try:
                page = int(parts[2])
            except ValueError:
                page = 0
        elif action == "REFRESH" and len(parts) >= 3:
            try:
                page = int(parts[2])
            except ValueError:
                page = 0
        else:
            page = 0
        return self._render_connected_page(page)

    def _render_connected_page(
        self, page: int
    ) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
        devices = self.store.list_devices()
        entries = self._prepare_connected_entries(devices)
        total = len(entries)
        total_pages = max(1, math.ceil(total / self.PAGE_SIZE))
        page = max(0, min(page, total_pages - 1))
        start = page * self.PAGE_SIZE
        end = start + self.PAGE_SIZE

        if total == 0:
            text = "Sin datos recientes. Usa /connected más tarde para refrescar."
        else:
            lines = []
            for idx, entry in enumerate(entries[start:end], start=1 + start):
                line = (
                    f"{idx}. {entry['mac']} [{entry['status']}] "
                    f"IP {entry['ip']} | {entry['name']} | {entry['vendor']} | {entry['last_seen']}"
                )
                lines.append(line)
            header = (
                f"Dispositivos vistos (página {page + 1}/{total_pages}, total {total})"
            )
            text = header + "\n" + "\n".join(lines)

        buttons: List[List[InlineKeyboardButton]] = []
        if total > 0:
            nav_row: List[InlineKeyboardButton] = []
            if total_pages > 1 and page > 0:
                nav_row.append(
                    InlineKeyboardButton(
                        "« Anterior", callback_data=f"CONNECTED|PAGE|{page - 1}"
                    )
                )
            nav_row.append(
                InlineKeyboardButton(
                    "Actualizar", callback_data=f"CONNECTED|REFRESH|{page}"
                )
            )
            if total_pages > 1 and page < total_pages - 1:
                nav_row.append(
                    InlineKeyboardButton(
                        "Siguiente »", callback_data=f"CONNECTED|PAGE|{page + 1}"
                    )
                )
            buttons.append(nav_row)
        else:
            buttons.append(
                [InlineKeyboardButton("Actualizar", callback_data="CONNECTED|REFRESH|0")]
            )

        markup = InlineKeyboardMarkup(buttons) if buttons else None
        return text, markup

    def _prepare_connected_entries(
        self, devices: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        now = datetime.now(timezone.utc)
        entries: List[Tuple[datetime, Dict[str, str]]] = []
        for mac, data in devices.items():
            last_ts = data.get("last_seen") or data.get("first_seen")
            last_dt = (
                self._parse_iso(last_ts)
                if last_ts
                else datetime.fromtimestamp(0, tz=timezone.utc)
            )
            status = self._status_for_device(data)
            entries.append(
                (
                    last_dt or datetime.fromtimestamp(0, tz=timezone.utc),
                    {
                        "mac": mac,
                        "ip": data.get("ip") or "?",
                        "name": data.get("name") or "—",
                        "vendor": data.get("vendor") or "?",
                        "status": status,
                        "last_seen": self._format_last_seen(last_dt, now),
                    },
                )
            )
        sorted_entries = sorted(entries, key=lambda item: item[0], reverse=True)
        return [entry for _, entry in sorted_entries]

    @staticmethod
    def _status_for_device(data: Dict[str, Any]) -> str:
        if data.get("block"):
            return "BLOCK"
        if data.get("allow"):
            return "ALLOW"
        return "NEW"

    @staticmethod
    def _parse_iso(value: str) -> Optional[datetime]:
        if not value:
            return None
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _format_last_seen(self, last_dt: Optional[datetime], now: datetime) -> str:
        if not last_dt:
            return "sin registro"
        delta = now - last_dt
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "hace <1m"
        if seconds < 3600:
            return f"hace {seconds // 60}m"
        if seconds < 86400:
            return f"hace {seconds // 3600}h"
        return f"hace {seconds // 86400}d"
