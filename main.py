"""Бот: просматривает закупочные площадки и присылает лоты по рекламе в Telegram.

  python main.py run --dry-run   пробный проход, сообщения печатаются на экран
  python main.py run             один проход с отправкой в Telegram
  python main.py loop            проверять постоянно, каждые interval_minutes минут
  python main.py prices          отчёт по ценам конкурентов в Milliy do'kon
  python main.py chatid          показать ID чатов, из которых писали боту
  python main.py test            отправить проверочное сообщение в Telegram
  python main.py wait            подождать до следующей проверки (для цепочки запусков на GitHub)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml

import health
from filters import LotFilter, fingerprint, vocabulary_signature
from http_client import HttpClient
from notifier import ConsoleNotifier, TelegramNotifier, find_chats, format_lot
from sources import ALL_SOURCES
from sources.base import TASHKENT
from sources.uzex_shop import price_report
from storage import Storage

ROOT = Path(__file__).resolve().parent
log = logging.getLogger("bot")


def load_env(path: Path) -> None:
    """Читает строки KEY=VALUE из .env в переменные окружения."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def tashkent_now() -> datetime:
    """Текущее время в Ташкенте без часового пояса — в таком виде сроки отдают площадки."""
    return datetime.now(TASHKENT).replace(tzinfo=None)


def is_expired(deadline: str, now: datetime) -> bool:
    try:
        end = datetime.fromisoformat(deadline)
    except (TypeError, ValueError):
        return False
    return end < now


def make_client(cfg: dict) -> HttpClient:
    return HttpClient(pause=float(cfg.get("request_pause_seconds", 0.5)),
                      host_pauses=cfg.get("host_pauses") or {})


def scan_source(source, client, cfg, lot_filter, storage, notifier, dry_run: bool) -> dict:
    stats = {"listed": 0, "new": 0, "in_region": 0, "sent": 0}
    now = tashkent_now()
    for lot in source.list_lots(client, cfg):
        stats["listed"] += 1
        if is_expired(lot.deadline, now) or storage.is_seen(lot.source, lot.lot_id):
            continue
        stats["new"] += 1
        if not lot_filter.region_ok(lot.region):
            if not dry_run:
                storage.mark(lot.source, lot.lot_id, False, lot.title)
            continue
        stats["in_region"] += 1
        try:
            lot = source.enrich(client, lot)
        except RuntimeError as exc:
            log.warning("Лот %s %s: подробности не получены (%s), попробую в следующий раз", lot.source, lot.lot_id, exc)
            continue
        services = lot_filter.match(lot.search_text())
        text = format_lot(lot, services, lot_filter.priority(lot.region))
        sent = bool(services) and deliver(lot, text, storage, notifier, now)
        stats["sent"] += sent
        if not dry_run:
            storage.mark(lot.source, lot.lot_id, sent, lot.title, fingerprint(lot), lot.deadline)
    return stats


def deliver(lot, text: str, storage, notifier, now: datetime) -> bool:
    """Отправляет сообщение о лоте, если такой же ещё не отправлялся. True — отправлен."""
    if storage.is_duplicate(fingerprint(lot), now.isoformat(timespec="seconds")):
        log.info("Лот %s %s: такой же уже отправлен, пропускаю", lot.source, lot.lot_id)
        return False
    notifier.send(text)  # при ошибке лот не помечается и уйдёт в следующий раз
    return True


def chosen_sources(cfg: dict, only: str | None) -> list:
    """Площадки для прохода: одна названная (даже выключенная) или все включённые в config.yaml."""
    enabled = cfg.get("sources") or {}
    return [s for s in ALL_SOURCES if (s.key == only if only else enabled.get(s.key, False))]


def check_source(source, client, cfg, lot_filter, storage, notifier, dry_run: bool) -> bool:
    """Проход по одной площадке. False — проверить не удалось."""
    try:
        stats = scan_source(source, client, cfg, lot_filter, storage, notifier, dry_run)
    except Exception:
        log.exception("%s: проход прерван из-за ошибки", source.key)
        return False
    log.info(
        "%s: в списке %s, новых %s, в нужном регионе %s, отправлено %s",
        source.key, stats["listed"], stats["new"], stats["in_region"], stats["sent"],
    )
    return True


def run_once(cfg: dict, notifier, dry_run: bool, only: str | None = None) -> list[str]:
    """Один проход по площадкам. Возвращает ключи площадок, которые проверить не удалось."""
    client = make_client(cfg)
    lot_filter = LotFilter(cfg)
    storage = Storage(str(ROOT / "lots.db"), tashkent_now)
    sources = chosen_sources(cfg, only)
    try:
        if not dry_run and storage.adopt_vocabulary(vocabulary_signature(cfg)):
            log.info("Слова или регионы изменились: открытые лоты, которые раньше не подошли, проверяю заново")
        failed = [source.key for source in sources
                  if not check_source(source, client, cfg, lot_filter, storage, notifier, dry_run)]
        if not dry_run:
            titles = {source.key: source.title for source in ALL_SOURCES}
            health.report(storage, notifier, tashkent_now(), titles, [source.key for source in sources], failed,
                          cfg.get("daily_summary_hour"))
    finally:
        storage.close()
    return failed


