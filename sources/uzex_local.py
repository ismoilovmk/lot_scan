"""xarid.uzex.uz — запрос предложений (Taklif so'rovi) и местный аукцион (Mahalliy auksion).

Эти разделы открываются только из Узбекистана. В списке есть категория, но нет названия лота:
названия и описания позиций приходят в карточке лота.
"""
from __future__ import annotations

import re

from .base import Lot, Source, join_region

ORIGIN = "https://xarid.uzex.uz"
PREQUEST = "https://xarid-api-prequest.uzex.uz/api/Public"
AUCTIONX = "https://xarid-api-auctionx.uzex.uz/api/Lot"
PAGE = 100
# Улица в адресе: «Тошкент кўчаси», «Farg'ona ko'chasi», «улица Ташкентская». Её название — не регион.
STREET = re.compile(r"[^\s,]+\s+(?:к[ўу]часи|ko.?chasi),?\s*|(?:улица|ул\.)\s*[^\s,]+,?\s*", re.IGNORECASE)


def _region(address: str | None) -> str:
    """Регион по адресу заказчика: отдельного поля в списке нет, а улицы названы в честь городов."""
    return STREET.sub("", address or "").strip()


def _rows(client, url: str):
    """Список раздела по страницам: ответ {Status, Data}, строки с 1, общее число — totalCount в каждой строке."""
    start = 1
    while True:
        rows = client.post_json(url, ORIGIN, {"from": start, "to": start + PAGE - 1}).get("Data") or []
        if not rows:
            return
        yield from rows
        start += len(rows)  # сервер может отдать меньше строк, чем просили
        if start > rows[0]["totalCount"]:
            return


def _positions(card: dict) -> tuple[list[str], list[str]]:
    """Названия позиций без повторов и их описания."""
    names, texts = [], []
    for item in card.get("details") or []:
        name = (item.get("productName") or "").strip()
        if name and name not in names:
            names.append(name)
        texts.append(item.get("description") or "")
    return names, texts


def _apply_card(lot: Lot, card: dict, extra: str = "") -> Lot:
    names, texts = _positions(card)
    if names:
        lot.title = "; ".join(names)[:300]
    lot.customer = (card.get("customerName") or "").strip() or lot.customer
    lot.details = "\n".join(text for text in (*texts, extra) if text)
    return lot


class UzexRequest(Source):
    key = "uzex_request"
    title = "UzEX запрос предложений (Taklif so'rovi)"

    def list_lots(self, client, cfg):
        for row in _rows(client, f"{PREQUEST}/GetLots"):
            yield Lot(
                source=self.key,
                source_title=self.title,
                lot_id=str(row["id"]),
                number=str(row.get("displayId") or ""),
                title=(row.get("categoryName") or "").strip(),
                customer=(row.get("customerName") or "").strip(),
                region=_region(row.get("address")),
                price=row.get("startCost"),
                deadline=row.get("endDate") or "",
                url=f"{ORIGIN}/request-proposal/3/detail/{row['id']}",
            )

    def enrich(self, client, lot):
        card = client.get_json(f"{PREQUEST}/GetLot?id={lot.lot_id}", ORIGIN).get("Data") or {}
        return _apply_card(lot, card, card.get("deliveryAddress") or "")


class UzexLocalAuction(Source):
    key = "uzex_local_auction"
    title = "UzEX местный аукцион (Mahalliy auksion)"

    def list_lots(self, client, cfg):
        for row in _rows(client, f"{AUCTIONX}/GetList"):
            yield Lot(
                source=self.key,
                source_title=self.title,
                lot_id=str(row["id"]),
                number=str(row.get("displayNo") or ""),
                title=(row.get("categoryName") or "").strip(),
                region=join_region(row.get("regionName"), row.get("districtName")),
                price=row.get("startCost"),
                deadline=row.get("endDate") or "",
                url=f"{ORIGIN}/new-auction/detail/{row['id']}",
            )

    def enrich(self, client, lot):
        card = client.get_json(f"{AUCTIONX}/Get?id={lot.lot_id}", ORIGIN).get("Data") or {}
        return _apply_card(lot, card)
