"""
 Karma Ultra Bot — VETRO UI EDITION
All v7.1 Logic + VETRO-Style GUI (Dark, Sidebar, Task Table)
"""

import asyncio
import concurrent.futures
import imaplib
import json
import random
import re
import string
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, asdict, field, fields
from email import message_from_bytes
from email.utils import getaddresses
from pathlib import Path

import httpx
import requests
import sys
import shutil
import subprocess
import os

# ═════════════════════════════════════════════
#  VERSION & AUTO-UPDATE
# ═════════════════════════════════════════════

VERSION = "1.9.42"  # one click push update
UPDATE_NOTE = "Settings can push this file to GitHub in one click"
UPDATE_URL = "https://raw.githubusercontent.com/YRLouis/KARMAULTRA.EXE/main/KarmaUltra.py"
UPDATE_EXE_URL = "https://github.com/YRLouis/KARMAULTRA.EXE/releases/latest/download/KarmaUltra.exe"

class Updater:
    """Check and install updates from a remote raw .py URL."""

    @staticmethod
    def _extract_version(text: str) -> str | None:
        m = re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', text)
        return m.group(1) if m else None

    @staticmethod
    def _extract_note(text: str) -> str:
        m = re.search(r'UPDATE_NOTE\s*=\s*["\']([^"\']+)["\']', text)
        return m.group(1) if m else ""

    @staticmethod
    def check(url: str) -> tuple[bool, str, str]:
        """Returns (is_newer, remote_version, message)."""
        if not url or not url.startswith("http"):
            return False, VERSION, "No valid update URL configured"
        try:
            r = requests.get(url, timeout=15)
            if r.status_code != 200:
                return False, VERSION, f"HTTP {r.status_code}"
            remote_ver = Updater._extract_version(r.text)
            Updater.last_note = Updater._extract_note(r.text)
            if not remote_ver:
                return False, VERSION, "Could not find VERSION in remote file"
            if remote_ver == VERSION:
                return False, remote_ver, f"Already on latest ({VERSION})"
            def parts(v):
                return [int(x) if x.isdigit() else 0 for x in v.split(".")]
            if parts(remote_ver) > parts(VERSION):
                return True, remote_ver, f"Update available: {VERSION}  {remote_ver}"
            return False, remote_ver, f"Remote is older or same ({remote_ver})"
        except Exception as e:
            return False, VERSION, f"Check failed: {e}"

    @staticmethod
    def install(url: str, current_path: Path | None = None) -> tuple[bool, str]:
        """Download, backup current, replace file. Returns (success, message)."""
        if not url or not url.startswith("http"):
            return False, "Invalid URL"
        current_path = current_path or Path(__file__).resolve()
        # When frozen (exe), we cannot replace the running exe easily
        if getattr(sys, "frozen", False):
            return False, "Running as .exe — download the new KarmaUltra.py from GitHub and rebuild, or run the .py version for auto-updates."
        try:
            r = requests.get(url, timeout=30)
            if r.status_code != 200:
                return False, f"Download failed: HTTP {r.status_code}"
            new_code = r.text
            if "VERSION" not in new_code or "def run_gui" not in new_code:
                return False, "Downloaded file does not look like a valid Karma Ultra script"
            backup = current_path.with_suffix(".py.bak")
            shutil.copy2(current_path, backup)
            current_path.write_text(new_code, encoding="utf-8")
            return True, f"Updated successfully. Backup saved to {backup.name}. Restart the bot to apply."
        except Exception as e:
            return False, f"Install failed: {e}"

    @staticmethod
    def install_exe(url: str) -> tuple[bool, str]:
        """Download a new exe beside this one, then swap it in after we exit."""
        if not getattr(sys, "frozen", False):
            return False, "Not running as an exe"
        exe = Path(sys.executable).resolve()
        new_path = exe.parent / "KarmaUltra.update.exe"
        try:
            r = requests.get(url, timeout=120, allow_redirects=True)
            if r.status_code != 200:
                return False, (
                    f"Exe download failed: HTTP {r.status_code}. "
                    "Upload KarmaUltra.exe to the latest GitHub Release."
                )
            data = r.content
            if not data.startswith(b"MZ") or len(data) < 100000:
                return False, "That file is not the exe. Add KarmaUltra.exe to a GitHub Release."
            new_path.write_bytes(data)
        except Exception as e:
            return False, f"Exe download failed: {e}"
        bat = exe.parent / "karma_update.bat"
        bat.write_text(
            "@echo off\r\n"
            "timeout /t 2 /nobreak >nul\r\n"
            f'move /Y "{new_path}" "{exe}"\r\n'
            f'start "" "{exe}"\r\n'
            'del "%~f0"\r\n',
            encoding="utf-8",
        )
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(
            ["cmd", "/c", str(bat)],
            cwd=str(exe.parent),
            close_fds=True,
            creationflags=flags,
        )
        return True, "Installing the new exe…"

    @staticmethod
    def restart():
        """Relaunch the current script."""
        python = sys.executable
        os.execv(python, [python] + sys.argv)

# ═════════════════════════════════════════════
#  PATHS / CONFIG
# ═════════════════════════════════════════════

def _has_saved_data(path: Path) -> bool:
    return any((path / name).exists() for name in (
        "config.json", "accounts.json", "task_groups.json", "proxy_groups.json"))


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _seed_data(dest: Path):
    """Copy an older data folder into dest once, so an update keeps accounts and tasks."""
    if _has_saved_data(dest):
        return
    seeds = []
    if getattr(sys, "frozen", False):
        seeds.append(Path(sys.executable).resolve().parent.parent / "data")
    seeds.append(Path.cwd() / "data")
    try:
        seeds.append(Path(__file__).resolve().parent / "data")
    except Exception:
        pass
    dest_resolved = dest.resolve()
    for src in seeds:
        try:
            src_resolved = src.resolve()
        except Exception:
            continue
        if src_resolved == dest_resolved or not _has_saved_data(src):
            continue
        dest.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            target = dest / item.name
            if target.exists():
                continue
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)
        return


BASE_DIR = _app_root()
DATA_DIR = BASE_DIR / "data"
_seed_data(DATA_DIR)
DATA_DIR.mkdir(exist_ok=True)
SESSIONS_DIR = DATA_DIR / "sessions"; SESSIONS_DIR.mkdir(exist_ok=True)
SHOTS_DIR = DATA_DIR / "screenshots"; SHOTS_DIR.mkdir(exist_ok=True)

CONFIG_FILE = DATA_DIR / "config.json"
ACCOUNTS_FILE = DATA_DIR / "accounts.json"
ACCOUNT_GROUPS_FILE = DATA_DIR / "account_groups.json"
QUEUE_FILE = DATA_DIR / "queue_history.json"
GROUPS_FILE = DATA_DIR / "task_groups.json"
PROXIES_FILE = DATA_DIR / "proxies.txt"
PROXY_GROUPS_FILE = DATA_DIR / "proxy_groups.json"
LEARNED_FILE = DATA_DIR / "learned_popups.json"

DEFAULT_CONFIG = {
    "discord": {
        "webhook_url": "https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE",
        "mention_user_id": "",
        "include_cookies": True, "include_screenshot": True,
        "include_cart_link": True,
    },
    "captcha": {"provider": "capsolver", "api_key": "YOUR_CAPSOLVER_KEY"},
    "general": {"headless": True, "hybrid_mode": False, "keep_browser_open_min": 15},
    "restock": {
        "events": [],
        "poll_interval_sec": 180, "jitter_sec": 60,
        "auto_cart": True, "default_qty": 2,
        "min_price": 0.0, "max_price": 250.0,
        "default_sections": [], "default_contiguous": True,
        "default_presale_codes": [], "min_qty_available": 1,
    },
    "ai": {"provider": "openai", "api_key": "", "model": "gpt-4o-mini",
           "temperature": 0.2},
    "imap": {"email": "", "password": "", "host": "", "port": 993, "ssl": True},
    "update": {
        "url": "https://raw.githubusercontent.com/YRLouis/KARMAULTRA.EXE/main/KarmaUltra.py",
        "check_on_start": False,
    },
}


@dataclass
class TaskGroup:
    id: str
    name: str
    event_url: str
    quantity: int = 2
    min_price: float = 0.0
    max_price: float = 250.0
    contiguous: bool = True
    section_mode: str = "include"
    sections: list = field(default_factory=list)
    account_group: str = "default"
    proxy_group: str = "any"
    max_tasks: int = 2
    enabled: bool = True
    presale_codes: list = field(default_factory=list)
    presale_played: list = field(default_factory=list)
    tasks: list = field(default_factory=list)
    task_count: int = 1
    mode: str = "normal"
    country: str = "NL"


