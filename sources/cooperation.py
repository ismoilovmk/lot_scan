"""new.cooperation.uz — электронный каталог: запросы цен местным производителям.

Открывается только с узбекского адреса. Остальные разделы портала (аукцион, тендер, отбор,
запрос предложений) почти пустые, поэтому читается только этот.

В открытом списке есть название товара, количество и срок. Заказчика, региона и цены нет,
поэтому лоты отсюда приходят с пометкой «регион не указан» (нужно allow_unknown_region: true).
Ссылка в сообщении ведёт на оферту, по которой запрошена цена: там цена за единицу и поставщик.
"""
from __future__ import annotations

from .base import Lot, Source

ORIGIN = "https://new.cooperation.uz"
API = f"{ORIGIN}/ocelot/api-shop/LotRequest/GetLotsInTrade"
PAGE = 500


def _amount(quantity, measure) -> str:
    """107, 'кв. метр' -> '107 кв. метр'; дробное количество остаётся дробным."""
    if quantity is None:
        return ""
    number = f"{quantity:g}" if isinstance(quantity, float) else str(quantity)
    return " ".join(part for part in (number, (measure or "").strip()) if part)


class CooperationCatalog(Source):
    key = "cooperation_catalog"
    title = "Cooperation (электронный каталог)"

    def list_lots(self, client, cfg):
        skip, count = 0, 1
        while skip < count:
            reply = client.get_json(f"{API}?skip={skip}&take={PAGE}", ORIGIN)
            if reply.get("statusCode") != 200 or not reply.get("result"):
                reason = reply.get("error") or reply.get("statusCode")
                raise RuntimeError(f"cooperation.uz: {reason}")
            rows, count = reply["result"]["result"], reply["result"]["count"]
            if not rows:
                return  # сайт обещал больше строк, чем отдал: не ждём их вечно
            for row in rows:
                yield self._lot(row)
            skip += len(rows)  # сайт может отдать меньше строк, чем просили

    def _lot(self, row: dict) -> Lot:
        name = (row.get("productName") or "").strip()
        amount = _amount(row.get("quantity"), row.get("measureName"))
        # Количество в названии: без заказчика и цены одинаковые товары иначе считались бы одним лотом
        return Lot(
            source=self.key,
            source_title=self.title,
            lot_id=row["lotNumber"],
            number=row["lotNumber"],
            title=f"{name} — {amount}" if amount else name,
            deadline=(row.get("endDate") or "")[:19],
            url=_url(row.get("offerNumber")),
        )


def _url(offer: str | None) -> str:
    """Страница оферты, по которой заказчик запросил цену: товар, цена за единицу, поставщик, описание.

    Своей страницы у запроса нет. В адресе сайт ждёт раздел каталога, но не проверяет его, поэтому 0.
    """
    offer = (offer or "").strip()
    return f"{ORIGIN}/e-catalog/0/{offer}" if offer else f"{ORIGIN}/active-trades?tab=eCatalog"
