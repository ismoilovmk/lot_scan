"""Milliy do'kon (xarid.uzex.uz) — витрина предложений поставщиков.

Это не заказы, а цены конкурентов. Используется только для отчёта по ценам.
"""
from __future__ import annotations

from statistics import median

from .base import paged

ORIGIN = "https://xarid.uzex.uz"
API = "https://xarid-api-shop.uzex.uz/Common/GetOffersList"


def _num(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def fetch_offers(client, keyword: str, max_rows: int = 300) -> tuple[list[dict], int]:
    """Предложения местных производителей по слову. Возвращает (строки, всего на сайте)."""
    body = {"is_local_manufacturer": 1, "producer_country_id": 244, "keyword": keyword}
    rows = list(paged(client, API, ORIGIN, body, page_size=100, max_rows=max_rows))
    total = rows[0].get("total_count", len(rows)) if rows else 0
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
