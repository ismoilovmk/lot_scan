# Reklama Master — lot scanner

Context for Claude Code. Read this first; `README.md` (in Russian) has the user-facing details.

## What this is

A bot that scans Uzbekistan procurement platforms and sends matching lots to Telegram.
It is built for a family business, "Reklama Master and Co" (Fergana): outdoor advertising and printing —
banners, oracal film, 3D letters, signs, UV print, DTF print on clothes, flyers, business cards.
A second direction, freight transport, goes to its own Telegram group.

- Regions: Fergana region is the priority (marked 🟢 in messages); Tashkent city and region are secondary.
- The people reading the messages are not programmers. Talk to the user in the language they write in
  and avoid jargon. Code comments, commit messages, log lines and Telegram texts are in Russian.

## How it runs in production

It runs on GitHub Actions, not on anyone's computer: `.github/workflows/scan.yml`.

- Every check ends by starting the next one (`workflow_dispatch` with `auto=true`). That run first waits
  (`python main.py wait`), then scans. GitHub's own cron fires only about twice a day here, so it is just a backup
  that restarts the chain.
- Checks run every 20 minutes, 07:00–20:59 Tashkent time (`work_hours` in `config.yaml`).
- The database of seen lots (`lots.db`) lives in the orphan branch `state`, one force-pushed commit.
- Secrets `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_CHAT_ID_TRANSPORT` are GitHub Actions secrets.
  The repository is public: never commit a token or a chat ID, and never paste them into a chat.

## Rules that are easy to break

1. **Do not run `python main.py run` or `loop` without `--dry-run` on your computer** while GitHub is running.
   A local run has its own `lots.db`, so every lot would arrive in the Telegram groups a second time.
   `--dry-run` prints lots to the screen, sends nothing and remembers nothing. It needs no `.env`.
2. Changes go test-first: write the failing test, see it fail, make it pass. Then `sh quality.sh crap`,
   `sh quality.sh dry`, `sh quality.sh mutate` — CRAP below 10, no duplication, no surviving mutants.
3. Small commits that say why, what changed and how it was proved (see `git log`). Pushing to `main` runs the
   tests on GitHub and the next scheduled check picks the new code up by itself.
4. Be gentle with the sites: keep the pauses in `config.yaml`, do not hammer them while exploring.

## The `.env` file

