"""Оформление лота и отправка в Telegram."""
from __future__ import annotations

import html
import logging
import time
from datetime import datetime

import requests

from sources.base import Lot

log = logging.getLogger(__name__)


def format_price(price, currency: str = "UZS") -> str:
    if price is None:
        return "не указана"
    unit = "сум" if currency in ("UZS", "Сом", "Сум", "") else currency
    return f"{price:,.0f}".replace(",", " ") + f" {unit}"


def format_deadline(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return value or "не указан"


def format_lot(lot: Lot, services: dict[str, list[str]], priority: str = "") -> str:
    """Текст сообщения в HTML-разметке Telegram. services — {услуга: найденные слова},
    priority — название приоритетного региона, если лот из него."""
    e = html.escape
    title = lot.title if len(lot.title) <= 400 else lot.title[:400] + "…"
    number = lot.number or lot.lot_id
    customer = lot.customer or "не указан"
    region = lot.region or "не указан"
    words = [word for found in services.values() for word in found]
    lines = [f"🟢 {e(priority)}"] if priority else []
    lines += [
        f"<b>{e(title)}</b>",
        "",
        f"Площадка: {e(lot.source_title)}",
        f"Лот №: {e(number)}",
        f"Заказчик: {e(customer)}",
        f"Регион: {e(region)}",
        f"Стартовая цена: {e(format_price(lot.price, lot.currency))}",
        f"Срок подачи: {e(format_deadline(lot.deadline))}",
        f"Услуга: {e('; '.join(services))}",
        f"Совпало: {e(', '.join(words))}",
        "",
        e(lot.url),
    ]
    return "\n".join(lines)


def chats_from_updates(updates: list[dict]) -> list[tuple[str, str]]:
    """Из ответа getUpdates достаёт чаты, которые писали боту: [(chat_id, название)]."""
    chats: dict[str, str] = {}
    for update in updates:
        for key in ("message", "channel_post", "my_chat_member"):
            chat = (update.get(key) or {}).get("chat")
            if not chat:
                continue
            name = chat.get("title") or " ".join(
                p for p in (chat.get("first_name"), chat.get("last_name")) if p
            ) or chat.get("username") or "без названия"
            kind = {"private": "личный чат", "channel": "канал"}.get(chat.get("type"), "группа")
            chats[str(chat["id"])] = f"{name} ({kind})"
    return list(chats.items())


def find_chats(token: str) -> list[tuple[str, str]]:
    """Спрашивает у Telegram, кто недавно писал боту."""
    resp = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30)
    if resp.status_code in (401, 404):
        raise RuntimeError("Telegram не принял токен. Проверьте TELEGRAM_BOT_TOKEN в файле .env.")
    if not resp.ok:
        raise RuntimeError(f"Telegram ответил {resp.status_code}: {resp.text[:300]}")
    return chats_from_updates(resp.json().get("result") or [])


class ConsoleNotifier:
    """Пробный режим: печатает сообщения вместо отправки."""

    def send(self, text: str) -> None:
        print("-" * 60)
        print(text)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, pause: float = 1.1):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.pause = pause  # Telegram разрешает около 1 сообщения в секунду в один чат

    def send(self, text: str) -> None:
        payload = {
            "chat_id": self.chat_id,
            "text": text[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        for _ in range(3):
            resp = requests.post(self.url, json=payload, timeout=30)
            if resp.status_code == 429:
                delay = resp.json().get("parameters", {}).get("retry_after", 5)
                log.warning("Telegram просит подождать %s с", delay)
                time.sleep(delay + 1)
                continue
            if not resp.ok:
                raise RuntimeError(f"Telegram ответил {resp.status_code}: {resp.text[:300]}")
            time.sleep(self.pause)
            return
        raise RuntimeError("Telegram не принял сообщение после трёх попыток")