def jload(path, default):
    if Path(path).exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def jsave(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def merge_config(cfg, defaults):
    for k, v in defaults.items():
        if k not in cfg:
            cfg[k] = v
        elif isinstance(v, dict):
            for kk, vv in v.items():
                cfg[k].setdefault(kk, vv)
    return cfg


CONFIG = merge_config(jload(CONFIG_FILE, {}), DEFAULT_CONFIG)
jsave(CONFIG_FILE, CONFIG)


def load_groups():
    known = {f.name for f in fields(TaskGroup)}
    out = []
    for g in jload(GROUPS_FILE, []):
        if not isinstance(g, dict):
            continue
        try:
            out.append(TaskGroup(**{k: v for k, v in g.items() if k in known}))
        except Exception:
            continue
    return out


def save_groups(groups):
    jsave(GROUPS_FILE, [asdict(g) for g in groups])


def load_accounts():
    return jload(ACCOUNTS_FILE, [])


def save_accounts(a):
    jsave(ACCOUNTS_FILE, a)


def load_account_group_names():
    names = jload(ACCOUNT_GROUPS_FILE, [])
    if not isinstance(names, list):
        names = []
    for a in load_accounts():
        g = a.get("group") or "default"
        if g not in names:
            names.append(g)
    return names


def save_account_group_names(names):
    jsave(ACCOUNT_GROUPS_FILE, names)


def record_queue_start(email, event, start_pos):
    if not email or not start_pos:
        return
    hist = jload(QUEUE_FILE, [])
    if not isinstance(hist, list):
        hist = []
    hist.append({
        "email": email,
        "event": str(event)[:180],
        "start_pos": int(start_pos),
        "at": datetime.now().isoformat(),
    })
    jsave(QUEUE_FILE, hist[-1000:])
    acc = get_account(email) or {}
    runs = int(acc.get("queue_runs", 0)) + 1
    best = acc.get("best_queue")
    start_pos = int(start_pos)
    if best is None or start_pos < int(best):
        best = start_pos
    update_account(email, last_queue=start_pos, best_queue=best,
                   queue_runs=runs, last_queue_at=datetime.now().isoformat())


# ═════════════════════════════════════════════
#   ACCOUNT HEALTH
# ═════════════════════════════════════════════

MAX_OTP_FAILS = 2


def get_account(email):
    for a in load_accounts():
        if a.get("email") == email:
            return a
    return None


def update_account(email, **kw):
    accs = load_accounts()
    for a in accs:
        if a.get("email") == email:
            a.update(kw)
            save_accounts(accs)
            return True
    return False


def record_otp_result(email, success, reason=""):
    acc = get_account(email)
    if not acc:
        return False
    if success:
        if acc.get("otp_fails", 0) > 0 or acc.get("status") == "otp_warn":
            update_account(email, otp_fails=0, status="ok")
        return True
    fails = acc.get("otp_fails", 0) + 1
    st = "dead_otp" if fails >= MAX_OTP_FAILS else "otp_warn"
    update_account(email, otp_fails=fails, status=st,
                   last_otp_fail=reason[:120],
                   last_fail_at=datetime.now().isoformat())
    print(f"{email}: OTP fail {fails}/{MAX_OTP_FAILS}  {st}")
    return st != "dead_otp"


def retire_account(email, reason):
    update_account(email, status="dead", fail_reason=reason[:120],
                   last_fail_at=datetime.now().isoformat())


def revive_account(email):
    update_account(email, status="ok", otp_fails=0, used=False,
                   fail_reason="", last_otp_fail="")


def accounts_in_group(group_name, healthy_only=True):
    good = ("ok", "otp_warn")
    return [a for a in load_accounts()
            if a.get("group", "default") == group_name
            and not a.get("used", False)
            and (not healthy_only or a.get("status", "ok") in good)]


# ═════════════════════════════════════════════
#   ERRORS + AI BRAIN
# ═════════════════════════════════════════════

ERROR_CODES = {
    "TM-QUEUE-TIMEOUT":  "Stuck in queue past the 15 min limit — task retries.",
    "TM-NO-MATCH":       "No offer passed your filters (sections/price/qty).",
    "TM-429":            "TM rate-limited us — bot backed off automatically.",
    "TM-403":            "Access denied — proxy rotates on retry.",
    "TM-BAP":            "Browser Activity Paused — .tmpt removed automatically.",
    "TM-CAPTCHA-FAIL":   "FunCaptcha unsolved — check CapSolver key/balance.",
    "TM-CART-FAIL":      "Add-to-cart didn't confirm — tickets may have vanished mid-click.",
    "TM-QTY-FORCE":      "Couldn't set exact quantity — dropdown missing/locked.",
    "TM-PRESALE-LOCKED": "All presale codes rejected — check spelling.",
    "TM-OTP":            "OTP email never arrived — check IMAP settings/catch-all.",
    "TM-NAV":            "Page failed to load — check URL and proxies.",
    "TM-SEL":            "Ticket list never appeared — layout change or redirect.",
    "TM-SESSION":        "Session rejected (OTP would be needed) — fresh login next run.",
    "TM-GEN":            "Unexpected error — see log.",
}

ENDPOINTS = {
    "openai":     "https://api.openai.com/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "groq":       "https://api.groq.com/openai/v1/chat/completions",
    "ollama":     "http://localhost:11434/v1/chat/completions",
}


def explain(exc=None, code="TM-GEN"):
    msg = str(exc) if exc else ""
    low = msg.lower()
    if exc is not None:
        if "timeout" in low and "captcha" in low:
            code = "TM-CAPTCHA-FAIL"
        elif "timeout" in low and "goto" in low:
            code = "TM-NAV"
        elif "timeout" in low:
            code = "TM-SEL"
        elif re.search(r"\b429\b", low):
            code = "TM-429"
        elif re.search(r"\b403\b", low):
            code = "TM-403"
    return code, ERROR_CODES.get(code, ERROR_CODES["TM-GEN"])


class AIBrain:
    def __init__(self):
        cfg = CONFIG.get("ai", {})
        self.key = cfg.get("api_key", "").strip()
        self.model = cfg.get("model", "gpt-4o-mini")
        self.temp = cfg.get("temperature", 0.2)
        self.endpoint = ENDPOINTS.get(cfg.get("provider", "openai"),
                                      ENDPOINTS["openai"])
        self.enabled = bool(self.key)
        self.calls = 0

    def _ask(self, system, user, max_tokens=200):
        if not self.enabled:
            return None
        try:
            headers = {"Authorization": f"Bearer {self.key}",
                       "Content-Type": "application/json"}
            if "openrouter.ai" in self.endpoint:
                headers["HTTP-Referer"] = "https://karmaultra.local"
                headers["X-Title"] = "Karma Ultra"
            r = requests.post(self.endpoint, timeout=20, json={
                "model": self.model, "temperature": self.temp,
                "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}]},
                headers=headers)
            if r.status_code == 200:
                self.calls += 1
                return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"AI call failed: {e}")
        return None

    def diagnose(self, code, exception, context=""):
        fallback = ERROR_CODES.get(code, ERROR_CODES["TM-GEN"])
        return self._ask(
            "You are a Ticketmaster bot engineer. Given an error code, raw "
            "exception and page context, explain in max 2 short sentences: "
            "(1) what failed, (2) the fix. Plain English.",
            f"Error code: {code}\nException: {exception}\n"
            f"Context: {str(context)[:800]}", max_tokens=120) or fallback

    def section_matches(self, filter_text, section_name, mode):
        a = self._ask(
            "Does this venue section match the fan's filter intent? Reply ONLY "
            "'YES' or 'NO'. Synonyms: Floor≈GA≈Pit, Lower≈100 level, "
            "Upper≈300 level. Ranges 101-110 inclusive.",
            f"Filter ({mode}): {filter_text}\nSection: {section_name}",
            max_tokens=5)
        if a and "YES" in a.upper():
            return True
        if a and "NO" in a.upper():
            return False
        return None

    def summarize_run(self, results):
        return self._ask(
            "Summarize a ticket bot run in 2-3 punchy Discord sentences. Wins "
            "first, then the most useful fix. Emojis.",
            json.dumps(results), max_tokens=150) or \
            f"{results.get('carts', 0)} cart(s), {len(results.get('fails', []))} fail(s)."

    def describe_page(self, text_snippet):
        return self._ask(
            "Identify this Ticketmaster page text: queue page, captcha, "
            "'browser paused' page, ticket list, or other. One short answer.",
            str(text_snippet)[:1500], max_tokens=80) or "unidentified"

    def next_click(self, page_text, buttons, goal):
        a = self._ask(
            "You control a Ticketmaster checkout bot. Reply with ONLY the exact "
            "button or link text to click next. Never choose accessible, wheelchair, "
            "rolstoel, or passkey add. Prefer Doorgaan, Niet nu, a ticket plus, or sign in. "
            "If nothing helps, reply NONE.",
            f"Goal: {goal}\nButtons: {json.dumps(buttons[:40])}\nPage: {str(page_text)[:1200]}",
            max_tokens=30)
        if not a:
            return None
        a = a.strip().strip('"').strip("'")
        return None if a.upper() == "NONE" else a

    def popup_button(self, caption, texts):
        a = self._ask(
            "You dismiss website popups. Given popup caption and its buttons, "
            "reply ONLY with the exact button text that dismisses/accepts it "
            "(prefer accepting consent). If none, reply NONE.",
            f"Popup caption: {caption}\nButtons: {json.dumps(texts)}",
            max_tokens=30)
        if a and a.upper().strip() != "NONE":
            return a
        return None


AI = AIBrain()


def explain_deep(exc=None, code="TM-GEN", context=""):
    code, base = explain(exc, code)
    if AI.enabled:
        return code, AI.diagnose(code, exc or Exception(code), context)
    return code, base


# ═════════════════════════════════════════════
#   CURRENCY-NATIVE PRICE ENGINE
# ═════════════════════════════════════════════

CURRENCY_MARKERS = [
    "MX$", "AR$", "CL$", "COP$", "AU$", "NZ$", "CA$", "HK$", "S$", "NT$",
    "R$", "US$", "kr", "zł", "¥", "£", "€", "₩", "₹", "$",
]


class PriceEngine:
    @staticmethod
    def detect_symbol(text):
        text = str(text)
        for m in CURRENCY_MARKERS:
            if m in text:
                return m
        return "$"

    @staticmethod
    def _num(s):
        s = str(s).strip()
        try:
            if "," in s and "." in s:
                if s.rfind(",") > s.rfind("."):
                    s = s.replace(".", "").replace(",", ".")
                else:
                    s = s.replace(",", "")
            elif "," in s:
                s = s.replace(",", "")
            return float(s)
        except ValueError:
            return None

    @staticmethod
    def parse_prices(text):
        out = []
        for m in re.finditer(
                r"(MX\$|AR\$|CL\$|COP\$|AU\$|NZ\$|CA\$|HK\$|S\$|NT\$|R\$|US\$|£|€|¥|₩|₹|\$)\s?"
                r"(\d{1,6}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)", text):
            v = PriceEngine._num(m.group(2))
            if v is not None:
                out.append(v)
        return out

    @staticmethod
    def within(unit_price, tg):
        if unit_price is None:
            return False
        return tg.min_price <= unit_price <= tg.max_price


# ═════════════════════════════════════════════
#   SESSION VAULT
# ═════════════════════════════════════════════

class SessionVault:
    FLAG_COOKIES = ("tmpt",)

    @staticmethod
    def _path(email):
        return SESSIONS_DIR / f"{str(email).replace('@', '_at_')}.json"

    @staticmethod
    def _scrub(state):
        state["cookies"] = [c for c in state.get("cookies", [])
                           if str(c.get("name", "")).lower().strip(".")
                           not in SessionVault.FLAG_COOKIES]
        return state

    @staticmethod
    async def save(context, email):
        state = context.storage_state()
        if asyncio.iscoroutine(state):
            state = await state
        state = SessionVault._scrub(state)
        state["_saved_at"] = datetime.now().isoformat()
        state["_email"] = email
        jsave(SessionVault._path(email), state)

    @staticmethod
    def load(email):
        p = SessionVault._path(email)
        if p.exists():
            try:
                with open(p) as f:
                    return SessionVault._scrub(json.load(f))
            except Exception:
                return None
        return None

    @staticmethod
    def has(email):
        return SessionVault._path(str(email)).exists()

    @staticmethod
    def import_cookies(text, email=None):
        cookies = []
        for m in re.finditer(r"`([^`]+)`\s*=\s*`([^`]+)`", text):
            cookies.append({"name": m.group(1), "value": m.group(2),
                            "domain": ".ticketmaster.com", "path": "/"})
        if not cookies:
            for pair in text.split(";"):
                if "=" in pair:
                    n, _, v = pair.strip().partition("=")
                    if n and v:
                        cookies.append({"name": n.strip(), "value": v.strip(),
                                        "domain": ".ticketmaster.com", "path": "/"})
        if not cookies:
            return False
        state = {"cookies": cookies, "origins": [],
                 "_saved_at": datetime.now().isoformat(),
                 "_email": email or "imported_manual", "_imported": True}
        jsave(SessionVault._path(email or "imported_manual"),
              SessionVault._scrub(state))
        return True

    @staticmethod
    def list_sessions():
        out = []
        for p in SESSIONS_DIR.glob("*.json"):
            try:
                m = SessionVault._scrub(jload(p, {}))
                out.append({"email": m.get("_email", p.stem),
                            "saved": str(m.get("_saved_at", "?"))[:16],
                            "cookies": len(m.get("cookies", [])),
                            "imported": m.get("_imported", False)})
            except Exception:
                out.append({"email": p.stem, "saved": "?", "cookies": 0,
                            "imported": False})
        return out


# ═════════════════════════════════════════════
#   STATUS BOARD
# ═════════════════════════════════════════════

class StatusBoard:
    def __init__(self):
        self.lock = threading.Lock()
        self.tasks = {}
        self._listeners = []

    def on_change(self, cb):
        self._listeners.append(cb)

    def _emit(self):
        with self.lock:
            snap = {k: dict(v) for k, v in self.tasks.items()}
        for cb in self._listeners:
            try:
                cb(snap)
            except Exception:
                pass

    def create(self, task_id, group, account):
        with self.lock:
            self.tasks[task_id] = {
                "group": group, "account": account, "state": "starting",
                "queue_pos": None, "queue_pct": None, "started": time.time(),
                "errors": [], "bap_heals": 0, "popups": 0,
                "takeover_available": False}
        self._emit()

    def update(self, task_id, **kw):
        with self.lock:
            if task_id in self.tasks:
                self.tasks[task_id].update(kw)
        self._emit()

    def error(self, task_id, code, message):
        with self.lock:
            t = self.tasks.get(task_id)
            if t:
                t["errors"].append((time.time(), code, message))
                t["errors"] = t["errors"][-10:]
        self._emit()

    def finish(self, task_id, done=True):
        self.update(task_id, state=("done" if done else "failed"),
                    takeover_available=False)

    def clear(self):
        with self.lock:
            self.tasks = {}
        self._emit()


STATUS = StatusBoard()


# ═════════════════════════════════════════════
#   BAP GUARD
# ═════════════════════════════════════════════

class BaPGuard:
    BAP_MARKERS = [
        "browser activity has been paused", "browser activity is paused",
        "we've detected unusual activity", "verify you are a human",
        "unusual browsing activity",
    ]

    def __init__(self):
        self.hits, self.heals = 0, 0

    @staticmethod
    async def is_bapped(page):
        try:
            body = (await page.content()).lower()
            return any(m in body for m in BaPGuard.BAP_MARKERS)
        except Exception:
            return False

    @staticmethod
    def _is_flag(c):
        return str(c.get("name", "")).lower().strip(".") == "tmpt"

    async def heal(self, context, page, log):
        self.hits += 1
        log(f"BAP #{self.hits} — removing .tmpt + refresh…")
        try:
            cookies = await context.cookies()
            good = [c for c in cookies if not self._is_flag(c)]
            if good and len(good) != len(cookies):
                try:
                    await context.clear_cookies()
                except Exception:
                    pass
                await context.add_cookies(good)
        except Exception:
            pass
        try:
            await page.reload(wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(1.5)
            if not await self.is_bapped(page):
                self.heals += 1
                log(f"BAP healed ({self.heals}/{self.hits})")
                return True
        except Exception:
            pass
        try:
            await page.evaluate(
                "document.cookie='.tmpt=; expires=Thu, 01 Jan 1970 00:00:01 GMT;"
                "domain=.ticketmaster.com; path=/'")
            await page.reload(wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(1.5)
            if not await self.is_bapped(page):
                self.heals += 1
                return True
        except Exception:
            pass
        return False

    async def guard(self, context, page, log):
        if await self.is_bapped(page):
            return await self.heal(context, page, log)
        return False


# ═════════════════════════════════════════════
#   POPUP GUARD v2 — static + AI +  teach
# ═════════════════════════════════════════════

class PopupGuard:
    STATIC_ACCEPT = [
        "i understand", "understood", "accept all", "accept cookies", "accept",
        "reject all", "i agree", "agree", "got it", "ok, got it", "continue",
        "allow all", "allow", "yes, accept", "sounds good", "dismiss", "close",
        "alles accepteren", "accepteren", "weigeren", "alle cookies",
    ]
    STATIC_SELECTORS = [
        "button#onetrust-accept-btn-handler",
        "button#onetrust-close-btn-container",
        "[aria-label='close']", "[aria-label='Close']",
        "button.close", ".modal-close", "#modal-close",
        "[data-testid='cookie-banner'] button",
    ]

    def __init__(self):
        self.static_hits, self.ai_hits, self.learned_hits = 0, 0, 0
        self.learned = jload(LEARNED_FILE, {})

    def _save_learned(self):
        jsave(LEARNED_FILE, self.learned)

    @staticmethod
    def _fingerprint(overlay):
        caption = re.sub(r"\d+", "#", overlay.get("caption", "").lower())
        return " ".join(re.findall(r"[a-z#]{4,}", caption)[:10])

    async def blocked_by(self, page):
        try:
            return await page.evaluate("""() => {
                const sels = ["[role='dialog']", "[class*='modal']",
                              "#onetrust-banner-sdk", "[class*='overlay']",
                              "[class*='consent']", "[class*='popup']"];
                for (const sel of sels) {
                    for (const el of document.querySelectorAll(sel)) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 150 && r.height > 80 &&
                            getComputedStyle(el).display !== 'none') {
                            const btns = [...el.querySelectorAll(
                                "button, a, [role='button']")]
                                .map(b => (b.textContent||"").trim())
                                .filter(t => t);
                            return {caption: (el.textContent||"").trim()
                                    .slice(0,200), texts: btns.slice(0,12)};
                        }
                    }
                }
                return null;
            }""")
        except Exception:
            return None

    async def _static_click(self, page):
        for sel in self.STATIC_SELECTORS:
            try:
                el = page.locator(sel).first
                if await el.is_visible():
                    await el.click(timeout=2000)
                    await asyncio.sleep(0.4)
                    self.static_hits += 1
                    return True
            except Exception:
                continue
        known = list(self.STATIC_ACCEPT) + \
            [e["button"].lower() for e in self.learned.values() if e.get("button")]
        for text in known:
            try:
                el = page.locator(
                    f"button:has-text(\"{text}\"), a:has-text(\"{text}\"), "
                    f"[role='button']:has-text(\"{text}\")").first
                if await el.is_visible():
                    await el.click(timeout=2000)
                    await asyncio.sleep(0.4)
                    self.static_hits += 1
                    return True
            except Exception:
                continue
        return False

    async def _learned_click(self, page, overlay):
        fp = self._fingerprint(overlay)
        entry = self.learned.get(fp)
        if not entry or not entry.get("button"):
            return None
        if entry["button"] not in overlay.get("texts", []):
            return None
        try:
            el = page.locator(f"button:has-text(\"{entry['button']}\"), "
                              f"a:has-text(\"{entry['button']}\")").first
            await el.click(timeout=2000)
            await asyncio.sleep(0.4)
            self.learned_hits += 1
            entry["hits"] = entry.get("hits", 0) + 1
            self._save_learned()
            return True
        except Exception:
            return None

    async def _ai_click(self, page, overlay, log):
        if not AI.enabled:
            return False
        answer = await asyncio.to_thread(AI.popup_button,
                                          overlay.get("caption", ""),
                                          overlay.get("texts", []))
        if not answer:
            return False
        for txt in overlay.get("texts", []):
            if txt.lower() in answer.lower() or answer.lower() in txt.lower():
                try:
                    await page.locator(f"button:has-text(\"{txt}\")").first \
                        .click(timeout=3000)
                    await asyncio.sleep(0.4)
                    self.ai_hits += 1
                    fp = self._fingerprint(overlay)
                    self.learned[fp] = {"button": txt, "hits": 1,
                                        "learned_at": datetime.now().isoformat(),
                                        "caption": overlay["caption"][:120]}
                    self._save_learned()
                    log(f"AI dismissed '{txt}' +  learned it")
                    return True
                except Exception:
                    continue
        return False

    async def sweep(self, page, log):
        if await self._static_click(page):
            return True
        overlay = await self.blocked_by(page)
        if not overlay or not overlay.get("texts"):
            return False
        learned = await self._learned_click(page, overlay)
        if learned:
            log("popup dismissed ( learned — instant)")
            return True
        if await self._ai_click(page, overlay, log):
            return True
        return False


# ═════════════════════════════════════════════
#   IMAP OTP FISHER (catch-all)
# ═════════════════════════════════════════════

class IMAPFisher:
    TM_SENDERS = ("ticketmaster", "tm-bot", "noreply", "tix")

    def __init__(self, cfg=None):
        c = cfg or CONFIG.get("imap", {})
        self.email = c.get("email", "")
        self.password = c.get("password", "")
        self.host = c.get("host", "")
        self.port = int(c.get("port", 993))
        self.ssl = c.get("ssl", True)

    @staticmethod
    def mailboxes():
        boxes = list((CONFIG.get("imap") or {}).get("mailboxes") or [])
        if boxes:
            return [b for b in boxes if b.get("email") and b.get("host") and b.get("password")]
        imap = CONFIG.get("imap") or {}
        if imap.get("email") and imap.get("host") and imap.get("password"):
            return [imap]
        return []

    @property
    def enabled(self):
        if self.email and self.password and self.host:
            return True
        return bool(IMAPFisher.mailboxes())

    def _connect(self):
        mb = (imaplib.IMAP4_SSL(self.host, self.port) if self.ssl
              else imaplib.IMAP4(self.host, self.port))
        mb.login(self.email, self.password)
        mb.select("INBOX")
        return mb

    @staticmethod
    def _body(msg):
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() in ("text/plain", "text/html"):
                    try:
                        return part.get_payload(decode=True).decode(errors="ignore")
                    except Exception:
                        continue
            return ""
        try:
            return msg.get_payload(decode=True).decode(errors="ignore")
        except Exception:
            return ""

    @staticmethod
    def _extract_code(text):
        m = re.search(r"(?:code|verify|verification|passcode|pin)"
                      r"[^0-9]{0,40}\b(\d{6})\b", text, re.I)
        if m:
            return m.group(1)
        weak = re.findall(r"(?<![\d.])(\d{6})(?![\d.])", text)
        return weak[0] if weak else None

    def scan_once(self, account_email, since):
        try:
            mb = self._connect()
            date_str = since.strftime("%d-%b-%Y")
            _, ids = mb.search(None, f'(UNSEEN SINCE "{date_str}")')
            if not ids or not ids[0]:
                return None
            for mid in ids[0].split()[-25:]:
                _, data = mb.fetch(mid, "(RFC822)")
                if not data or not data[0]:
                    continue
                msg = message_from_bytes(data[0][1])
                to_list = [a[1].lower() for a in
                           getaddresses(msg.get_all("To", []) or [])]
                if account_email.lower() not in to_list:
                    continue
                frm = " ".join(a[1].lower() for a in
                              getaddresses(msg.get_all("From", []) or []))
                if frm and not any(s in frm for s in self.TM_SENDERS):
                    continue
                body = self._body(msg)
                code = self._extract_code(body) or \
                    self._extract_code(str(msg.get("Subject", "")))
                if code:
                    mb.store(mid, "+FLAGS", "\\Seen")
                    return code
            return None
        except Exception as e:
            print(f"IMAP error: {e}")
            return None

    def wait_for_otp(self, account_email, since, timeout=120):
        boxes = self.mailboxes() or ([
            {"email": self.email, "password": self.password, "host": self.host,
             "port": self.port, "ssl": self.ssl}] if self.email and self.host else [])
        if not boxes:
            return None
        t0 = time.time()
        print(f"fishing OTP for {account_email}…")
        while time.time() - t0 < timeout:
            for box in boxes:
                code = IMAPFisher(box).scan_once(account_email, since)
                if code:
                    print(f"OTP {code} in {time.time()-t0:.0f}s")
                    return code
            time.sleep(4)
        return None

    @staticmethod
    def fetch_headers(cfg, page=0, size=8):
        from email.header import decode_header
        mb = IMAPFisher(cfg)._connect()
        try:
            mb.select("INBOX", readonly=True)
            _, data = mb.search(None, "ALL")
            ids = data[0].split() if data and data[0] else []
            total = len(ids)
            newest = list(reversed(ids))
            chunk = newest[page * size:(page + 1) * size]
            rows = []
            for mid in chunk:
                _, msgdata = mb.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
                raw = b""
                if msgdata and isinstance(msgdata[0], tuple):
                    raw = msgdata[0][1] or b""
                msg = message_from_bytes(raw)

                def dec(value):
                    if not value:
                        return ""
                    out = []
                    for text, enc in decode_header(value):
                        if isinstance(text, bytes):
                            out.append(text.decode(enc or "utf-8", errors="ignore"))
                        else:
                            out.append(text)
                    return " ".join(s.strip() for s in out if s).strip()

                rows.append({
                    "subject": dec(msg.get("Subject")) or "(no subject)",
                    "from": dec(msg.get("From")),
                    "date": dec(msg.get("Date")),
                })
            return rows, total
        finally:
            try:
                mb.logout()
            except Exception:
                pass

    def test_connection(self):
        try:
            mb = self._connect()
            _, cnt = mb.search(None, "ALL")
            n = len(cnt[0].split()) if cnt and cnt[0] else 0
            return True, f" connected to {self.host} — {n} mail(s)"
        except Exception as e:
            return False, f" {e}"


# ═════════════════════════════════════════════
#   DISCORD (ONE channel, async-safe)
# ═════════════════════════════════════════════

EMOJI = {"queue": (0x5865F2, ""), "carted": (0x57F287, ""),
         "fail": (0xED4245, ""), "info": (0x99AAB5, "ℹ")}


class DiscordNotifier:
    _POOL = concurrent.futures.ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="discord")

    def __init__(self, url):
        self.webhook_url = url
        self.fail_count = 0

    def test(self):
        url = (self.webhook_url or "").strip()
        if not url or "YOUR_WEBHOOK" in url:
            return False, "paste the Discord webhook URL first"
        if not url.startswith("https://discord.com/api/webhooks/") and not url.startswith("https://discordapp.com/api/webhooks/"):
            return False, "that is not a Discord webhook URL"
        try:
            r = requests.post(
                url,
                json={"username": "Karma Ultra",
                      "content": "Webhook test. If you see this, Discord is connected."},
                headers={"User-Agent": "KarmaUltra"},
                timeout=15)
            if r.status_code in (200, 204):
                return True, "test message sent to the channel"
            return False, f"HTTP {r.status_code}: {r.text[:160]}"
        except Exception as e:
            return False, f"webhook unreachable: {e}"

    def _post(self, payload, file_path=None, extra_files=None):
        for _ in range(2):
            handles = []
            try:
                files = {}
                if file_path and Path(file_path).exists():
                    fh = open(file_path, "rb")
                    handles.append(fh)
                    files["files[0]"] = (Path(file_path).name, fh, "image/png")
                for i, item in enumerate(extra_files or [], start=len(files)):
                    files[f"files[{i}]"] = item
                if files:
                    r = requests.post(self.webhook_url, data={"payload_json": json.dumps(payload)},
                                      files=files, timeout=15)
                else:
                    r = requests.post(self.webhook_url, json=payload, timeout=15)
                if r.status_code in (200, 204):
                    self.fail_count = 0
                    return True
                print(f"webhook HTTP {r.status_code}")
            except Exception as e:
                print(f"webhook: {e}")
            finally:
                for fh in handles:
                    fh.close()
            time.sleep(2)
        self.fail_count += 1
        return False

    @staticmethod
    def brand_icon():
        candidates = []
        here = Path(__file__).resolve().parent
        candidates += [here / "icon.png", here / "icon.ico", Path.cwd() / "icon.png", Path.cwd() / "icon.ico"]
        me = getattr(sys, "_MEIPASS", None)
        if me:
            candidates += [Path(me) / "icon.png", Path(me) / "icon.ico"]
        for path in candidates:
            if not path.exists():
                continue
            if path.suffix.lower() == ".png":
                return path.read_bytes()
            try:
                from PIL import Image
                import io
                img = Image.open(path).convert("RGBA")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue()
            except Exception:
                continue
        return None

    def send(self, kind, title, description="", fields=None, content="",
             file_path=None, thumbnail=None, footer=None, color=None,
             footer_icon=False, stamp=True, cookies_file=None):
        default_color, icon = EMOJI.get(kind, EMOJI["info"])
        embed = {"title": title if not icon else f"{icon} {title}",
                 "description": description or None,
                 "color": color if color is not None else default_color,
                 "footer": {"text": footer or (
                     f"Karma Ultra • {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")}}
        if stamp:
            embed["timestamp"] = datetime.now(timezone.utc).isoformat()
        extra = []
        if footer_icon:
            raw = self.brand_icon()
            if raw:
                embed["footer"]["icon_url"] = "attachment://karma.png"
                extra.append(("karma.png", raw, "image/png"))
        if cookies_file:
            extra.append(("cookies.json", cookies_file, "application/json"))
        if thumbnail:
            embed["thumbnail"] = {"url": thumbnail}
        if fields:
            embed["fields"] = [{"name": n, "value": str(v) or "—", "inline": i}
                               for n, v, i in fields]
        payload = {k: v for k, v in {"content": content,
                                     "username": "Karma Ultra",
                                     "embeds": [embed]}.items() if v}
        DiscordNotifier._POOL.submit(self._post, payload, file_path, extra or None)

    @staticmethod
    def cookie_file(cookies):
        same_map = {"none": "no_restriction", "lax": "lax", "strict": "strict"}
        out = []
        for c in cookies or []:
            if not c.get("name"):
                continue
            same = same_map.get(str(c.get("sameSite") or "lax").lower(), "lax")
            exp = c.get("expires") or 0
            out.append({
                "name": c.get("name"),
                "value": c.get("value", ""),
                "domain": c.get("domain") or "",
                "path": c.get("path") or "/",
                "expirationDate": exp if exp and exp > 0 else None,
                "httpOnly": bool(c.get("httpOnly")),
                "secure": bool(c.get("secure")),
                "sameSite": same,
            })
        if not out:
            return None
        return json.dumps(out, ensure_ascii=False).encode("utf-8")

    def notify_queue_passed(self, task_id, gn, cookies, url):
        cookie_bytes = DiscordNotifier.cookie_file(cookies) if cookies else None
        count = len(cookies or [])
        self.send(
            "queue", f"QUEUE PASSED — [{gn}]",
            description="Import the attached cookies.json, then open the event link.",
            fields=[
                ("Task", task_id, True),
                ("Event", f"[Open event]({url})", True),
                ("Cookies", f"Full browser jar attached ({count} cookies)." if cookie_bytes else "No cookies captured.", False),
            ],
            cookies_file=cookie_bytes,
        )

    def notify_carted(self, task_id, gn, section, row, seats, qty, unit,
                      total, expires, checkout_url, contiguous, bap_heals,
                      currency="$", tg_min=0, tg_max=0, screenshot=None,
                      email="", mode="normal", event_name="", store="",
                      image=None, cookies=None, event_url="",
                      when="", venue="", ticket_text="", total_label=""):
        cfg = CONFIG["discord"]
        mention = f"<@{cfg['mention_user_id']}>" if cfg.get("mention_user_id") else ""
        cur = {"$": "USD", "€": "EUR", "£": "GBP"}.get(currency, currency or "USD")
        price = f"{total:,.2f} {cur} ({unit:,.2f} x {qty})"
        ticket = f"Section: {section or '—'}"
        if row and row != "—":
            ticket += f" · Row {row}"
        if seats:
            ticket += f" · {', '.join(str(s) for s in seats)}"
        host = f"{event_url} {checkout_url}".lower()
        if not store:
            if "ticketmaster.co.uk" in host:
                store = "Ticketmaster UK"
            elif "ticketmaster.de" in host:
                store = "Ticketmaster DE"
            elif "ticketmaster.nl" in host:
                store = "Ticketmaster NL"
            elif "ticketmaster.fr" in host:
                store = "Ticketmaster FR"
            elif "ticketmaster.ca" in host:
                store = "Ticketmaster CA"
            elif "livenation" in host:
                store = "Live Nation"
            else:
                store = "Ticketmaster US"
        desc = ""
        if isinstance(expires, datetime):
            ts = int(expires.timestamp())
            desc = f"Expires <t:{ts}:f> (<t:{ts}:R>)"
        if cfg.get("include_cart_link", True) and checkout_url:
            desc = (desc + "\n" if desc else "") + f"[Complete the checkout]({checkout_url})"
        if not image and screenshot:
            image = f"attachment://{Path(screenshot).name}"
        if ticket_text:
            ticket = ticket_text
        fields = [
            ("Store", store, True),
            ("Email", email or "—", True),
            ("Event", event_name or gn, False),
            ("When", when or "—", True),
            ("Venue", venue or "—", True),
            ("Price", total_label or price, True),
            ("Mode", (mode or "normal").title(), True),
            ("Quantity", str(qty), True),
            ("Ticket", ticket, False),
        ]
        cookie_bytes = DiscordNotifier.cookie_file(cookies) if cookies else None
        if cookie_bytes:
            fields.append(("Cookies", f"Full browser jar attached ({len(cookies)} cookies). Import cookies.json, then open the checkout link.", False))
        self.send("carted", "Karma Ultra Successful Checkout",
                  description=desc,
                  content=mention, fields=fields,
                  file_path=screenshot if cfg.get("include_screenshot") else None,
                  thumbnail=image, color=0x3B82F6,
                  footer=f"Karma Ultra • {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
                  footer_icon=True, stamp=False, cookies_file=cookie_bytes)

    def notify_bap(self, task_id, gn, hits, heals):
        self.send("fail", f" BAP Auto-Healed — [{gn}]",
                  description=f"Paused **{hits}×** — `.tmpt` removed & refreshed "
                              f"automatically ({heals} heals). No action needed.")

    def fail(self, task_id, gn, reason):
        self.send("fail", f"Failed — [{gn}]",
                  fields=[(" Task", str(task_id), True),
                          (" Reason", str(reason)[:400], False)])

    def info(self, title, msg):
        self.send("info", title, description=msg)


# ═════════════════════════════════════════════
#  ACCOUNTS / PROXIES (groups) / CAPTCHA
# ═════════════════════════════════════════════

class AccountGenerator:
    FIRST = ["James", "Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Sophia"]
    LAST = ["Smith", "Johnson", "Brown", "Wilson", "Taylor", "Clark", "Lewis",
            "Walker"]

    @staticmethod
    def _rand(n=10):
        return "".join(random.choice(string.ascii_letters + string.digits)
                      for _ in range(n))

    @staticmethod
    def random_email():
        dom = CONFIG.get("imap", {}).get("domain_hint", "")
        if dom:
            return f"tm.bot.{AccountGenerator._rand(8).lower()}@{dom}"
        try:
            d = requests.get("https://api.mail.tm/domains", timeout=10) \
                     .json()["hydra:member"][0]["domain"]
            return f"tm.bot.{AccountGenerator._rand(8).lower()}@{d}"
        except Exception:
            return f"tm.bot.{AccountGenerator._rand(8).lower()}@gmail.com"

    def create(self, group="default"):
        return {"email": self.random_email(),
                "password": self._rand(14),
                "first_name": random.choice(self.FIRST),
                "last_name": random.choice(self.LAST),
                "phone": f"+1{random.randint(2000000000, 9999999999)}",
                "created_at": datetime.now().isoformat(),
                "group": group, "verified": False, "used": False,
                "status": "ok", "otp_fails": 0}


class ProxyGroupManager:
    @staticmethod
    def load():
        return jload(PROXY_GROUPS_FILE, {})

    @staticmethod
    def save(groups):
        jsave(PROXY_GROUPS_FILE, groups)

    @staticmethod
    def get(group="any"):
        g = ProxyGroupManager.load()
        if group in ("any", "", None):
            flat = [p for lst in g.values() for p in lst]
            random.shuffle(flat)
            return flat
        return g.get(group, [])

    @staticmethod
    def to_playwright(line):
        if "@" in line:
            creds, _, host = line.partition("@")
            u, _, pw = creds.partition(":")
            return {"server": f"http://{host}", "username": u, "password": pw}
        return {"server": f"http://{line}"}


class ProxyManager:
    def __init__(self):
        self.proxies, self.i, self.lock = [], 0, threading.Lock()
        if PROXIES_FILE.exists():
            with open(PROXIES_FILE) as f:
                self.proxies = [l.strip() for l in f if l.strip()]

    def next(self):
        with self.lock:
            if not self.proxies:
                return None
            p = self.proxies[self.i % len(self.proxies)]
            self.i += 1
            return {"server": f"http://{p}"}


class CaptchaSolver:
    def __init__(self, key=None):
        self.key = key or CONFIG["captcha"]["api_key"]

    async def solve(self, public_key, site_url):
        async with httpx.AsyncClient(timeout=30) as c:
            r = (await c.post("https://api.capsolver.com/createTask", json={
                "clientKey": self.key,
                "task": {"type": "FunCaptchaTaskProxyLess",
                         "websitePublicKey": public_key,
                         "websiteURL": site_url}})).json()
            t0 = time.time()
            while time.time() - t0 < 180:
                res = (await c.post("https://api.capsolver.com/getTaskResult", json={
                    "clientKey": self.key, "taskId": r.get("taskId")})).json()
                if res.get("status") == "ready":
                    return res["solution"]["token"]
                await asyncio.sleep(2)
        raise TimeoutError("captcha solve timeout")


# ═════════════════════════════════════════════
#  BROWSER ENGINE (hybrid + proxy groups + proxy continuity)
# ═════════════════════════════════════════════

def prepare_playwright() -> str:
    """Point a frozen exe at the Chromium already installed for the user."""
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    browsers = Path(local) / "ms-playwright"
    notes = []
    if browsers.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)
        notes.append(f"browsers {browsers}")
    else:
        notes.append("browsers folder missing")
    if not getattr(sys, "frozen", False):
        return " ".join(notes)
    cli = None
    bundled = Path(getattr(sys, "_MEIPASS", "")) / "playwright" / "driver" / "package" / "cli.js"
    found = []
    if bundled.exists():
        found.append(bundled)
    root = Path(local)
    found += sorted(root.glob("Python/pythoncore-*/Lib/site-packages/playwright/driver/package/cli.js"))
    found += sorted(root.glob("Programs/Python/Python*/Lib/site-packages/playwright/driver/package/cli.js"))
    cli = found[-1] if found else None
    if cli is None:
        notes.append("driver missing")
        return " ".join(notes)
    node = cli.parent.parent / "node.exe"
    if not node.exists():
        notes.append(f"node missing at {node}")
        return " ".join(notes)
    import playwright._impl._driver as drv
    drv.compute_driver_executable = lambda n=str(node), c=str(cli): (n, c)
    notes.append("driver linked")
    return " ".join(notes)


class BrowserEngine:
    STEALTH_JS = ("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                 "Object.defineProperty(navigator,'languages',"
                 "{get:()=>['en-US','en']});window.chrome={runtime:{}};")
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

    def __init__(self, pm, headless=True, hybrid=True):
        self.browser_note = prepare_playwright()
        from playwright.async_api import async_playwright
        self.pw = async_playwright()
        self.pm, self.headless, self.hybrid = pm, headless, hybrid
        self._plock = threading.Lock()
        self._pi = {}
        self._started = False
        self._last_proxy = None

    async def start(self):
        if not self._started:
            self.pw_ = await self.pw.start()
            self._started = True

    async def stop(self):
        if self._started:
            await self.pw_.stop()
            self._started = False

    def _next_proxy(self, group):
        with self._plock:
            pool = ProxyGroupManager.get(group)
            if not pool:
                return self.pm.next() if self.pm.proxies else None
            line = pool[self._pi.get(group, 0) % len(pool)]
            self._pi[group] = self._pi.get(group, 0) + 1
            return ProxyGroupManager.to_playwright(line)

    async def new_context(self, headless=None, email=None, proxy_group="any",
                          force_visible=False):
        headless = False if force_visible else \
            (self.headless if headless is None else headless)
        proxy = self._next_proxy(proxy_group)
        self._last_proxy = proxy
        browser = await asyncio.wait_for(self.pw_.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"]), timeout=30)
        saved = SessionVault.load(email) if email else None
        storage = None
        if isinstance(saved, dict):
            storage = {"cookies": saved.get("cookies") or [],
                       "origins": saved.get("origins") or []}
        ctx = await browser.new_context(
            proxy=proxy, user_agent=self.UA,
            viewport={"width": 1920, "height": 1080}, locale="en-US",
            storage_state=storage)
        await ctx.add_init_script(self.STEALTH_JS)
        return browser, ctx

    async def go_visible(self, ctx):
        state = ctx.storage_state()
        if asyncio.iscoroutine(state):
            state = await state
        state = SessionVault._scrub(state)
        browser = await self.pw_.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled",
                  "--window-position=100,50"])
        c = await browser.new_context(user_agent=self.UA, locale="en-US",
                                      storage_state=state,
                                      proxy=self._last_proxy)
        await c.add_init_script(self.STEALTH_JS)
        return browser, c


# ═════════════════════════════════════════════
#   SECTION FILTER (+AI intent)
# ═════════════════════════════════════════════

class SectionFilter:
    @staticmethod
    def _norm(s):
        return re.sub(r"\s+", " ", s.lower()).strip()

    @staticmethod
    def _filter_matches(f_, s_):
        f_, s_ = SectionFilter._norm(f_), SectionFilter._norm(s_)
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", f_)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            return any(lo <= int(n) <= hi for n in re.findall(r"\d+", s_))
        m = re.fullmatch(r"(.+?)\s+(\d+)\s*-\s*(\d+)", f_)
        if m:
            w, lo, hi = m.group(1), int(m.group(2)), int(m.group(3))
            return (w in s_ and
                    any(lo <= int(n) <= hi for n in re.findall(r"\d+", s_)))
        return f_ in s_

    @staticmethod
    def allowed(section_name, tg):
        if not tg.sections:
            return True
        matches = any(SectionFilter._filter_matches(f, section_name)
                      for f in tg.sections)
        verdict = matches if tg.section_mode == "include" else not matches
        if not verdict and AI.enabled:
            for f in tg.sections:
                if AI.section_matches(f, section_name, tg.section_mode) is True:
                    return True if tg.section_mode == "include" else False
        return verdict

    @staticmethod
    def describe(tg):
        if not tg.sections:
            return "any section"
        mode = "ONLY" if tg.section_mode == "include" else "NOT"
        return f"{mode}: {', '.join(tg.sections)}"


def seats_contiguous(nums):
    if len(nums) < 2:
        return True
    s = sorted(int(x) for x in nums)
    return all(b - a == 1 for a, b in zip(s, s[1:]))


def extract_seat_numbers(text):
    nums = []
    for m in re.finditer(r"seats?\s*:?\s*(\d+)\s*[-–]\s*(\d+)", text, re.I):
        nums.extend(range(int(m.group(1)), int(m.group(2)) + 1))
    for m in re.finditer(r"seats?\s*:?\s*((?:\d+[,\s]+)+\d+)", text, re.I):
        for x in re.findall(r"\d+", m.group(1)):
            if int(x) not in nums:
                nums.append(int(x))
    for m in re.finditer(r"seat\s+(\d+)\b", text, re.I):
        if int(m.group(1)) not in nums:
            nums.append(int(m.group(1)))
    return nums


# ═════════════════════════════════════════════
#   PURCHASE BOT
# ═════════════════════════════════════════════

CAPTCHA_HOSTS = ("arkoselabs", "funcaptcha", "arkose")


class PurchaseBot:
    def __init__(self, engine, solver, notifier, tg):
        self.engine, self.solver, self.discord = engine, solver, notifier
        self.tg = tg
        self.task_id = uuid.uuid4().hex[:8]
        self.bap = BaPGuard()
        self.popup = PopupGuard()
        self.imap = IMAPFisher()
        self.currency = "$"
        self._takeover = False

    @staticmethod
    def _page_is_queue(url, html):
        u = (url or "").lower()
        if "queue.ticketmaster." in u or "queue-it.net" in u or "/queue" in u:
            return True
        low = (html or "").lower()
        return any(x in low for x in (
            "you are now in line", "your estimated wait",
            "you are now in the queue", "people ahead of you",
            "users ahead of you", "personen voor je",
            "welcome to the waiting room", "until sale begins",
        ))

    @staticmethod
    def _read_queue(text):
        if not text:
            return None
        qid = ""
        found = re.search(r"queue\s*id\s*[:#]?\s*([A-Za-z0-9-]{8,})", text, re.I)
        if found:
            qid = found.group(1)
        patterns = (
            r"([\d][\d\s,\.]*)\s*(?:people|persons|personnes|personen|mensen|persone|personas)?\s*(?:ahead of you|voor je|voor u|vor dir|devant vous|delante|davanti|à sua frente)",
            r"(?:you are now in the queue|now in the queue|in de wachtrij|warteschlange|file d'attente).{0,120}?([\d][\d\s,\.]*)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.I | re.S)
            if not match:
                continue
            digits = re.sub(r"[^\d]", "", match.group(1))
            if digits:
                return {"pos": int(digits), "queue_id": qid}
        return None

    async def _page_text(self, page):
        try:
            data = await page.evaluate("""() => {
                const text = (document.body && document.body.innerText) || '';
                const img = [...document.querySelectorAll('img')]
                    .map(i => ({src: i.currentSrc || i.src || '', w: i.naturalWidth || i.width || 0, alt: i.alt || ''}))
                    .find(i => i.src && i.w >= 48 && !/logo|icon|sprite|svg/i.test(i.src + i.alt));
                return {text, image: img ? img.src : ''};
            }""")
        except Exception:
            return ""
        self._last_checkout_image = (data or {}).get("image") or ""
        return (data or {}).get("text") or ""

    async def _where(self, page):
        url = (page.url or "").lower()
        text = (await self._page_text(page) or "").lower()
        if "/checkout" in url or "afrekenen" in text or "resterende tijd" in text:
            return "checkout"
        if "passkey" in text or "niet nu" in text and "passkey" in text:
            return "passkey"
        if any(x in url for x in ("auth.ticketmaster", "sign-in", "/login")) or "e-mailadres" in text or "wachtwoord" in text:
            return "sign-in"
        if any(x in text for x in ("waiting room", "wachtruimte", "mins until", "personen voor je", "people ahead")):
            return "queue"
        if any(x in text for x in ("best beschikbaar", "per stuk", "doorgaan", "tickets zoeken")):
            return "tickets"
        if any(x in text for x in ("plattegrond", "selecteer je plaatsen", "seat map")):
            return "map"
        return "event"

    @staticmethod
    def _is_checkout_text(text):
        low = (text or "").lower()
        has_cart = any(w in low for w in ("afrekenen", "checkout", "resterende tijd", "time remaining", "time left"))
        has_total = any(w in low for w in ("totaal", "total", "zitplaatsen", "tickets"))
        return bool(text and has_cart and has_total)

    def _is_ticket_page(text):
        low = (text or "").lower()
        return any(w in low for w in (
            "selecteer je plaatsen", "plattegrond", "best beschikbaar",
            "bekijk plattegrond", "select tickets", "seat map", "choose your seats",
            "staansplaatsen", "staanplaatsen",
        ))

    @staticmethod
    def _is_lobby(text):
        low = (text or "").lower()
        return any(w in low for w in (
            "join waiting room", "waiting room", "the lobby", "the sale begins",
            "wachtruimte", "de verkoop begint", "warteraum", "salle d'attente",
            "sala de espera", "sala d'attesa", "venterom", "väntrum",
        ))

    async def _join_waiting_room(self, page, log):
        prefer = re.compile(
            r"join waiting|waiting room|wachtruimte|wachtrij|warteraum|"
            r"salle d'attente|sala de espera|sala d'attesa|venterom|väntrum|"
            r"join the queue|deelnemen|beitreten|rejoindre|unirse|entrar na sala",
            re.I)
        skip = re.compile(
            r"what is|wat is|qu.est|was ist|check your account|keep you|"
            r"sign in|inloggen|log in|account",
            re.I)
        deadline = time.time() + 15
        while time.time() < deadline:
            for scope in await self._scopes(page):
                try:
                    buttons = scope.locator("button, a")
                    count = min(await buttons.count(), 25)
                except Exception:
                    continue
                for i in range(count):
                    el = buttons.nth(i)
                    try:
                        if not await el.is_visible():
                            continue
                        name = re.sub(r"\s+", " ", (await el.inner_text() or "")).strip()
                        if not name or len(name) > 60 or skip.search(name):
                            continue
                        if prefer.search(name):
                            await el.click(timeout=5000)
                            log(f"[{self.tg.name}] pressed {name}")
                            return True
                    except Exception:
                        continue
            await asyncio.sleep(0.4)
        return False

    @staticmethod
    def _read_wait(text):
        if not text:
            return None
        low = text.lower()
        if not any(w in low for w in (
            "waiting room", "wachtruimte", "warteraum", "salle d'attente",
            "sala de espera", "until sale", "sale begins", "tot de verkoop",
            "verkauf beginnt",
        )):
            return None
        hours = minutes = seconds = 0
        hm = re.search(r"(\d+)\s*(hours?|uur|stunden?|heures?|horas?)\b", text, re.I)
        mm = re.search(r"(\d+)\s*(mins?|minutes?|minuten|minuut)\b", text, re.I)
        sm = re.search(r"(\d+)\s*(secs?|seconds?|seconden)\b", text, re.I)
        if hm:
            hours = int(hm.group(1))
        if mm:
            minutes = int(mm.group(1))
        if sm:
            seconds = int(sm.group(1))
        if not (hours or minutes or seconds):
            return None
        if hours:
            label = f"{hours}h {minutes}m" if minutes else f"{hours}h"
        elif minutes:
            label = f"{minutes}m"
        else:
            label = f"{seconds}s"
        qid = ""
        found = re.search(r"queue\s*id\s*[:#]?\s*([A-Za-z0-9-]{8,})", text, re.I)
        if found:
            qid = found.group(1)
        return {"label": label, "seconds": hours * 3600 + minutes * 60 + seconds, "queue_id": qid}

    async def _watch_waiting_room(self, page, email, log):
        seen = False
        last = ""
        idle = 0
        deadline = time.time() + 3 * 3600
        while time.time() < deadline:
            info = self._read_wait(await self._page_text(page))
            if info:
                seen = True
                idle = 0
                STATUS.update(self.task_id, state="waiting", wait_label=info["label"],
                              queue_id=info["queue_id"], wait_seconds=info["seconds"])
                if info["label"] != last:
                    last = info["label"]
                    update_account(email, wait_left=info["label"], wait_queue=info["queue_id"])
                    extra = f" — {info['queue_id']}" if info["queue_id"] else ""
                    log(f"[{self.tg.name}] waiting room {info['label']} left{extra}")
            else:
                idle += 1
                if seen or idle >= 8:
                    if seen:
                        log(f"[{self.tg.name}] waiting room ended")
                        update_account(email, wait_left="", wait_queue="")
                        STATUS.update(self.task_id, state="queue", wait_label="")
                    else:
                        log(f"[{self.tg.name}] waiting room has no timer")
                    return
            await asyncio.sleep(2)

    async def _dismiss_cookies(self, page, log):
        names = (
            "Accept Cookies", "Reject All", "Accept all", "Allow all",
            "Alles accepteren", "Alle cookies accepteren", "Accepteren",
            "Weigeren", "Alles weigeren",
        )
        for _ in range(3):
            clicked = False
            for scope in await self._scopes(page):
                for name in names:
                    try:
                        btn = scope.get_by_role("button", name=name)
                        if await btn.count() and await btn.first.is_visible():
                            await btn.first.click(timeout=2500)
                            log(f"[{self.tg.name}] dismissed cookies: {name}")
                            await asyncio.sleep(0.6)
                            clicked = True
                            break
                    except Exception:
                        continue
                if clicked:
                    break
            if not clicked:
                try:
                    clicked = await page.evaluate("""() => {
                        const words = /accept cookies|reject all|alles accepteren|accepteren|weigeren|allow all/i;
                        const nodes = [...document.querySelectorAll('button, a, [role="button"]')];
                        const hit = nodes.find(el => words.test((el.innerText || '').trim()) && el.offsetParent);
                        if (!hit) return false;
                        hit.click();
                        return true;
                    }""")
                except Exception:
                    clicked = False
                if clicked:
                    log(f"[{self.tg.name}] dismissed cookies")
                    await asyncio.sleep(0.6)
            if not clicked:
                break
        await self.popup.sweep(page, log)

    async def _click_label(self, page, labels):
        for label in labels:
            for scope in await self._scopes(page):
                try:
                    el = scope.get_by_text(label, exact=True).first
                    if await el.count() and await el.is_visible():
                        await el.click(timeout=3000)
                        return label
                except Exception:
                    continue
                try:
                    btn = scope.get_by_role("button", name=label).first
                    if await btn.count() and await btn.is_visible():
                        await btn.click(timeout=3000)
                        return label
                except Exception:
                    continue
        return ""

    async def _map_moved(self, page):
        url = (page.url or "").lower()
        text = (await self._page_text(page) or "").lower()
        return any(x in url for x in ("auth.ticketmaster", "checkout", "/afrekenen")) or any(
            x in text for x in ("resterende tijd", "wachtwoord", "e-mailadres", "passkey toevoegen")
        )

    async def _raise_best_available(self, page, tg, qty, lo, hi):
        text = await self._page_text(page) or ""
        blocked = re.compile(r"rolstoel|wheelchair|accessible|invalide|invalid|mindervalide|gehandicap|disabled|companion|begeleider", re.I)
        names = []
        for name, raw in re.findall(r"(Golden Circle|Staanplaatsen|Zitplaatsen|Official Platinum Ticket)\s*€\s*([\d.]+,\d{2})", text):
            if blocked.search(name):
                continue
            price = float(raw.replace(".", "").replace(",", "."))
            if hi > 0 and not (lo <= price <= hi):
                continue
            if name not in [n for n, _ in names]:
                names.append((name, price))
        if not names:
            return {"ok": False, "found": 0, "qty": 0, "text": "no ticket rows"}
        name, price = random.choice(names)
        target = page.get_by_text(name, exact=True).first
        try:
            await target.wait_for(state="visible", timeout=4000)
            box = await target.bounding_box()
        except Exception:
            return {"ok": False, "found": len(names), "qty": 0, "text": f"{name} not visible"}
        plus = None
        buttons = page.locator("button, [role='button']")
        try:
            count = min(await buttons.count(), 80)
        except Exception:
            count = 0
        best_x = -1
        for i in range(count):
            btn = buttons.nth(i)
            try:
                if not await btn.is_visible():
                    continue
                b = await btn.bounding_box()
                if not b or not box:
                    continue
                if abs((b["y"] + b["height"] / 2) - (box["y"] + 12)) > 36:
                    continue
                if b["x"] < box["x"] + 30 or b["width"] > 70:
                    continue
                if b["x"] > best_x:
                    best_x = b["x"]
                    plus = btn
            except Exception:
                continue
        current = 0
        shown = re.search(rf"{re.escape(name)}\s*€.*?per stuk\s*(\d+)", text, re.I)
        if shown:
            current = int(shown.group(1))
        if plus is None and box:
            x = box["x"] + box["width"] + 210
            y = box["y"] + box["height"] / 2
            for _ in range(qty - current):
                await page.mouse.click(x, y)
                await asyncio.sleep(0.15)
            fresh = await self._page_text(page) or ""
            found = re.search(rf"{re.escape(name)}\s*€.*?per stuk\s*(\d+)", fresh, re.I)
            current = int(found.group(1)) if found else current
            return {"ok": current >= qty, "found": len(names), "qty": current, "text": f"{name} €{price:.2f}"}
        for _ in range(qty + 1):
            if current >= qty:
                break
            try:
                await plus.click(timeout=2000, force=True)
            except Exception:
                break
            await asyncio.sleep(0.15)
            fresh = await self._page_text(page) or ""
            found = re.search(rf"{re.escape(name)}\s*€.*?per stuk\s*(\d+)", fresh, re.I)
            current = int(found.group(1)) if found else current
        return {"ok": current >= qty, "found": len(names), "qty": current, "text": f"{name} €{price:.2f}"}

    async def _ai_click(self, page, log, goal):
        if not AI.enabled:
            return False
        try:
            buttons = await page.evaluate("""() => [...document.querySelectorAll('button, a, [role="button"]')]
                .map(el => (el.innerText || el.getAttribute('aria-label') || '').trim())
                .filter(t => t && t.length < 40)
                .slice(0, 40)""")
        except Exception:
            buttons = []
        if not buttons:
            return False
        choice = await asyncio.to_thread(AI.next_click, await self._page_text(page), buttons, goal)
        if not choice:
            return False
        log(f"[{self.tg.name}] AI says click {choice}")
        pressed = await self._click_label(page, (choice,))
        if pressed:
            await asyncio.sleep(0.4)
            return True
        return False

    async def _pick_from_map(self, page, tg, log):
        await self._dismiss_cookies(page, log)
        qty = max(1, int(getattr(tg, "quantity", 1) or 1))
        lo = float(getattr(tg, "min_price", 0) or 0)
        hi = float(getattr(tg, "max_price", 0) or 0)
        for attempt in range(1, 7):
            log(f"[{tg.name}] seat try {attempt}")
            opened = await self._click_label(page, ("Best beschikbaar", "Best available", "Beste beschikbare"))
            if opened:
                log(f"[{tg.name}] opened {opened}")
                await asyncio.sleep(0.35)
            try:
                raised = await self._raise_best_available(page, tg, qty, lo, hi)
            except Exception as e:
                raised = {"ok": False, "found": 0}
                log(f"[{tg.name}] plus scan failed: {str(e).splitlines()[0]}")
            if raised and raised.get("ok"):
                confirmed = await self._quantity_is(page, qty, raised.get("text") or "")
                if not confirmed:
                    log(f"[{tg.name}] quantity is not {qty} yet — not pressing Doorgaan")
                else:
                    log(f"[{tg.name}] quantity {qty} confirmed — {raised.get('text')}")
                    await asyncio.sleep(0.2)
                    if await self._press_cart(page, tg, log):
                        return True
                    log(f"[{tg.name}] quantity set, Doorgaan still missing")
            elif raised and raised.get("qty"):
                log(f"[{tg.name}] quantity stayed {raised.get('qty')}, wanted {qty}")
            else:
                log(f"[{tg.name}] no ticket stepper — {raised.get('text') or raised.get('found', 0)}")
            # Map path only if the quick list is not there.
            section = await self._click_map_section(page, tg, attempt)
            if section:
                log(f"[{tg.name}] opened section {section}")
                await asyncio.sleep(0.45)
            seats = await self._click_adjacent_seats(page, qty)
            if seats:
                log(f"[{tg.name}] selected {seats} seat(s) next to each other")
                await asyncio.sleep(0.2)
                if seats >= qty and await self._press_cart(page, tg, log):
                    return True
                log(f"[{tg.name}] selected {seats}, wanted {qty}")
            if await self._map_moved(page):
                log(f"[{tg.name}] left the map")
                return True
            try:
                await page.get_by_text("Bekijk plattegrond", exact=False).first.click(timeout=2000)
            except Exception:
                pass
            await asyncio.sleep(0.2)
        log(f"[{tg.name}] seat map did not cart after retries")
        return False

    async def _click_map_section(self, page, tg, attempt):
        try:
            return await page.evaluate("""(attempt) => {
                const nodes = [...document.querySelectorAll('text, tspan, button, div, span, a, [role="button"]')];
                const hits = nodes.filter(el => {
                    const label = (el.textContent || '').trim();
                    if (!/^\\d{2,3}$/.test(label)) return false;
                    const around = ((el.parentElement && el.parentElement.innerText) || '').toLowerCase();
                    if (/rolstoel|wheelchair|accessible|invalide|invalid|mindervalide|gehandicap/.test(around)) return false;
                    const box = el.getBoundingClientRect();
                    return box.width > 10 && box.height > 10 && box.top > 90 && box.top < window.innerHeight - 40;
                });
                if (!hits.length) return '';
                const el = hits[(attempt - 1) % hits.length];
                const target = el.closest('button, a, [role="button"]') || el.parentElement || el;
                target.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
                return (el.textContent || '').trim();
            }""", attempt)
        except Exception:
            return ""

    async def _click_adjacent_seats(self, page, qty):
        try:
            return await page.evaluate("""(qty) => {
                const blueish = (el) => {
                    const s = getComputedStyle(el);
                    const blob = [s.fill, s.backgroundColor, s.stroke, el.getAttribute('fill'), el.getAttribute('stroke')].join(' ');
                    const m = blob.match(/rgb\\(\\s*(\\d+)\\s*,\\s*(\\d+)\\s*,\\s*(\\d+)/i);
                    if (m) return Number(m[3]) > 140 && Number(m[1]) < 120;
                    return /#(?:0|1|2)?[0-9a-f]{2}(?:6|7|8|9|a|b)[0-9a-f](?:c|d|e|f)[0-9a-f]/i.test(blob);
                };
                const nodes = [...document.querySelectorAll('circle, ellipse, [data-seat], [aria-label*="seat" i], [aria-label*="stoel" i]')];
                const seats = nodes.map(el => {
                    const box = el.getBoundingClientRect();
                    return {el, x: box.x + box.width / 2, y: box.y + box.height / 2, w: box.width, h: box.height};
                }).filter(s => s.w >= 5 && s.w <= 22 && s.h >= 5 && s.h <= 22 && s.y > 80 && blueish(s.el));
                if (seats.length < qty) return 0;
                seats.sort((a, b) => a.y - b.y || a.x - b.x);
                let pair = [];
                for (let i = 0; i < seats.length; i++) {
                    const group = [seats[i]];
                    for (let j = i + 1; j < seats.length && group.length < qty; j++) {
                        const prev = group[group.length - 1];
                        if (Math.abs(seats[j].y - seats[i].y) < 12 && seats[j].x > prev.x && seats[j].x - prev.x < 24) group.push(seats[j]);
                    }
                    if (group.length >= qty) { pair = group.slice(0, qty); break; }
                }
                if (pair.length < qty) return 0;
                pair.forEach(s => {
                    const target = s.el.closest('[role="button"], button') || s.el;
                    target.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
                });
                return pair.length;
            }""", qty)
        except Exception:
            return 0

    async def _quantity_is(self, page, qty, label):
        text = await self._page_text(page) or ""
        name = (label or "").split(" €")[0].strip()
        if name:
            found = re.search(rf"{re.escape(name)}\s*€.*?per stuk\s*(\d+)", text, re.I)
            if found and int(found.group(1)) == qty:
                return True
        basket = re.search(r"[×x]\s*(\d+)", text)
        if basket and int(basket.group(1)) == qty:
            return True
        return False

    async def _press_cart(self, page, tg, log):
        added = await self._click_label(page, (
            "DOORGAAN", "Doorgaan", "Toevoegen", "Selecteer", "Selecteren",
            "Ga verder", "Volgende", "Bestellen", "Afrekenen", "Checkout",
            "Continue", "Next", "Naar winkelwagen", "Bevestigen", "Confirm",
        ))
        if not added:
            try:
                added = await page.evaluate("""() => {
                    const words = /doorgaan|toevoegen|ga verder|volgende|afrekenen|checkout|continue|bevestigen/i;
                    const nodes = [...document.querySelectorAll('button, a, [role="button"]')];
                    const hit = nodes.find(el => words.test((el.innerText || el.getAttribute('aria-label') || '').trim()) && el.offsetParent);
                    if (!hit) return '';
                    hit.click();
                    return (hit.innerText || hit.getAttribute('aria-label') || 'cart').trim().slice(0, 40);
                }""")
            except Exception:
                added = ""
        if added:
            log(f"[{tg.name}] pressed {added}")
            await asyncio.sleep(0.45)
            return True
        return False

    def _parse_checkout(self, text):
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        blob = "\n".join(lines)
        info = {"image": getattr(self, "_last_checkout_image", "") or ""}
        timer = re.search(r"(?:resterende tijd|time remaining|time left)[^\d]{0,30}(\d{1,2}):(\d{2})", blob, re.I)
        if timer:
            info["minutes"] = int(timer.group(1))
            info["seconds"] = int(timer.group(2))
        money = re.search(r"(€|£|\$)\s*([\d\.\s]+,\d{2}|[\d,]+\.\d{2}|[\d\.\s]+)", blob)
        if not money:
            money = re.search(r"(?:totaal|total)[^\d€£$]{0,20}(€|£|\$)?\s*([\d\.\s]+,\d{2}|[\d,]+\.\d{2})", blob, re.I)
        if money:
            symbol = money.group(1) or "€"
            raw = money.group(2).strip().replace(" ", "")
            if "," in raw and "." in raw:
                raw = raw.replace(".", "").replace(",", ".") if raw.rfind(",") > raw.rfind(".") else raw.replace(",", "")
            elif "," in raw:
                raw = raw.replace(".", "").replace(",", ".")
            try:
                info["total"] = float(raw)
            except ValueError:
                info["total"] = None
            info["currency"] = {"€": "€", "£": "£", "$": "$"}.get(symbol, symbol)
            info["total_label"] = f"{symbol} {money.group(2).strip()}"
        qty = re.search(r"(?:zitplaatsen|seats|tickets)\s*x\s*(\d+)", blob, re.I)
        if qty:
            info["qty"] = int(qty.group(1))
        seat_line = ""
        for ln in lines:
            if re.search(r"vak\s+|row\s+|rij\s+|section\s+|stoel|seat", ln, re.I):
                seat_line = ln
                break
        if seat_line:
            info["ticket"] = re.sub(r"\s+", " ", seat_line)
            vak = re.search(r"vak\s+([^•·]+)", seat_line, re.I)
            row = re.search(r"(?:rij|row)\s+([A-Za-z0-9]+)", seat_line, re.I)
            seats = re.search(r"(?:stoelen|seats?)\s+([\d\s\-–]+)", seat_line, re.I)
            if vak:
                info["section"] = vak.group(1).strip(" -")
            if row:
                info["row"] = row.group(1)
            if seats:
                nums = re.findall(r"\d+", seats.group(1))
                info["seats"] = nums
        date_i = None
        for i, ln in enumerate(lines):
            if re.search(r"20\d{2}", ln) and re.search(r"\d{1,2}:\d{2}|jan|feb|mrt|maa|apr|mei|jun|jul|aug|sep|okt|oct|nov|dec", ln, re.I):
                if re.search(r"resterende|remaining", ln, re.I):
                    continue
                date_i = i
                break
        if date_i is not None:
            info["when"] = lines[date_i]
            title = []
            for ln in reversed(lines[max(0, date_i - 4):date_i]):
                if re.search(r"adres|tickets|totaal|total|afrekenen|checkout|bewerken|mobile", ln, re.I):
                    break
                title.append(ln)
            if title:
                info["event"] = " ".join(reversed(title))
            if date_i + 1 < len(lines):
                info["venue"] = lines[date_i + 1]
        return info

    async def apply_presale_code(self, page, log):
        tg = self.tg
        codes = [c.strip() for c in (tg.presale_codes or []) if c.strip()]
        if not codes:
            return True
        try:
            await page.wait_for_selector(
                "input[placeholder*='offer' i], input[placeholder*='code' i], "
                "button:has-text('Unlock'), text=/enter.*code/i", timeout=6000)
        except Exception:
            return True
        for code in codes:
            if code in tg.presale_played:
                continue
            try:
                box = page.locator("input[placeholder*='offer' i], "
                                    "input[placeholder*='code' i]").first
                await box.fill(code, timeout=5000)
                await page.locator(
                    "button:has-text('Unlock'), button:has-text('Submit'), "
                    "button:has-text('Apply')").first.click(timeout=5000)
                await asyncio.sleep(2)
                body = (await page.content()).lower()
                if not any(x in body for x in
                          ["invalid", "not valid", "expired", "incorrect code",
                           "code is not recognized", "try again"]):
                    tg.presale_played.append(code)
                    log(f"[{tg.name}] unlocked with {code}")
                    return True
            except Exception:
                continue
        return False

    async def _inject_captcha_token(self, page, token, log):
        try:
            found = await page.evaluate("""(token) => {
                let ok = false;
                for (const sel of ['#FunCaptcha-Token',
                                   'input[name="fc-token"]',
                                   'textarea[name="fc-token"]',
                                   'input[name="ARKOSE_TOKEN"]']) {
                    const el = document.querySelector(sel);
                    if (el) { el.value = token; ok = true; }
                }
                try {
                    window.postMessage(
                        JSON.stringify({eventId: 'challenge-complete',
                                        payload: {validation_token: token}}),
                        '*');
                    ok = true;
                } catch (e) {}
                return ok;
            }""", token)
            for sel in ["button:has-text('Verify You Are Human')",
                        "button:has-text('Continue')",
                        "[data-testid='submit-captcha']"]:
                try:
                    b = page.locator(sel).first
                    if await b.is_visible():
                        await b.click(timeout=2000)
                        break
                except Exception:
                    continue
            log(f"[{self.tg.name}] captcha token injected"
                f"{' (field+event)' if found else ' (event only)'}")
        except Exception as e:
            log(f"[{self.tg.name}] token inject: {e}")

    async def login_account(self, page, account, log):
        email = (account.get("email") or "").strip()
        password = account.get("password") or ""
        tg = self.tg
        if SessionVault.has(email):
            if await self._signed_in(page):
                await self._dismiss_passkey(page, log)
                log(f"[{tg.name}] saved session still signed in as {email}")
                return True
            log(f"[{tg.name}] saved session expired, signing in again")
        if not email or not password:
            log(f"[{tg.name}] {email or 'account'} has no password saved")
            return False
        if await self._signed_in(page):
            await self._dismiss_passkey(page, log)
            log(f"[{tg.name}] already signed in as {email}")
            return True
        event = self.tg.event_url or page.url
        already = any(x in page.url for x in ("auth.ticketmaster", "identity.ticketmaster", "sign-in", "/login"))
        if "/checkout" in page.url:
            log(f"[{tg.name}] checkout is open, skipping sign-in")
            return True
        if already:
            log(f"[{tg.name}] already on the sign-in page")
        else:
            log(f"[{tg.name}] opening sign-in for {email}")
            try:
                await page.wait_for_function(
                    "() => (document.body && (document.body.innerText || '').trim().length > 40)",
                    timeout=20000)
            except Exception:
                log(f"[{tg.name}] event page stayed blank")
                await self._log_page(page, log, f"[{tg.name}] blank event page")
                return False
            opened = await self._open_site_login(page)
            if not opened:
                text = await self._page_text(page)
                if "/checkout" in page.url or self._is_checkout_text(text):
                    log(f"[{tg.name}] no sign-in button because checkout is already open")
                    return True
                log(f"[{tg.name}] no sign-in button on the event page")
                await self._log_page(page, log, f"[{tg.name}] sign-in button missing")
                return False
            try:
                await page.wait_for_url(re.compile(r"auth\.ticketmaster|sign-in|login|identity\.ticketmaster"), timeout=20000)
            except Exception:
                pass
        log(f"[{tg.name}] sign-in page {page.url}")
        await self._dismiss_passkey(page, log)
        try:
            title = (await page.title()) or ""
        except Exception:
            title = ""
        if "error" in title.lower() or "unexpected error" in ((await self._page_text(page)) or "").lower():
            log(f"[{tg.name}] Ticketmaster rejected the login page: {title or 'error'}")
            await self._log_page(page, log, f"[{tg.name}] login error")
            return False
        email_re = re.compile(
            r"e-?mail|correo|courriel|posta|e-post|sähköposti|emailadres", re.I)
        try:
            await page.get_by_text(email_re).first.wait_for(timeout=15000)
            log(f"[{tg.name}] login card is on screen")
        except Exception:
            pass
        box = await self._labeled_box(page, email_re, 6000)
        if box is None:
            box = await self._visible_box(
                page, "input[type='email'], input[autocomplete='username'], input[name='email'], input[type='text']",
                6000)
        if box is None and await self._fill_shadow(page, email, "email"):
            log(f"[{tg.name}] email entered")
        elif box is None:
            text = (await self._page_text(page) or "").lower()
            if "passkey" in text or "niet nu" in text:
                await self._dismiss_passkey(page, log)
                log(f"[{tg.name}] saved session skipped the email box")
                try:
                    await SessionVault.save(page.context, email)
                except Exception:
                    pass
                return True
            await self._log_page(page, log, f"[{tg.name}] no email box")
            return False
        else:
            await box.click()
            await box.fill(email)
            log(f"[{tg.name}] email entered")
        pressed = await self._click_primary(page)
        if not pressed and box is not None:
            try:
                await box.press("Enter")
                pressed = "Enter"
            except Exception:
                pass
        if not pressed:
            log(f"[{tg.name}] could not press continue")
            return False
        log(f"[{tg.name}] pressed {pressed}")
        pw = await self._visible_box(page, "input[type='password']", 20000)
        if pw is None and await self._fill_shadow(page, password, "password"):
            log(f"[{tg.name}] password entered")
        elif pw is None:
            await self._log_page(page, log, f"[{tg.name}] no password box")
            return False
        else:
            await pw.click()
            await pw.fill(password)
            log(f"[{tg.name}] password entered")
        pressed = await self._click_primary(page)
        if not pressed and pw is not None:
            try:
                await pw.press("Enter")
                pressed = "Enter"
            except Exception:
                pass
        if not pressed:
            log(f"[{tg.name}] could not press sign-in")
            return False
        log(f"[{tg.name}] pressed {pressed}")
        await asyncio.sleep(2)
        await self._dismiss_passkey(page, log)
        if not await self.handle_otp(page, account, log):
            return False
        await self._dismiss_passkey(page, log)
        try:
            await SessionVault.save(page.context, email)
        except Exception:
            pass
        if any(x in page.url for x in ("sign-in", "login", "authorization.oauth2", "auth.ticketmaster")):
            try:
                await page.goto(event, wait_until="domcontentloaded", timeout=25000)
            except Exception as e:
                log(f"[{tg.name}] back to event failed: {str(e).splitlines()[0]}")
                return False
        log(f"[{tg.name}] signed in, back on the event")
        return True


    async def _dismiss_passkey(self, page, log):
        skip = re.compile(r"^\s*(niet nu|not now|skip|later|maybe later|nicht jetzt|später|pas maintenant|plus tard|ahora no)\s*$", re.I)
        for _ in range(6):
            text = (await self._page_text(page) or "").lower()
            if "passkey" not in text and "wachtwoord in te voeren" not in text:
                return False
            pressed = ""
            for scope in await self._scopes(page):
                try:
                    btn = scope.get_by_role("button", name=skip).first
                    if await btn.count() and await btn.is_visible():
                        await btn.click(timeout=3000)
                        pressed = "Niet nu"
                        break
                except Exception:
                    continue
                try:
                    btn = scope.get_by_text("Niet nu", exact=False).first
                    if await btn.count() and await btn.is_visible():
                        await btn.click(timeout=3000, force=True)
                        pressed = "Niet nu"
                        break
                except Exception:
                    continue
            if not pressed:
                try:
                    pressed = await page.evaluate("""() => {
                        const words = /^\\s*(niet nu|not now|skip|later|nicht jetzt|pas maintenant|ahora no)\\s*$/i;
                        const nodes = [...document.querySelectorAll('button, a, [role="button"], div')];
                        const hit = nodes.find(el => words.test((el.innerText || '').trim()) && el.offsetParent);
                        if (!hit) return '';
                        (hit.closest('button, a, [role="button"]') || hit).click();
                        return 'Niet nu';
                    }""")
                except Exception:
                    pressed = ""
            if pressed:
                log(f"[{self.tg.name}] skipped passkey")
                await asyncio.sleep(1)
                return True
            await asyncio.sleep(0.4)
        log(f"[{self.tg.name}] passkey prompt stayed open")
        return False

    async def _open_site_login(self, page):
        name_re = re.compile(r"inloggen|sign in|log in|aanmelden|se connecter|anmelden", re.I)
        deadline = time.time() + 20
        while time.time() < deadline:
            for scope in await self._scopes(page):
                for sel in (
                    "a[href*='sign-in']",
                    "a[href*='identity.ticketmaster']",
                    "a[href*='/login']",
                    "[data-testid*='account']",
                    "[data-testid*='sign-in']",
                    "[aria-label*='Inloggen' i]",
                    "[aria-label*='Sign in' i]",
                ):
                    try:
                        loc = scope.locator(sel).first
                        if await loc.count() and await loc.is_visible():
                            await loc.click(timeout=5000)
                            return True
                    except Exception:
                        continue
                for role in ("link", "button"):
                    try:
                        loc = scope.get_by_role(role, name=name_re)
                        count = await loc.count()
                    except Exception:
                        continue
                    for i in range(min(count, 6)):
                        el = loc.nth(i)
                        try:
                            label = (await el.inner_text() or "") + " " + (await el.get_attribute("aria-label") or "")
                            if re.search(r"passkey|vergeten|forgot", label, re.I):
                                continue
                            if await el.is_visible():
                                await el.click(timeout=5000)
                                return True
                        except Exception:
                            continue
                try:
                    clicked = await scope.evaluate("""() => {
                        const words = /inloggen|sign in|log in|aanmelden/i;
                        const skip = /passkey|vergeten|forgot/i;
                        const all = [];
                        const walk = (root) => {
                            if (!root || !root.querySelectorAll) return;
                            root.querySelectorAll('a,button,[role="button"]').forEach(el => all.push(el));
                            root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) walk(el.shadowRoot); });
                        };
                        walk(document);
                        const hit = all.find(el => {
                            const blob = ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('href') || ''));
                            return words.test(blob) && !skip.test(blob);
                        });
                        if (!hit) return false;
                        hit.click();
                        return true;
                    }""")
                    if clicked:
                        return True
                except Exception:
                    pass
            await asyncio.sleep(0.5)
        return False

    async def _scopes(self, page):
        scopes = [page]
        try:
            scopes.extend(page.frames)
        except Exception:
            pass
        return scopes

    async def _labeled_box(self, page, label_re, timeout_ms):
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            for scope in await self._scopes(page):
                try:
                    labels = scope.get_by_text(label_re)
                    if await labels.count() and await labels.first.is_visible():
                        box = labels.first.locator("xpath=following::input[1]")
                        if await box.count() and await box.first.is_visible():
                            return box.first
                except Exception:
                    pass
                for loc in (scope.get_by_label(label_re), scope.get_by_role("textbox", name=label_re)):
                    try:
                        if await loc.count() and await loc.first.is_visible():
                            return loc.first
                    except Exception:
                        continue
            await asyncio.sleep(0.3)
        return None

    async def _click_primary(self, page):
        skip = re.compile(
            r"passkey|terug|back|zuruck|zurück|retour|volver|atrás|forgot|vergeten|"
            r"vergessen|oubli|olvid|reset|aanmaken|sign up|registr|create",
            re.I)
        prefer = re.compile(
            r"doorgaan|continue|next|volgende|weiter|continuer|continuar|suivant|"
            r"siguiente|inloggen|sign in|log in|anmelden|connexion|entrar|accedi|"
            r"einloggen|submit|iniciar|prihlási|zaloguj|logga",
            re.I)
        for scope in await self._scopes(page):
            try:
                buttons = scope.locator("button, input[type='submit']")
                count = await buttons.count()
            except Exception:
                continue
            fallback = None
            fallback_name = ""
            for i in range(min(count, 12)):
                el = buttons.nth(i)
                try:
                    if not await el.is_visible():
                        continue
                    if await el.get_attribute("disabled") is not None:
                        continue
                    name = (await el.inner_text() or "").strip()
                    if skip.search(name):
                        continue
                    if prefer.search(name):
                        await el.click(timeout=5000)
                        return name or "submit"
                    if fallback is None:
                        fallback, fallback_name = el, name
                except Exception:
                    continue
            if fallback is not None:
                try:
                    await fallback.click(timeout=5000)
                    return fallback_name or "submit"
                except Exception:
                    continue
        return ""

    async def _visible_box(self, page, selector, timeout_ms):
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            scopes = [page]
            try:
                scopes.extend(page.frames)
            except Exception:
                pass
            for scope in scopes:
                try:
                    loc = scope.locator(selector)
                    count = min(await loc.count(), 6)
                except Exception:
                    continue
                for i in range(count):
                    el = loc.nth(i)
                    try:
                        if await el.is_visible():
                            return el
                    except Exception:
                        continue
            await asyncio.sleep(0.3)
        return None

    async def _fill_shadow(self, page, value, kind):
        script = """([value, kind]) => {
            const seen = [];
            const walk = (root) => {
                if (!root || !root.querySelectorAll) return;
                root.querySelectorAll('input').forEach(i => seen.push(i));
                root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) walk(el.shadowRoot); });
            };
            walk(document);
            const box = seen.find(i => {
                const blob = ((i.id || '') + ' ' + (i.name || '') + ' ' + (i.type || '') + ' ' + (i.getAttribute('autocomplete') || '')).toLowerCase();
                if (kind === 'password') return i.type === 'password' || blob.includes('pass');
                return /email|user/.test(blob) || i.type === 'email' || i.type === 'text';
            });
            if (!box) return false;
            box.focus();
            box.value = value;
            box.dispatchEvent(new Event('input', {bubbles: true}));
            box.dispatchEvent(new Event('change', {bubbles: true}));
            return true;
        }"""
        scopes = [page]
        try:
            scopes.extend(page.frames)
        except Exception:
            pass
        for scope in scopes:
            try:
                if await scope.evaluate(script, [value, kind]):
                    return True
            except Exception:
                continue
        return False

    async def _log_page(self, page, log, prefix):
        log(f"{prefix}")
        log(f"url: {page.url}")
        try:
            log(f"title: {await page.title()}")
        except Exception:
            pass
        try:
            frames = [f.url for f in page.frames if f.url and f.url != "about:blank" and f.url != page.url]
            if frames:
                log("frames: " + " | ".join(frames))
        except Exception:
            pass
        try:
            text = await page.evaluate("() => (document.body && document.body.innerText || '').replace(/\\s+/g, ' ').trim()")
            log("page text: " + (text or "(empty)"))
        except Exception as e:
            log(f"page text unreadable: {e}")

    async def _input_names(self, page):
        found = []
        scopes = [page]
        try:
            scopes.extend(page.frames)
        except Exception:
            pass
        for scope in scopes:
            try:
                rows = await scope.evaluate("""() => [...document.querySelectorAll('input')]
                    .slice(0, 8).map(i => (i.id || i.name || i.type || 'input'))""")
                found.extend(rows or [])
            except Exception:
                continue
        return ", ".join(found)[:140]

    async def _signed_in(self, page):
        try:
            out = page.get_by_role("link", name=re.compile(r"sign out|log out|uitloggen", re.I))
            if await out.count() and await out.first.is_visible():
                return True
        except Exception:
            pass
        try:
            link = page.get_by_role("link", name=re.compile(r"sign in|log in|inloggen", re.I))
            if await link.count() and await link.first.is_visible():
                return False
        except Exception:
            pass
        return False

    async def _choose_email_otp(self, page, log):
        email_re = re.compile(r"e-?mail", re.I)
        sms_re = re.compile(r"sms|text message|text me|phone|telefoon|sms-bericht", re.I)
        try:
            html = (await page.content()).lower()
        except Exception:
            return None
        if not any(w in html for w in ("sms", "text message", "text me", "telefoon")):
            return None
        radios = page.locator("input[type='radio']")
        try:
            radio_count = await radios.count()
        except Exception:
            radio_count = 0
        for i in range(radio_count):
            el = radios.nth(i)
            try:
                blob = " ".join(filter(None, [
                    await el.get_attribute("value"),
                    await el.get_attribute("id"),
                    await el.get_attribute("name"),
                    await el.get_attribute("aria-label"),
                ])).lower()
                if "email" not in blob and "e-mail" not in blob:
                    continue
                if any(w in blob for w in ("sms", "phone", "text")):
                    continue
                await el.click(timeout=1500, force=True)
                log(f"[{self.tg.name}] selected EMAIL, skipped SMS")
                picked = True
                break
            except Exception:
                continue
        if not picked:
            picked = False
        for role in ("radio", "button", "link"):
            try:
                loc = page.get_by_role(role, name=email_re)
                count = await loc.count()
            except Exception:
                continue
            for i in range(min(count, 6)):
                el = loc.nth(i)
                try:
                    label = (await el.inner_text()) or ""
                    if sms_re.search(label) or not await el.is_visible():
                        continue
                    await el.click(timeout=1200)
                    picked = True
                    log(f"[{self.tg.name}] chose email, not SMS")
                    break
                except Exception:
                    continue
            if picked:
                break
        if not picked:
            try:
                lab = page.locator("label, div, span").filter(has_text=email_re)
                count = await lab.count()
                for i in range(min(count, 8)):
                    el = lab.nth(i)
                    label = (await el.inner_text()) or ""
                    if sms_re.search(label) or len(label) > 80:
                        continue
                    if await el.is_visible():
                        await el.click(timeout=1200)
                        picked = True
                        log(f"[{self.tg.name}] chose email, not SMS")
                        break
            except Exception:
                pass
        if not picked:
            log(f"[{self.tg.name}] email option not found — not sending SMS")
            return False
        for name in ("E-mail", "Email", "Email me", "Send email", "Send code",
                     "Code per e-mail", "Stuur een e-mail", "Continue", "Verstuur", "Doorgaan"):
            try:
                btn = page.get_by_role("button", name=name).first
                text = (await btn.inner_text()) or ""
                if sms_re.search(text):
                    continue
                await btn.click(timeout=1000)
                break
            except Exception:
                continue
        return True

    async def handle_otp(self, page, account, log):
        choice = await self._choose_email_otp(page, log)
        if choice is False:
            return False
        try:
            await page.wait_for_selector(
                "input[autocomplete='one-time-code'], input[name*='code' i], "
                "input[placeholder*='code' i]",
                timeout=5000)
        except Exception:
            return True
        if not self.imap.enabled:
            log(f"[{self.tg.name}] OTP is asking for email, but IMAP is not set in Settings")
            return False
        log(f"[{self.tg.name}] OTP screen — reading IMAP for {account.get('email')}")
        STATUS.update(self.task_id, state="otp")
        since = datetime.now() - timedelta(minutes=2)
        code = await asyncio.to_thread(self.imap.wait_for_otp,
                                       account["email"], since, 120)
        if not code:
            still_ok = record_otp_result(account["email"], False,
                                        "no OTP email in timeout")
            code_, text = await asyncio.to_thread(explain_deep, code="TM-OTP")
            STATUS.error(self.task_id, "TM-OTP",
                         text + ("  account retired" if not still_ok else ""))
            self.discord.fail(self.task_id, self.tg.name,
                              f"TM-OTP — {text}")
            return False
        try:
            boxes = page.locator("input[autocomplete='one-time-code'], "
                                 "input[name*='code' i]")
            if await boxes.count() == 1:
                await boxes.first.fill(code, timeout=5000)
            else:
                for i, d in enumerate(code):
                    await boxes.nth(i).fill(d, timeout=3000)
            await page.locator("button:has-text('Verify'), "
                               "button:has-text('Submit'), "
                               "button:has-text('Continue')").first \
                .click(timeout=5000)
            await asyncio.sleep(2)
            record_otp_result(account["email"], True)
            log(f"[{self.tg.name}] OTP {code} submitted")
            return True
        except Exception as e:
            log(f"OTP fill error: {e}")
            return False

    async def offer_takeover(self, browser, context, page, reason, log):
        try:
            state = context.storage_state()
            if asyncio.iscoroutine(state):
                state = await state
            state = SessionVault._scrub(state)
            vb = await self.engine.pw_.chromium.launch(
                headless=False,
                args=["--window-position=80,40", "--start-maximized"])
            vctx = await vb.new_context(user_agent=self.engine.UA,
                                        locale="en-US",
                                        storage_state=state,
                                        proxy=self.engine._last_proxy)
            await vctx.add_init_script(self.engine.STEALTH_JS)
            vpage = await vctx.new_page()
            await vpage.goto(self.tg.event_url, wait_until="domcontentloaded",
                             timeout=25000)
            STATUS.update(self.task_id, state="failed",
                          takeover_available=True)
            self._takeover = True
            self.discord.fail(self.task_id, self.tg.name,
                              f" TAKEOVER OPEN ({reason}): visible browser "
                              f"with your session is on the event page — "
                              f"cart manually now.")
            log(f"[{self.tg.name}] takeover window open")
            hold = CONFIG["general"].get("keep_browser_open_min", 15) * 60
            end = time.time() + hold
            while time.time() < end and not vpage.is_closed():
                await asyncio.sleep(5)
        except Exception as e:
            log(f"takeover failed: {e}")

    async def run(self, account, log):
        tg = self.tg
        url, qty = tg.event_url, tg.quantity
        STATUS.create(self.task_id, tg.name, account["email"])
        country = getattr(tg, "country", "NL") or "NL"
        log(f"[{tg.name}] Ticketmaster {country}")
        log(f"[{tg.name}] qty={qty} | {tg.min_price}-{tg.max_price}/tk | "
            f"{SectionFilter.describe(tg)} | {'' if tg.contiguous else ''} | "
            f"pool:{tg.account_group} net:{tg.proxy_group}")

        had_session = SessionVault.has(account["email"])
        visible = not CONFIG["general"].get("headless", True)
        log(f"[{tg.name}] launching Chromium ({'visible' if visible else 'headless'}) "
            f"proxy={tg.proxy_group} session={'yes' if had_session else 'no'}")
        try:
            browser, context = await self.engine.new_context(
                headless=not visible, email=account["email"], proxy_group=tg.proxy_group)
        except asyncio.TimeoutError:
            log(f"[{tg.name}] Chromium did not open in 30s. Run: py -m playwright install chromium")
            STATUS.finish(self.task_id, done=False)
            return False
        except Exception as e:
            log(f"[{tg.name}] Chromium failed: {e}")
            if "executable" in str(e).lower() or "playwright" in str(e).lower():
                log("Install the browser with: py -m playwright install chromium")
            STATUS.finish(self.task_id, done=False)
            return False
        log(f"[{tg.name}] browser open")
        page = await context.new_page()

        async def route_guard(route):
            req = route.request
            if (req.resource_type in ("image", "media", "font")
                    and not any(h in req.url for h in CAPTCHA_HOSTS)):
                await route.abort()
            else:
                await route.continue_()
        await page.route("**/*", route_guard)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            log(f"[{tg.name}] page loaded — {page.url}")
            await self.popup.sweep(page, log)
            STATUS.update(self.task_id, popups=self.popup.static_hits +
                          self.popup.learned_hits + self.popup.ai_hits)

            self.currency = PriceEngine.detect_symbol(await page.content())
            log(f"[{tg.name}] currency: {self.currency}")
            try:
                await page.wait_for_function(
                    """() => {
                        const t = (document.body && document.body.innerText || '').toLowerCase();
                        return t.length > 40 && (
                            t.includes('plattegrond') || t.includes('selecteer je plaatsen') ||
                            t.includes('best beschikbaar') || t.includes('waiting room') ||
                            t.includes('wachtruimte') || t.includes('inloggen') || t.includes('sign in')
                        );
                    }""",
                    timeout=12000)
            except Exception:
                pass
            await self.popup.sweep(page, log)
            page_text = await self._page_text(page)
            ticket_first = self._is_ticket_page(page_text)
            if ticket_first:
                log(f"[{tg.name}] ticket page is open — carting before sign-in")
                await self._dismiss_cookies(page, log)
            elif self._is_lobby(page_text):
                log(f"[{tg.name}] waiting room is open")
                if await self._join_waiting_room(page, log):
                    log(f"[{tg.name}] joined the waiting room")
                else:
                    log(f"[{tg.name}] no join button")
                await asyncio.sleep(1)
                if any(x in page.url for x in ("auth.ticketmaster", "sign-in", "login")):
                    if not await self.login_account(page, account, log):
                        STATUS.finish(self.task_id, done=False)
                        return False
                await self._watch_waiting_room(page, account.get("email", ""), log)
            elif not await self.login_account(page, account, log):
                page_text = await self._page_text(page)
                if self._is_ticket_page(page_text):
                    ticket_first = True
                    log(f"[{tg.name}] seat map is open — carting before sign-in")
                    await self._dismiss_cookies(page, log)
                else:
                    STATUS.finish(self.task_id, done=False)
                    return False

            if await self.bap.guard(context, page, log):
                STATUS.update(self.task_id, bap_heals=self.bap.heals)
                self.discord.notify_bap(self.task_id, tg.name,
                                       self.bap.hits, self.bap.heals)

            text = await self._page_text(page)
            if not self._page_is_queue(page.url, text) and not self._read_queue(text):
                log(f"[{tg.name}] no queue — going to tickets")
                passed = True
            else:
                log(f"[{tg.name}] waiting for queue…")
                STATUS.update(self.task_id, state="queue")
                passed, t0, start_pos, last_pos = False, time.time(), None, None
                while not passed and time.time() - t0 < 4 * 3600:
                    text = await self._page_text(page)
                    low = text.lower()
                    info = self._read_queue(text)
                    if not self._page_is_queue(page.url, text) and not info:
                        passed = True
                        log(f"[{tg.name}] queue cleared")
                        update_account(account["email"], wait_left="", wait_queue="")
                        break
                    if info:
                        pos = info["pos"]
                        if start_pos is None and pos > 0:
                            start_pos = pos
                            record_queue_start(account["email"], tg.event_url, pos)
                        pct = (100 * (start_pos - pos) / start_pos) if start_pos else 0
                        STATUS.update(self.task_id, state="queue", queue_pos=pos,
                                      queue_pct=round(pct, 1), wait_label=f"#{pos}",
                                      queue_id=info.get("queue_id") or "")
                        if pos != last_pos:
                            last_pos = pos
                            update_account(account["email"], wait_left=f"#{pos}",
                                           wait_queue=info.get("queue_id") or "")
                            extra = f" — {info['queue_id']}" if info.get("queue_id") else ""
                            log(f"[{tg.name}] queue position {pos}{extra}")
                    if any(x in low for x in ("it's your turn", "select tickets",
                                             "het is jouw beurt")) and not info:
                        passed = True
                        STATUS.update(self.task_id, queue_pos=0, queue_pct=100.0)
                        break
                    if await self.popup.sweep(page, log):
                        STATUS.update(self.task_id,
                                     popups=self.popup.static_hits +
                                     self.popup.learned_hits + self.popup.ai_hits)
                    if await self.bap.guard(context, page, log):
                        STATUS.update(self.task_id, bap_heals=self.bap.heals)
                        self.discord.notify_bap(self.task_id, tg.name,
                                               self.bap.hits, self.bap.heals)
                    await asyncio.sleep(1)
            if not passed:
                code, text = await asyncio.to_thread(explain_deep,
                                                     code="TM-QUEUE-TIMEOUT")
                STATUS.error(self.task_id, code, text)
                self.discord.fail(self.task_id, tg.name, f"{code} — {text}")
                await self.offer_takeover(browser, context, page, code, log)
                return False

            cookies = await context.cookies()
            await SessionVault.save(context, account["email"])
            self.discord.notify_queue_passed(self.task_id, tg.name, cookies, url)
            log(f"[{tg.name}] queue passed "
                f"({' reused' if had_session else 'fresh'})")

            if self.engine.hybrid:
                vb, vctx = await self.engine.go_visible(context)
                await browser.close()
                browser, context = vb, vctx
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded",
                                timeout=25000)
                await self.popup.sweep(page, log)
                await self.bap.guard(context, page, log)

            if not await self.handle_otp(page, account, log):
                await self.offer_takeover(browser, context, page, "OTP", log)
                return False

            if not await self.apply_presale_code(page, log):
                code, text = await asyncio.to_thread(explain_deep,
                                                     code="TM-PRESALE-LOCKED")
                STATUS.error(self.task_id, code, text)
                self.discord.fail(self.task_id, tg.name, f"{code} — {text}")
                await self.offer_takeover(browser, context, page, code, log)
                return False
            await self.popup.sweep(page, log)

            selected = False
            STATUS.update(self.task_id, state="hunting")
            for label in ("Find Tickets", "See Tickets", "Get Tickets",
                          "Bekijk tickets", "Koop tickets"):
                try:
                    btn = page.get_by_role("link", name=label).first
                    if await btn.is_visible():
                        await btn.click(timeout=3000)
                        log(f"[{tg.name}] opened {label}")
                        break
                except Exception:
                    continue
            try:
                await page.wait_for_selector(
                    "[data-testid='ticket-list'], .ticket-list", timeout=2500)
            except Exception:
                if not self._is_ticket_page(await self._page_text(page)):
                    ctx_txt = (await page.content())[:1500]
                    ai_view = await asyncio.to_thread(AI.describe_page, ctx_txt) \
                        if AI.enabled else "—"
                    code, text = await asyncio.to_thread(explain_deep, None, "TM-SEL", ctx_txt)
                    log(f"page: {ai_view}")
                    STATUS.error(self.task_id, code, f"{text} ({ai_view})")
                    self.discord.fail(self.task_id, tg.name, f"{code} — {text} (page: {ai_view})")
                    await self.offer_takeover(browser, context, page, code, log)
                    return False
                log(f"[{tg.name}] using the seat map")
                if await self._pick_from_map(page, tg, log):
                    selected = True

            cart = {"section": "—", "row": "—", "unit": 0.0, "seats": []}
            offers = page.locator("div[aria-label]")
            total = min(await offers.count(), 60)
            for i in range(total):
                if selected:
                    break
                if i % 5 == 0 and await self.bap.guard(context, page, log):
                    STATUS.update(self.task_id, bap_heals=self.bap.heals)
                try:
                    el = offers.nth(i)
                    label = await el.get_attribute("aria-label") or ""
                    txt = label + "\n" + (await el.inner_text()
                                         if await el.is_visible() else "")
                except Exception:
                    continue
                section_name = label or txt.split("\n")[0]
                if not await asyncio.to_thread(SectionFilter.allowed,
                                               section_name, tg):
                    continue
                parsed = PriceEngine.parse_prices(txt)
                unit = parsed[0] if parsed else None
                em = re.search(r"(?:each|ea|per ticket)[^\d]{0,25}"
                               r"(?:MX\$|AR\$|R\$|£|€|\$|¥)\s?(\d[\d.,]*)",
                               txt, re.I)
                if em:
                    v = PriceEngine._num(em.group(1))
                    if v:
                        unit = v
                if unit is None or not PriceEngine.within(unit, tg):
                    continue
                avail = extract_seat_numbers(txt)
                m = re.search(r"(\d+)\s*(?:left|remaining|available)",
                              txt, re.I)
                n_avail = int(m.group(1)) if m else (len(avail) if avail else qty)
                if n_avail < qty:
                    continue
                if tg.contiguous and avail and len(avail) >= qty:
                    if not seats_contiguous(avail[:qty]):
                        continue
                try:
                    await el.click()
                except Exception:
                    continue
                rm = re.search(r"row\s+(\w+)", txt, re.I)
                cart.update(section=section_name[:40], unit=unit,
                           row=rm.group(1).upper() if rm else "—",
                           seats=[str(x) for x in avail[:qty]])
                selected = True
                log(f"[{tg.name}] {section_name[:30]} "
                    f"{self.currency}{unit} ×{qty}")
            if not selected:
                selected = await self._pick_from_map(page, tg, log)
            if not selected:
                code, text = await asyncio.to_thread(explain_deep,
                                                     code="TM-NO-MATCH")
                STATUS.error(self.task_id, code,
                             f"{text} ({SectionFilter.describe(tg)}, "
                             f"{self.currency}[{tg.min_price}-{tg.max_price}]/tk)")
                self.discord.fail(self.task_id, tg.name, f"{code} — {text}")
                await self.offer_takeover(browser, context, page, code, log)
                return False

            try:
                await page.wait_for_url(re.compile(r"/checkout"), timeout=4000)
            except Exception:
                pass
            where = await self._where(page)
            log(f"[{tg.name}] page is {where}")
            if where == "checkout":
                log(f"[{tg.name}] already on checkout — sending the card")
            elif where == "passkey":
                await self._dismiss_passkey(page, log)
                where = await self._where(page)
                log(f"[{tg.name}] page is {where}")
            elif ticket_first and where != "checkout":
                log(f"[{tg.name}] seats held — signing in now")
                if not await self.login_account(page, account, log):
                    page_text = await self._page_text(page)
                    if "/checkout" in page.url or self._is_checkout_text(page_text):
                        log(f"[{tg.name}] sign-in skipped, checkout is open")
                    else:
                        STATUS.finish(self.task_id, done=False)
                        return False

            try:
                await page.locator("select[name='quantity']") \
                    .select_option(str(qty))
            except Exception:
                try:
                    await page.locator(
                        f"button[aria-label='quantity {qty}'], "
                        f"[data-qty='{qty}']").first.click(timeout=3000)
                except Exception:
                    code, text = await asyncio.to_thread(explain_deep,
                                                         code="TM-QTY-FORCE")
                    STATUS.error(self.task_id, code, text)

            try:
                await page.wait_for_selector("#FunCaptcha-Arkose", timeout=4000)
                STATUS.update(self.task_id, state="captcha")
                log(f"[{tg.name}] solving captcha…")
                token = await self.solver.solve(
                    "A2A14B1D-1AF3-C791-9BBC-EE33CC7A0A6F", url)
                await self._inject_captcha_token(page, token, log)
            except Exception as e:
                if "timeout" in str(e).lower() and "captcha" in str(e).lower():
                    code, text = await asyncio.to_thread(
                        explain_deep, e, "TM-CAPTCHA-FAIL")
                    STATUS.error(self.task_id, code, text)
                    self.discord.fail(self.task_id, tg.name, f"{code} — {text}")
                    await self.offer_takeover(browser, context, page, code, log)
                    return False

            await self.handle_otp(page, account, log)
            page_text = await self._page_text(page)
            on_checkout = self._is_checkout_text(page_text)
            if not on_checkout:
                try:
                    await page.click("[data-bd='funzone']", timeout=8000)
                    await page.wait_for_load_state("domcontentloaded")
                    page_text = await self._page_text(page)
                    on_checkout = self._is_checkout_text(page_text)
                except Exception:
                    page_text = await self._page_text(page)
                    on_checkout = self._is_checkout_text(page_text)
            if not on_checkout:
                code, text = await asyncio.to_thread(
                    explain_deep, None, "TM-CART-FAIL", page_text[:800])
                STATUS.error(self.task_id, code, text)
                self.discord.fail(self.task_id, tg.name, f"{code} — {text}")
                await self.offer_takeover(browser, context, page, code, log)
                return False
            info = self._parse_checkout(page_text)
            log(f"[{tg.name}] checkout {info.get('total_label') or ''} {info.get('ticket') or ''}".strip())
            await self.bap.guard(context, page, log)

            body = await page.content()
            final_seats = extract_seat_numbers(body)
            if final_seats:
                cart["seats"] = [str(s) for s in final_seats[:qty]]
            contig = seats_contiguous(final_seats[:qty]) if final_seats else True
            checkout_url = url
            try:
                found = await page.evaluate("""() => {
                    const nodes = [...document.querySelectorAll('a[href]')];
                    const hit = nodes.find(el => /checkout|\\/cart|payment/i.test(el.href));
                    if (hit) return hit.href;
                    if (/checkout|cartId|payment/i.test(location.href)) return location.href;
                    return '';
                }""")
                if found:
                    checkout_url = found
            except Exception:
                if any(x in page.url for x in ("/checkout", "cartId", "payment")):
                    checkout_url = page.url
            if info.get("qty"):
                qty = int(info["qty"])
            if info.get("total") is not None:
                cart["unit"] = round(info["total"] / max(qty, 1), 2)
            if info.get("currency"):
                self.currency = info["currency"]
            if info.get("section"):
                cart["section"] = info["section"]
            if info.get("row"):
                cart["row"] = info["row"]
            if info.get("seats"):
                cart["seats"] = info["seats"]
            expires = datetime.now() + timedelta(minutes=10)
            if info.get("minutes") is not None:
                expires = datetime.now() + timedelta(minutes=int(info["minutes"]), seconds=int(info.get("seconds") or 0))
            checkout_url = page.url or url

            await SessionVault.save(context, account["email"])
            STATUS.update(self.task_id, state="carted")
            shot = str(SHOTS_DIR / f"cart_{self.task_id}.png")
            await page.screenshot(path=shot)
            event_name = info.get("event") or tg.event_url
            image = info.get("image") or None
            if image and str(image).startswith("//"):
                image = "https:" + image
            try:
                cookies = await context.cookies()
            except Exception:
                cookies = []
            log(f"[{tg.name}] sending cart card")
            self.discord.notify_carted(
                self.task_id, tg.name, cart["section"], cart["row"], cart["seats"],
                qty, cart["unit"], round(cart["unit"] * qty, 2), expires,
                checkout_url, contig, self.bap.heals, self.currency,
                tg.min_price, tg.max_price, shot,
                email=account.get("email", ""),
                mode=getattr(tg, "mode", "normal"),
                event_name=event_name, image=image, cookies=cookies,
                event_url=tg.event_url, when=info.get("when") or "",
                venue=info.get("venue") or "", ticket_text=info.get("ticket") or "",
                total_label=info.get("total_label") or "")
            log(f"[{tg.name}] CARTED ×{qty} @ {self.currency}"
                f"{cart['unit']}/tk — link sent")

            STATUS.update(self.task_id, state="holding")
            hold = ((expires - datetime.now()).total_seconds() +
                    CONFIG["general"].get("keep_browser_open_min", 15) * 60)
            end, last = time.time() + max(hold, 0), time.time()
            while time.time() < end:
                await asyncio.sleep(5)
                if page.is_closed():
                    break
                await self.bap.guard(context, page, log)
                if time.time() - last > 120:
                    await SessionVault.save(context, account["email"])
                    last = time.time()
            STATUS.finish(self.task_id, done=True)
            return True

        except Exception as e:
            log(f"[{tg.name}] {type(e).__name__}: {e}")
            for tb_line in traceback.format_exc().splitlines():
                log(tb_line)
            STATUS.error(self.task_id, type(e).__name__, str(e).splitlines()[0][:300] if str(e) else type(e).__name__)
            STATUS.finish(self.task_id, done=False)
            return False
        finally:
            try:
                await SessionVault.save(context, account["email"])
            except Exception:
                pass
            if not self._takeover:
                try:
                    await browser.close()
                except Exception:
                    pass


# ═════════════════════════════════════════════
#   RESTOCK MONITOR (JSON backbone, non-blocking auto-cart)
# ═════════════════════════════════════════════

class RestockMonitor:
    UAS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ",
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    ]

    def __init__(self, notifier, log):
        self.discord, self.log = notifier, log
        cfg = CONFIG["restock"]
        self.poll_interval = cfg.get("poll_interval_sec", 180)
        self.jitter = cfg.get("jitter_sec", 60)
        self.auto_cart = cfg.get("auto_cart", True)
        self.min_qty = cfg.get("min_qty_available", 1)
        self.state, self.backoff, self.api_fails = {}, 1, {}

    @staticmethod
    def event_id_from_url(url):
        m = re.search(r"/event/([A-Za-z0-9]{8,20})", url)
        if m:
            return m.group(1)
        if re.fullmatch(r"[A-Za-z0-9]{8,20}", url.strip()):
            return url.strip()
        return None

    @staticmethod
    def parse_event_line(line):
        parts = [p.strip() for p in line.split("::")]
        rc = CONFIG["restock"]
        return {"url": parts[0],
                "qty": int(parts[1]) if len(parts) > 1 and parts[1].isdigit()
                      else rc.get("default_qty", 2),
                "min_price": float(parts[2]) if len(parts) > 2
                             else rc.get("min_price", 0.0),
                "max_price": float(parts[3]) if len(parts) > 3
                             else rc.get("max_price", 250.0),
                "sections": [s.strip() for s in parts[4].split(",")]
                            if len(parts) > 4 else rc.get("default_sections", []),
                "codes": [c.strip() for c in parts[5].split(",")]
                         if len(parts) > 5 else rc.get("default_presale_codes", []),
                "proxy_group": parts[6] if len(parts) > 6 else "any"}

    def _headers(self, api=False):
        h = {"User-Agent": random.choice(self.UAS),
             "Accept-Language": "en-US,en;q=0.9",
             "Accept": "application/json" if api else
                       "text/html,application/xhtml+xml,*/*;q=0.8"}
        if api:
            h["Origin"] = "https://www.ticketmaster.com"
            h["Referer"] = "https://www.ticketmaster.com/"
        return h

    async def check_api(self, client, event_id):
        url = (f"https://availability.ticketmaster.com/api/v2/"
               f"availability/{event_id}")
        try:
            r = await client.get(url, headers=self._headers(api=True),
                                 timeout=15)
            if r.status_code == 200:
                data = r.json()
                offers = []
                for offer in data.get("offers", []):
                    attrs = {str(a.get("name", "")).strip().lower():
                             a.get("value", "")
                             for a in offer.get("attributes", [])}
                    price = PriceEngine._num(
                        str(attrs.get("price", "")).replace("$", ""))
                    mq = re.search(r"\d+",
                                   str(attrs.get("quantity",
                                                attrs.get("quantities")) or ""))
                    offers.append({"price": price,
                                   "qty": int(mq.group()) if mq else None,
                                   "section": attrs.get("section")
                                              or attrs.get("name") or ""})
                for seg in (data.get("offersByPrice") or []) + \
                           (data.get("segments") or []):
                    if isinstance(seg, dict):
                        p = PriceEngine._num(str(seg.get("price",
                                                    seg.get("amount", ""))))
                        if p is not None:
                            offers.append({"price": p, "qty": None,
                                           "section": seg.get("name", "")})
                self.api_fails[event_id] = 0
                prices = [o["price"] for o in offers if o["price"] is not None]
                return {"in_stock": bool(prices) or data.get("ticketable",
                                                             False),
                        "cheapest": min(prices) if prices else None,
                        "offers": offers, "source": "api"}
            elif r.status_code == 404:
                self.api_fails[event_id] = self.api_fails.get(event_id, 0) + 1
                return {"in_stock": False, "cheapest": None, "offers": [],
                        "source": "api-404"}
            else:
                self.api_fails[event_id] = self.api_fails.get(event_id, 0) + 1
                return None
        except Exception:
            self.api_fails[event_id] = self.api_fails.get(event_id, 0) + 1
            return None

    async def check_html(self, client, url):
        try:
            r = await client.get(url, headers=self._headers(), timeout=20,
                                 follow_redirects=True)
            html = r.text.lower()
            isin = any(m in html for m in
                       ["see tickets", "find tickets", "get tickets",
                        "best available", "tickets from"])
            sold = any(m in html for m in
                       ["sold out", "currently unavailable", "no tickets",
                        "not on sale"])
            prices = [p for p in (PriceEngine._num(x) for x in
                       re.findall(r"\$(\d{2,6}(?:\.\d{2})?)", html)[:30]) if p]
            return {"in_stock": isin and not sold,
                    "cheapest": min(prices) if prices else None,
                    "offers": [], "source": "html"}
        except Exception:
            return None

    async def check(self, client, url):
        eid = self.event_id_from_url(url)
        if eid and self.api_fails.get(eid, 0) < 3:
            result = await self.check_api(client, eid)
            if result is not None:
                return result
        return await self.check_html(client, url)

    @staticmethod
    def offers_signature(offers):
        return "|".join(sorted(f"{o['section']}@{o['price']}x{o['qty'] or '?'}"
                              for o in offers))

    def alert(self, url, info, is_new, filtered):
        mention = CONFIG["discord"].get("mention_user_id")
        lines = []
        for o in sorted(filtered, key=lambda x: x["price"] or 0)[:8]:
            qty_txt = f" ×{o['qty']}" if o.get("qty") else ""
            lines.append(f"`{o['section'] or 'General'}` — "
                         f"**${o['price']:,.2f}**{qty_txt}")
        title = " RESTOCK! Tickets Available" if is_new else " Offer Changed"
        self.discord.send("carted", title,
                          description=f"##  [**BUY HERE NOW**]({url})\n"
                                      + ("\n".join(lines) or "*(not itemized)*"),
                          content=f"<@{mention}>" if mention else "",
                          fields=[(" From",
                                   f"${info['cheapest']:,.2f}"
                                   if info.get("cheapest") else "—", True),
                                  (" Source", info["source"], True)])

    async def _trigger_cart(self, ev, cheapest):
        url, qty = ev["url"], ev["qty"]
        self.log(f"AUTO-CART: {self.event_id_from_url(url)} "
                 f"(qty={qty}, {ev['min_price']}-{ev['max_price']}/tk)")
        try:
            pm = ProxyManager()
            engine = BrowserEngine(pm, headless=CONFIG["general"]["headless"],
                                  hybrid=CONFIG["general"].get("hybrid_mode",
                                                                True))
            self.log(engine.browser_note)
            solver = CaptchaSolver()
            await engine.start()
            try:
                tg = TaskGroup(id=uuid.uuid4().hex[:8], name=" Restock",
                               event_url=url, quantity=qty,
                               min_price=ev["min_price"],
                               max_price=ev["max_price"],
                               contiguous=CONFIG["restock"].get(
                                   "default_contiguous", True),
                               sections=ev["sections"],
                               presale_codes=ev.get("codes", []),
                               proxy_group=ev.get("proxy_group", "any"),
                               max_tasks=1)
                accounts = accounts_in_group(ev.get("account_group") or "default")
                if not accounts:
                    raise RuntimeError("no healthy account in 'default' pool")
                accounts.sort(key=lambda a: not SessionVault.has(a["email"]))
                return await PurchaseBot(engine, solver, self.discord, tg) \
                    .run(accounts[0], self.log)
            finally:
                await engine.stop()
        except Exception as e:
            code, text = await asyncio.to_thread(explain_deep, e)
            self.log(f"auto-cart error: {text}")
            self.discord.fail("restock", " Auto-cart", f"{code} — {text}")
            return False

    async def run(self, stop_flag):
        events = []
        for g in load_groups():
            if not g.enabled:
                continue
            for t in g.tasks or []:
                if (t.get("mode") or "normal") != "restock":
                    continue
                events.append({
                    "url": t.get("event") or g.event_url,
                    "qty": int(t.get("quantity", g.quantity) or 2),
                    "min_price": float(t.get("min_price", g.min_price) or 0),
                    "max_price": float(t.get("max_price", g.max_price) or 250),
                    "sections": t.get("sections") or list(g.sections or []),
                    "codes": t.get("presale_codes") or list(g.presale_codes or []),
                    "proxy_group": t.get("proxy") or g.proxy_group,
                    "account_group": t.get("account") or g.account_group,
                })
        events = [e for e in events if self.event_id_from_url(e["url"])]
        if not events:
            self.log("no restock tasks")
            return
        self.log(f"monitor: {len(events)} event(s)")
        self.discord.info(" Restock Monitor Online",
                          f"JSON backbone • {len(events)} event(s) 24/7 • "
                          f"{'AUTO-CART & HOLD ' if self.auto_cart else 'notify-only'}")
        held = {}
        inflight = set()

        def _cart_done(url, task):
            inflight.discard(task)
            try:
                if not task.result():
                    held.pop(url, None)
            except Exception:
                held.pop(url, None)

        async with httpx.AsyncClient() as client:
            while not stop_flag[0]:
                hits = 0
                for ev in events:
                    url = ev["url"]
                    if stop_flag[0] or self.backoff > 1:
                        break
                    if url in held and time.time() - held[url] < 1200:
                        continue
                    await asyncio.sleep(random.uniform(2, 5))
                    info = await self.check(client, url)
                    if info is None:
                        self.backoff = min(self.backoff * 2, 10)
                        self.log(f"backing off ×{self.backoff}")
                        continue
                    self.backoff = max(1, self.backoff / 2)
                    prev = self.state.get(url, {"in_stock": False, "sig": ""})
                    filtered = [o for o in info.get("offers", [])
                                if o["price"] is not None
                                and ev["min_price"] <= o["price"] <= ev["max_price"]
                                and (o.get("qty") or self.min_qty) >= self.min_qty]
                    is_new = info["in_stock"] and not prev["in_stock"]
                    sig = self.offers_signature(filtered)
                    changed = info["in_stock"] and sig and sig != prev["sig"]
                    cheapest = info.get("cheapest")
                    price_ok = (cheapest is None or
                                ev["min_price"] <= cheapest <= ev["max_price"])
                    if info["in_stock"] and price_ok and (is_new or changed):
                        hits += 1
                        if self.auto_cart:
                            held[url] = time.time()
                            task = asyncio.create_task(
                                self._trigger_cart(ev, cheapest))
                            inflight.add(task)
                            task.add_done_callback(
                                lambda t, u=url: _cart_done(u, t))
                        else:
                            self.alert(url, info, is_new, filtered)
                    self.state[url] = {"in_stock": info["in_stock"], "sig": sig}
                total = self.poll_interval * self.backoff + \
                    random.uniform(0, self.jitter)
                self.log(f"sweep ({'hit' if hits else 'empty'}) -> {int(total)}s")
                end = time.time() + total
                while time.time() < end and not stop_flag[0]:
                    await asyncio.sleep(2)
        if inflight:
            self.log(f"waiting on {len(inflight)} cart attempt(s)…")
            await asyncio.gather(*inflight, return_exceptions=True)


