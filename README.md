# Tennis court booking bot (UofT Recreation)

Watches a booking page on recreation.utoronto.ca and books a court as soon as a slot matching your
preferences frees up. It drives a real Chromium browser (Playwright) using your own UofT login.

## Setup (once)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp config.example.yaml config.yaml      # then edit your days/times
python court_bot.py login               # a browser opens: sign in with UTORid + Duo, then press Enter
```

The login session is saved in `.profile/` (git-ignored), so you don't need to sign in every time.
If it expires, the bot stops and tells you to run `login` again.

## Run

```bash
python court_bot.py watch --dry-run --once   # first: just show what's open and matches, book nothing
python court_bot.py watch                    # poll every poll_seconds and book a match
```

Set `headless: false` in `config.yaml` to watch it click. Screenshots of each booking attempt and
any errors go to `screenshots/`. Add an `ntfy_topic` to get a phone push when it books.

Keep it running on a computer that stays awake (or a small always-on machine) for it to catch
cancellations.

## How it works

For each court tab and each date button on the page, it reads the slot list, parses the time
("7 - 8 PM"), and clicks **Book Now** on the first slot that fits one of your `windows`. If a
confirmation dialog appears it confirms it, then checks the page for a success message.

## Caveats

- The page layout was written against the standard Innosoft Fusion booking layout that
  recreation.utoronto.ca uses, but couldn't be tested against the live site. If it never finds slots,
  run with `headless: false` and check the `screenshots/` folder; the CSS selectors are at the top
  of `court_bot.py`.
- If the site adds a CAPTCHA to booking, the bot can't get past it.
- Please be polite: keep `poll_seconds` at 30 or more, and check the Recreation booking rules
  about automated bookings.

## Tests

```bash
pytest   # parsing unit tests + an end-to-end run against tests/mock_booking.html
```