`.env` sits in the project root next to `main.py`. Git ignores it, so it is never in the repository and a fresh
clone does not have one. It holds `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (advertising group) and
`TELEGRAM_CHAT_ID_TRANSPORT` (freight group); `.env.example` shows the format. The same values are stored on
GitHub as Actions secrets, which cannot be read back.

- **You do not need `.env` for development.** Tests, `--dry-run` passes and exploring sites read no Telegram
  settings. If a command stops with "Не заданы TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID", add `--dry-run` instead of
  asking for the file.
- Only `run`, `loop`, `test` and `prices` without `--dry-run`, and `chatid`, need the token.
- If the owner did share `.env` with this computer, rule 1 below still holds: a real run from here duplicates
  every lot in both groups. A real run from a second computer is right only after the owner has decided to move
  the bot there and the GitHub schedule has been switched off.
- Do not print the token, copy it into another file, or commit it. Do not ask the user to paste it into the chat.
  If it leaks: @BotFather → `/revoke`, then update the GitHub secret and every `.env`.

## Layout

| File | Role |
|---|---|
| `main.py` | CLI and the pass over platforms: `run`, `loop`, `wait`, `prices`, `chatid`, `test` |
| `filters.py` | text normalisation, service matching, regions, duplicate fingerprint |
| `storage.py` | SQLite: seen/sent lots, notes between runs |
| `notifier.py` | message text and Telegram sending |
| `health.py` | "platform stopped answering" alert and the daily summary |
| `http_client.py` | requests with per-host pauses and retries |
| `sources/` | one module per platform; `sources/__init__.py` lists them in `ALL_SOURCES` |
| `config.yaml` | services and their words, regions, work hours, which platforms are on |
| `tests/` | pytest; `tests/fakes.py` has fake site, source and notifier |

Setup: Python 3.10 or newer, `pip install -r requirements-dev.txt`, `python -m pytest -q`.

## How matching works

- A lot matches when any word of any service in `config.yaml` → `services` is found in its title, positions or
  description. Categories are deliberately ignored: customers file lots under anything.
- Words are substrings after normalisation (case, Uzbek letters ў қ ғ ҳ, apostrophes, Cyrillic/Latin lookalikes).
  Write both Cyrillic and Latin spellings. A rule `a + b` needs both parts.
- `tests/test_vocabulary.py` holds real catalogue names that must match and look-alikes that must not.
  The firm's own list of 18 services is there as `OWN_SERVICES`. New words come with new test lines.
- `service_chats` sends a service to another Telegram group (freight transport does this).
- After words or regions change, the bot re-checks open lots it had rejected. Sent lots are never repeated.

## Adding a platform

Subclass `Source` in `sources/base.py`: `list_lots` yields `Lot` objects from the open list, `enrich` loads details
for lots that passed the region filter. Find the site's JSON API in the browser's network tab, test it with
`FakeClient` from `tests/fakes.py`, add it to `ALL_SOURCES` and to `sources:` in `config.yaml`, then check it with
`python main.py run --dry-run --source <key>`.

## What is scanned now

- etender.uzex.uz — tenders, best-offer selection, civil contracts
- xarid.uzex.uz — reduction auction (Auksion), best-offer selection under Resolution 69
- xt-xarid.uz — auction, selection, request for proposals, tender
- tendergpt.uz — purchases of private companies
- ebirja.uz — auction, local auction, selection, tender, request for proposals
- Milliy do'kon on xarid.uzex.uz (`ShopLots` in `sources/uzex_shop.py`) — trades on supplier offers. The shop has
  no public list of trades, so the bot finds offers by `shop_keywords` and reads each offer's trades, one part of
  the offers per pass, chosen by the clock. The owner's father says most of the relevant lots are here.
- Elektron do'kon on xarid.uzex.uz (`EShopLots`, key `uzex_eshop`) — the same shop without the local-manufacturer
  filter: a separate set of offers, same trades and the same trade page. It has its own part per pass.
- new.cooperation.uz — e-catalog price requests to local manufacturers (`sources/cooperation.py`). It opens only
  from an Uzbek IP, so it is off in `config.yaml` and GitHub does not scan it. From a computer in Uzbekistan run
  `python main.py loop --source cooperation_catalog`: that checks only this platform, so nothing arrives twice.

## Open work that needs an Uzbek IP address

GitHub's servers are abroad, where these do not open (the connection times out). On 2026-11-11 all of them were
confirmed to open from a computer in Uzbekistan.

| Target | What it is | Known so far |
|---|---|---|
| `new.cooperation.uz` other sections | auction, local auction, request for proposals, tender, selection | APIs `cabinet.cooperation.uz/api/{auction,local-auction,bid-flow}/public/lots`, `/api/{tender,selection}/public`; almost empty when checked |
| `xarid-api-auctionx.uzex.uz` | xarid.uzex.uz → Mahalliy auksion (`/new-auction/list`) | list: `/api/Lot/GetList`; 1 open lot when checked |
| `xarid-api-prequest.uzex.uz` | xarid.uzex.uz → Taklif so'rovi (`/request-proposal/3/list`) | list: `/api/Public/GetLots`; ~1000 open lots with customer and price — the most useful next source |
| `new-xarid.uzex.uz` | beta front-end of xarid | uses the same APIs as xarid.uzex.uz; nothing new to scan |
| `api.xt-xarid.uz` | already scanned | from Uzbekistan 3 requests 3 s apart all succeeded; on GitHub `host_pauses` must stay 65 |

Not explored for other reasons: tender pages of banks (nbu.uz and others).

Looked at on 2026-11-12 and left out on purpose: To'g'ridan-to'g'ri elektron shartnoma and Davlat xaridlari are
registries of contracts already signed (the supplier is named); Hadli kelishuv and Master-plan on etender had
0 lots; IMI-XDMI has 276 purchases with no region; Reja jadval is purchase plans, not lots (2 million rows) —
it could serve as an early signal if the owner asks for it.

A source that works only from Uzbekistan cannot run on GitHub: keep it `false` in `config.yaml` and run it from
Uzbekistan with `--source`, as `cooperation_catalog` does. On 2026-11-11 the whole bot ran from a laptop in
Uzbekistan for a day; on 2026-11-12 the owner moved it back to GitHub and that laptop's database became the
`state` branch. Moving the whole bot again is the owner's decision (Muhammadbilol): the scheduler, the `state`
database and the secrets have to move together, otherwise lots arrive twice.
