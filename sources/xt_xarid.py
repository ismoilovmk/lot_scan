"""xt-xarid.uz (Hayot Birja) — аукционы, отборы, запросы предложений и тендеры.

Название, заказчик, регион и позиции приходят прямо в списке, поэтому отдельные
запросы по каждому лоту не нужны. Из-за рубежа сайт даёт один запрос в 60 секунд —
пауза задаётся в config.yaml (host_pauses).
"""
from __future__ import annotations

from datetime import datetime

from .base import TASHKENT, Lot, Source, join_region

ORIGIN = "https://xt-xarid.uz"
API = "https://api.xt-xarid.uz/rpc"
PAGE = 100
FIELDS = ["id", "name", "status", "close_at", "currency", "area", "meta"]
COUNTRY = "Республика Узбекистан"

# справочник, название раздела, статус «идёт приём заявок», поле с ценой
PROCEDURES = [
    ("ref_reduction_object_public", "аукцион", "publicated", "start_price"),
    ("ref_selection_public", "отбор", "open", "totalcost"),
    ("ref_request_proposals_public", "запрос предложений", "open", "totalcost"),
    ("ref_tender_public", "тендер", "open", "totalcost"),
]


def _deadline(value: str | None) -> str:
    """Срок сайта -> ташкентское время. Сайт отдаёт либо UTC с буквой Z, либо только день."""
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if moment.tzinfo is None:
        return value if "T" in value else f"{value}T23:59:59"  # только день — открыт до его конца
    return moment.astimezone(TASHKENT).replace(tzinfo=None).isoformat(timespec="seconds")


def _goods(meta: dict) -> tuple[str, str]:
    """Возвращает (названия позиций через '; ', описания и переводы одним текстом)."""
    names, texts = [], []
    for good in meta.get("good_maps") or []:
        name = (good.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
        texts.append(good.get("desc"))
        texts.extend((good.get("translate_name") or {}).values())
    return "; ".join(names), "\n".join(text for text in texts if text)


class XtXarid(Source):
    key = "xt_xarid"
    title = "XT-Xarid"

    def list_lots(self, client, cfg):
        regions = cfg.get("xt_xarid_regions") or []
        for ref, kind, status, price_field in PROCEDURES:
            filters = {"status": [status]}
            if regions:
                filters["delivery_regions"] = regions
            for row in self._rows(client, ref, filters, FIELDS + [price_field]):
                yield self._lot(row, kind, price_field)

    def _rows(self, client, ref: str, filters: dict, fields: list[str]):
        offset = 0
        while True:
            params = {"ref": ref, "op": "read", "limit": PAGE, "offset": offset, "filters": filters, "fields": fields}
            reply = client.post_json(API, ORIGIN, {"id": 1, "jsonrpc": "2.0", "method": "ref", "params": params})
            if "error" in reply:
                raise RuntimeError(f"xt-xarid.uz: {reply['error'].get('message')}")
            rows = reply["result"]
            yield from rows
            if len(rows) < PAGE:
                return
            offset += PAGE

    def _lot(self, row: dict, kind: str, price_field: str) -> Lot:
        meta = row.get("meta") or {}
        goods, texts = _goods(meta)
        name = (row.get("name") or "").strip()
        areas = [area.get("name") for area in meta.get("area_path") or []]
        return Lot(
            source=self.key,
            source_title=f"{self.title} ({kind})",
            lot_id=str(row["id"]),
            number=str(row["id"]),
            title=" — ".join(dict.fromkeys(part for part in (name, goods) if part))[:300],
            customer=(meta.get("company_name") or "").strip(),
            region=join_region(*(area for area in areas if area != COUNTRY)),
            price=row.get(price_field),
            currency=row.get("currency") or "UZS",
            deadline=_deadline(row.get("close_at")),
            url=f"{ORIGIN}/procedure/{row['id']}/core",
            details=texts,
        )