# ═════════════════════════════════════════════
#  RUNNERS
# ═════════════════════════════════════════════

async def run_group(tg, engine, solver, notifier, log, stop_flag):
    accounts = accounts_in_group(tg.account_group)
    if not accounts and "@" in str(tg.account_group or ""):
        one = get_account(tg.account_group)
        accounts = [one] if one else []
    if not accounts:
        log(f"[{tg.name}] pool '{tg.account_group}' empty/unhealthy")
        return
    count = max(1, int(getattr(tg, "task_count", 0) or tg.max_tasks or 1))
    slots = [accounts[i % len(accounts)] for i in range(count)]
    per = {}
    for a in slots:
        per[a["email"]] = per.get(a["email"], 0) + 1
    log(f"[{tg.name}] {count} tasks, {len(accounts)} accounts, up to {max(per.values())} each")
    started = time.time()

    async def runner(acc):
        if stop_flag[0]:
            return False
        try:
            ok = await PurchaseBot(engine, solver, notifier, tg).run(acc, log)
        except Exception as e:
            log(f"[{tg.name}] {e}")
            return False
        if ok:
            update_account(acc["email"], used=True,
                           last_win=datetime.now().isoformat())
        return bool(ok)

    results = await asyncio.gather(
        *[runner(a) for a in slots],
        return_exceptions=True)
    wins = sum(1 for r in results if r is True)
    for r in results:
        if isinstance(r, Exception):
            log(f"[{tg.name}] {r}")
    log(f"[{tg.name}] finished — {wins} cart(s)")


