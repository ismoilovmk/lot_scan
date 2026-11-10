"""Служебные сообщения: площадка перестала отвечать и итог дня.

Без них молчание бота не отличить от поломки.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

log = logging.getLogger("bot")

ALERT_AFTER = 3  # столько сбоев подряд — и бот пишет о площадке; один сбой бывает у любого сайта


def review(streaks: dict[str, int], titles: dict[str, str], checked: list[str],
           failed: list[str]) -> tuple[dict[str, int], list[str]]:
    """По итогам прохода обновляет счёт сбоев подряд. Возвращает (новый счёт, сообщения)."""
    streaks, messages = dict(streaks), []
    for key in checked:
        before = streaks.pop(key, 0)
        if key in failed:
            streaks[key] = before + 1
            if streaks[key] == ALERT_AFTER:
                messages.append(f"⚠️ {titles[key]} не отвечает уже {ALERT_AFTER} проверки подряд. "
                                "Лоты с неё пока не приходят.")
        elif before >= ALERT_AFTER:
            messages.append(f"✅ {titles[key]} снова отвечает.")
    return streaks, messages


def summary(now: datetime, seen: int, sent: int, failing: list[str]) -> str:
    state = f"Сбой при последней проверке: {', '.join(failing)}." if failing else "Все площадки отвечают."
    return f"📊 Итог дня {now:%d.%m}: новых лотов просмотрено — {seen}, отправлено — {sent}. {state}"


def report(storage, notifier, now: datetime, titles: dict[str, str], checked: list[str], failed: list[str],
           summary_hour: int | None) -> None:
    """Шлёт служебные сообщения после прохода. Запоминает их только если они дошли."""
    before = json.loads(storage.note("failures") or "{}")
    streaks, alerts = review(before, titles, checked, failed)
    day = now.date().isoformat()
    due = summary_hour is not None and now.hour >= summary_hour and storage.note("summary_day") != day
    messages = [summary(now, *storage.day_counts(day), [titles[key] for key in streaks])] if due else []
    try:
        for text in messages + alerts:
            notifier.send(text)
    except RuntimeError as exc:
        log.warning("Служебное сообщение не отправлено (%s), повторю при следующей проверке", exc)
        return
    storage.write_note("failures", json.dumps(streaks))
    if due:
        storage.write_note("summary_day", day)
