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

## Open work that needs an Uzbek IP address

Development so far happened from South Korea, and GitHub's servers are abroad too. From there these do not open
(the host name resolves, the connection times out), so they are not connected. Nobody has confirmed yet that they
open from inside Uzbekistan — checking that is the first step.

| Target | What it is | Known so far |
|---|---|---|
| `cooperation.uz` | purchases from local manufacturers; named as one of the three main platforms | nothing explored |
| `xarid-api-auctionx.uzex.uz` | API behind xarid.uzex.uz → Mahalliy auksion (`/new-auction/list`), auctions for local manufacturers | endpoints unknown |
| `xarid-api-prequest.uzex.uz` | API behind xarid.uzex.uz → Taklif so'rovi (request for proposals) | endpoints unknown |
| `new-xarid.uzex.uz` | new version of xarid | nothing explored |
| `api.xt-xarid.uz` | already scanned | from abroad it allows one request per 60 s; `host_pauses` in `config.yaml` is 65. Try a small value from Uzbekistan |

Not explored for other reasons: xarid.uzex.uz sections To'g'ridan-to'g'ri elektron shartnoma, Davlat xaridlari,
Hadli kelishuv, Reja jadval; tender pages of banks (nbu.uz and others). Milliy do'kon and Elektron do'kon are
supplier storefronts, not orders — the bot only builds a competitor price report from Milliy do'kon.

A source that works only from Uzbekistan cannot run on GitHub. Running the whole bot from an Uzbek server or
computer is a decision for the owner (Muhammadbilol): the scheduler, the `state` database and the secrets would
have to move together, otherwise lots arrive twice.