async def run_all_groups(groups, log, stop_flag):
    active = []
    for g in groups:
        if not g.enabled:
            continue
        if not g.tasks:
            active.append(g)
            continue
        for t in g.tasks:
            if (t.get("mode") or "normal") == "restock":
                continue
            active.append(TaskGroup(
                id=t.get("id", g.id), name=g.name,
                event_url=t.get("event") or g.event_url,
                quantity=int(t.get("quantity", g.quantity) or 2),
                min_price=float(t.get("min_price", g.min_price) or 0),
                max_price=float(t.get("max_price", g.max_price) or 250),
                contiguous=bool(t.get("contiguous", g.contiguous)),
                section_mode=t.get("section_mode", g.section_mode) or "include",
                sections=t.get("sections") or [],
                account_group=t.get("account") or g.account_group,
                proxy_group=t.get("proxy") or g.proxy_group,
                max_tasks=int(t.get("task_count") or t.get("max_tasks") or g.max_tasks or 1),
                task_count=int(t.get("task_count") or t.get("max_tasks") or g.max_tasks or 1),
                enabled=True,
                presale_codes=t.get("presale_codes") or [],
                mode=(t.get("mode") or "normal"),
            ))
    if not active:
        return
    pm = ProxyManager()
    engine = BrowserEngine(pm, CONFIG["general"]["headless"],
                          CONFIG["general"].get("hybrid_mode", True))
    log(getattr(engine, "browser_note", ""))
    solver, notifier = CaptchaSolver(), DiscordNotifier(
        CONFIG["discord"]["webhook_url"])
    await engine.start()
    try:
        await asyncio.gather(*[run_group(g, engine, solver, notifier,
                                         log, stop_flag) for g in active])
    finally:
        await engine.stop()


