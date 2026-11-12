"""ebirja.uz (Ташкентская товарно-сырьевая биржа) — госзакупки: аукцион, отбор, тендер, запрос предложений.

Третий оператор госзакупок наряду с UzEX и xt-xarid. Списки отдают название лота, заказчика и регион,
а названия позиций — отдельным запросом по каждому лоту.
"""
from __future__ import annotations

from urllib.parse import urlencode

from .base import Lot, Source, join_region

SITE = "https://ebirja.uz"
API = "https://xarid-api.ebirja.uz"
PAGE = 100
OPEN = 50  # состояние «опубликован»: идёт приём предложений

# раздел: адрес списка, его параметры, адрес карточки, поле с позициями, страница лота на сайте
SECTIONS = {
    "auction": ("auction/auction/active", [("auction_type", 1)], "auction/auction/auction-view",
                "auction_classifiers", "auction"),
    "local": ("auction/auction/active", [("auction_type", 2)], "auction/auction/auction-view",
              "auction_classifiers", "local-auction"),
    # тендеры (типы 1, 3, 5) и отборы (2, 4, 6, 8) сайт отдаёт одним списком
    "tender": ("tender-v2/producer/landing-lots", [("type[]", kind) for kind in (1, 2, 3, 4, 5, 6, 8)] + [("state[]", OPEN)],
               "tender-v2/producer/landing-lots-view", "products", "tender"),
    "offer": ("offer-request/offer-request/announce-list", [], "offer-request/offer-request/announce-view",
              "classifiers", "offer-request"),
}
TITLES = {"auction": "аукцион", "local": "местный аукцион", "offer": "запрос предложений"}


def _get(client, path: str, params: list[tuple]) -> dict:
    reply = client.get_json(f"{API}/{path}?{urlencode(params)}", SITE)
    if reply.get("result") is None:
        raise RuntimeError(f"ebirja.uz: {reply.get('errors')}")
    return reply["result"]


def _kind(section: str, row: dict) -> str:
    if section != "tender":
        return TITLES[section]
    return "тендер" if row.get("type") in (1, 3, 5) else "отбор"


def _region(row: dict) -> str:
    """Место поставки, а если площадка его не указала — регион заказчика."""
    place = row if row.get("region") else row.get("company") or {}
    return join_region(*((place.get(key) or {}).get("title_ru") for key in ("region", "district")))


def _position_texts(position: dict) -> list[str]:
    classifier = position.get("classifier") or {}
    return [classifier.get(key) for key in ("title_ru", "title_uz", "title_uzk")] + [position.get("description")]


class Ebirja(Source):
    key = "ebirja"
    title = "Ebirja"

    def list_lots(self, client, cfg):
        for section, (path, params, _, _, page_name) in SECTIONS.items():
            for row in self._rows(client, path, params):
                yield Lot(
                    source=self.key,
                    source_title=f"{self.title} ({_kind(section, row)})",
                    lot_id=f"{section}-{row['id']}",
                    number=str(row.get("lot") or ""),
                    title=(row.get("title") or "").strip(),
                    customer=((row.get("company") or {}).get("title") or "").strip(),
                    region=_region(row),
                    price=row.get("total_sum", row.get("total_price")),
                    deadline=(row.get("auction_end") or row.get("end_date") or "").replace(" ", "T"),
                    url=f"{SITE}/ru/{page_name}/{row['id']}",
                )

    def _rows(self, client, path: str, params: list[tuple]):
        page = 0
        while True:
            result = _get(client, path, [("currentPage", page), ("perPage", PAGE), *params, ("size", PAGE)])
            yield from result["data"]
            page += 1
            if page >= result["meta"]["pageCount"]:
                return

    def enrich(self, client, lot):
        section, lot_id = lot.lot_id.split("-")
        _, _, path, field, _ = SECTIONS[section]
        data = _get(client, path, [("id", lot_id), ("expand", "e_references")])
        texts = [text for position in data.get(field) or [] for text in _position_texts(position)]
        lot.details = "\n".join(text for text in texts + [data.get("description")] if text)
        return lot
