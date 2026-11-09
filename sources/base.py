"""Общий формат лота и базовый класс площадки."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import Iterator

TASHKENT = timezone(timedelta(hours=5))  # сроки лотов бот хранит по ташкентскому времени


@dataclass
class Lot:
    source: str            # ключ площадки, например "uzex_etender"
    source_title: str      # название площадки для сообщения
    lot_id: str            # внутренний id лота на площадке
    title: str             # название лота (или категория, пока нет подробностей)
    number: str = ""       # номер лота, который видит человек на сайте
    customer: str = ""
    region: str = ""
    price: float | None = None
    currency: str = "UZS"
    deadline: str = ""     # срок подачи, ISO-строка по ташкентскому времени
    url: str = ""
    details: str = ""      # доп. текст для поиска по словам: категория, описание, позиции

    def search_text(self) -> str:
        return f"{self.title}\n{self.details}"


class Source:
    key = ""
    title = ""

    def list_lots(self, client, cfg: dict) -> Iterator[Lot]:
        """Список открытых лотов с минимумом полей."""
        raise NotImplementedError

    def enrich(self, client, lot: Lot) -> Lot:
        """Дозагрузить подробности лота. По умолчанию ничего не делает."""
        return lot


def join_region(*parts) -> str:
    return ", ".join(p.strip() for p in parts if p and p.strip())


def paged(client, url: str, origin: str, body: dict, page_size: int = 100, max_rows: int | None = None):
    """Постранично читает списки UzEX: строки нумеруются с 1, границы from/to включительно."""
    start = 1
    while True:
        end = start + page_size - 1
        if max_rows is not None:
            end = min(end, max_rows)
        rows = client.post_json(url, origin, {**body, "from": start, "to": end})
        if not rows:
            return
        yield from rows
        total = rows[0]["total_count"]  # нет общего числа — падаем, а не молча теряем страницы
        start += len(rows)  # сервер может отдать меньше строк, чем просили
        if start > total or (max_rows is not None and start > max_rows):
            return
