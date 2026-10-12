import os
from pathlib import Path

import pytest

import court_bot as cb


@pytest.mark.parametrize(
    "text,expected",
    [
        ("7 - 8 PM", (19 * 60, 20 * 60)),
        ("11 AM - 12 PM", (11 * 60, 12 * 60)),
        ("11 - 12 PM", (11 * 60, 12 * 60)),
        ("7:30 PM - 8:30 PM", (19 * 60 + 30, 20 * 60 + 30)),
        ("19:00 - 20:00", (19 * 60, 20 * 60)),
        ("12 - 1 AM", (0, 60)),
    ],
)
def test_parse_time_range(text, expected):
    assert cb.parse_time_range(text) == expected


def test_find_in_blob():
    assert cb.find_time_range("Court 3 7 - 8 PM 1 spot available Book Now") == (19 * 60, 20 * 60)
    assert cb.find_weekday("Saturday Oct 17") == "Sat"


def test_windows():
    w = [cb.Window.from_cfg({"days": ["Sat", "Sunday"], "start": "09:00", "end": "12:00"})]
    assert cb.slot_wanted(w, "Sat", (11 * 60, 12 * 60))
    assert not cb.slot_wanted(w, "Mon", (11 * 60, 12 * 60))
    assert not cb.slot_wanted(w, "Sun", (11 * 60, 13 * 60))
    assert cb.slot_wanted([], "Mon", (0, 60))


def test_books_against_mock_page(tmp_path, monkeypatch):
    sync_api = pytest.importorskip("playwright.sync_api")
    monkeypatch.setattr(cb, "SHOT_DIR", tmp_path)
    url = (Path(__file__).parent / "mock_booking.html").resolve().as_uri()
    cfg = {"booking_url": url, "courts": ["Court 2"], "max_bookings": 1}
    windows = [cb.Window.from_cfg({"days": ["Mon"], "start": "18:00", "end": "21:00"})]
    with sync_api.sync_playwright() as pw:
        exe = os.environ.get("CHROMIUM_PATH")
        browser = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
        page = browser.new_page()
        booked = []
        cb.scan_once(page, cfg, windows, dry_run=False, booked=booked)
        browser.close()
    assert booked == ["Court 2 | Mon Oct 12 | 19:00-20:00"]
