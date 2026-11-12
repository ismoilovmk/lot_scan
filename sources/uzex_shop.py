"""Milliy do'kon (xarid.uzex.uz) — витрина предложений поставщиков и торги по ним.

Сами предложения — это цены конкурентов (отчёт по ценам). Заказ появляется, когда заказчик выбирает
предложение: по нему 48 часов идёт торг, и другие поставщики того же товара могут дать цену ниже.
"""
from __future__ import annotations

import math
import time
from statistics import median

from .base import Lot, Source, paged

ORIGIN = "https://xarid.uzex.uz"
API = "https://xarid-api-shop.uzex.uz/Common/GetOffersList"
LOCAL = {"is_local_manufacturer": 1, "producer_country_id": 244}  # отбор Milliy do'kon: местные производители


def _num(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def fetch_offers(client, keyword: str, max_rows: int = 300) -> tuple[list[dict], int]:
    """Предложения местных производителей по слову. Возвращает (строки, всего на сайте)."""
    body = {**LOCAL, "keyword": keyword}
    rows = list(paged(client, API, ORIGIN, body, page_size=100, max_rows=max_rows))
    total = rows[0]["total_count"] if rows else 0
    return rows, total


def price_report(client, keywords: list[str]) -> str:
    lines = ["Цены в Milliy do'kon (предложения поставщиков)"]
    for keyword in keywords:
        rows, total = fetch_offers(client, keyword)
        lines.append("")
        lines.append(f"«{keyword}»: всего предложений {total}, просмотрено {len(rows)}")
        groups: dict[tuple[str, str], list[float]] = {}
        for row in rows:
            price = row.get("price")
            if not price:
                continue
            key = ((row.get("product_name") or "").strip(), row.get("unit_name") or "ед.")
            groups.setdefault(key, []).append(float(price))
        top = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)[:8]
        for (name, unit), prices in top:
            lines.append(
                f"  • {name} — {len(prices)} предл., за {unit}: "
                f"мин {_num(min(prices))}, медиана {_num(median(prices))}, макс {_num(max(prices))} сум"
            )
    return "\n".join(lines)


# --- торги: заказчик выбрал предложение поставщика, и 48 часов другие поставщики могут дать цену ниже ---

SHOP = "https://xarid-api-shop.uzex.uz/Common"
PAGE = 12  # больше строк за запрос магазин не отдаёт, сколько ни проси
NEW = 1    # состояние торга «Новый»: идёт приём цен


def _offers(client, scope: dict, keyword: str, start: int) -> list[dict]:
    body = {**scope, "keyword": keyword, "from": start, "to": start + PAGE - 1}
    return client.post_json(API, ORIGIN, body)


def _region(areas: list[dict]) -> str:
    """Куда везти: область и её районы, как их отдаёт площадка."""
    names = []
    for area in areas or []:
        names += [area.get("name")] + [child.get("name") for child in area.get("children") or []]
    return ", ".join(name for name in names if name)


class ShopLots(Source):
    """Общего списка торгов у магазина нет: они видны только в карточке предложения.

    Поэтому бот находит предложения по словам shop_keywords и смотрит торги каждого. Предложений тысячи,
    так что за проход проверяется часть (shop_offers_per_pass), а какая — решают часы: части идут по кругу.
    """
    key = "uzex_shop"
    title = "Milliy do'kon (торг по предложению)"
    scope = LOCAL  # чем запрос списка предложений отличает этот магазин

    def list_lots(self, client, cfg):
        checked = set()
        for keyword, start in self._part(client, cfg):
            for offer in _offers(client, self.scope, keyword, start):
                if offer["id"] not in checked:
                    checked.add(offer["id"])
                    yield from self._trades(client, offer)

    def _part(self, client, cfg) -> list[tuple[str, int]]:
        """Страницы списка предложений на этот проход: [(слово, с какой строки)]."""
        pages = []
        for keyword in cfg.get("shop_keywords") or []:
            rows = _offers(client, self.scope, keyword, 1)
            total = rows[0]["total_count"] if rows else 0
            pages += [(keyword, start) for start in range(1, total + 1, PAGE)]
        size = max(1, int(cfg.get("shop_offers_per_pass", 300)) // PAGE)
        parts = max(1, math.ceil(len(pages) / size))
        turn = int(time.time() // (int(cfg.get("interval_minutes", 20)) * 60)) % parts
        return pages[turn * size:(turn + 1) * size]

    def _trades(self, client, offer: dict):
        for trade in client.get_json(f"{SHOP}/GetOfferLots/{offer['id']}", ORIGIN):
            if trade.get("status_id") != NEW:
                continue
            areas = client.get_json(f"{SHOP}/GetLotRegionsDistricts/{trade['id']}", ORIGIN)
            yield Lot(
                source=self.key,
                source_title=self.title,
                lot_id=str(trade["id"]),
                number=str(trade.get("display_no") or ""),
                title=(offer.get("product_name") or "").strip(),
                region=_region(areas),
                price=(trade.get("price") or 0) * (trade.get("amount") or 0) or None,
                deadline=trade.get("end_date") or "",
                url=f"{ORIGIN}/shop/lot-details/{trade['id']}",
            )

    def enrich(self, client, lot):
        data = client.get_json(f"{SHOP}/GetLot/{lot.lot_id}", ORIGIN)
        lot.details = data.get("condition") or ""
        return lot


class EShopLots(ShopLots):
    """Elektron do'kon: тот же магазин и те же торги, но предложения любых поставщиков, а не только местных."""
    key = "uzex_eshop"
    title = "Elektron do'kon (торг по предложению)"
    scope = {}
