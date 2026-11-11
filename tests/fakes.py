"""Подмены сайта, площадки и Telegram для тестов."""
from sources.base import Lot, Source


class FakeClient:
    """Вместо HttpClient: отвечает через handler(method, url, body)."""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def post_json(self, url, origin, body):
        self.calls.append(("POST", url, body))
        return self.handler("POST", url, body)

    def get_json(self, url, origin):
        self.calls.append(("GET", url, None))
        return self.handler("GET", url, None)


def uzex_list(rows, reject_above=None, silent_cap=None):
    """Ведёт себя как списки UzEX: строки from..to включительно, total_count в каждой строке.

    reject_above — сервер падает, если просят больше строк (как аукцион при 50).
    silent_cap — сервер молча отдаёт не больше стольких строк (как Milliy do'kon, 12).
    """

    def handler(method, url, body):
        start, end = body["from"], body["to"]
        if reject_above is not None and end - start + 1 > reject_above:
            raise RuntimeError("HTTP 500")
        if silent_cap is not None:
            end = min(end, start + silent_cap - 1)
        page = rows[start - 1:end]
        return [{**row, "rn": start + i, "total_count": len(rows)} for i, row in enumerate(page)]

    return handler


def make_lot(lot_id="1", title="Изготовление баннера", region="Ферганская область",
             deadline="2999-01-01T00:00:00", source="fake", **extra) -> Lot:
    return Lot(source=source, source_title="Тестовая площадка", lot_id=lot_id, title=title,
               region=region, deadline=deadline, url=f"https://example.test/lot/{lot_id}", **extra)


class FakeSource(Source):
    title = "Тестовая площадка"

    def __init__(self, lots, key="fake", details=None, broken_ids=(), fail_listing=False):
        self.key = key
        self.lots = lots
        self.details = details or {}      # lot_id -> текст, который появляется после enrich
        self.broken_ids = set(broken_ids)  # для этих лотов подробности не грузятся
        self.fail_listing = fail_listing
        self.enriched = []

    def list_lots(self, client, cfg):
        if self.fail_listing:
            raise RuntimeError("сайт недоступен")
        # каждый проход — свежие объекты, как при новом запросе к сайту
        return iter([Lot(**vars(lot)) for lot in self.lots])

    def enrich(self, client, lot):
        if lot.lot_id in self.broken_ids:
            raise RuntimeError("HTTP 500")
        self.enriched.append(lot.lot_id)
        lot.details = self.details.get(lot.lot_id, lot.details)
        return lot


class FakeNotifier:
    def __init__(self, fail=False):
        self.sent = []
        self.chats = []
        self.fail = fail

    def send(self, text, chat=""):
        if self.fail:
            raise RuntimeError("Telegram недоступен")
        self.sent.append(text)
        self.chats.append(chat)       # в какой чат ушло; пусто — в основной