def make_notifier(dry_run: bool):
    if dry_run:
        return ConsoleNotifier()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        sys.exit("Не заданы TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в файле .env. Для пробы без Telegram добавьте --dry-run.")
    return TelegramNotifier(token, chat_id)


def show_chats() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("Сначала впишите TELEGRAM_BOT_TOKEN в файл .env.")
    try:
        chats = find_chats(token)
    except RuntimeError as exc:
        sys.exit(str(exc))
    if not chats:
        sys.exit("Боту пока никто не писал. Отправьте ему /start (или добавьте в группу и напишите там) и повторите.")
    print("Чаты, из которых писали боту. Нужный ID впишите в .env как TELEGRAM_CHAT_ID:")
    for chat_id, name in chats:
        print(f"  {chat_id}   {name}")


def send_test_message(notifier) -> None:
    try:
        notifier.send("Проверка связи: бот Reklama Master подключён и может присылать лоты.")
    except RuntimeError as exc:
        sys.exit(
            f"{exc}\n"
            "Проверьте TELEGRAM_CHAT_ID в .env: команда «python main.py chatid» покажет чаты, "
            "из которых писали боту. Бот не может писать туда, где ему не нажали «Старт» "
            "и куда его не добавили."
        )
    print("Сообщение отправлено — проверьте Telegram.")


def setup_logging(path: Path) -> None:
    """Журнал работы: на экран и в файл."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(path, encoding="utf-8")],
        force=True,
    )


MAX_WAIT = 5 * 3600  # задание на GitHub живёт не дольше шести часов, поэтому ночь пережидаем по частям


def work_hours(cfg: dict) -> tuple[int, int]:
    """Первый и последний час суток (по Ташкенту), когда бот проверяет площадки сам."""
    first, last = cfg.get("work_hours") or (0, 23)
    return int(first), int(last)


def in_work_hours(now: datetime, cfg: dict) -> bool:
    first, last = work_hours(cfg)
    return first <= now.hour <= last


def next_check(previous: datetime, now: datetime, cfg: dict) -> datetime:
    """Когда пора делать следующую проверку: через интервал после начала прошлой, но в рабочие часы."""
    due = max(previous + timedelta(minutes=int(cfg.get("interval_minutes", 20))), now)
    if in_work_hours(due, cfg):
        return due
    morning = due.replace(hour=work_hours(cfg)[0], minute=0, second=0, microsecond=0)
    # утро того же дня, а если оно уже прошло — следующего: разность «утро − срок» тогда равна −1 дню
    return morning - timedelta(days=(morning - due).days)


def wait_for_next_check(cfg: dict, since: str) -> None:
    """Спит до следующей проверки. since — когда началась прошлая, в секундах эпохи; пусто — только что."""
    now = tashkent_now()
    previous = datetime.fromtimestamp(int(since), TASHKENT).replace(tzinfo=None) if since else now
    due = next_check(previous, now, cfg)
    seconds = min(int((due - now).total_seconds()), MAX_WAIT)
    log.info("Следующая проверка в %s, жду %s мин", due.strftime("%d.%m %H:%M"), seconds // 60)
    time.sleep(seconds)


def run_command(cfg: dict, notifier, args) -> None:
    if args.work_hours_only and not in_work_hours(tashkent_now(), cfg):
        log.info("Нерабочие часы: проверку пропускаю")
        return
    failed = run_once(cfg, notifier, args.dry_run, args.source)
    if failed:  # ненулевой код выхода: планировщик на сервере увидит неполный проход
        sys.exit(f"Не удалось проверить площадки: {', '.join(failed)}")


def loop_command(cfg: dict, notifier, args) -> None:
    interval = int(cfg.get("interval_minutes", 20)) * 60
    while True:
        run_once(cfg, notifier, args.dry_run, args.source)
        log.info("Следующая проверка через %s мин", interval // 60)
        time.sleep(interval)


# Команды, которым нужен Telegram (или экран при --dry-run)
COMMANDS = {
    "run": run_command,
    "loop": loop_command,
    "test": lambda cfg, notifier, args: send_test_message(notifier),
    "prices": lambda cfg, notifier, args: notifier.send(price_report(make_client(cfg), cfg.get("shop_keywords") or [])),
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Сканер тендеров на наружную рекламу")
    parser.add_argument("command", choices=[*COMMANDS, "chatid", "wait"])
    parser.add_argument("--dry-run", action="store_true", help="печатать на экран, ничего не отправлять и не запоминать")
    parser.add_argument("--source", help="проверить только одну площадку, например uzex_etender")
    parser.add_argument("--work-hours-only", action="store_true", help="run: вне рабочих часов ничего не проверять")
    parser.add_argument("--since", default="", help="wait: когда началась прошлая проверка, секунды эпохи")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    setup_logging(ROOT / "bot.log")
    load_env(ROOT / ".env")
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    if args.command == "chatid":
        show_chats()
    elif args.command == "wait":
        wait_for_next_check(cfg, args.since)
    else:
        COMMANDS[args.command](cfg, make_notifier(args.dry_run), args)


if __name__ == "__main__":
    main()
