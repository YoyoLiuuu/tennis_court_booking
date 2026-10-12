#!/usr/bin/env python3
"""Run court_bot.py as an always-on background service on this computer.

    python service.py install     # start now, and again automatically every time you log in
    python service.py stop        # stop it (e.g. before `python court_bot.py login`)
    python service.py start       # start it again
    python service.py status
    python service.py logs        # follow the log
    python service.py uninstall

macOS uses launchd (and `caffeinate` so the Mac doesn't sleep while it runs), Linux uses a
systemd user service, Windows uses Task Scheduler. All restart the bot if it crashes.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOT = HERE / "court_bot.py"
LOG_DIR = HERE / "logs"
LOG = LOG_DIR / "bot.log"
NAME = "tennis-court-bot"
MAC_LABEL = "com.tennis-court-bot"
MAC_PLIST = Path.home() / "Library/LaunchAgents" / f"{MAC_LABEL}.plist"
SYSTEMD_UNIT = Path.home() / ".config/systemd/user" / f"{NAME}.service"
WIN_TASK = "TennisCourtBot"


def sh(*cmd: str, check: bool = True) -> int:
    print("$", " ".join(cmd))
    return subprocess.run(cmd, check=check).returncode


def require_config() -> None:
    if not (HERE / "config.yaml").exists():
        sys.exit("config.yaml not found — copy config.example.yaml to config.yaml and edit it first.")
    if not (HERE / ".profile").exists():
        sys.exit("Not signed in yet — run  python court_bot.py login  first.")


# ---------------------------------------------------------------- macOS


def mac_plist() -> str:
    args = ["/usr/bin/caffeinate", "-i", sys.executable, "-u", str(BOT), "watch"]
    arg_xml = "".join(f"<string>{a}</string>" for a in args)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{MAC_LABEL}</string>
  <key>ProgramArguments</key><array>{arg_xml}</array>
  <key>WorkingDirectory</key><string>{HERE}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>{LOG}</string>
  <key>StandardErrorPath</key><string>{LOG}</string>
</dict></plist>
"""


def mac(action: str) -> None:
    domain = f"gui/{os.getuid()}"
    if action == "install":
        MAC_PLIST.parent.mkdir(parents=True, exist_ok=True)
        MAC_PLIST.write_text(mac_plist())
        sh("launchctl", "bootout", f"{domain}/{MAC_LABEL}", check=False)
        sh("launchctl", "bootstrap", domain, str(MAC_PLIST))
    elif action == "start":
        sh("launchctl", "bootstrap", domain, str(MAC_PLIST), check=False)
        sh("launchctl", "kickstart", f"{domain}/{MAC_LABEL}")
    elif action == "stop":
        sh("launchctl", "bootout", f"{domain}/{MAC_LABEL}", check=False)
    elif action == "status":
        sh("launchctl", "print", f"{domain}/{MAC_LABEL}", check=False)
    elif action == "uninstall":
        sh("launchctl", "bootout", f"{domain}/{MAC_LABEL}", check=False)
        MAC_PLIST.unlink(missing_ok=True)


# ---------------------------------------------------------------- Linux


def systemd_unit() -> str:
    return f"""[Unit]
Description=Tennis court auto-booking bot
After=network-online.target

[Service]
WorkingDirectory={HERE}
ExecStart="{sys.executable}" -u "{BOT}" watch
Restart=on-failure
RestartSec=30
StandardOutput=append:{LOG}
StandardError=append:{LOG}

[Install]
WantedBy=default.target
"""


def linux(action: str) -> None:
    ctl = ["systemctl", "--user"]
    if action == "install":
        SYSTEMD_UNIT.parent.mkdir(parents=True, exist_ok=True)
        SYSTEMD_UNIT.write_text(systemd_unit())
        sh(*ctl, "daemon-reload")
        sh(*ctl, "enable", "--now", NAME)
        # keep running when you're logged out
        sh("loginctl", "enable-linger", os.environ.get("USER", ""), check=False)
    elif action in ("start", "stop", "status"):
        sh(*ctl, action, NAME, check=False)
    elif action == "uninstall":
        sh(*ctl, "disable", "--now", NAME, check=False)
        SYSTEMD_UNIT.unlink(missing_ok=True)
        sh(*ctl, "daemon-reload", check=False)


# ---------------------------------------------------------------- Windows


def run_forever() -> None:
    """Supervisor used on Windows: restart the bot whenever it crashes."""
    LOG_DIR.mkdir(exist_ok=True)
    while True:
        with LOG.open("a") as f:
            code = subprocess.call([sys.executable, "-u", str(BOT), "watch"], cwd=HERE, stdout=f, stderr=f)
        if code == 0:  # finished normally (max_bookings reached)
            return
        time.sleep(30)


def windows(action: str) -> None:
    pyw = Path(sys.executable).with_name("pythonw.exe")
    py = pyw if pyw.exists() else Path(sys.executable)
    if action == "install":
        tr = f'"{py}" "{Path(__file__).resolve()}" run'
        sh("schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", WIN_TASK, "/TR", tr)
        sh("schtasks", "/Run", "/TN", WIN_TASK)
        print("Note: also set Windows power settings so the PC doesn't sleep while plugged in.")
    elif action == "start":
        sh("schtasks", "/Run", "/TN", WIN_TASK)
    elif action == "stop":
        sh("schtasks", "/End", "/TN", WIN_TASK, check=False)
    elif action == "status":
        sh("schtasks", "/Query", "/TN", WIN_TASK, "/V", "/FO", "LIST", check=False)
    elif action == "uninstall":
        sh("schtasks", "/End", "/TN", WIN_TASK, check=False)
        sh("schtasks", "/Delete", "/F", "/TN", WIN_TASK, check=False)


# ----------------------------------------------------------------


def follow_log() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    LOG.touch()
    with LOG.open() as f:
        print(f.read()[-5000:], end="")
        try:
            while True:
                line = f.readline()
                if line:
                    print(line, end="", flush=True)
                else:
                    time.sleep(1)
        except KeyboardInterrupt:
            pass


def main() -> None:
    actions = ["install", "start", "stop", "status", "logs", "uninstall", "run"]
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        sys.exit(__doc__)
    action = sys.argv[1]
    LOG_DIR.mkdir(exist_ok=True)
    if action == "logs":
        return follow_log()
    if action == "run":
        return run_forever()
    if action in ("install", "start"):
        require_config()

    system = platform.system()
    {"Darwin": mac, "Linux": linux, "Windows": windows}.get(system, lambda _: sys.exit(f"Unsupported OS: {system}"))(action)
    if action == "install":
        print(f"\nInstalled. The bot is running and will start again whenever you log in.\nLog: {LOG}")


if __name__ == "__main__":
    main()
