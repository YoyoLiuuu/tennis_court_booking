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
python court_bot.py watch                    # run in this terminal (Ctrl+C to stop)
```

Set `headless: false` in `config.yaml` to watch it click. Screenshots of each booking attempt and
any errors go to `screenshots/`.

## Run it as an always-on service

Once the dry run looks right:

```bash
python service.py install    # starts now and again every time you log in; restarts if it crashes
python service.py logs       # follow what it's doing
python service.py stop | start | status | uninstall
```

It keeps checking every `poll_seconds` and books every slot that matches your `windows`, at most
`max_per_day` slots on any one date (default 1), forever (`max_bookings: 0`). What it has booked is
recorded in `bookings.json`, so a restart won't double-book a day.

- **Get notified:** set `ntfy_topic` in `config.yaml` and subscribe to that topic in the
  [ntfy](https://ntfy.sh) phone app. You get a push for every booking, and if your UofT login expires.
- **When the login expires**, the bot keeps running and retries every 15 min. To fix it:
  `python service.py stop`, then `python court_bot.py login`, then `python service.py start`.
  (Stop first; the running bot holds the browser profile.)
- **Keep the computer on.** On a Mac the service uses `caffeinate` to prevent idle sleep, but closing
  the lid still sleeps it. On Windows, turn off sleep in power settings. A spare always-on machine
  (old laptop, Raspberry Pi) works well.
- Using a venv? Run `service.py install` with the venv's python so the service uses it too.

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
