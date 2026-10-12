#!/usr/bin/env python3
"""Watch a UofT Recreation (Innosoft Fusion) booking page and book a court when one frees up.

Usage:
    python court_bot.py login              # once: sign in with UTORid + Duo in a real browser window
    python court_bot.py watch              # poll and book matching slots
    python court_bot.py watch --dry-run    # only report open slots, never book
    python court_bot.py watch --once       # check a single time and exit
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
PROFILE_DIR = HERE / ".profile"
SHOT_DIR = HERE / "screenshots"

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Fusion markup varies a bit between schools/versions, so every lookup tries a few selectors.
DATE_BUTTON_SELECTORS = [
    "button.single-date-select-button",
    "#divBookingDateSelector button",
    "button[data-date-text]",
]
FACILITY_BUTTON_SELECTORS = [
    "#tabBookingFacilities button",
    "#divBookingFacilities button",
    "button[data-facility-id]",
]
SLOT_SELECTORS = [
    ".booking-slot-item",
    "#divBookingSlots > div",
    "#divBookingSlots .card",
]
BOOK_BUTTON_RE = re.compile(r"^\s*(book( now)?|reserve)\s*$", re.I)
CONFIRM_BUTTON_RE = re.compile(r"^\s*(confirm|yes|book|book now|reserve|ok|submit)\s*$", re.I)
LOGIN_HINT_RE = re.compile(r"(sign in|log ?in)", re.I)


# ---------------------------------------------------------------- parsing helpers (pure, tested)

_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*([ap]\.?\s*m\.?)?", re.I)


def _meridiem(s: str | None) -> str | None:
    if not s:
        return None
    return "am" if s.strip().lower().startswith("a") else "pm"


def _to_minutes(h: int, m: int, mer: str | None) -> int:
    if mer == "am":
        h = 0 if h == 12 else h
    elif mer == "pm":
        h = h if h == 12 else h + 12
    return h * 60 + m


def parse_time_range(text: str) -> tuple[int, int] | None:
    """Parse '7 - 8 PM', '11 AM - 12 PM', '7:30 PM - 8:30 PM', '19:00 - 20:00' into minutes past midnight."""
    parts = re.split(r"\s*(?:-|–|—|to)\s*", text.strip(), maxsplit=1)
    if len(parts) != 2:
        return None
    a, b = (_TIME_RE.search(p) for p in parts)
    if not a or not b:
        return None
    end_mer = _meridiem(b.group(3))
    start_mer = _meridiem(a.group(3)) or end_mer
    end = _to_minutes(int(b.group(1)), int(b.group(2) or 0), end_mer)
    start = _to_minutes(int(a.group(1)), int(a.group(2) or 0), start_mer)
    # '11 - 12 PM' really means 11 AM - 12 PM
    if a.group(3) is None and start_mer == "pm" and start > end:
        start -= 12 * 60
    return start, end


def find_time_range(text: str) -> tuple[int, int] | None:
    """Find the first time range anywhere inside a blob of slot text."""
    m = re.search(
        r"\d{1,2}(?::\d{2})?\s*(?:[ap]\.?\s*m\.?)?\s*(?:-|–|—|to)\s*\d{1,2}(?::\d{2})?\s*(?:[ap]\.?\s*m\.?)?",
        text,
        re.I,
    )
    return parse_time_range(m.group(0)) if m else None


def find_weekday(text: str) -> str | None:
    m = re.search(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", text, re.I)
    return m.group(1).capitalize() if m else None


def hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@dataclass
class Window:
    days: list[str] = field(default_factory=lambda: list(DAYS))
    start: int = 0
    end: int = 24 * 60

    @classmethod
    def from_cfg(cls, d: dict) -> "Window":
        def mins(s: str) -> int:
            h, m = s.split(":")
            return int(h) * 60 + int(m)

        days = [x[:3].capitalize() for x in d.get("days") or DAYS]
        return cls(days, mins(d.get("start", "00:00")), mins(d.get("end", "24:00")))

    def matches(self, weekday: str | None, rng: tuple[int, int]) -> bool:
        if weekday and weekday not in self.days:
            return False
        return self.start <= rng[0] and rng[1] <= self.end


def slot_wanted(windows: list[Window], weekday: str | None, rng: tuple[int, int] | None) -> bool:
    if rng is None:
        return False
    return any(w.matches(weekday, rng) for w in windows) if windows else True


# ---------------------------------------------------------------- browser side


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def notify(cfg: dict, msg: str) -> None:
    topic = cfg.get("ntfy_topic")
    if not topic:
        return
    try:
        urllib.request.urlopen(
            urllib.request.Request(f"https://ntfy.sh/{topic}", data=msg.encode(), method="POST"), timeout=10
        )
    except Exception as e:  # notification failure must never stop booking
        log(f"ntfy failed: {e}")


def screenshot(page, name: str) -> None:
    SHOT_DIR.mkdir(exist_ok=True)
    path = SHOT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        log(f"screenshot: {path}")
    except Exception:
        pass


def first_present(page, selectors: list[str]):
    for sel in selectors:
        loc = page.locator(sel)
        if loc.count():
            return loc
    return None


def visible_buttons_matching(scope, pattern: re.Pattern):
    out = []
    for btn in scope.locator("button, a.btn, input[type=submit]").all():
        try:
            if btn.is_visible() and btn.is_enabled() and pattern.match(btn.inner_text() or btn.get_attribute("value") or ""):
                out.append(btn)
        except Exception:
            continue
    return out


def wait_for_slots(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass
    page.wait_for_timeout(800)


def looks_logged_out(page) -> bool:
    if "weblogin" in page.url or "idpz" in page.url or "/Account/Login" in page.url:
        return True
    return bool(visible_buttons_matching(page, LOGIN_HINT_RE)) and not page.locator("text=/log ?out|sign ?out/i").count()


def try_book(page, slot, label: str, dry_run: bool) -> bool:
    buttons = visible_buttons_matching(slot, BOOK_BUTTON_RE)
    if not buttons:
        return False
    if dry_run:
        log(f"OPEN (dry run, not booking): {label}")
        return False

    log(f"Booking {label} ...")
    buttons[0].click()
    page.wait_for_timeout(1500)

    # Some setups pop a confirmation modal; click its confirm button if there is one.
    modal = first_present(page, [".modal.show", ".modal.in", "[role=dialog]:visible", ".swal2-popup"])
    if modal is not None:
        confirms = visible_buttons_matching(modal, CONFIRM_BUTTON_RE)
        if confirms:
            confirms[-1].click()
            page.wait_for_timeout(2000)

    wait_for_slots(page)
    body = page.inner_text("body")
    ok = bool(re.search(r"success|booked|confirmed|your booking", body, re.I)) and not re.search(
        r"error|not available|failed|limit", body, re.I
    )
    screenshot(page, "booked" if ok else "book-attempt")
    log(("BOOKED: " if ok else "Clicked book but could not confirm success — check screenshot: ") + label)
    return ok


def scan_once(page, cfg: dict, windows: list[Window], dry_run: bool, booked: list[str]) -> None:
    page.goto(cfg["booking_url"], wait_until="domcontentloaded")
    wait_for_slots(page)

    if looks_logged_out(page):
        screenshot(page, "logged-out")
        raise SystemExit("Looks like you are not signed in. Run:  python court_bot.py login")

    courts_filter = [c.lower() for c in cfg.get("courts") or []]
    facilities = first_present(page, FACILITY_BUTTON_SELECTORS)
    facility_count = facilities.count() if facilities is not None else 1

    found_any = False
    for fi in range(facility_count):
        court = "court"
        if facilities is not None:
            fbtn = facilities.nth(fi)
            court = (fbtn.inner_text() or f"facility {fi + 1}").strip()
            if courts_filter and not any(c in court.lower() for c in courts_filter):
                continue
            fbtn.click()
            wait_for_slots(page)

        dates = first_present(page, DATE_BUTTON_SELECTORS)
        date_count = dates.count() if dates is not None else 1
        for di in range(date_count):
            day_text = ""
            if dates is not None:
                dbtn = dates.nth(di)
                day_text = " ".join((dbtn.inner_text() or "").split())
                if dbtn.is_disabled():
                    continue
                dbtn.click()
                wait_for_slots(page)
            weekday = find_weekday(day_text)

            slots = first_present(page, SLOT_SELECTORS)
            if slots is None:
                continue
            for si in range(slots.count()):
                slot = slots.nth(si)
                text = " ".join((slot.inner_text() or "").split())
                rng = find_time_range(text)
                if not slot_wanted(windows, weekday, rng):
                    continue
                if not visible_buttons_matching(slot, BOOK_BUTTON_RE):
                    continue
                found_any = True
                label = f"{court} | {day_text or weekday or '?'} | {hhmm(rng[0])}-{hhmm(rng[1])}"
                if try_book(page, slot, label, dry_run):
                    booked.append(label)
                    notify(cfg, f"Booked tennis: {label}")
                    # page state changed; rescan from the top on the next round
                    return
                elif dry_run:
                    notify(cfg, f"Open tennis slot: {label}")
    if not found_any:
        log("No matching open slots.")


def load_cfg(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        sys.exit(f"{p} not found — copy config.example.yaml to config.yaml and edit it.")
    return yaml.safe_load(p.read_text()) or {}


def launch(pw, headless: bool):
    PROFILE_DIR.mkdir(exist_ok=True)
    return pw.chromium.launch_persistent_context(str(PROFILE_DIR), headless=headless, viewport={"width": 1280, "height": 1000})


def cmd_login(cfg: dict) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = launch(pw, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(cfg["booking_url"])
        input("Sign in with your UTORid (and Duo) in the browser window, open the booking page, then press Enter here... ")
        ctx.close()
    log("Session saved to .profile/ — you can now run:  python court_bot.py watch")


def cmd_watch(cfg: dict, dry_run: bool, once: bool) -> None:
    from playwright.sync_api import sync_playwright

    windows = [Window.from_cfg(w) for w in cfg.get("windows") or []]
    poll = max(int(cfg.get("poll_seconds", 60)), 15)
    booked: list[str] = []
    with sync_playwright() as pw:
        ctx = launch(pw, headless=cfg.get("headless", True))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        while True:
            try:
                scan_once(page, cfg, windows, dry_run, booked)
            except SystemExit:
                raise
            except Exception as e:
                log(f"scan error: {e}")
                screenshot(page, "error")
            if len(booked) >= cfg.get("max_bookings", 1):
                log(f"Done. Booked: {json.dumps(booked)}")
                break
            if once:
                break
            time.sleep(poll)
        ctx.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["login", "watch"])
    ap.add_argument("--config", default=str(HERE / "config.yaml"))
    ap.add_argument("--dry-run", action="store_true", help="report open slots but never book")
    ap.add_argument("--once", action="store_true", help="check once and exit")
    args = ap.parse_args()
    cfg = load_cfg(args.config)
    if args.command == "login":
        cmd_login(cfg)
    else:
        cmd_watch(cfg, args.dry_run, args.once)


if __name__ == "__main__":
    main()