async def run_restock(log, stop_flag):
    notifier = DiscordNotifier(CONFIG["discord"]["webhook_url"])
    await RestockMonitor(notifier, log).run(stop_flag)


# ═════════════════════════════════════════════
#   KARMA ULTRA — FUTURISTIC NEON GUI
# ═════════════════════════════════════════════

def run_gui():
    import customtkinter as ctk
    _CTkFont = ctk.CTkFont

    def CTkFont(*args, **kwargs):
        kwargs.setdefault("family", "Segoe UI")
        size = kwargs.get("size")
        if isinstance(size, int) and size < 15:
            kwargs["size"] = size + 2
        return _CTkFont(*args, **kwargs)

    ctk.CTkFont = CTkFont
    from tkinter import StringVar, BooleanVar, END as TKEND, messagebox
    import tkinter as tk

    # ── NEON FUTURISTIC PALETTE ──────────────────
    BG          = "#0C0F14"
    SIDEBAR     = "#090C11"
    CARD        = "#141922"
    CARD_HOVER  = "#1C2330"
    BORDER      = "#2A3342"
    ACCENT      = "#67C6F2"
    ACCENT2     = "#8B7CFF"
    ACCENT3     = "#E7B3C8"
    GREEN       = "#3DDC97"
    RED         = "#FF4466"
    YELLOW      = "#FFD60A"
    ORANGE      = "#FF8C42"
    TEXT        = "#E8E8F0"
    MUTED       = "#6B6B80"
    DIM         = "#3A3A50"

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    app = ctk.CTk()
    app.title("KARMA ULTRA")
    app.geometry("1280x780")
    app.minsize(1100, 680)
    app.configure(fg_color=BG)

    def _dark_title():
        if os.name != "nt":
            return
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(app.winfo_id())
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))

    app.after(50, _dark_title)

    # Make window draggable by the top bar
    def start_move(event):
        app._ox = event.x_root
        app._oy = event.y_root
        app._wx = app.winfo_x()
        app._wy = app.winfo_y()

    def do_move(event):
        app.geometry(f"+{app._wx + (event.x_root - app._ox)}+{app._wy + (event.y_root - app._oy)}")

    # Bind drag to the top bar later (after top is created)

    # ── STATE ────────────────────────────────────
    state = {
        "groups": load_groups(),
        "running": False,
        "stopref": [False],
        "selected": None,
        "page": "dashboard",
        "log_lines": [],
    }
    if not state["groups"]:
        state["groups"].append(TaskGroup(
            id=uuid.uuid4().hex[:8],
            name="Example Group",
            event_url="https://www.ticketmaster.com/event/your-event-id"))
        save_groups(state["groups"])

    # ── HELPERS ──────────────────────────────────
    def neon_btn(parent, text, color, cmd=None, width=None, height=34, **kw):
        return ctk.CTkButton(
            parent, text=text, command=cmd,
            fg_color=color, hover_color=_darken(color),
            text_color="#0A0A0F" if color in (ACCENT, GREEN, YELLOW) else TEXT,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            corner_radius=8, height=height, width=width,
            border_width=0, **kw)

    def _darken(hex_color, factor=0.75):
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"#{int(r*factor):02x}{int(g*factor):02x}{int(b*factor):02x}"

    def card(parent, **kw):
        return ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12,
                            border_width=1, border_color=BORDER, **kw)

    def section_label(parent, text):
        return ctk.CTkLabel(parent, text=text,
                            font=ctk.CTkFont(size=11, weight="bold"),
                            text_color=MUTED, anchor="w")

    def field_label(parent, text):
        return ctk.CTkLabel(parent, text=text,
                            font=ctk.CTkFont(size=11), text_color=MUTED, anchor="w")

    # ════════════════════════════════════════════
    #  TOP BAR (Vetro-style)
    # ════════════════════════════════════════════
    top = ctk.CTkFrame(app, fg_color="#0A0A0A", height=48, corner_radius=0)
    top.pack(fill="x")
    top.pack_propagate(False)

    # Left: logo + title
    left_top = ctk.CTkFrame(top, fg_color="transparent")
    left_top.pack(side="left", padx=12, pady=6)

    icon_path = Path(__file__).parent / "icon.ico"
    if not icon_path.exists():
        icon_path = Path.cwd() / "icon.ico"
    if icon_path.exists():
        try:
            from PIL import Image
            img = Image.open(icon_path).resize((22, 22), Image.LANCZOS)
            logo_img = ctk.CTkImage(light_image=img, dark_image=img, size=(22, 22))
            ctk.CTkLabel(left_top, image=logo_img, text="").pack(side="left", padx=(0, 8))
        except Exception:
            pass

    ctk.CTkLabel(left_top, text="KARMA ULTRA",
                 font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                 text_color=TEXT).pack(side="left")
    ctk.CTkLabel(left_top, text="  |  TASKS",
                 font=ctk.CTkFont(size=12), text_color=MUTED).pack(side="left", padx=(4, 0))

    # Right: status + window controls
    right_top = ctk.CTkFrame(top, fg_color="transparent")
    right_top.pack(side="right", padx=8, pady=6)

    # Status pill (compact)
    status_pill = ctk.CTkFrame(right_top, fg_color="#1A1A1A", corner_radius=12,
                               border_width=1, border_color=YELLOW)
    status_pill.pack(side="left", padx=(0, 12))
    status_dot = ctk.CTkLabel(status_pill, text="●", font=ctk.CTkFont(size=9),
                              text_color=YELLOW)
    status_dot.pack(side="left", padx=(8, 3), pady=3)
    status_lbl = ctk.CTkLabel(status_pill, text="IDLE",
                              font=ctk.CTkFont(size=10, weight="bold"),
                              text_color=YELLOW)
    status_lbl.pack(side="left", padx=(0, 8), pady=3)

    accent_line = ctk.CTkFrame(app, height=1, fg_color="#1A1A24", corner_radius=0)
    accent_line.pack(fill="x")

    update_bar = ctk.CTkFrame(app, fg_color="#10242C", height=48, corner_radius=0)
    update_bar.pack_propagate(False)
    ctk.CTkLabel(update_bar, text="", width=28,
                 font=ctk.CTkFont(size=16, weight="bold"),
                 text_color=ACCENT).pack(side="left", padx=(12, 4))
    update_title = ctk.CTkLabel(update_bar, text="Update available",
                                font=ctk.CTkFont(size=13, weight="bold"),
                                text_color=TEXT)
    update_title.pack(side="left", padx=(4, 8))
    update_note = ctk.CTkLabel(update_bar, text="",
                               font=ctk.CTkFont(size=12), text_color=MUTED)
    update_note.pack(side="left", padx=(0, 8))

    update_state = {"shown": None, "dismissed": None}

    def dismiss_update():
        update_state["dismissed"] = update_state.get("shown")
        update_bar.pack_forget()

    def show_update_banner(ver, note):
        update_state["shown"] = ver
        update_title.configure(text=f"Update available: v{ver}")
        update_note.configure(text=f"—  {note}" if note else "", text_color=MUTED)
        if not update_bar.winfo_ismapped():
            update_bar.pack(fill="x", before=body)

    def refresh_update_check():
        def work():
            url = UPDATE_URL
            is_new, ver, _msg = Updater.check(url)
            def apply():
                if is_new and update_state.get("dismissed") != ver:
                    show_update_banner(ver, Updater.last_note)
                elif not is_new and update_bar.winfo_ismapped():
                    update_bar.pack_forget()
            app.after(0, apply)
        threading.Thread(target=work, daemon=True).start()

    def watch_updates():
        refresh_update_check()
        app.after(120000, watch_updates)

    def apply_update_now():
        update_note.configure(text="Downloading…", text_color=YELLOW)

        def work():
            if getattr(sys, "frozen", False):
                ok, msg = Updater.install_exe(UPDATE_EXE_URL)
            else:
                ok, msg = Updater.install(UPDATE_URL)
            def done():
                update_note.configure(text=msg, text_color=GREEN if ok else RED)
                if not ok:
                    return
                if getattr(sys, "frozen", False):
                    app.after(400, lambda: (app.destroy(), os._exit(0)))
                else:
                    app.after(600, Updater.restart)
            app.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    neon_btn(update_bar, "UPDATE NOW", ACCENT, apply_update_now, width=120, height=30).pack(side="right", padx=(4, 12))
    neon_btn(update_bar, "DISMISS", YELLOW, dismiss_update, width=90, height=30).pack(side="right", padx=4)
    ctk.CTkButton(update_bar, text="", width=32, height=30, corner_radius=16,
                  fg_color="#163038", hover_color="#1C4050", text_color=TEXT,
                  command=refresh_update_check).pack(side="right", padx=4)

    # ════════════════════════════════════════════
    #  MAIN BODY
    # ════════════════════════════════════════════
    body = ctk.CTkFrame(app, fg_color=BG, corner_radius=0)
    body.pack(fill="both", expand=True)

    # ── LEFT SIDEBAR ─────────────────────────────
    sidebar = ctk.CTkFrame(body, fg_color=SIDEBAR, width=96, corner_radius=0)
    sidebar.pack(side="left", fill="y")
    sidebar.pack_propagate(False)

    nav_btns = {}
    pages = {}

    def switch_page(name):
        if name not in pages:
            return
        if state.get("page") == name and pages[name].winfo_ismapped():
            return
        state["page"] = name
        for n, btn in nav_btns.items():
            if n == name:
                btn.configure(fg_color="#17202B", text_color=ACCENT)
            else:
                btn.configure(fg_color="transparent", text_color=MUTED)
        frame = pages[name]
        frame.grid()
        for n, fr in pages.items():
            if n != name:
                fr.grid_remove()

    nav_items = [
        ("dashboard", "Home"),
        ("tasks", "Tasks"),
        ("accounts", "Accounts"),
        ("analytics", "Stats"),
        ("proxies", "Proxies"),
        ("settings", "Settings"),
        ("logs", "Log"),
    ]

    ctk.CTkLabel(sidebar, text="KU",
                 font=ctk.CTkFont(size=16, weight="bold"),
                 text_color=ACCENT).pack(pady=(16, 10))

    for key, label in nav_items:
        b = ctk.CTkButton(
            sidebar, text=label, anchor="center",
            fg_color="transparent", text_color=MUTED,
            hover_color=CARD, height=36, width=76, corner_radius=10,
            font=ctk.CTkFont(size=12),
            command=lambda k=key: switch_page(k))
        b.pack(pady=3)
        nav_btns[key] = b

    # Sidebar footer stats
    side_stats = ctk.CTkFrame(sidebar, fg_color=CARD, corner_radius=10)
    side_stats.pack(side="bottom", fill="x", padx=12, pady=16)
    groups_stat = ctk.CTkLabel(side_stats, text="0 groups",
                               font=ctk.CTkFont(size=11), text_color=MUTED)
    groups_stat.pack(pady=(8, 2))
    acc_stat = ctk.CTkLabel(side_stats, text="0 accounts",
                            font=ctk.CTkFont(size=11), text_color=MUTED)
    acc_stat.pack(pady=(0, 8))

    def refresh_side_stats():
        groups_stat.configure(text=f"{len(state['groups'])} groups")
        accs = load_accounts()
        healthy = sum(1 for a in accs if a.get("status", "ok") in ("ok", "otp_warn"))
        acc_stat.configure(text=f"{healthy}/{len(accs)} healthy")

    # ── CONTENT AREA ─────────────────────────────
    content = ctk.CTkFrame(body, fg_color=BG, corner_radius=0)
    content.pack(side="left", fill="both", expand=True)
    content.grid_rowconfigure(0, weight=1)
    content.grid_columnconfigure(0, weight=1)

    # ════════════════════════════════════════════
    #  PAGE: DASHBOARD
    # ════════════════════════════════════════════
    page_dash = ctk.CTkFrame(content, fg_color=BG)
    pages["dashboard"] = page_dash

    # Hero row
    hero = ctk.CTkFrame(page_dash, fg_color="transparent")
    hero.pack(fill="x", pady=(0, 12))

    ctk.CTkLabel(hero, text="Karma Ultra",
                 font=ctk.CTkFont(size=22, weight="bold"),
                 text_color=TEXT).pack(side="left")

    # Quick action buttons
    qa = ctk.CTkFrame(hero, fg_color="transparent")
    qa.pack(side="right")

    def start_bot():
        if state["running"]:
            return
        state["running"] = True
        state["stopref"] = [False]
        set_status("RUNNING", GREEN)
        STATUS.clear()
        log("Engine starting — all enabled groups")

        def threader():
            try:
                async def main():
                    await asyncio.gather(
                        run_all_groups(state["groups"], log, state["stopref"]),
                        run_restock(log, state["stopref"]),
                    )
                asyncio.run(main())
            except Exception as e:
                log(f"Engine error: {type(e).__name__}: {e}")
            finally:
                state["running"] = False
                STATUS.clear()
                set_status("IDLE", YELLOW)

        threading.Thread(target=threader, daemon=True).start()

    def stop_bot():
        if state.get("stopref"):
            state["stopref"][0] = True
        STATUS.clear()
        state["running"] = False
        set_status("IDLE", YELLOW)
        log("Stopped")

    def start_restock():
        if state["running"]:
            return
        state["running"] = True
        state["stopref"] = [False]
        set_status("RESTOCK", ACCENT2)
        log("Restock monitor launching…")

        def threader():
            try:
                async def main():
                    await run_restock(log, state["stopref"])
                asyncio.run(main())
            except Exception as e:
                log(f"Restock error: {e}")
            finally:
                state["running"] = False
                STATUS.clear()
                set_status("IDLE", YELLOW)

        threading.Thread(target=threader, daemon=True).start()

    neon_btn(qa, "RUN ALL", GREEN, start_bot, width=120).pack(side="left", padx=4)
    neon_btn(qa, "STOP", RED, stop_bot, width=100).pack(side="left", padx=4)

    home_grid = ctk.CTkFrame(page_dash, fg_color="transparent")
    home_grid.pack(fill="x", pady=(0, 12))
    home_cards = [
        ("Tasks", "Groups, runs and ticket rows", "tasks"),
        ("Accounts", "Named groups and sessions", "accounts"),
        ("Proxies", "Groups you can pick on a task", "proxies"),
        ("Stats", "Queue history for each account", "analytics"),
        ("Settings", "Keys, mail and updates", "settings"),
        ("Log", "What the current run is doing", "logs"),
    ]
    for col in range(3):
        home_grid.grid_columnconfigure(col, weight=1)
    for i, (title, sub, key) in enumerate(home_cards):
        cell = ctk.CTkFrame(home_grid, fg_color=CARD, corner_radius=14,
                            border_width=1, border_color=BORDER, height=96)
        cell.grid(row=i // 3, column=i % 3, sticky="nsew", padx=6, pady=6)
        cell.grid_propagate(False)
        ctk.CTkLabel(cell, text=title, font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=16, pady=(16, 0))
        ctk.CTkLabel(cell, text=sub, font=ctk.CTkFont(size=12),
                     text_color=MUTED).pack(anchor="w", padx=16, pady=(2, 0))
        cell.bind("<Button-1>", lambda e, k=key: switch_page(k))
        for child in cell.winfo_children():
            child.bind("<Button-1>", lambda e, k=key: switch_page(k))

    # Metric cards row
    metrics = ctk.CTkFrame(page_dash, fg_color="transparent")
    metrics.pack(fill="x", pady=(0, 12))

    def metric_card(parent, title, value, color):
        f = card(parent)
        f.pack(side="left", fill="x", expand=True, padx=4)
        ctk.CTkLabel(f, text=title, font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=MUTED).pack(anchor="w", padx=14, pady=(12, 0))
        lbl = ctk.CTkLabel(f, text=value, font=ctk.CTkFont(size=26, weight="bold"),
                           text_color=color)
        lbl.pack(anchor="w", padx=14, pady=(2, 12))
        return lbl

    m_groups = metric_card(metrics, "TASK GROUPS", "0", ACCENT)
    m_tasks  = metric_card(metrics, "ACTIVE TASKS", "0", GREEN)
    m_carts  = metric_card(metrics, "CARTED", "0", ACCENT3)
    m_fails  = metric_card(metrics, "FAILS", "0", RED)

    # Live task board
    board_card = card(page_dash)
    board_card.pack(fill="both", expand=True)

    board_header = ctk.CTkFrame(board_card, fg_color="transparent")
    board_header.pack(fill="x", padx=14, pady=(12, 4))
    ctk.CTkLabel(board_header, text="◈ LIVE TASK BOARD",
                 font=ctk.CTkFont(size=13, weight="bold"),
                 text_color=ACCENT).pack(side="left")

    # Column headers
    cols_frame = ctk.CTkFrame(board_card, fg_color="transparent")
    cols_frame.pack(fill="x", padx=14, pady=(4, 0))
    for col, w in [("TASK", 80), ("GROUP", 120), ("ACCOUNT", 160),
                   ("STATE", 100), ("QUEUE", 80), ("ERRORS", 60), ("TIME", 70)]:
        ctk.CTkLabel(cols_frame, text=col, width=w, anchor="w",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=DIM).pack(side="left", padx=2)

    ctk.CTkFrame(board_card, height=1, fg_color=BORDER).pack(fill="x", padx=14, pady=4)

    board_scroll = ctk.CTkScrollableFrame(board_card, fg_color="transparent",
                                          height=280)
    board_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    board_rows = {}
    board_state = {"snap": {}, "dirty": False, "sig": ""}

    def _row_signature(snap):
        parts = []
        for tid, t in snap.items():
            parts.append(f"{tid}|{t.get('state')}|{t.get('queue_pos')}|{t.get('wait_label')}|{len(t.get('errors', []))}|{int(time.time()-t.get('started', time.time()))}")
        return "|".join(parts)

    def refresh_board(snap=None):
        snap = snap if snap is not None else board_state["snap"]
        board_state["snap"] = snap
        sig = _row_signature(snap)
        if sig == board_state["sig"] and board_scroll.winfo_children():
            return
        board_state["sig"] = sig

        for w in board_scroll.winfo_children():
            w.destroy()
        board_rows.clear()

        if not snap:
            ctk.CTkLabel(board_scroll, text="No active tasks — hit RUN ALL to launch",
                         font=ctk.CTkFont(size=12), text_color=DIM).pack(pady=40)
            m_tasks.configure(text="0")
            m_carts.configure(text="0")
            m_fails.configure(text="0")
            return

        carts = fails = 0
        for tid, t in snap.items():
            row = ctk.CTkFrame(board_scroll, fg_color=CARD_HOVER, corner_radius=8,
                               height=36)
            row.pack(fill="x", pady=2, padx=2)
            row.pack_propagate(False)

            st = t.get("state", "?")
            st_color = {
                "starting": MUTED, "queue": ACCENT, "waiting": YELLOW, "otp": YELLOW,
                "hunting": ACCENT2, "captcha": ORANGE, "carted": GREEN,
                "holding": GREEN, "done": GREEN, "failed": RED,
            }.get(st, TEXT)

            if st in ("carted", "holding", "done"):
                carts += 1
            if st == "failed":
                fails += 1

            elapsed = int(time.time() - t.get("started", time.time()))
            qpos = t.get("queue_pos")
            if t.get("state") == "waiting" and t.get("wait_label"):
                qtxt = t.get("wait_label")
            elif qpos is not None:
                qtxt = f"#{qpos}"
            else:
                qtxt = t.get("wait_label") or "—"
            if t.get("queue_pct") is not None and t.get("state") != "waiting":
                qtxt += f" {t['queue_pct']}%"

            vals = [
                (tid[:8], 80, MUTED),
                (t.get("group", "?")[:14], 120, TEXT),
                (t.get("account", "?")[:22], 160, MUTED),
                (st.upper(), 100, st_color),
                (qtxt, 80, ACCENT),
                (str(len(t.get("errors", []))), 60, RED if t.get("errors") else MUTED),
                (f"{elapsed}s", 70, MUTED),
            ]
            for txt, w, col in vals:
                ctk.CTkLabel(row, text=txt, width=w, anchor="w",
                             font=ctk.CTkFont(size=11), text_color=col).pack(
                    side="left", padx=2, pady=6)

        m_tasks.configure(text=str(len(snap)))
        m_carts.configure(text=str(carts))
        m_fails.configure(text=str(fails))

    def schedule_board(snap):
        board_state["snap"] = snap
        if board_state["dirty"]:
            return
        board_state["dirty"] = True
        def flush():
            board_state["dirty"] = False
            refresh_board(board_state["snap"])
        app.after(180, flush)

    STATUS.on_change(lambda snap: app.after(0, lambda s=snap: schedule_board(s)))

    # ════════════════════════════════════════════
    #  PAGE: TASK GROUPS
    # ════════════════════════════════════════════
    page_tasks = ctk.CTkFrame(content, fg_color=BG)
    pages["tasks"] = page_tasks

    tasks_top = ctk.CTkFrame(page_tasks, fg_color="transparent")
    tasks_top.pack(fill="x", pady=(0, 8))
    ctk.CTkLabel(tasks_top, text="TICKETMASTER TASKS",
                 font=ctk.CTkFont(size=18, weight="bold"),
                 text_color=TEXT).pack(side="left")
    neon_btn(tasks_top, "+  ADD TASK", ACCENT, lambda: add_group(), width=130).pack(side="right", padx=4)

    tasks_split = ctk.CTkFrame(page_tasks, fg_color="transparent")
    tasks_split.pack(fill="both", expand=True)

    # Side rail
    list_card = card(tasks_split, width=230)
    list_card.pack(side="left", fill="y", padx=(0, 8))
    list_card.pack_propagate(False)

    search_var = StringVar()
    search_box = ctk.CTkEntry(list_card, textvariable=search_var, height=32,
                              placeholder_text="Search tasks...",
                              fg_color=BG, border_color=BORDER, text_color=TEXT)
    search_box.pack(fill="x", padx=10, pady=(10, 6))
    search_var.trace_add("write", lambda *_: refresh_group_list())

    group_list = ctk.CTkScrollableFrame(list_card, fg_color="transparent")
    group_list.pack(fill="both", expand=True, padx=6, pady=(0, 6))

    # Main table
    table_card = card(tasks_split)
    table_card.pack(side="left", fill="both", expand=True)

    header = ctk.CTkFrame(table_card, fg_color="transparent")
    header.pack(fill="x", padx=8, pady=(8, 0))
    for col, w in [("#", 36), ("EVENT", 200), ("MODE", 80),
                   ("ACCOUNT", 140), ("PROXY", 140), ("STATUS", 80)]:
        ctk.CTkLabel(header, text=col, width=w, anchor="w",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=DIM).pack(side="left", padx=2)
    ctk.CTkFrame(table_card, height=1, fg_color=BORDER).pack(fill="x", padx=8, pady=4)

    task_table = ctk.CTkScrollableFrame(table_card, fg_color="transparent")
    task_table.pack(fill="both", expand=True, padx=6, pady=(0, 4))

    bar = ctk.CTkFrame(table_card, fg_color="transparent")
    bar.pack(fill="x", padx=8, pady=(0, 8))

    form = {}

    # Overlay form
    form_panel = ctk.CTkFrame(page_tasks, fg_color="#0E0E16", corner_radius=16,
                              border_width=1, border_color=ACCENT)

    def hide_form():
        form_panel.place_forget()
        form.clear()

    def flash_form():
        return

    def new_task(g):
        return {
            "id": uuid.uuid4().hex[:8],
            "event": g.event_url,
            "mode": "normal",
            "account": g.account_group,
            "proxy": g.proxy_group,
            "quantity": g.quantity,
            "min_price": g.min_price,
            "max_price": g.max_price,
            "sections": list(g.sections or []),
            "section_mode": g.section_mode,
            "presale_codes": list(g.presale_codes or []),
            "contiguous": g.contiguous,
            "max_tasks": g.max_tasks,
            "status": "idle",
        }

    def task_to_group(g, task):
        return TaskGroup(
            id=task.get("id", g.id), name=g.name,
            event_url=task.get("event") or g.event_url,
            quantity=int(task.get("quantity", g.quantity) or 2),
            min_price=float(task.get("min_price", g.min_price) or 0),
            max_price=float(task.get("max_price", g.max_price) or 250),
            contiguous=bool(task.get("contiguous", g.contiguous)),
            section_mode=task.get("section_mode", g.section_mode) or "include",
            sections=task.get("sections") or [],
            account_group=task.get("account") or g.account_group,
            proxy_group=task.get("proxy") or g.proxy_group,
            max_tasks=int(task.get("task_count") or task.get("max_tasks") or 1),
            task_count=int(task.get("task_count") or task.get("max_tasks") or 1),
            enabled=True,
            presale_codes=task.get("presale_codes") or [],
            mode=(task.get("mode") or "normal"),
        )

    save_job = {"id": None}

    def schedule_autosave(g):
        if save_job["id"]:
            try:
                app.after_cancel(save_job["id"])
            except Exception:
                pass
        save_job["id"] = app.after(350, lambda: save_group(g, close=False, quiet=True))

    def show_edit(g, task=None):
        state["selected"] = g
        if not g.tasks:
            g.tasks = [new_task(g)]
        task = task or g.tasks[0]
        state["edit_task"] = task.get("id")
        refresh_group_list()
        for w in form_panel.winfo_children():
            w.destroy()
        form.clear()

        head = ctk.CTkFrame(form_panel, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(head, text=g.name,
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEXT).pack(side="left")
        neon_btn(head, "X", RED, hide_form, width=36, height=28).pack(side="right")

        bodyf = ctk.CTkFrame(form_panel, fg_color="transparent")
        bodyf.pack(fill="both", expand=True, padx=12, pady=4)
        cols = []
        for _ in range(3):
            c = ctk.CTkFrame(bodyf, fg_color="transparent")
            c.pack(side="left", fill="both", expand=True, padx=6)
            cols.append(c)

        def ment(parent, key, label, value, width=220):
            ctk.CTkLabel(parent, text=label, font=ctk.CTkFont(size=11),
                         text_color=ACCENT).pack(anchor="w", pady=(8, 0))
            e = ctk.CTkEntry(parent, width=width, height=32, fg_color=BG,
                             border_color=BORDER, text_color=TEXT)
            e.insert(0, str(value))
            e.pack(anchor="w", pady=(2, 0))
            form[key] = e
            e.bind("<KeyRelease>", lambda _e, gg=g: schedule_autosave(gg))

        def msw(parent, key, label, value):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=8)
            ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=12),
                         text_color=TEXT).pack(side="left")
            var = BooleanVar(value=value)
            ctk.CTkSwitch(row, text="", variable=var, progress_color=ACCENT,
                          button_color=TEXT, fg_color=DIM,
                          command=lambda gg=g: schedule_autosave(gg)).pack(side="right")
            form[key] = var

        ment(cols[0], "name", "Task name", g.name)
        countries = ["NL", "BE", "DE", "GB", "FR", "AT", "CH", "US", "CA", "AU"]
        country_now = task.get("country") or getattr(g, "country", "NL") or "NL"
        if country_now not in countries:
            countries = [country_now] + countries
        country_var = StringVar(value=country_now)
        ctk.CTkLabel(cols[0], text="Country", font=ctk.CTkFont(size=12),
                     text_color=TEXT).pack(anchor="w", pady=(6, 0))
        ctk.CTkOptionMenu(cols[0], values=countries, variable=country_var,
                          fg_color=BG, button_color=CARD_HOVER, button_hover_color=BORDER,
                          text_color=TEXT,
                          command=lambda _c, gg=g: schedule_autosave(gg)).pack(anchor="w", pady=(2, 0))
        form["country"] = country_var
        ment(cols[0], "quantity", "Ticket quantity", task.get("quantity", g.quantity))
        ment(cols[0], "min_price", "Min price", task.get("min_price", g.min_price))
        acc_names = load_account_group_names() or ["default"]
        current_acc = task.get("account") or g.account_group or acc_names[0]
        if current_acc not in acc_names:
            acc_names = [current_acc] + acc_names
        acc_var = StringVar(value=current_acc)
        ctk.CTkLabel(cols[0], text="Account group", font=ctk.CTkFont(size=12),
                     text_color=TEXT).pack(anchor="w", pady=(6, 0))
        ctk.CTkOptionMenu(cols[0], values=acc_names, variable=acc_var,
                          fg_color=BG, button_color=CARD_HOVER, button_hover_color=BORDER,
                          text_color=TEXT,
                          command=lambda _c, gg=g: schedule_autosave(gg)).pack(anchor="w", pady=(2, 0))
        form["account_group"] = acc_var
        ment(cols[0], "task_count", "Tasks", task.get("task_count") or task.get("max_tasks") or g.max_tasks)
        ctk.CTkLabel(cols[0], text="50 accounts and 50 tasks = 1 each. 50 accounts and 100 tasks = 2 each.",
                     font=ctk.CTkFont(size=11), text_color=MUTED, wraplength=240, justify="left").pack(anchor="w", pady=(2, 6))
        ment(cols[1], "event_url", "Event link", task.get("event", g.event_url), 280)
        mode_var = StringVar(value="Restock" if task.get("mode") == "restock" else "Normal")
        ctk.CTkLabel(cols[1], text="Mode", font=ctk.CTkFont(size=12),
                     text_color=TEXT).pack(anchor="w", pady=(6, 0))
        mode_hint = ctk.CTkLabel(cols[1], text="", font=ctk.CTkFont(size=11),
                                 text_color=MUTED, wraplength=260, justify="left")

        def show_mode(_choice=None):
            if mode_var.get() == "Restock":
                mode_hint.configure(text="Restock: watches the event and carts only when tickets come back in stock.")
            else:
                mode_hint.configure(text="Normal: opens the event now and tries to cart right away.")

        ctk.CTkOptionMenu(cols[1], values=["Normal", "Restock"], variable=mode_var,
                          fg_color=BG, button_color=CARD_HOVER, button_hover_color=BORDER,
                          text_color=TEXT, command=lambda c: (show_mode(c), schedule_autosave(g))
                          ).pack(anchor="w", pady=(2, 0))
        mode_hint.pack(anchor="w", pady=(4, 6))
        show_mode()
        form["mode"] = mode_var
        ment(cols[1], "max_price", "Max price", task.get("max_price", g.max_price))
        px_names = ["any"] + sorted(ProxyGroupManager.load().keys())
        current_px = task.get("proxy") or g.proxy_group or "any"
        if current_px not in px_names:
            px_names.append(current_px)
        px_var = StringVar(value=current_px)
        ctk.CTkLabel(cols[1], text="Proxy group", font=ctk.CTkFont(size=12),
                     text_color=TEXT).pack(anchor="w", pady=(6, 0))
        ctk.CTkOptionMenu(cols[1], values=px_names, variable=px_var,
                          fg_color=BG, button_color=CARD_HOVER, button_hover_color=BORDER,
                          text_color=TEXT,
                          command=lambda _c, gg=g: schedule_autosave(gg)).pack(anchor="w", pady=(2, 0))
        form["proxy_group"] = px_var
        ment(cols[1], "presale_codes", "Presale code",
             ", ".join(task.get("presale_codes") or g.presale_codes or []))
        ment(cols[2], "sections", "Sections",
             ", ".join(task.get("sections") or []) or "Section1,Section2")
        sec_now = "OFF" if (task.get("section_mode") or g.section_mode) == "exclude" else "ON"
        sec_var = StringVar(value=sec_now)
        ctk.CTkLabel(cols[2], text="Section filter", font=ctk.CTkFont(size=12),
                     text_color=TEXT).pack(anchor="w", pady=(6, 0))
        sec_hint = ctk.CTkLabel(cols[2], text="", font=ctk.CTkFont(size=11),
                                text_color=MUTED, wraplength=240, justify="left")

        def show_sec(_c=None):
            if sec_var.get() == "ON":
                sec_hint.configure(text="ON: only the sections listed above.")
            else:
                sec_hint.configure(text="OFF: skip the sections listed above.")

        ctk.CTkOptionMenu(cols[2], values=["ON", "OFF"], variable=sec_var,
                          fg_color=BG, button_color=CARD_HOVER, button_hover_color=BORDER,
                          text_color=TEXT,
                          command=lambda c, gg=g: (show_sec(c), schedule_autosave(gg))
                          ).pack(anchor="w", pady=(2, 0))
        sec_hint.pack(anchor="w", pady=(4, 6))
        show_sec()
        form["section_mode"] = sec_var
        msw(cols[2], "contiguous", "Contiguous seats", task.get("contiguous", g.contiguous))
        msw(cols[0], "enabled", "Task enabled", g.enabled)

        act = ctk.CTkFrame(form_panel, fg_color="transparent")
        act.pack(fill="x", padx=16, pady=12)
        neon_btn(act, "SAVE", GREEN, lambda: save_group(g), width=110).pack(side="left", padx=4)
        neon_btn(act, "RUN THIS", ACCENT, lambda: (save_group(g, close=False, quiet=True), run_task(g, task)), width=120).pack(side="left", padx=4)
        neon_btn(act, "DELETE", RED, lambda: delete_group(g), width=100).pack(side="left", padx=4)

        form_panel.place(relx=0.16, rely=0.06, relwidth=0.82, relheight=0.88)
        form_panel.lift()
        flash_form()

    def save_group(g, close=True, quiet=False):
        try:
            if "name" not in form:
                return
            g.name = form["name"].get().strip() or g.name
            mode = form["mode"].get().strip().lower() or "normal"
            if mode not in ("normal", "restock"):
                mode = "normal"
            g.country = form["country"].get().strip() or "NL"
            g.event_url = form["event_url"].get().strip()
            g.quantity = int(float(form["quantity"].get() or 2))
            g.min_price = float(form["min_price"].get() or 0)
            g.max_price = float(form["max_price"].get() or 250)
            g.account_group = form["account_group"].get().strip() or "default"
            g.proxy_group = form["proxy_group"].get().strip() or "any"
            g.section_mode = "exclude" if form["section_mode"].get().strip().upper() == "OFF" else "include"
            secs = form["sections"].get().strip()
            placeholder = secs.strip().lower() in ("section1,section2", "section1, section2")
            g.sections = [] if placeholder or not secs else [s.strip() for s in secs.split(",") if s.strip()]
            codes = form["presale_codes"].get().strip()
            g.presale_codes = [c.strip() for c in codes.split(",") if c.strip()] if codes else []
            g.contiguous = form["contiguous"].get()
            g.enabled = form["enabled"].get()
            g.task_count = max(1, int(float(form["task_count"].get() or 1)))
            g.max_tasks = g.task_count
            tid = state.get("edit_task")
            row = next((t for t in g.tasks if t.get("id") == tid), None)
            if row is None:
                row = new_task(g)
                g.tasks.append(row)
                state["edit_task"] = row["id"]
            row.update({
                "event": g.event_url,
                "country": g.country,
                "mode": mode,
                "account": g.account_group,
                "proxy": g.proxy_group,
                "quantity": g.quantity,
                "min_price": g.min_price,
                "max_price": g.max_price,
                "sections": list(g.sections),
                "section_mode": g.section_mode,
                "presale_codes": list(g.presale_codes),
                "contiguous": g.contiguous,
                "max_tasks": g.max_tasks,
                "task_count": g.task_count,
                "status": row.get("status", "idle"),
            })
            save_groups(state["groups"])
            refresh_side_stats()
            m_groups.configure(text=str(len(state["groups"])))
            if not quiet:
                log(f"Saved [{g.name}]")
            if close:
                hide_form()
            refresh_group_list()
        except Exception as e:
            if not quiet:
                log(f"Save error: {e}")

    def delete_group(g):
        state["groups"] = [x for x in state["groups"] if x.id != g.id]
        if state.get("selected") and state["selected"].id == g.id:
            state["selected"] = None
        save_groups(state["groups"])
        hide_form()
        refresh_group_list()
        refresh_side_stats()
        m_groups.configure(text=str(len(state["groups"])))
        log(f"Deleted [{g.name}]")

    def save_all_groups():
        save_groups(state["groups"])
        log("All tasks saved")

    def run_single(g, all_accounts=False):
        if state["running"]:
            log("Already running")
            return
        if all_accounts:
            g.max_tasks = 999
            save_groups(state["groups"])
        state["running"] = True
        state["stopref"] = [False]
        set_status("RUNNING", GREEN)
        STATUS.clear()
        log(f"Launching [{g.name}]" + (" — every account" if all_accounts or g.max_tasks >= 999 else ""))

        def threader():
            try:
                async def main():
                    pm = ProxyManager()
                    engine = BrowserEngine(pm, CONFIG["general"]["headless"],
                                          CONFIG["general"].get("hybrid_mode", True))
                    log(engine.browser_note)
                    solver = CaptchaSolver()
                    notifier = DiscordNotifier(CONFIG["discord"]["webhook_url"])
                    log("Playwright starting")
                    await engine.start()
                    log("Playwright ready")
                    try:
                        await run_group(g, engine, solver, notifier, log, state["stopref"])
                    finally:
                        await engine.stop()
                asyncio.run(main())
            except Exception as e:
                log(f"Launch error: {type(e).__name__}: {e}")
            finally:
                state["running"] = False
                STATUS.clear()
                set_status("IDLE", YELLOW)

        threading.Thread(target=threader, daemon=True).start()

    def run_selected_all():
        g = state.get("selected") or (state["groups"][0] if state["groups"] else None)
        if not g:
            log("No task selected")
            return
        run_single(g, all_accounts=True)

    def add_group():
        g = TaskGroup(id=uuid.uuid4().hex[:8], name=f"TM Task {len(state['groups'])+1}",
                      event_url="https://www.ticketmaster.com/event/")
        g.tasks = [new_task(g)]
        state["groups"].append(g)
        state["selected"] = g
        save_groups(state["groups"])
        refresh_side_stats()
        m_groups.configure(text=str(len(state["groups"])))
        show_edit(g, g.tasks[0])
        log(f"Created [{g.name}]")

    def select_group(g):
        state["selected"] = g
        hide_form()
        mark_selected_rail()
        refresh_task_table()

    def add_task_row():
        g = state.get("selected")
        if not g and state["groups"]:
            g = state["groups"][0]
            state["selected"] = g
        if not g:
            add_group()
            return
        if not g.tasks:
            g.tasks = [new_task(g)]
        t = new_task(g)
        g.tasks.append(t)
        save_groups(state["groups"])
        show_edit(g, t)

    def duplicate_task(g, task):
        if not g.tasks:
            g.tasks = [dict(task)]
        copy = dict(task)
        copy["id"] = uuid.uuid4().hex[:8]
        copy["status"] = "idle"
        g.tasks.append(copy)
        save_groups(state["groups"])
        state["selected"] = g
        refresh_group_list()
        log(f"Duplicated task in [{g.name}]")

    def delete_task(g, task):
        g.tasks = [t for t in (g.tasks or []) if t.get("id") != task.get("id")]
        if not g.tasks:
            g.tasks = [new_task(g)]
        save_groups(state["groups"])
        refresh_group_list()
        log(f"Removed task from [{g.name}]")

    def run_task(g, task):
        if task.get("mode") == "restock":
            task["status"] = "restock"
            save_groups(state["groups"])
            refresh_group_list()
            log(f"Restock watching {task.get('event') or g.event_url}")
            start_restock()
            return
        task["status"] = "running"
        save_groups(state["groups"])
        clone = task_to_group(g, task)
        run_single(clone)
        def mark_idle():
            if not state["running"]:
                task["status"] = "idle"
                save_groups(state["groups"])
                refresh_group_list()
            else:
                app.after(1000, mark_idle)
        app.after(1000, mark_idle)

    def delete_all_groups():
        state["groups"] = []
        state["selected"] = None
        save_groups(state["groups"])
        hide_form()
        refresh_group_list()
        refresh_side_stats()
        m_groups.configure(text="0")
        log("Deleted all tasks")

    group_rails = {}

    def mark_selected_rail():
        sel = state.get("selected")
        for gid, (rail, name_lbl) in group_rails.items():
            on = bool(sel and sel.id == gid)
            rail.configure(fg_color="#172433" if on else CARD_HOVER,
                           border_color=ACCENT if on else BORDER)
            name_lbl.configure(text_color=ACCENT if on else TEXT)

    def refresh_task_table():
        for w in task_table.winfo_children():
            w.destroy()
        sel = state.get("selected")
        if not sel:
            ctk.CTkLabel(task_table, text="Pick a task group on the left",
                         text_color=DIM, font=ctk.CTkFont(size=12)).pack(pady=20)
            return
        ctk.CTkLabel(task_table, text=sel.name,
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=ACCENT).pack(anchor="w", padx=8, pady=(4, 6))
        if not sel.tasks:
            sel.tasks = [new_task(sel)]
        for i, task in enumerate(sel.tasks, 1):
            row = ctk.CTkFrame(task_table, fg_color=CARD, corner_radius=8, height=40)
            row.pack(fill="x", pady=2)
            row.pack_propagate(False)
            event_short = str(task.get("event", "")).replace("https://www.ticketmaster.com", "")[:28] or "—"
            mode = str(task.get("mode", "normal")).upper()
            st = str(task.get("status", "idle")).upper()
            st_col = GREEN if st == "RUNNING" else (ACCENT2 if st == "RESTOCK" else MUTED)
            vals = [
                (str(i), 36, MUTED),
                (event_short, 200, TEXT),
                (mode, 80, ACCENT if mode == "NORMAL" else ACCENT2),
                (str(task.get("account", "—"))[:18], 140, TEXT),
                (str(task.get("proxy", "—"))[:18], 140, MUTED),
                (st, 80, st_col),
            ]
            for txt, w, col in vals:
                ctk.CTkLabel(row, text=txt, width=w, anchor="w",
                             font=ctk.CTkFont(size=11), text_color=col).pack(side="left", padx=2)
            g = sel
            neon_btn(row, "RUN", GREEN, lambda gg=g, tt=task: run_task(gg, tt), width=58, height=26).pack(side="right", padx=2)
            neon_btn(row, "EDIT", ACCENT, lambda gg=g, tt=task: show_edit(gg, tt), width=58, height=26).pack(side="right", padx=2)
            neon_btn(row, "COPY", ACCENT2, lambda gg=g, tt=task: duplicate_task(gg, tt), width=58, height=26).pack(side="right", padx=2)
            neon_btn(row, "DEL", RED, lambda gg=g, tt=task: delete_task(gg, tt), width=58, height=26).pack(side="right", padx=2)

    def refresh_group_list():
        q = ""
        try:
            q = search_var.get().strip().lower()
        except Exception:
            q = ""
        shown = [g for g in state["groups"] if not q or q in g.name.lower() or q in g.event_url.lower()]
        for w in group_list.winfo_children():
            w.destroy()
        group_rails.clear()
        if not shown:
            ctk.CTkLabel(group_list, text="No tasks", text_color=DIM,
                         font=ctk.CTkFont(size=12)).pack(pady=16)
            refresh_task_table()
            return
        sel = state.get("selected")
        for g in shown:
            selected = sel and sel.id == g.id
            rail = ctk.CTkFrame(group_list,
                                fg_color="#172433" if selected else CARD_HOVER,
                                corner_radius=10, height=58,
                                border_width=1,
                                border_color=ACCENT if selected else BORDER)
            rail.pack(fill="x", pady=3)
            rail.pack_propagate(False)
            name_lbl = ctk.CTkLabel(rail, text=g.name, anchor="w",
                                    font=ctk.CTkFont(size=12, weight="bold"),
                                    text_color=ACCENT if selected else TEXT)
            name_lbl.pack(anchor="w", padx=8, pady=(8, 0))
            ctk.CTkLabel(rail, text=f"{len(g.tasks) or 1} tasks",
                         anchor="w", font=ctk.CTkFont(size=10),
                         text_color=MUTED).pack(anchor="w", padx=8)
            group_rails[g.id] = (rail, name_lbl)
            rail.bind("<Button-1>", lambda e, gg=g: select_group(gg))
            for ch in rail.winfo_children():
                ch.bind("<Button-1>", lambda e, gg=g: select_group(gg))
        refresh_task_table()

    neon_btn(bar, "ADD TASK", ACCENT, add_task_row, width=110, height=32).pack(side="left", padx=2)
    neon_btn(bar, "RUN ALL", GREEN, start_bot, width=100, height=32).pack(side="left", padx=2)
    neon_btn(bar, "RUN ALL IN ONE", ACCENT2, run_selected_all, width=140, height=32).pack(side="left", padx=2)
    neon_btn(bar, "STOP", YELLOW, stop_bot, width=80, height=32).pack(side="left", padx=2)
    neon_btn(bar, "DELETE ALL", RED, delete_all_groups, width=110, height=32).pack(side="left", padx=2)


    # ════════════════════════════════════════════
    #  PAGE: ACCOUNTS
    # ════════════════════════════════════════════
    page_acc = ctk.CTkFrame(content, fg_color=BG)
    pages["accounts"] = page_acc

    acc_top = ctk.CTkFrame(page_acc, fg_color="transparent")
    acc_top.pack(fill="x", pady=(0, 8))
    ctk.CTkLabel(acc_top, text="ACCOUNTS",
                 font=ctk.CTkFont(size=18, weight="bold"),
                 text_color=TEXT).pack(side="left")
    neon_btn(acc_top, "+ GROUP", ACCENT, lambda: add_account_group(), width=110).pack(side="right", padx=4)

    acc_split = ctk.CTkFrame(page_acc, fg_color="transparent")
    acc_split.pack(fill="both", expand=True)
    acc_rail_card = card(acc_split, width=220)
    acc_rail_card.pack(side="left", fill="y", padx=(0, 8))
    acc_rail_card.pack_propagate(False)
    acc_search = StringVar()
    ctk.CTkEntry(acc_rail_card, textvariable=acc_search, height=32,
                 placeholder_text="Search group...",
                 fg_color=BG, border_color=BORDER, text_color=TEXT).pack(fill="x", padx=8, pady=(8, 4))
    acc_search.trace_add("write", lambda *_: refresh_accounts())
    acc_rail = ctk.CTkScrollableFrame(acc_rail_card, fg_color="transparent")
    acc_rail.pack(fill="both", expand=True, padx=6, pady=4)

    acc_main = card(acc_split)
    acc_main.pack(side="left", fill="both", expand=True)
    acc_head = ctk.CTkFrame(acc_main, fg_color="transparent")
    acc_head.pack(fill="x", padx=8, pady=(8, 0))
    for col, w in [("#", 36), ("EMAIL", 280), ("PASSWORD", 160)]:
        ctk.CTkLabel(acc_head, text=col, width=w, anchor="w",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=DIM).pack(side="left", padx=2)
    acc_scroll = ctk.CTkScrollableFrame(acc_main, fg_color="transparent")
    acc_scroll.pack(fill="both", expand=True, padx=6, pady=4)
    acc_bar = ctk.CTkFrame(acc_main, fg_color="transparent")
    acc_bar.pack(fill="x", padx=8, pady=(0, 8))

    acc_ui = {"selected": None, "show_pw": set()}
    acc_form = ctk.CTkFrame(page_acc, fg_color="#0E0E16", corner_radius=16,
                            border_width=1, border_color=ACCENT)

    def hide_acc_form():
        acc_form.place_forget()

    def selected_account_group():
        names = load_account_group_names()
        if acc_ui["selected"] in names:
            return acc_ui["selected"]
        return names[0] if names else None

    def add_account_group():
        # In-app prompt. The Windows dialog never shows on a borderless window.
        for w in acc_form.winfo_children():
            w.destroy()
        ctk.CTkLabel(acc_form, text="New account group",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=20, pady=(18, 6))
        ctk.CTkLabel(acc_form, text="Example: Ticketmaster US",
                     text_color=MUTED, font=ctk.CTkFont(size=12)).pack(anchor="w", padx=20)
        entry = ctk.CTkEntry(acc_form, height=36, fg_color=BG,
                             border_color=BORDER, text_color=TEXT,
                             placeholder_text="Group name")
        entry.pack(fill="x", padx=20, pady=12)

        def commit(_e=None):
            name = entry.get().strip()
            if not name:
                return
            names = load_account_group_names()
            if name not in names:
                names.append(name)
                save_account_group_names(names)
            acc_ui["selected"] = name
            hide_acc_form()
            refresh_accounts()
            log(f"Account group [{name}]")

        row = ctk.CTkFrame(acc_form, fg_color="transparent")
        row.pack(anchor="w", padx=20, pady=(0, 16))
        neon_btn(row, "CREATE", GREEN, commit, width=110).pack(side="left", padx=(0, 8))
        neon_btn(row, "CANCEL", DIM, hide_acc_form, width=100).pack(side="left")
        entry.bind("<Return>", commit)
        acc_form.place(relx=0.28, rely=0.22, relwidth=0.44, relheight=0.34)
        acc_form.lift()
        entry.focus()

    def delete_account_group():
        name = selected_account_group()
        if not name:
            return
        if not messagebox.askyesno("Delete group", f"Delete group '{name}' and its accounts?"):
            return
        names = [n for n in load_account_group_names() if n != name]
        save_account_group_names(names)
        accs = [a for a in load_accounts() if a.get("group") != name]
        save_accounts(accs)
        acc_ui["selected"] = names[0] if names else None
        refresh_accounts()
        refresh_side_stats()

    def upsert_account(email, password, group, old_email=None):
        email = email.strip()
        if not email or "@" not in email:
            return False
        accs = load_accounts()
        target = old_email or email
        found = False
        for a in accs:
            if a.get("email") == target:
                a["email"] = email
                if password:
                    a["password"] = password
                a["group"] = group
                found = True
                break
        if not found:
            accs.append({
                "email": email, "password": password, "group": group,
                "status": "ok", "otp_fails": 0, "used": False,
                "created_at": datetime.now().isoformat(),
                "queue_runs": 0,
            })
        save_accounts(accs)
        return True

    def open_account_form(existing=None):
        group = selected_account_group()
        if not group:
            add_account_group()
            group = selected_account_group()
            if not group:
                return
        for w in acc_form.winfo_children():
            w.destroy()
        head = ctk.CTkFrame(acc_form, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(head, text="Add Ticketmaster Account",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEXT).pack(side="left")
        neon_btn(head, "X", RED, hide_acc_form, width=36, height=28).pack(side="right")
        ctk.CTkLabel(acc_form, text="Email", text_color=ACCENT).pack(anchor="w", padx=20)
        em = ctk.CTkEntry(acc_form, height=34, fg_color=BG, border_color=BORDER, text_color=TEXT)
        em.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(acc_form, text="Password", text_color=ACCENT).pack(anchor="w", padx=20, pady=(8, 0))
        pw = ctk.CTkEntry(acc_form, height=34, fg_color=BG, border_color=BORDER, text_color=TEXT)
        pw.pack(fill="x", padx=20, pady=4)
        if existing:
            em.insert(0, existing.get("email", ""))
            pw.insert(0, existing.get("password", ""))
        ctk.CTkLabel(acc_form, text="Or paste many  ·  email:password  one per line",
                     text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=20, pady=(10, 0))
        bulk = ctk.CTkTextbox(acc_form, height=120, fg_color=BG, text_color=TEXT,
                              border_width=1, border_color=BORDER)
        bulk.pack(fill="x", padx=20, pady=4)

        def commit():
            n = 0
            if bulk.get("1.0", TKEND).strip():
                for line in bulk.get("1.0", TKEND).splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    if ":" in line:
                        email, _, password = line.partition(":")
                    elif "," in line:
                        email, _, password = line.partition(",")
                    else:
                        email, password = line, ""
                    if upsert_account(email, password.strip(), group):
                        n += 1
            elif em.get().strip():
                if upsert_account(em.get(), pw.get(), group,
                                  old_email=(existing or {}).get("email")):
                    n = 1
            hide_acc_form()
            refresh_accounts()
            refresh_side_stats()
            log(f"Saved {n} account(s) in [{group}]")

        neon_btn(acc_form, "SAVE", GREEN, commit, width=120).pack(anchor="w", padx=20, pady=12)
        acc_form.place(relx=0.22, rely=0.08, relwidth=0.7, relheight=0.78)
        acc_form.lift()

    def import_accounts():
        open_account_form()

    def copy_email(email):
        app.clipboard_clear()
        app.clipboard_append(email)
        log(f"Copied {email}")

    def toggle_pw(email):
        if email in acc_ui["show_pw"]:
            acc_ui["show_pw"].discard(email)
        else:
            acc_ui["show_pw"].add(email)
        refresh_accounts()

    def open_session(email):
        sess = SessionVault.load(email)
        if not sess:
            messagebox.showinfo("Session", f"No saved session for {email}")
            return
        messagebox.showinfo(
            "Session",
            f"{email}\nSaved: {str(sess.get('_saved_at', '?'))[:19]}\nCookies: {len(sess.get('cookies', []))}")

    def delete_account(email):
        save_accounts([a for a in load_accounts() if a.get("email") != email])
        refresh_accounts()
        refresh_side_stats()

    def delete_accounts_in_group():
        name = selected_account_group()
        if not name:
            return
        if not messagebox.askyesno("Delete all", f"Remove every account in '{name}'?"):
            return
        save_accounts([a for a in load_accounts() if a.get("group") != name])
        refresh_accounts()
        refresh_side_stats()

    def refresh_accounts():
        for w in acc_rail.winfo_children():
            w.destroy()
        for w in acc_scroll.winfo_children():
            w.destroy()
        q = ""
        try:
            q = acc_search.get().strip().lower()
        except Exception:
            q = ""
        names = [n for n in load_account_group_names() if not q or q in n.lower()]
        if acc_ui["selected"] not in load_account_group_names():
            acc_ui["selected"] = names[0] if names else None
        if not names:
            ctk.CTkLabel(acc_rail, text="No groups", text_color=DIM).pack(pady=12)
            ctk.CTkLabel(acc_scroll, text="Add an account group first",
                         text_color=DIM).pack(pady=30)
            return
        all_accs = load_accounts()
        for name in names:
            count = sum(1 for a in all_accs if a.get("group") == name)
            on = name == acc_ui["selected"]
            b = ctk.CTkButton(
                acc_rail, text=f"{name}    {count}", anchor="w", height=40,
                fg_color="#142028" if on else "transparent",
                text_color=ACCENT if on else TEXT, hover_color=CARD_HOVER,
                command=lambda n=name: (acc_ui.__setitem__("selected", n), refresh_accounts()))
            b.pack(fill="x", pady=2)
        group = acc_ui["selected"]
        rows = [a for a in all_accs if a.get("group") == group]
        if not rows:
            ctk.CTkLabel(acc_scroll, text=f"No accounts in {group}",
                         text_color=DIM).pack(pady=30)
            return
        for i, a in enumerate(rows, 1):
            email = a.get("email", "")
            row = ctk.CTkFrame(acc_scroll, fg_color="#14141C", corner_radius=8, height=38)
            row.pack(fill="x", pady=2)
            row.pack_propagate(False)
            shown_pw = a.get("password", "") if email in acc_ui["show_pw"] else "••••••••"
            live_wait = ""
            for task in STATUS.tasks.values():
                if task.get("account") != email:
                    continue
                if task.get("queue_pos") is not None and task.get("state") == "queue":
                    live_wait = f"#{task.get('queue_pos')}"
                    break
                if task.get("wait_label"):
                    live_wait = task.get("wait_label")
                    break
            wait_txt = live_wait or a.get("wait_left") or "—"
            for txt, w, col in [(str(i), 36, MUTED), (email[:32], 250, TEXT),
                                (shown_pw[:14], 120, MUTED), (wait_txt, 70, YELLOW if wait_txt != "—" else MUTED)]:
                ctk.CTkLabel(row, text=txt, width=w, anchor="w",
                             font=ctk.CTkFont(size=11), text_color=col).pack(side="left", padx=2)
            neon_btn(row, "SHOW", DIM, lambda e=email: toggle_pw(e), width=58, height=26).pack(side="right", padx=1)
            neon_btn(row, "COPY", ACCENT2, lambda e=email: copy_email(e), width=58, height=26).pack(side="right", padx=1)
            neon_btn(row, "OPEN", ACCENT, lambda e=email: open_session(e), width=58, height=26).pack(side="right", padx=1)
            neon_btn(row, "EDIT", ACCENT, lambda acc=a: open_account_form(acc), width=58, height=26).pack(side="right", padx=1)
            neon_btn(row, "DEL", RED, lambda e=email: delete_account(e), width=58, height=26).pack(side="right", padx=1)

    neon_btn(acc_bar, "ADD ACCOUNT", ACCENT, lambda: open_account_form(), width=130, height=32).pack(side="left", padx=2)
    neon_btn(acc_bar, "IMPORT", ACCENT2, import_accounts, width=100, height=32).pack(side="left", padx=2)
    neon_btn(acc_bar, "DELETE GROUP", RED, delete_account_group, width=130, height=32).pack(side="left", padx=2)
    neon_btn(acc_bar, "DELETE ALL", YELLOW, delete_accounts_in_group, width=120, height=32).pack(side="left", padx=2)

    # ════════════════════════════════════════════
    #  PAGE: ANALYTICS
    # ════════════════════════════════════════════
    page_an = ctk.CTkFrame(content, fg_color=BG)
    pages["analytics"] = page_an
    an_top = ctk.CTkFrame(page_an, fg_color="transparent")
    an_top.pack(fill="x", pady=(0, 8))
    ctk.CTkLabel(an_top, text="ACCOUNT QUEUE HISTORY",
                 font=ctk.CTkFont(size=18, weight="bold"),
                 text_color=TEXT).pack(side="left")
    neon_btn(an_top, "REFRESH", DIM, lambda: refresh_analytics(), width=100).pack(side="right")
    ctk.CTkLabel(page_an, text="Lower start position is better. Recorded the first time each account enters a queue.",
                 font=ctk.CTkFont(size=11), text_color=MUTED).pack(anchor="w", pady=(0, 6))
    an_scroll = ctk.CTkScrollableFrame(page_an, fg_color=CARD, corner_radius=12)
    an_scroll.pack(fill="both", expand=True)

    def refresh_analytics():
        for w in an_scroll.winfo_children():
            w.destroy()
        hist = jload(QUEUE_FILE, [])
        if not isinstance(hist, list):
            hist = []
        hdr = ctk.CTkFrame(an_scroll, fg_color="transparent")
        hdr.pack(fill="x", padx=8, pady=(8, 2))
        for col, w in [("ACCOUNT", 240), ("RUNS", 60), ("BEST START", 90),
                       ("AVG START", 90), ("LAST START", 90), ("LAST EVENT", 220)]:
            ctk.CTkLabel(hdr, text=col, width=w, anchor="w",
                         font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=DIM).pack(side="left", padx=2)
        by = {}
        for h in hist:
            by.setdefault(h.get("email", "?"), []).append(h)
        if not by:
            ctk.CTkLabel(an_scroll, text="No queues recorded yet. Run a drop and this fills in automatically.",
                         text_color=DIM).pack(pady=30)
            return
        ranked = sorted(by.items(), key=lambda kv: min(int(x.get("start_pos", 10**9)) for x in kv[1]))
        for email, rows in ranked:
            poss = [int(r.get("start_pos", 0)) for r in rows if r.get("start_pos")]
            best = min(poss) if poss else "—"
            avg = int(sum(poss) / len(poss)) if poss else "—"
            last = rows[-1]
            line = ctk.CTkFrame(an_scroll, fg_color="#14141C", corner_radius=8, height=36)
            line.pack(fill="x", padx=4, pady=2)
            line.pack_propagate(False)
            vals = [
                (str(email)[:32], 240, TEXT),
                (str(len(rows)), 60, MUTED),
                (str(best), 90, GREEN),
                (str(avg), 90, ACCENT),
                (str(last.get("start_pos", "—")), 90, TEXT),
                (str(last.get("event", ""))[:28], 220, MUTED),
            ]
            for txt, w, col in vals:
                ctk.CTkLabel(line, text=txt, width=w, anchor="w",
                             font=ctk.CTkFont(size=11), text_color=col).pack(side="left", padx=2)

    # ════════════════════════════════════════════
    #  PAGE: PROXIES
    # ════════════════════════════════════════════
    page_proxy = ctk.CTkFrame(content, fg_color=BG)
    pages["proxies"] = page_proxy

    px_top = ctk.CTkFrame(page_proxy, fg_color="transparent")
    px_top.pack(fill="x", pady=(0, 8))
    ctk.CTkLabel(px_top, text="PROXY GROUPS",
                 font=ctk.CTkFont(size=18, weight="bold"),
                 text_color=TEXT).pack(side="left")

    px_split = ctk.CTkFrame(page_proxy, fg_color="transparent")
    px_split.pack(fill="both", expand=True)
    px_rail_card = card(px_split, width=220)
    px_rail_card.pack(side="left", fill="y", padx=(0, 8))
    px_rail_card.pack_propagate(False)
    px_rail = ctk.CTkScrollableFrame(px_rail_card, fg_color="transparent")
    px_rail.pack(fill="both", expand=True, padx=6, pady=6)

    px_main = card(px_split)
    px_main.pack(side="left", fill="both", expand=True)
    px_title = ctk.CTkLabel(px_main, text="Select a proxy group",
                            font=ctk.CTkFont(size=14, weight="bold"), text_color=ACCENT)
    px_title.pack(anchor="w", padx=12, pady=(10, 4))
    proxy_box = ctk.CTkTextbox(px_main, fg_color=BG, text_color=TEXT,
                               font=ctk.CTkFont(family="Consolas", size=12),
                               corner_radius=10, border_width=1, border_color=BORDER)
    proxy_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    px_state = {"groups": {}, "selected": None, "loading": False}

    def _write_flat():
        flat = [p for lst in px_state["groups"].values() for p in lst]
        PROXIES_FILE.write_text(("\n".join(flat) + "\n") if flat else "")

    def refresh_proxy_rail():
        for w in px_rail.winfo_children():
            w.destroy()
        names = list(px_state["groups"].keys())
        if not names:
            ctk.CTkLabel(px_rail, text="No groups", text_color=DIM).pack(pady=12)
            return
        for name in names:
            on = name == px_state["selected"]
            b = ctk.CTkButton(
                px_rail, text=f"{name}   ({len(px_state['groups'][name])})",
                anchor="w", height=36, corner_radius=8,
                fg_color="#142028" if on else "transparent",
                text_color=ACCENT if on else TEXT,
                hover_color=CARD_HOVER,
                command=lambda n=name: open_proxy_group(n))
            b.pack(fill="x", pady=2)

    def open_proxy_group(name):
        if px_state["selected"] and px_state["selected"] != name and not px_state["loading"]:
            save_proxies(quiet=True)
        px_state["selected"] = name
        px_state["loading"] = True
        proxy_box.delete("1.0", TKEND)
        proxy_box.insert("1.0", "\n".join(px_state["groups"].get(name, [])))
        px_state["loading"] = False
        px_title.configure(text=name)
        refresh_proxy_rail()

    def load_proxies_ui():
        data = ProxyGroupManager.load()
        if not data and PROXIES_FILE.exists():
            lines = [l.strip() for l in PROXIES_FILE.read_text().splitlines() if l.strip()]
            if lines:
                data = {"default": lines}
                ProxyGroupManager.save(data)
        px_state["groups"] = data or {}
        if px_state["groups"] and not px_state["selected"]:
            px_state["selected"] = next(iter(px_state["groups"]))
        refresh_proxy_rail()
        if px_state["selected"]:
            open_proxy_group(px_state["selected"])

    def save_proxies(quiet=False):
        name = px_state.get("selected")
        if not name or px_state["loading"]:
            return
        lines = [l.strip() for l in proxy_box.get("1.0", TKEND).splitlines() if l.strip()]
        px_state["groups"][name] = lines
        ProxyGroupManager.save(px_state["groups"])
        _write_flat()
        refresh_proxy_rail()
        if not quiet:
            log(f"Saved proxy group [{name}] ({len(lines)})")

    px_form = ctk.CTkFrame(page_proxy, fg_color="#0E0E16", corner_radius=16,
                           border_width=1, border_color=ACCENT)

    def hide_px_form():
        px_form.place_forget()

    def prompt_proxy_name(title, current, on_ok):
        for w in px_form.winfo_children():
            w.destroy()
        ctk.CTkLabel(px_form, text=title, font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=20, pady=(16, 4))
        entry = ctk.CTkEntry(px_form, height=36, fg_color=BG, border_color=BORDER, text_color=TEXT)
        if current:
            entry.insert(0, current)
        entry.pack(fill="x", padx=20, pady=10)

        def commit(_e=None):
            name = entry.get().strip()
            if not name:
                return
            hide_px_form()
            on_ok(name)

        row = ctk.CTkFrame(px_form, fg_color="transparent")
        row.pack(anchor="w", padx=20, pady=(0, 14))
        neon_btn(row, "SAVE", GREEN, commit, width=90).pack(side="left", padx=(0, 8))
        neon_btn(row, "CANCEL", DIM, hide_px_form, width=90).pack(side="left")
        entry.bind("<Return>", commit)
        px_form.place(relx=0.28, rely=0.24, relwidth=0.44, relheight=0.32)
        px_form.lift()
        entry.focus()

    def add_proxy_group():
        def create(name):
            if name in px_state["groups"]:
                log(f"Proxy group [{name}] already exists")
                open_proxy_group(name)
                return
            px_state["groups"][name] = []
            ProxyGroupManager.save(px_state["groups"])
            open_proxy_group(name)
            log(f"Proxy group [{name}]")
        prompt_proxy_name("New proxy group", "", create)

    def edit_proxy_group():
        old = px_state.get("selected")
        if not old:
            log("Select a proxy group first")
            return
        def rename(name):
            if name == old:
                return
            if name in px_state["groups"]:
                log(f"Proxy group [{name}] already exists")
                return
            save_proxies(quiet=True)
            ordered = [(name if k == old else k, v) for k, v in px_state["groups"].items()]
            px_state["groups"] = dict(ordered)
            ProxyGroupManager.save(px_state["groups"])
            for g in state["groups"]:
                if g.proxy_group == old:
                    g.proxy_group = name
                for t in g.tasks or []:
                    if t.get("proxy") == old:
                        t["proxy"] = name
            save_groups(state["groups"])
            px_state["selected"] = name
            open_proxy_group(name)
            log(f"Renamed proxy group [{old}]  [{name}]")
        prompt_proxy_name("Rename proxy group", old, rename)

    def delete_proxy_group():
        name = px_state.get("selected")
        if not name:
            return
        px_state["groups"].pop(name, None)
        ProxyGroupManager.save(px_state["groups"])
        _write_flat()
        px_state["selected"] = next(iter(px_state["groups"]), None)
        if px_state["selected"]:
            open_proxy_group(px_state["selected"])
        else:
            proxy_box.delete("1.0", TKEND)
            px_title.configure(text="Select a proxy group")
            refresh_proxy_rail()

    neon_btn(px_top, "+ GROUP", ACCENT, add_proxy_group, width=100).pack(side="right", padx=4)
    neon_btn(px_top, "EDIT", ACCENT2, edit_proxy_group, width=80).pack(side="right", padx=4)
    neon_btn(px_top, "DELETE", RED, delete_proxy_group, width=90).pack(side="right", padx=4)

    _proxy_job = {"id": None}

    def queue_proxy_save(_e=None):
        if px_state["loading"]:
            return
        if _proxy_job["id"]:
            app.after_cancel(_proxy_job["id"])
        _proxy_job["id"] = app.after(500, lambda: save_proxies(quiet=True))

    proxy_box.bind("<KeyRelease>", queue_proxy_save)

    # ════════════════════════════════════════════
    #  PAGE: SETTINGS
    # ════════════════════════════════════════════
    page_set = ctk.CTkFrame(content, fg_color=BG)
    pages["settings"] = page_set

    ctk.CTkLabel(page_set, text="SETTINGS",
                 font=ctk.CTkFont(size=20, weight="bold"),
                 text_color=TEXT).pack(anchor="w", pady=(0, 8))

    tab_bar = ctk.CTkFrame(page_set, fg_color="transparent")
    tab_bar.pack(fill="x", pady=(0, 8))
    set_body = ctk.CTkFrame(page_set, fg_color="transparent")
    set_body.pack(fill="both", expand=True)
    set_tabs = {}
    set_tab_btns = {}

    def show_set_tab(name):
        for n, fr in set_tabs.items():
            if n == name:
                fr.pack(fill="both", expand=True)
            else:
                fr.pack_forget()
        for n, b in set_tab_btns.items():
            on = n == name
            b.configure(fg_color=ACCENT if on else CARD,
                        text_color="#061018" if on else TEXT)

    for _name in ("General", "Captchas", "Webhook", "IMAP", "Update"):
        _b = ctk.CTkButton(tab_bar, text=_name, width=110, height=32, corner_radius=8,
                           fg_color=CARD, hover_color=CARD_HOVER, text_color=TEXT,
                           command=lambda n=_name: show_set_tab(n))
        _b.pack(side="left", padx=(0, 6))
        set_tab_btns[_name] = _b
        set_tabs[_name] = ctk.CTkScrollableFrame(set_body, fg_color="transparent")

    set_vars = {}

    def settings_section(title, parent):
        ctk.CTkLabel(parent, text=title,
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=ACCENT).pack(anchor="w", pady=(14, 4), padx=4)
        f = card(parent)
        f.pack(fill="x", pady=2)
        return f

    # ── AUTO UPDATE ─────────────────────────────
    upd = settings_section("AUTO UPDATE", set_tabs["Update"])
    field_label(upd, "Update URL (raw .py file)").pack(anchor="w", padx=12, pady=(10, 0))
    set_vars["update_url"] = ctk.CTkEntry(upd, height=32, fg_color=BG,
                                          border_color=BORDER, text_color=TEXT)
    set_vars["update_url"].insert(0, CONFIG.get("update", {}).get("url", ""))
    set_vars["update_url"].pack(fill="x", padx=12, pady=4)

    set_vars["check_on_start"] = BooleanVar(value=CONFIG.get("update", {}).get("check_on_start", False))
    ctk.CTkSwitch(upd, text="Check for updates on startup",
                  variable=set_vars["check_on_start"],
                  progress_color=ACCENT, button_color=TEXT, fg_color=DIM,
                  text_color=TEXT).pack(anchor="w", padx=12, pady=6)

    update_status = ctk.CTkLabel(upd, text=f"Current version: {VERSION}",
                                 font=ctk.CTkFont(size=11), text_color=MUTED)
    update_status.pack(anchor="w", padx=12, pady=(2, 8))

    upd_btns = ctk.CTkFrame(upd, fg_color="transparent")
    upd_btns.pack(fill="x", padx=12, pady=(0, 12))

    def do_check_update():
        url = set_vars["update_url"].get().strip()
        update_status.configure(text="Checking…", text_color=YELLOW)
        def work():
            is_new, ver, msg = Updater.check(url)
            color = GREEN if is_new else MUTED
            app.after(0, lambda: update_status.configure(text=msg, text_color=color))
            app.after(0, lambda: log(f"Update check: {msg}"))
        threading.Thread(target=work, daemon=True).start()

    def do_push_update():
        folder = Path(__file__).resolve().parent
        update_status.configure(text="Pushing to GitHub…", text_color=YELLOW)
        def work():
            try:
                add = subprocess.run(["git", "add", "KarmaUltra.py"], cwd=folder, capture_output=True, text=True)
                commit = subprocess.run(["git", "commit", "-m", f"update {VERSION}"], cwd=folder, capture_output=True, text=True)
                push = subprocess.run(["git", "push"], cwd=folder, capture_output=True, text=True)
                ok = push.returncode == 0
                msg = (push.stdout or push.stderr or commit.stderr or "pushed").strip().splitlines()[-1]
                if add.returncode != 0:
                    ok = False
                    msg = (add.stderr or "git add failed").strip()
            except Exception as e:
                ok, msg = False, str(e)
            app.after(0, lambda: update_status.configure(text=msg[:120], text_color=GREEN if ok else RED))
            app.after(0, lambda: log(f"Push update: {msg}"))
        threading.Thread(target=work, daemon=True).start()

    def do_install_update():
        url = set_vars["update_url"].get().strip()
        if not messagebox.askyesno("Confirm Update",
                                   "This will replace the current script with the remote version.\n"
                                   "A .bak backup will be created.\n\nContinue?"):
            return
        update_status.configure(text="Downloading…", text_color=YELLOW)
        def work():
            ok, msg = Updater.install(url)
            color = GREEN if ok else RED
            app.after(0, lambda: update_status.configure(text=msg, text_color=color))
            app.after(0, lambda: log(f"Update: {msg}"))
            if ok:
                app.after(0, lambda: messagebox.showinfo(
                    "Update Ready",
                    "Update installed.\nRestart the bot to use the new version.\n\n"
                    "Click OK then close and relaunch, or use the Restart button."))
        threading.Thread(target=work, daemon=True).start()

    def do_restart():
        if messagebox.askyesno("Restart", "Restart Karma Ultra now?"):
            log("Restarting…")
            app.after(200, Updater.restart)

    neon_btn(upd_btns, "CHECK", ACCENT, do_check_update, width=100, height=30).pack(side="left", padx=2)
    neon_btn(upd_btns, "INSTALL", GREEN, do_install_update, width=110, height=30).pack(side="left", padx=2)
    neon_btn(upd_btns, "PUSH", ACCENT, do_push_update, width=90, height=30).pack(side="left", padx=2)
    neon_btn(upd_btns, "RESTART", ORANGE, do_restart, width=100, height=30).pack(side="left", padx=2)

    # Discord
    disc = settings_section("DISCORD", set_tabs["Webhook"])
    field_label(disc, "Webhook URL").pack(anchor="w", padx=12, pady=(10, 0))
    set_vars["webhook"] = ctk.CTkEntry(disc, height=32, fg_color=BG,
                                       border_color=BORDER, text_color=TEXT)
    set_vars["webhook"].insert(0, CONFIG["discord"].get("webhook_url", ""))
    set_vars["webhook"].pack(fill="x", padx=12, pady=4)
    field_label(disc, "Mention User ID").pack(anchor="w", padx=12, pady=(6, 0))
    set_vars["mention"] = ctk.CTkEntry(disc, height=32, fg_color=BG,
                                       border_color=BORDER, text_color=TEXT, width=200)
    set_vars["mention"].insert(0, CONFIG["discord"].get("mention_user_id", ""))
    set_vars["mention"].pack(anchor="w", padx=12, pady=(2, 10))

    # Captcha keys and which provider to use per type. Stored only.
    cap = settings_section("CAPTCHA", set_tabs["Captchas"])
    ctk.CTkLabel(cap, text="Solver keys", font=ctk.CTkFont(size=14, weight="bold"),
                 text_color=TEXT).pack(anchor="w", padx=12, pady=(10, 0))
    ctk.CTkLabel(cap, text="Paste a different key in each box. It is saved on this PC.",
                 font=ctk.CTkFont(size=11), text_color=MUTED).pack(anchor="w", padx=12, pady=(0, 6))
    key_grid = ctk.CTkFrame(cap, fg_color="transparent")
    key_grid.pack(fill="x", padx=8, pady=4)
    for col in range(3):
        key_grid.grid_columnconfigure(col, weight=1)
    providers = [
        "2Captcha", "AntiCaptcha", "CapMonster", "CapSolver", "Uncaptcha", "CaptchaFun",
        "AYCD", "Hyper Solutions", "KagedCap", "DispurCaptcha", "Resolvr",
    ]
    balance_urls = {
        "2Captcha": "https://api.2captcha.com/getBalance",
        "AntiCaptcha": "https://api.anti-captcha.com/getBalance",
        "CapMonster": "https://api.capmonster.cloud/getBalance",
        "CapSolver": "https://api.capsolver.com/getBalance",
    }
    saved_keys = CONFIG["captcha"].get("keys") or {}
    if not saved_keys.get("CapSolver"):
        saved_keys["CapSolver"] = CONFIG["captcha"].get("api_key", "")
    set_vars["cap_keys"] = {}

    def check_solver_balance(name):
        key = set_vars["cap_keys"][name].get().strip()
        url = balance_urls.get(name)
        if not key:
            log(f"{name}: paste a key first")
            return
        if not url:
            log(f"{name}: this provider has no balance check")
            return

        def work():
            try:
                data = requests.post(url, json={"clientKey": key}, timeout=20).json()
                if data.get("balance") is not None and not data.get("errorId"):
                    msg = f"balance {data.get('balance')}"
                else:
                    msg = data.get("errorDescription") or data.get("errorCode") or "could not read balance"
            except Exception as e:
                msg = str(e)
            app.after(0, lambda m=msg: log(f"{name}: {m}"))

        threading.Thread(target=work, daemon=True).start()

    for i, name in enumerate(providers):
        cell = ctk.CTkFrame(key_grid, fg_color="#101018", corner_radius=10,
                            border_width=1, border_color=BORDER)
        cell.grid(row=i // 3, column=i % 3, sticky="nsew", padx=6, pady=6)
        head = ctk.CTkFrame(cell, fg_color="transparent")
        head.pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(head, text=name, font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT).pack(side="left")
        if name in balance_urls:
            neon_btn(head, "CHECK BALANCE", ACCENT, lambda n=name: check_solver_balance(n),
                     width=118, height=24).pack(side="left", padx=(8, 0))
        entry = ctk.CTkEntry(cell, height=32, fg_color=BG, border_color=BORDER,
                             text_color=TEXT, placeholder_text=f"Insert {name} key")
        if saved_keys.get(name) and saved_keys.get(name) != "YOUR_CAPSOLVER_KEY":
            entry.insert(0, saved_keys.get(name, ""))
        entry.pack(fill="x", padx=10, pady=(0, 10))
        set_vars["cap_keys"][name] = entry

    ctk.CTkLabel(cap, text="Solver method", font=ctk.CTkFont(size=14, weight="bold"),
                 text_color=TEXT).pack(anchor="w", padx=12, pady=(12, 0))
    ctk.CTkLabel(cap, text="Which saved provider you want noted for each captcha type.",
                 font=ctk.CTkFont(size=11), text_color=MUTED).pack(anchor="w", padx=12, pady=(0, 6))
    method_grid = ctk.CTkFrame(cap, fg_color="transparent")
    method_grid.pack(fill="x", padx=8, pady=(0, 10))
    for col in range(4):
        method_grid.grid_columnconfigure(col, weight=1)
    captcha_types = [
        "Recaptcha v2", "Recaptcha v3", "HCaptcha", "Text captcha",
        "Datadome", "Funcaptcha", "Cloudflare", "AWS WAF",
        "Captcha fox", "Icon captcha", "Incapsula", "Kasada",
    ]
    method_choices = ["Manual"] + providers
    saved_methods = CONFIG["captcha"].get("methods") or {}
    set_vars["cap_methods"] = {}
    for i, name in enumerate(captcha_types):
        cell = ctk.CTkFrame(method_grid, fg_color="transparent")
        cell.grid(row=i // 4, column=i % 4, sticky="nsew", padx=6, pady=4)
        ctk.CTkLabel(cell, text=name, font=ctk.CTkFont(size=12),
                     text_color=ACCENT).pack(anchor="w")
        current = saved_methods.get(name) or ("CapSolver" if name == "Funcaptcha" else "Manual")
        if current not in method_choices:
            current = "Manual"
        var = StringVar(value=current)
        ctk.CTkOptionMenu(cell, values=method_choices, variable=var, height=32,
                          fg_color=BG, button_color=CARD_HOVER, button_hover_color=BORDER,
                          text_color=TEXT).pack(fill="x", pady=(2, 0))
        set_vars["cap_methods"][name] = var

    # AI
    ai_f = settings_section("AI BRAIN", set_tabs["General"])
    AI_MODELS = {
        "openrouter": [
            "openrouter/free",
            "thinkingmachines/inkling:free",
            "thinkingmachines/inkling-small:free",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "nvidia/nemotron-3.5-lightning:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "google/gemma-4-31b-it:free",
            "google/gemma-4-26b-a4b-it:free",
            "qwen/qwen3.8-27b:free",
            "cohere/north-mini-code:free",
            "inclusionai/ling-3.1-flash",
        ],
        "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "o4-mini"],
        "groq": ["llama-3.1-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        "ollama": ["llama3.1", "qwen2.5", "mistral"],
    }
    field_label(ai_f, "Provider").pack(anchor="w", padx=12, pady=(10, 0))
    set_vars["aiprov"] = StringVar(value=CONFIG["ai"].get("provider", "openrouter"))
    ctk.CTkOptionMenu(ai_f, values=["openrouter", "openai", "groq", "ollama"],
                      variable=set_vars["aiprov"], height=32, fg_color=BG,
                      button_color=CARD_HOVER, button_hover_color=BORDER,
                      text_color=TEXT, width=180).pack(anchor="w", padx=12, pady=2)
    field_label(ai_f, "API Key").pack(anchor="w", padx=12, pady=(6, 0))
    set_vars["aikey"] = ctk.CTkEntry(ai_f, height=32, fg_color=BG,
                                     border_color=BORDER, text_color=TEXT, show="•")
    set_vars["aikey"].insert(0, CONFIG["ai"].get("api_key", ""))
    set_vars["aikey"].pack(fill="x", padx=12, pady=2)
    field_label(ai_f, "Model").pack(anchor="w", padx=12, pady=(6, 0))
    current_model = CONFIG["ai"].get("model", "openrouter/free")
    set_vars["aimodel"] = StringVar(value=current_model)
    model_menu = ctk.CTkOptionMenu(ai_f, values=AI_MODELS.get(set_vars["aiprov"].get(), AI_MODELS["openrouter"]),
                                   variable=set_vars["aimodel"], height=32, fg_color=BG,
                                   button_color=CARD_HOVER, button_hover_color=BORDER,
                                   text_color=TEXT, width=280)
    model_menu.pack(anchor="w", padx=12, pady=(2, 10))

    def on_ai_provider(*_):
        choices = AI_MODELS.get(set_vars["aiprov"].get(), AI_MODELS["openrouter"])
        model_menu.configure(values=choices)
        if set_vars["aimodel"].get() not in choices:
            set_vars["aimodel"].set(choices[0])

    set_vars["aiprov"].trace_add("write", on_ai_provider)

    # IMAP mailboxes
    imap_wrap = ctk.CTkFrame(set_tabs["IMAP"], fg_color="transparent")
    imap_wrap.pack(fill="both", expand=True)
    ctk.CTkLabel(imap_wrap, text="Mailboxes used to read the email code. Open one to see the inbox.",
                 font=ctk.CTkFont(size=12), text_color=MUTED, wraplength=720, justify="left"
                 ).pack(anchor="w", padx=4, pady=(8, 6))
    imap_list = ctk.CTkScrollableFrame(imap_wrap, fg_color="transparent", height=280)
    imap_list.pack(fill="both", expand=True, padx=2)
    add_box = card(imap_wrap)
    add_box.pack(fill="x", pady=8)
    ctk.CTkLabel(add_box, text="Add mailbox", font=ctk.CTkFont(size=13, weight="bold"),
                 text_color=TEXT).pack(anchor="w", padx=12, pady=(8, 4))
    add_row = ctk.CTkFrame(add_box, fg_color="transparent")
    add_row.pack(fill="x", padx=12, pady=(0, 10))
    imap_email_e = ctk.CTkEntry(add_row, width=220, height=32, placeholder_text="email",
                                fg_color=BG, border_color=BORDER, text_color=TEXT)
    imap_pass_e = ctk.CTkEntry(add_row, width=160, height=32, placeholder_text="app password",
                               fg_color=BG, border_color=BORDER, text_color=TEXT, show="•")
    imap_host_e = ctk.CTkEntry(add_row, width=180, height=32, placeholder_text="imap.gmail.com",
                               fg_color=BG, border_color=BORDER, text_color=TEXT)
    imap_port_e = ctk.CTkEntry(add_row, width=70, height=32, placeholder_text="993",
                               fg_color=BG, border_color=BORDER, text_color=TEXT)
    imap_port_e.insert(0, "993")
    for w, px in ((imap_email_e, 0), (imap_pass_e, 6), (imap_host_e, 6), (imap_port_e, 6)):
        w.pack(side="left", padx=(px, 0))
    imap_edit = {"index": None}

    def mailbox_rows():
        boxes = list((CONFIG.get("imap") or {}).get("mailboxes") or [])
        if not boxes and (CONFIG.get("imap") or {}).get("email"):
            one = CONFIG["imap"]
            boxes = [{"email": one.get("email", ""), "password": one.get("password", ""),
                      "host": one.get("host", ""), "port": one.get("port", 993)}]
        return boxes

    def store_mailboxes(boxes):
        CONFIG.setdefault("imap", {})
        CONFIG["imap"]["mailboxes"] = boxes
        if boxes:
            CONFIG["imap"]["email"] = boxes[0].get("email", "")
            CONFIG["imap"]["password"] = boxes[0].get("password", "")
            CONFIG["imap"]["host"] = boxes[0].get("host", "")
            CONFIG["imap"]["port"] = int(boxes[0].get("port") or 993)
        jsave(CONFIG_FILE, CONFIG)

    def refresh_mailboxes():
        for w in imap_list.winfo_children():
            w.destroy()
        boxes = mailbox_rows()
        if not boxes:
            ctk.CTkLabel(imap_list, text="No mailboxes yet", text_color=DIM).pack(anchor="w", pady=8)
            return
        for i, box in enumerate(boxes):
            row = ctk.CTkFrame(imap_list, fg_color=CARD, corner_radius=10)
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=box.get("email") or "?", font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=TEXT).pack(anchor="w", padx=12, pady=(8, 0))
            ctk.CTkLabel(row, text=f"{box.get('host') or '?'}:{box.get('port') or 993}",
                         font=ctk.CTkFont(size=11), text_color=MUTED).pack(anchor="w", padx=12)
            btns = ctk.CTkFrame(row, fg_color="transparent")
            btns.pack(anchor="e", padx=8, pady=(0, 8))
            neon_btn(btns, "OPEN", ACCENT, lambda b=box: open_mailbox(b), width=70, height=28).pack(side="left", padx=3)
            neon_btn(btns, "EDIT", CARD_HOVER, lambda n=i, b=box: edit_mailbox(n, b), width=70, height=28).pack(side="left", padx=3)
            neon_btn(btns, "DELETE", RED, lambda n=i: delete_mailbox(n), width=80, height=28).pack(side="left", padx=3)

    def edit_mailbox(index, box):
        imap_edit["index"] = index
        imap_email_e.delete(0, "end")
        imap_pass_e.delete(0, "end")
        imap_host_e.delete(0, "end")
        imap_port_e.delete(0, "end")
        imap_email_e.insert(0, box.get("email", ""))
        imap_pass_e.insert(0, box.get("password", ""))
        imap_host_e.insert(0, box.get("host", ""))
        imap_port_e.insert(0, str(box.get("port") or 993))

    def delete_mailbox(index):
        boxes = mailbox_rows()
        if 0 <= index < len(boxes):
            boxes.pop(index)
        store_mailboxes(boxes)
        refresh_mailboxes()

    def add_mailbox():
        email = imap_email_e.get().strip()
        password = imap_pass_e.get().strip()
        host = imap_host_e.get().strip()
        if not host and email.endswith("@gmail.com"):
            host = "imap.gmail.com"
        if not email or not password or not host:
            log("Mailbox needs email, password and host")
            return
        try:
            port = int(imap_port_e.get() or 993)
        except ValueError:
            port = 993
        boxes = mailbox_rows()
        row = {"email": email, "password": password, "host": host, "port": port, "ssl": True}
        if imap_edit["index"] is not None and 0 <= imap_edit["index"] < len(boxes):
            boxes[imap_edit["index"]] = row
        else:
            boxes.append(row)
        imap_edit["index"] = None
        store_mailboxes(boxes)
        refresh_mailboxes()
        log(f"Mailbox saved {email}")

    neon_btn(add_row, "SAVE", GREEN, add_mailbox, width=80, height=32).pack(side="left", padx=8)

    mail_view = {"frame": None}

    def open_mailbox(box):
        if mail_view["frame"] is not None:
            try:
                mail_view["frame"].destroy()
            except Exception:
                pass
        panel = ctk.CTkFrame(page_set, fg_color="#101018", corner_radius=16,
                             border_width=1, border_color=BORDER)
        panel.place(relx=0.08, rely=0.08, relwidth=0.84, relheight=0.84)
        mail_view["frame"] = panel
        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=10)
        ctk.CTkLabel(head, text=f"Mailbox — {box.get('email')}",
                     font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT).pack(side="left")
        neon_btn(head, "X", RED, panel.destroy, width=36, height=28).pack(side="right")
        body = ctk.CTkScrollableFrame(panel, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=4)
        foot = ctk.CTkFrame(panel, fg_color="transparent")
        foot.pack(fill="x", padx=12, pady=8)
        status = ctk.CTkLabel(foot, text="Loading inbox…", text_color=MUTED)
        status.pack(side="left")
        state = {"page": 0, "total": 0}

        def draw(rows, total, page):
            for w in body.winfo_children():
                w.destroy()
            state["total"] = total
            pages = max(1, (total + 7) // 8)
            status.configure(text=f"INBOX · page {page + 1} / {pages} — {total} messages")
            if not rows:
                ctk.CTkLabel(body, text="No messages", text_color=DIM).pack(pady=20)
                return
            for msg in rows:
                cell = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10)
                cell.pack(fill="x", pady=4)
                ctk.CTkLabel(cell, text=msg["subject"][:110], anchor="w",
                             font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT
                             ).pack(fill="x", padx=12, pady=(8, 0))
                ctk.CTkLabel(cell, text=f"{msg['from'][:70]}  ·  {msg['date'][:40]}",
                             anchor="w", font=ctk.CTkFont(size=11), text_color=MUTED
                             ).pack(fill="x", padx=12, pady=(0, 8))

        def load(page):
            status.configure(text="Loading inbox…")

            def work():
                try:
                    rows, total = IMAPFisher.fetch_headers(box, page, 8)
                    app.after(0, lambda: draw(rows, total, page))
                except Exception as e:
                    app.after(0, lambda: status.configure(text=str(e).splitlines()[0][:140]))

            threading.Thread(target=work, daemon=True).start()

        def prev():
            if state["page"] > 0:
                state["page"] -= 1
                load(state["page"])

        def nxt():
            if (state["page"] + 1) * 8 < state["total"]:
                state["page"] += 1
                load(state["page"])

        neon_btn(foot, "PREV", CARD_HOVER, prev, width=70, height=28).pack(side="right", padx=4)
        neon_btn(foot, "NEXT", ACCENT, nxt, width=70, height=28).pack(side="right", padx=4)
        load(0)

    refresh_mailboxes()

    # General
    gen_f = settings_section("GENERAL", set_tabs["General"])
    set_vars["headless"] = BooleanVar(value=CONFIG["general"].get("headless", True))
    set_vars["hybrid"] = BooleanVar(value=CONFIG["general"].get("hybrid_mode", True))
    row_g = ctk.CTkFrame(gen_f, fg_color="transparent")
    row_g.pack(fill="x", padx=12, pady=10)
    ctk.CTkSwitch(row_g, text="Headless", variable=set_vars["headless"],
                  progress_color=ACCENT, button_color=TEXT, fg_color=DIM,
                  text_color=TEXT).pack(side="left", padx=(0, 20))
    ctk.CTkSwitch(row_g, text="Show browser window",
                  variable=set_vars["hybrid"],
                  progress_color=ACCENT, button_color=TEXT, fg_color=DIM,
                  text_color=TEXT).pack(side="left")

    field_label(gen_f, "Keep browser open (minutes)").pack(anchor="w", padx=12, pady=(4, 0))
    set_vars["keep_min"] = ctk.CTkEntry(gen_f, height=32, fg_color=BG,
                                        border_color=BORDER, text_color=TEXT, width=80)
    set_vars["keep_min"].insert(0, str(CONFIG["general"].get("keep_browser_open_min", 15)))
    set_vars["keep_min"].pack(anchor="w", padx=12, pady=(2, 12))

    def save_settings(quiet=False):
        CONFIG["discord"]["webhook_url"] = set_vars["webhook"].get().strip()
        CONFIG["discord"]["mention_user_id"] = set_vars["mention"].get().strip()
        keys = {n: w.get().strip() for n, w in set_vars["cap_keys"].items()}
        methods = {n: w.get().strip() for n, w in set_vars["cap_methods"].items()}
        CONFIG["captcha"]["keys"] = keys
        CONFIG["captcha"]["methods"] = methods
        CONFIG["captcha"]["api_key"] = keys.get("CapSolver", "")
        CONFIG["captcha"]["provider"] = methods.get("Funcaptcha", "CapSolver")
        CONFIG["ai"]["provider"] = set_vars["aiprov"].get().strip()
        CONFIG["ai"]["api_key"] = set_vars["aikey"].get().strip()
        CONFIG["ai"]["model"] = set_vars["aimodel"].get().strip()
        CONFIG["general"]["headless"] = set_vars["headless"].get()
        CONFIG["general"]["hybrid_mode"] = set_vars["hybrid"].get()
        try:
            CONFIG["general"]["keep_browser_open_min"] = int(set_vars["keep_min"].get())
        except ValueError:
            pass
        if "update" not in CONFIG:
            CONFIG["update"] = {}
        CONFIG["update"]["url"] = set_vars["update_url"].get().strip()
        CONFIG["update"]["check_on_start"] = set_vars["check_on_start"].get()
        jsave(CONFIG_FILE, CONFIG)
        global AI
        AI = AIBrain()
        if not quiet:
            log("Settings saved")

    _set_job = {"id": None}

    def queue_settings_save(_e=None):
        if _set_job["id"]:
            app.after_cancel(_set_job["id"])
        _set_job["id"] = app.after(500, lambda: save_settings(quiet=True))

    for _k, _w in set_vars.items():
        widgets = list(_w.values()) if isinstance(_w, dict) else [_w]
        for w in widgets:
            if isinstance(w, (BooleanVar, StringVar)):
                w.trace_add("write", lambda *_: queue_settings_save())
            elif hasattr(w, "bind"):
                w.bind("<KeyRelease>", queue_settings_save)

    def test_discord():
        n = DiscordNotifier(set_vars["webhook"].get().strip())
        ok, msg = n.test()
        log(("OK" if ok else "Error") + f" Discord: {msg}")
        if not ok:
            return
        n.notify_carted(
            "TEST", "Test cart", "GA", "A", ["1", "2"],
            2, 136.78, 273.56, datetime.now() + timedelta(minutes=10),
            "https://www.ticketmaster.com/", True, 0, "$", 0, 250, None,
            email="test@example.com", mode="normal",
            event_name="Test cart notification", store="Ticketmaster US",
            event_url="https://www.ticketmaster.com/")
        log("Test cart notification sent")

    def test_imap():
        boxes = mailbox_rows()
        if not boxes:
            log("Add a mailbox first")
            return
        fisher = IMAPFisher(boxes[0])
        ok, msg = fisher.test_connection()
        log(("OK" if ok else "Error") + f" IMAP: {msg}")


    set_act = ctk.CTkFrame(page_set, fg_color="transparent")
    set_act.pack(fill="x", pady=(8, 0))
    neon_btn(set_act, "SAVE SETTINGS", GREEN, save_settings, width=160).pack(side="left", padx=4)
    neon_btn(set_act, "TEST DISCORD", ACCENT, test_discord, width=150).pack(side="left", padx=4)
    neon_btn(set_act, "TEST IMAP", ACCENT2, test_imap, width=130).pack(side="left", padx=4)
    show_set_tab("General")

    # ════════════════════════════════════════════
    #  PAGE: LIVE LOG
    # ════════════════════════════════════════════
    page_log = ctk.CTkFrame(content, fg_color=BG)
    pages["logs"] = page_log

    log_top = ctk.CTkFrame(page_log, fg_color="transparent")
    log_top.pack(fill="x", pady=(0, 8))
    ctk.CTkLabel(log_top, text="LIVE LOG",
                 font=ctk.CTkFont(size=20, weight="bold"),
                 text_color=TEXT).pack(side="left")
    neon_btn(log_top, "CLR", DIM, lambda: clear_log(), width=60, height=28).pack(side="right")

    log_box = ctk.CTkTextbox(page_log, fg_color=CARD, text_color=TEXT,
                             font=ctk.CTkFont(family="Consolas", size=12),
                             corner_radius=12, border_width=1, border_color=BORDER,
                             wrap="word", state="disabled")
    log_box.pack(fill="both", expand=True)

    def log(msg):
        ts = datetime.now().strftime("%H:%M:%S")
        raw = str(msg)
        pieces = []
        for part in raw.splitlines() or [""]:
            while len(part) > 160:
                pieces.append(part[:160])
                part = part[160:]
            pieces.append(part)
        lines = []
        for i, piece in enumerate(pieces):
            lines.append(f"[{ts}]  {piece}" if i == 0 else f"[{ts}]    {piece}")

        def write():
            for line in lines:
                print(line)
                state["log_lines"].append(line)
            if len(state["log_lines"]) > 2000:
                state["log_lines"] = state["log_lines"][-1500:]
            try:
                log_box.configure(state="normal")
                log_box.insert(TKEND, "\n".join(lines) + "\n")
                log_box.see(TKEND)
                log_box.configure(state="disabled")
            except Exception:
                pass

        try:
            app.after(0, write)
        except Exception:
            write()

    def clear_log():
        state["log_lines"].clear()
        log_box.configure(state="normal")
        log_box.delete("1.0", TKEND)
        log_box.configure(state="disabled")

    # ── STATUS HELPER ────────────────────────────
    def set_status(text, color):
        def apply():
            status_lbl.configure(text=text, text_color=color)
            status_dot.configure(text_color=color)
            status_pill.configure(border_color=color)
            state["status_color"] = color
        try:
            app.after(0, apply)
        except Exception:
            apply()

    pulse = {"i": 0}

    def pulse_status():
        return

    # ── INIT ─────────────────────────────────────
    refresh_group_list()
    refresh_accounts()
    refresh_analytics()
    load_proxies_ui()
    refresh_side_stats()
    m_groups.configure(text=str(len(state["groups"])))
    refresh_board()
    for _name, _frame in pages.items():
        _frame.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        _frame.grid_remove()
    switch_page("dashboard")
    state["status_color"] = YELLOW
    pulse_status()
    log(f"Karma Ultra online — Neon Core v{VERSION}")
    watch_updates()

    grip = ctk.CTkLabel(app, text="◢", width=22, height=22,
                        font=ctk.CTkFont(size=14), text_color=MUTED,
                        fg_color="#0A0A0A", cursor="size_nw_se")
    grip.place(relx=1.0, rely=1.0, anchor="se")
    grip.lift()

    def start_resize(event):
        app._rw = app.winfo_width()
        app._rh = app.winfo_height()
        app._rx = event.x_root
        app._ry = event.y_root

    def do_resize(event):
        w = max(1100, app._rw + (event.x_root - app._rx))
        h = max(680, app._rh + (event.y_root - app._ry))
        app.geometry(f"{int(w)}x{int(h)}")

    grip.bind("<Button-1>", start_resize)
    grip.bind("<B1-Motion>", do_resize)

    app.mainloop()


if __name__ == "__main__":
    print("Karma Ultra — Neon Core GUI")
    run_gui()
