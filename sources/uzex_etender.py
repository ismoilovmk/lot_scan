"""etender.uzex.uz — тендеры и отбор наилучших предложений."""
from __future__ import annotations

import json

from .base import Lot, Source, join_region, paged

ORIGIN = "https://etender.uzex.uz"
API = "https://apietender.uzex.uz/api/common"

# typeid в запросе -> как называется раздел
TYPES = {1: "отбор", 2: "тендер"}


def _positions(value) -> list[dict]:
    """Позиции лота. Сайт отдаёт их списком или JSON-строкой; нечитаемую строку ищем как текст."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return [{"Description": value}]
    return value if isinstance(value, list) else []


class UzexEtender(Source):
    key = "uzex_etender"
    title = "UzEX etender"

    def list_lots(self, client, cfg):
        for type_id, type_name in TYPES.items():
            body = {"is_agent": None, "Is_Scientific": None, "System_Id": 0, "typeid": type_id}
            for row in paged(client, f"{API}/TradeList", ORIGIN, body):
                yield Lot(
                    source=self.key,
                    source_title=f"{self.title} ({type_name})",
                    lot_id=str(row["id"]),
                    number=str(row.get("display_no") or ""),
                    title=(row.get("name") or "").strip(),
                    customer=(row.get("seller_name") or "").strip(),
                    region=join_region(row.get("region_name"), row.get("district_name")),
                    price=row.get("cost"),
                    currency=row.get("currency_codeabc") or "UZS",
                    deadline=row.get("end_date") or "",
                    url=f"{ORIGIN}/lot/{row['id']}",
                )

    def enrich(self, client, lot):
        """Название лота бывает общим («Закупка для школы»), а баннер стоит одной из позиций —
        поэтому в поиск идут все позиции, их свойства и описания."""
        data = client.get_json(f"{API}/GetTrade/{lot.lot_id}/0", ORIGIN)
        texts = []
        for item in _positions(data.get("budget_products")) + _positions(data.get("products")):
            texts += [item.get("Product_Name"), item.get("Description")]
            texts += [prop.get("User_Value") for prop in item.get("Js_Properties") or []]
        texts += [data.get("addon_description"), data.get("technical_description"), data.get("description")]
        lot.details = "\n".join(str(text) for text in texts if text)
        return lot
