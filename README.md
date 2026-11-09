# Reklama Master — сканер тендеров

Бот просматривает закупочные площадки Узбекистана и присылает в Telegram лоты
по наружной рекламе и печати (баннер, оракал, объёмные буквы, UV-печать).

## Что проверяется сейчас
- etender.uzex.uz — тендеры и отборы
- xarid.uzex.uz — аукцион на понижение
- xarid.uzex.uz — отбор наилучших предложений (69-ПКМ)

## Настройка Telegram
1. В Telegram напишите @BotFather, команда `/newbot`, получите токен.
2. Откройте файл `.env` и впишите токен после `TELEGRAM_BOT_TOKEN=`.
3. Напишите своему новому боту `/start` (или добавьте его в группу и напишите там).
4. Выполните `python main.py chatid` — покажет ID чата. Впишите его после `TELEGRAM_CHAT_ID=`.
5. Выполните `python main.py test` — в Telegram должно прийти проверочное сообщение.

## Запуск
```
python main.py run --dry-run    пробный проход: печатает на экран, ничего не шлёт и не запоминает
python main.py run              один проход с отправкой в Telegram
python main.py loop             работать постоянно (интервал в config.yaml)
python main.py prices           цены конкурентов в Milliy do'kon
```
Ключевые слова и регионы меняются в `config.yaml`.
Уже отправленные лоты хранятся в `lots.db`; если удалить файл, бот пришлёт всё заново.

## Работа по расписанию на GitHub
Файл `.github/workflows/scan.yml` запускает `python main.py run` каждые 30 минут
с 08:00 до 19:30 по Ташкенту.

1. В репозитории: Settings → Secrets and variables → Actions → New repository secret.
   Добавьте два секрета: `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID` (значения из `.env`).
2. Вкладка Actions → «Скан лотов» → Run workflow — запуск вручную, можно с галочкой пробного прохода.

Если проход не смог проверить какую-то площадку, запуск помечается красным и GitHub присылает письмо.
Пока бот работает на GitHub, не запускайте `python main.py loop` на компьютере: базы у них разные,
и лоты придут дважды.

## Проверка кода
```
pip install -r requirements-dev.txt
python -m pytest -q
sh quality.sh crap      # CRAP каждой функции ниже 10
sh quality.sh dry       # дублирование
sh quality.sh mutate    # мутационные тесты
```
