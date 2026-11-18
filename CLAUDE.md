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

Since 2026-11-18 it runs on a VPS in Tashkent (the brother's server, Teleport DC), not on GitHub Actions.

- Service `lot-scan.service` (systemd, user `dismoilov`) runs `python main.py loop` in `/home/dismoilov/lot_scan`
  with Python 3.12 from `.venv` (installed with `uv`; the system Python there is 3.8). It restarts by itself
  after a crash or a reboot.
- `loop` checks every 20 minutes, 07:00–20:59 Tashkent time (`work_hours` in `config.yaml`) and sleeps at night.
- The database of seen lots is the file `lots.db` in that folder; `.env` with the token is next to it (mode 600).
- SSH from the owner's computer: `ssh uz_vps` (entry in `~/.ssh/config`). Another project of the brother
  ("Bedana shop", `bedana.service`, Caddy) lives on the same server: do not touch it.
- **New code does not reach the bot by itself.** After pushing to `main`:
  `ssh uz_vps 'cd ~/lot_scan && git pull && sudo systemctl restart lot-scan'`.
  Log: `ssh uz_vps 'journalctl -u lot-scan -n 50 -o cat'`.
- The GitHub workflow `.github/workflows/scan.yml` («Скан лотов») is disabled and must stay disabled while the
  server runs: both together would send every lot twice. The branch `state` holds the database as it was at the
  move (2026-11-17) and is no longer updated. To go back to GitHub: stop the service, push the server's
  `lots.db` to `state`, enable the workflow.
- The repository is public: never commit a token or a chat ID, and never paste them into a chat.

## Rules that are easy to break

1. **Do not run `python main.py run` or `loop` without `--dry-run` on your computer** while the server is running.
   A local run has its own `lots.db`, so every lot would arrive in the Telegram groups a second time.
   `--dry-run` prints lots to the screen, sends nothing and remembers nothing. It needs no `.env`.
2. Changes go test-first: write the failing test, see it fail, make it pass. Then `sh quality.sh crap`,
   `sh quality.sh dry`, `sh quality.sh mutate` — CRAP below 10, no duplication, no surviving mutants.
3. Small commits that say why, what changed and how it was proved (see `git log`). Pushing to `main` runs the
   tests on GitHub; then update the server (see above).
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
| `http_client.py` | requests with per-host pauses, retries and per-host proxies |
| `bridge.py` | finds the live bridge port (see "The bridge for new.cooperation.uz") |
| `tools/most.bat` | run on a Windows computer in Uzbekistan to be the bridge |
| `sources/` | one module per platform; `sources/__init__.py` lists them in `ALL_SOURCES` |
| `config.yaml` | services and their words, regions, work hours, which platforms are on |
| `tests/` | pytest; `tests/fakes.py` has fake site, source and notifier |

Setup: Python 3.10 or newer, `pip install -r requirements-dev.txt`, `python -m pytest -q`.

## How matching works

- `LotFilter.match(title, details)`: a word of any service in `config.yaml` → `services` found in the title
  (lot name or position names) is enough. A word found only in the description counts when at least two
  different services are found in the whole text: one word in a long description is usually incidental
  ("халат с логотипом", "перевозка грузов прицепом" for a cultivator). This rule came from reviewing all
  113 lots sent on 2026-11-09…18. Categories are deliberately ignored: customers file lots under anything.
- Words match at the start of a word, after normalisation (case, Uzbek letters ў қ ғ ҳ, apostrophes,
  Cyrillic/Latin lookalikes): «orakal» is not found inside «Qorakaltak». Write both Cyrillic and Latin
  spellings. A rule `a + b` needs both parts.
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
- xarid.uzex.uz — request for proposals (Taklif so'rovi) and local auction (Mahalliy auksion), `sources/uzex_local.py`.
  They open only from Uzbekistan, which the server provides. Taklif so'rovi has no region field: the region is
  read from the customer's address with street names removed (a street called «Тошкент кўчаси» is not Tashkent).
- xt-xarid.uz — auction, selection, request for proposals, tender
- tendergpt.uz — purchases of private companies
- ebirja.uz — auction, local auction, selection, tender, request for proposals
- Milliy do'kon on xarid.uzex.uz (`ShopLots` in `sources/uzex_shop.py`) — trades on supplier offers. The shop has
  no public list of trades, so the bot finds offers by `shop_keywords` and reads each offer's trades, one part of
  the offers per pass, chosen by the clock. The owner's father says most of the relevant lots are here.
- Elektron do'kon on xarid.uzex.uz (`EShopLots`, key `uzex_eshop`) — the same shop without the local-manufacturer
  filter: a separate set of offers, same trades and the same trade page. It has its own part per pass.
- new.cooperation.uz (the former cooperation.uz) — e-catalog price requests to local manufacturers
  (`sources/cooperation.py`). It is scanned only through the bridge, see below.

## The bridge for new.cooperation.uz

The portal silently drops connections from data-centre addresses: from abroad, and from the VPS in Tashkent too
(checked 2026-11-18: every app host on 185.100.53.216/.244 times out, a neighbour address in the same network
answers; MaxMind places the VPS address in Kazakhstan). From ordinary home or office internet in Uzbekistan it
opens (the brother's laptop, 2026-11-11). No other public host of the portal serves the price requests.

So the bot reaches it through a bridge: a Windows computer in Uzbekistan runs `tools/most.bat`
(`ssh -N -R <port> uz_vps`, remote dynamic forwarding), which opens a SOCKS5 port on the server's localhost
that exits through that computer. `bridge.py` finds the live port (`bridge.ports` in `config.yaml`, it sends a
SOCKS greeting because a dead tunnel's port can stay open), `main.bridged` routes `bridge.hosts` through it and,
while no bridge answers, switches `bridge.sources` off for that pass — a skip, not a failure, so no alert.
`--source cooperation_catalog` still runs directly, for a computer that is itself in Uzbekistan.

- Verified 2026-11-18 with a test bridge from the owner's computer in Korea: the server's requests left through
  it. Not verified: the last hop to the portal — nobody has run the bridge from Uzbekistan yet.
- Do not run `python main.py loop --source cooperation_catalog` on a second computer while the bridge is used:
  that is a second bot with its own database, and lots would arrive twice.
- A cleaner fix would be a server address the portal accepts (ask Teleport DC for another address, or wait for
  the geolocation databases to catch up); then the bridge section can simply be removed from `config.yaml`.

## Open work that needs an Uzbek IP address

GitHub's servers are abroad, where these do not open (the connection times out). On 2026-11-11 all of them were
confirmed to open from a computer in Uzbekistan.

| Target | What it is | Known so far |
|---|---|---|
| `new.cooperation.uz` other sections | auction, local auction, request for proposals, tender, selection | APIs `cabinet.cooperation.uz/api/{auction,local-auction,bid-flow}/public/lots`, `/api/{tender,selection}/public`; almost empty when checked |
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
`state` branch; on 2026-11-18 he moved it to the VPS (see "How it runs in production"). Moving the whole bot
again is the owner's decision (Muhammadbilol): the scheduler, the database and the secrets have to move together,
otherwise lots arrive twice.

Checked from the VPS on 2026-11-17: `xarid-api-prequest.uzex.uz` and `xarid-api-auctionx.uzex.uz` answer (send
`Origin: https://xarid.uzex.uz`); Taklif so'rovi and Mahalliy auksion are scanned since 2026-11-18.
`new.cooperation.uz`, `cabinet.cooperation.uz` and `cooperation.uz` time out from the VPS as well (data-centre
address); `cooperation_catalog` goes through the bridge (see "The bridge for new.cooperation.uz").
