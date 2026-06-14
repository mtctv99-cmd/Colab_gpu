"""Playwright automation module for controlling Google Colab workers."""

import asyncio
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from app.config import DATA_DIR, PROFILES_DIR, GITHUB_USER, GITHUB_REPO, COLAB_NOTEBOOK_PATH, WORKER_KEEPALIVE_INTERVAL, QUOTA_RESET_HOURS
from app.database import async_session
from app.models import GoogleAccount
from sqlalchemy import update

logger = logging.getLogger(__name__)

CELL_START_TIMEOUT_SECONDS = 90
CELL_START_BACKOFF_MINUTES = 10
LOGIN_WATCH_TIMEOUT_SECONDS = 300

ROLE_WORKER = "worker"
ROLE_LOGIN = "login"


@dataclass
class BrowserEntry:
    email: str
    role: str
    pw: Any = None
    context: Any = None
    page: Any = None
    pid: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    keepalive_task: asyncio.Task | None = None
    login_watcher_task: asyncio.Task | None = None


class BrowserRegistry:
    """Single source of truth for all managed browser instances."""

    def __init__(self):
        self._entries: dict[str, BrowserEntry] = {}

    def register(self, email: str, role: str, pw=None, context=None, page=None) -> BrowserEntry:
        entry = BrowserEntry(email=email, role=role, pw=pw, context=context, page=page)
        if pw and hasattr(pw, 'pid'):
            try:
                entry.pid = pw.pid
            except Exception:
                pass
        self._entries[email] = entry
        return entry

    def unregister(self, email: str) -> BrowserEntry | None:
        return self._entries.pop(email, None)

    def get(self, email: str) -> BrowserEntry | None:
        return self._entries.get(email)

    def is_running(self, email: str) -> bool:
        return email in self._entries

    def get_pid(self, email: str) -> int:
        e = self._entries.get(email)
        return e.pid if e else 0

    def get_all(self) -> dict[str, BrowserEntry]:
        return dict(self._entries)

    def get_active_profiles(self) -> set[str]:
        return {str(PROFILES_DIR / email) for email in self._entries}

    def get_emails_by_role(self, role: str) -> list[str]:
        return [e.email for e in self._entries.values() if e.role == role]

    async def stop_one(self, email: str):
        """Stop a single browser by email: cancel tasks, close context, kill process."""
        entry = self._entries.get(email)
        if not entry:
            return

        # Cancel keepalive
        if entry.keepalive_task and not entry.keepalive_task.done():
            entry.keepalive_task.cancel()
            try:
                await entry.keepalive_task
            except (asyncio.CancelledError, Exception):
                pass

        # Cancel login watcher
        if entry.login_watcher_task and not entry.login_watcher_task.done():
            entry.login_watcher_task.cancel()
            try:
                await entry.login_watcher_task
            except (asyncio.CancelledError, Exception):
                pass

        # Close context & playwright
        if entry.context:
            try:
                await entry.context.close()
            except Exception:
                pass
        if entry.pw:
            try:
                await entry.pw.stop()
            except Exception:
                pass

        # Kill lingering Chrome process by PID
        if entry.pid:
            try:
                os.kill(entry.pid, 9)
            except (ProcessLookupError, PermissionError, OSError):
                pass

        self._entries.pop(email, None)
        logger.info("Stopped browser [role=%s] for %s (pid=%s)", entry.role, email, entry.pid)

    async def stop_all(self):
        for email in list(self._entries.keys()):
            await self.stop_one(email)

    async def stop_role(self, role: str):
        for email in list(self._entries.keys()):
            if self._entries.get(email, {}).get('role') == role:
                await self.stop_one(email)

    def set_page(self, email: str, page):
        e = self._entries.get(email)
        if e:
            e.page = page

    def set_keepalive_task(self, email: str, task: asyncio.Task):
        e = self._entries.get(email)
        if e:
            e.keepalive_task = task

    def set_login_watcher_task(self, email: str, task: asyncio.Task):
        e = self._entries.get(email)
        if e:
            e.login_watcher_task = task

    def set_pid(self, email: str, pid: int):
        e = self._entries.get(email)
        if e:
            e.pid = pid


_registry = BrowserRegistry()


# JS utilities for Playwright automation - injected via add_init_script
_JS_UTILS = """
(function() {
    console.log('Injecting __colabUtils...');
    window.__colabUtils = {
        findByText: function(root, texts, tags) {
            const tagSet = tags ? new Set(tags.map(t => t.toUpperCase())) : null;
            for (const el of root.querySelectorAll('*')) {
                if (tagSet && !tagSet.has(el.tagName)) {
                    if (el.shadowRoot) {
                        const r = this.findByText(el.shadowRoot, texts, tags);
                        if (r) return r;
                    }
                    continue;
                }
                const txt = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
                if (texts.some(t => txt === t || txt.startsWith(t))) return el;
                if (el.shadowRoot) {
                    const r = this.findByText(el.shadowRoot, texts, tags);
                    if (r) return r;
                }
            }
            return null;
        },
        checkGpuStatus: function() {
            const host = document.querySelector('colab-connect-button');
            if (!host || !host.shadowRoot) return 'unknown';
            const txt = host.shadowRoot.innerText || '';
            if (txt.includes('Connected') && (txt.includes('RAM') || host.shadowRoot.querySelector('colab-usage-meter'))) {
                if (txt.includes('T4') || txt.includes('GPU')) return 't4_connected';
                return 'connected';
            }
            return 'disconnected';
        },
        checkRamConnected: function() {
            // Connected detection for Colab's shadow DOM UI.
            // Do NOT use "Run all" visibility: Run all can appear before runtime is connected.
            if (document.querySelector('colab-usage-meter')) return true;
            if (document.querySelector('.memory-display')) return true;

            function deepText(root, seen = new Set()) {
                if (!root || seen.has(root)) return '';
                seen.add(root);
                let text = '';
                if (root.nodeType === Node.ELEMENT_NODE) {
                    text += ' ' + (root.innerText || root.textContent || '');
                    if (root.shadowRoot) text += ' ' + deepText(root.shadowRoot, seen);
                }
                for (const child of (root.children || [])) {
                    text += ' ' + deepText(child, seen);
                }
                return text;
            }

            const connectBtn = document.querySelector('colab-connect-button');
            if (connectBtn && connectBtn.shadowRoot) {
                if (connectBtn.shadowRoot.querySelector('colab-usage-meter')) return true;
                const txt = deepText(connectBtn.shadowRoot);
                if (txt.includes('Connected')) return true;
                if (txt.includes('RAM') && txt.includes('Disk')) return true;
                if (txt.includes('T4') && !txt.toLowerCase().includes('connect')) return true;
            }

            // Page-level fallback: screenshot shows "RAM" and "Disk" in top-right when connected.
            const pageText = deepText(document.body);
            if (pageText.includes('RAM') && pageText.includes('Disk') && !pageText.includes('Connect to a hosted runtime')) return true;

            return false;
        },
        findElementByPatterns: function(patterns) {
            patterns = patterns || ["usage limit", "quota", "gpu limit", "cannot connect", "too many sessions"];
            const dialogs = document.querySelectorAll('colab-dialog, paper-dialog, mwc-dialog, dialog, [role="dialog"]');
            for (const dlg of dialogs) {
                if (dlg.offsetParent !== null) {
                    const t = (dlg.innerText || "").toLowerCase();
                    for (const p of patterns) { if (t.includes(p)) return "dialog:" + p; }
                }
            }
            const bodyText = (document.body && document.body.innerText || "").toLowerCase();
            for (const cp of ["usage limit", "cannot connect", "too many active sessions"]) {
                if (bodyText.includes(cp)) return "body:" + cp;
            }
            return null;
        }
    };
    console.log('__colabUtils injected successfully.');
})();
"""


async def cleanup_zombie_browsers(kill_active: bool = False) -> int:
    """Kill Chromium/Chrome processes launched with this app's profile directory.

    If kill_active is False, keep currently tracked worker profile processes alive.
    Supports Windows (PowerShell) and Linux (pgrep+kill).
    """
    profiles_base = str(PROFILES_DIR)
    active_profiles = _registry.get_active_profiles()
    killed = 0

    if sys.platform.startswith("win"):
        return await _cleanup_zombies_win(profiles_base, active_profiles, kill_active)
    else:
        return await _cleanup_zombies_linux(profiles_base, active_profiles, kill_active)


async def _cleanup_zombies_linux(profiles_base: str, active_profiles: set[str], kill_active: bool) -> int:
    """Linux zombie cleanup via pgrep + /proc reading."""
    killed = 0
    try:
        # Find all chrome/chromium processes with --colab-role flag
        proc = await asyncio.create_subprocess_exec(
            "pgrep", "-f", "chrom(e|ium).*--colab-role",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return killed

        pids = [p.strip() for p in stdout.decode().splitlines() if p.strip()]
        for pid_str in pids:
            try:
                pid = int(pid_str)
                # Read cmdline to check profile path
                try:
                    with open(f"/proc/{pid}/cmdline", "r", errors="ignore") as f:
                        cmdline = f.read().replace("\0", " ")
                except (FileNotFoundError, PermissionError):
                    continue

                cmd_lower = cmdline.lower()
                if profiles_base.lower() not in cmd_lower:
                    continue
                if not kill_active and any(p.lower() in cmd_lower for p in active_profiles):
                    continue

                os.kill(pid, 9)
                killed += 1
                logger.info("Killed zombie browser PID=%s (Linux)", pid)
            except (ValueError, OSError):
                continue
    except FileNotFoundError:
        logger.debug("pgrep not found, skipping zombie cleanup")
    except Exception as exc:
        logger.warning("cleanup_zombies_linux failed: %s", exc)
    return killed


async def _cleanup_zombies_win(profiles_base: str, active_profiles: set[str], kill_active: bool) -> int:
    try:
        proc = await asyncio.create_subprocess_exec(
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -match 'chrome|chromium|msedge' } | "
            "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("Browser cleanup process listing failed: %s", stderr.decode(errors="ignore")[:300])
            return killed

        import json
        raw = stdout.decode(errors="ignore").strip()
        if not raw:
            return killed
        entries = json.loads(raw)
        if isinstance(entries, dict):
            entries = [entries]

        for entry in entries:
            cmd = (entry.get("CommandLine") or "").lower()
            pid = entry.get("ProcessId")
            if not pid:
                continue
            # Only kill browsers launched by this app (tagged with --colab-role)
            if '--colab-role' not in cmd and profiles_base not in cmd:
                continue
            if not kill_active and any(profile in cmd for profile in active_profiles):
                continue
            result = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(pid), "/F", "/T",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await result.wait()
            killed += 1
            logger.info("Killed zombie browser process PID=%s", pid)
    except Exception as exc:
        logger.warning("cleanup_zombies_win failed: %s", exc)

    return killed


def _colab_url() -> str:
    return (
        f"https://colab.research.google.com/github/"
        f"{GITHUB_USER}/{GITHUB_REPO}/blob/main/{COLAB_NOTEBOOK_PATH}"
    )


async def add_google_account_session(email: str) -> None:
    """Open a headed Chromium window so the user can log into their Google account.

    The persistent context saves all cookies / local storage to the profile dir
    so the session is reusable later.
    """
    profile_dir = str(PROFILES_DIR / email)
    Path(profile_dir).mkdir(parents=True, exist_ok=True)

    pw = await async_playwright().start()
    try:
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,
            user_agent=user_agent,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--colab-role=login"
            ],
            ignore_default_args=["--enable-automation"]
        )
        page = await context.new_page()
        
        await page.add_init_script(_JS_UTILS)
        await page.add_init_script("delete navigator.__proto__.webdriver;")

        await _dismiss_chrome_restore_pages(page)
        await page.goto("https://accounts.google.com/")

        # Register with centralized registry
        entry = _registry.register(email, role=ROLE_LOGIN, pw=pw, context=context, page=page)
        logger.info("Opened login window for %s (pid=%s)", email, entry.pid)

        # Auto-close once Google login session detected
        existing = _registry.get(email)
        if existing and existing.login_watcher_task and not existing.login_watcher_task.done():
            existing.login_watcher_task.cancel()
        _registry.set_login_watcher_task(email, asyncio.create_task(_watch_google_login(email)))
    except Exception as exc:
        await pw.stop()
        logger.error("Failed to open login window for %s: %s", email, exc)
        raise


async def finish_google_account_session(email: str) -> None:
    """Close the login browser window. Cookies are already persisted."""
    await _registry.stop_one(email)


async def _watch_google_login(email: str) -> None:
    """Auto-close login browser when Google session cookie SID appears."""
    deadline = asyncio.get_event_loop().time() + LOGIN_WATCH_TIMEOUT_SECONDS
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(2)
        entry = _registry.get(email)
        if not entry or not entry.context:
            return
        ctx = entry.context
        try:
            cookies = await ctx.cookies("https://accounts.google.com")
        except Exception:
            return
        names = {c.get("name") for c in cookies}
        if "SID" in names and ("SAPISID" in names or "HSID" in names):
            logger.info("Detected Google login session for %s, auto-closing browser", email)
            try:
                await finish_google_account_session(email)
                async with async_session() as db:
                    result = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
                    account = result.scalar_one_or_none()
                    if account:
                        account.status = "OFFLINE"
                        account.last_active = datetime.now(timezone.utc)
                        await db.commit()
                logger.info("Login session saved and account marked OFFLINE for %s", email)
            except Exception as exc:
                logger.warning("Auto-close failed for %s: %s", email, exc)
            return
    logger.warning("Login watcher for %s timed out after %ds", email, LOGIN_WATCH_TIMEOUT_SECONDS)



async def _fill_colab_param(page: Page, param_name: str, value: str) -> bool:
    """Helper to locate and fill a @param input on the Colab interface."""
    selectors = [
        f"div.form-field-container:has(span:has-text('{param_name}')) input",
        f"div.colab-form-field:has(label:has-text('{param_name}')) input",
        f"div.colab-form-field:has-text('{param_name}') input",
        f"input[name='{param_name}']",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                await loc.fill(value)
                await loc.dispatch_event("change")
                await loc.dispatch_event("input")
                logger.info("Filled parameter %s using selector: %s", param_name, sel)
                return True
        except Exception:
            pass
    # Deep DOM fallback for Colab generated form inputs.
    try:
        res = await page.evaluate(
            """({ paramName, value }) => {
                const seen = new Set();
                function walk(root, out = []) {
                    if (!root || seen.has(root)) return out;
                    seen.add(root);
                    if (root.nodeType === Node.ELEMENT_NODE) out.push(root);
                    if (root.shadowRoot) walk(root.shadowRoot, out);
                    for (const child of (root.children || [])) walk(child, out);
                    return out;
                }
                function textAround(el) {
                    let cur = el;
                    let text = '';
                    for (let i = 0; i < 5 && cur; i++) {
                        text += ' ' + ((cur.innerText || cur.textContent || '').trim());
                        cur = cur.parentNode || cur.host;
                    }
                    return text.toLowerCase();
                }
                function setNativeValue(el, val) {
                    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                    if (setter) setter.call(el, val);
                    else el.value = val;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.blur?.();
                }
                const all = walk(document.body);
                const param = paramName.toLowerCase();
                const inputs = all.filter(el => ['INPUT', 'TEXTAREA'].includes(el.tagName));
                for (const input of inputs) {
                    const attrs = [input.name, input.id, input.placeholder, input.getAttribute('aria-label')]
                        .filter(Boolean).join(' ').toLowerCase();
                    if (attrs.includes(param) || textAround(input).includes(param)) {
                        setNativeValue(input, value);
                        return 'input-set:' + (input.name || input.id || input.placeholder || input.tagName);
                    }
                }
                return 'not-found';
            }""",
            {"paramName": param_name, "value": value},
        )
        if str(res).startswith("input-set"):
            logger.info("Filled parameter %s via deep input fallback: %s", param_name, res)
            return True
    except Exception as exc:
        logger.debug("Failed deep input fallback for %s: %s", param_name, exc)
    # Fallback: Colab forms often keep the value in the code cell itself.
    # Update the literal assignment in visible CodeMirror/editor text and trigger input events.
    try:
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        res = await page.evaluate(f"""() => {{
            const paramName = {param_name!r};
            const value = {value!r};
            const candidates = Array.from(document.querySelectorAll('.view-line, .cm-line, pre, code, textarea'));
            let changed = 0;
            for (const el of candidates) {{
                const txt = el.innerText || el.textContent || el.value || '';
                if (!txt.includes(paramName) || !txt.includes('#@param')) continue;
                const re = new RegExp(paramName + "\\\\s*=\\\\s*(['\\\"])(.*?)\\\\1");
                const next = txt.replace(re, paramName + " = '" + value + "'");
                if (next !== txt) {{
                    if ('value' in el) el.value = next;
                    else el.textContent = next;
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    changed++;
                }}
            }}
            return changed;
        }}""")
        if res:
            logger.info("Filled parameter %s via editor fallback (%s replacements)", param_name, res)
            return True
    except Exception as exc:
        logger.debug("Failed editor fallback for %s: %s", param_name, exc)
    logger.warning("Could not fill Colab parameter %s", param_name)
    return False


async def _shadow_click(page: Page, js_expr: str) -> str:
    try:
        res = await page.evaluate(js_expr)
        return res or "no-result"
    except Exception as e:
        return f"err:{type(e).__name__}"


async def _dismiss_chrome_restore_pages(page: Page) -> None:
    """Close Chromium's 'Restore pages?' bubble if it appears after a profile crash."""
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(200)
    except Exception:
        pass


async def _dismiss_run_anyway_once(page: Page, email: str) -> bool:
    """Fast non-blocking Run Anyway dismiss for wait loops."""
    try:
        result = await page.evaluate("""() => {
            const dialog = document.querySelector('mwc-dialog[open], mwc-dialog[aria-hidden="false"], mwc-dialog');
            if (!dialog || !dialog.hasAttribute('open')) return 'no-dialog';
            const text = (dialog.innerText || dialog.textContent || '').toLowerCase();
            if (!text.includes('run anyway') && !text.includes('warning') && !text.includes('github')) return 'not-run-anyway';

            const textButtons = dialog.querySelectorAll('md-text-button');
            const runAnywayHost = textButtons[1];
            if (runAnywayHost) {
                const innerBtn = runAnywayHost.shadowRoot?.querySelector('button');
                if (innerBtn) innerBtn.click();
                else runAnywayHost.click();
                return 'dismissed-md-text-button-2';
            }

            const actionBtn = dialog.querySelector('[dialogAction="ok"], [dialogaction="ok"]');
            if (actionBtn) {
                const innerBtn = actionBtn.shadowRoot?.querySelector('button');
                if (innerBtn) innerBtn.click();
                else actionBtn.click();
                return 'dismissed-action';
            }
            return 'no-button';
        }""")
        if result and 'dismissed' in result:
            logger.info("Dismissed Run anyway once for %s: %s", email, result)
            return True
    except Exception as exc:
        logger.debug("Fast Run anyway dismiss failed for %s: %s", email, exc)
    return False


async def _dismiss_colab_security_warning(page: Page, email: str) -> bool:
    """Click Colab's GitHub security warning: 'Run anyway'."""
    logger.info("Waiting for Colab 'Run anyway' warning for %s", email)

    try:
        screenshot_path = DATA_DIR / "colab_run_anyway_before.png"
        await page.screenshot(path=str(screenshot_path))
        logger.info("Saved pre-dismiss screenshot to %s", screenshot_path)
    except Exception as exc:
        logger.debug("Could not save pre-dismiss screenshot: %s", exc)

    for attempt in range(60):
        # Fast path: mwc-dialog > md-text-button[2] (shadow) > button
        try:
            shadow_result = await page.evaluate("""() => {
                const dialog = document.querySelector('mwc-dialog[open], mwc-dialog[aria-hidden="false"], mwc-dialog');
                if (!dialog || !dialog.hasAttribute('open')) return 'no-dialog';

                // Exact XPath mapping: /mwc-dialog/md-text-button[2]//button/span[1]
                const textButtons = dialog.querySelectorAll('md-text-button');
                const runAnywayHost = textButtons[1];
                if (runAnywayHost) {
                    const shadow = runAnywayHost.shadowRoot;
                    const innerBtn = shadow?.querySelector('button');
                    if (innerBtn) {
                        innerBtn.click();
                        return 'dismissed-md-text-button-2';
                    }
                    runAnywayHost.click();
                    return 'dismissed-md-text-button-2-host';
                }

                // Fallback: scan button text
                const buttons = dialog.querySelectorAll('md-text-button, md-filled-button');
                for (const btn of buttons) {
                    const shadow = btn.shadowRoot;
                    const innerBtn = shadow?.querySelector('button');
                    const txt = (innerBtn?.innerText || btn.innerText || btn.textContent || '').toLowerCase();
                    if (txt.includes('run anyway') || txt.includes('ok')) {
                        if (innerBtn) innerBtn.click();
                        else btn.click();
                        return 'dismissed-shadow:' + txt.trim().slice(0, 40);
                    }
                }

                // Also try direct dialogAction buttons
                const actionBtn = dialog.querySelector('[dialogAction="ok"], [dialogaction="ok"]');
                if (actionBtn) {
                    const s = actionBtn.shadowRoot;
                    if (s) { const b = s.querySelector('button'); if (b) b.click(); else actionBtn.click(); }
                    else actionBtn.click();
                    return 'dismissed-action';
                }

                return 'buttons-no-match';
            }""")
            if shadow_result and 'dismissed' in shadow_result:
                logger.info("Dismissed Run anyway via shadow DOM for %s (attempt %d): %s", email, attempt + 1, shadow_result)
                return True
        except Exception as exc:
            logger.debug("Shadow dismiss attempt %d: %s", attempt + 1, exc)

        try:
            ok_locator = page.locator(
                '[dialogAction="ok"], [dialogaction="ok"], #ok, '
                'md-filled-button:has-text("Run anyway"), '
                'md-text-button:has-text("Run anyway"), '
                'mwc-button:has-text("Run anyway"), '
                'paper-button:has-text("Run anyway")'
            ).last
            if await ok_locator.count() > 0 and await ok_locator.is_visible():
                await ok_locator.click(force=True, timeout=1000)
                logger.info("Dismissed Run anyway via dialogAction locator for %s", email)
                return True
        except Exception as exc:
            logger.debug("dialogAction locator attempt %d failed: %s", attempt + 1, exc)

        try:
            for label in ["Run anyway", "Vẫn chạy", "van chay"]:
                role_locator = page.get_by_role("button", name=label).last
                if await role_locator.count() > 0 and await role_locator.is_visible():
                    await role_locator.click(force=True, timeout=1000)
                    logger.info("Dismissed Run anyway via role locator for %s: %s", email, label)
                    return True
        except Exception as exc:
            logger.debug("role locator attempt %d failed: %s", attempt + 1, exc)

        try:
            warning_res = await page.evaluate("""() => {
                const labels = ['run anyway', 'vẫn chạy', 'van chay'];
                const seen = new Set();
                const textOf = (node) => ((node && (node.innerText || node.textContent)) || '').trim().toLowerCase();
                const visible = (node) => {
                    if (!node || node.nodeType !== Node.ELEMENT_NODE) return false;
                    const style = window.getComputedStyle(node);
                    const rect = node.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                };
                const disabled = (node) => node?.disabled || node?.hasAttribute?.('disabled') || node?.getAttribute?.('aria-disabled') === 'true';

                function walk(root, visitor) {
                    if (!root || seen.has(root)) return null;
                    seen.add(root);
                    const hit = visitor(root);
                    if (hit) return hit;
                    if (root.shadowRoot) {
                        const shadowHit = walk(root.shadowRoot, visitor);
                        if (shadowHit) return shadowHit;
                    }
                    for (const child of (root.children || [])) {
                        const childHit = walk(child, visitor);
                        if (childHit) return childHit;
                    }
                    return null;
                }

                function matchesRunAnyway(node) {
                    const tag = node.tagName || '';
                    const role = node.getAttribute?.('role');
                    const action = (node.getAttribute?.('dialogAction') || node.getAttribute?.('dialogaction') || '').toLowerCase();
                    const id = (node.id || '').toLowerCase();
                    const buttonLike = tag === 'BUTTON' || tag.includes('BUTTON') || tag === 'PAPER-BUTTON' || role === 'button';
                    if (action === 'ok' || id === 'ok') return true;
                    if (!buttonLike) return false;
                    let cur = node;
                    for (let depth = 0; depth < 8 && cur; depth++) {
                        const txt = textOf(cur);
                        if (labels.some(label => txt.includes(label))) return true;
                        cur = cur.parentNode || cur.host;
                    }
                    return false;
                }

                function clickable(node) {
                    let cur = node;
                    for (let depth = 0; depth < 8 && cur; depth++) {
                        const tag = cur.tagName || '';
                        const role = cur.getAttribute?.('role');
                        if (tag === 'BUTTON' || tag.includes('BUTTON') || tag === 'PAPER-BUTTON' || role === 'button') return cur;
                        cur = cur.parentNode || cur.host;
                    }
                    return node;
                }

                const target = walk(document.body, node => {
                    if (node.nodeType !== Node.ELEMENT_NODE) return null;
                    if (!matchesRunAnyway(node)) return null;
                    const clickTarget = clickable(node);
                    if (!visible(clickTarget) || disabled(clickTarget)) return null;
                    return clickTarget;
                });

                if (!target) return 'not-found';
                target.scrollIntoView({ block: 'center', inline: 'center' });
                target.focus?.();
                for (const type of ['pointerdown', 'mousedown', 'mouseup', 'pointerup', 'click']) {
                    target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
                }
                target.click?.();
                return 'dismissed:' + (target.tagName || target.nodeName) + ':' + textOf(target).slice(0, 80);
            }""")
            if warning_res and "dismissed" in warning_res:
                logger.info("Dismissed Run anyway via deep JS for %s (attempt %d): %s", email, attempt + 1, warning_res)
                return True
        except Exception as exc:
            logger.debug("deep JS attempt %d failed: %s", attempt + 1, exc)

        if attempt in (20, 35, 50):
            try:
                await page.keyboard.press("Tab")
                await page.keyboard.press("Enter")
                logger.info("Tried keyboard Tab+Enter fallback for Run anyway (%s, attempt %d)", email, attempt + 1)
            except Exception as exc:
                logger.debug("keyboard fallback failed: %s", exc)

        await page.wait_for_timeout(250)

    try:
        fail_path = DATA_DIR / "colab_run_anyway_failed.png"
        await page.screenshot(path=str(fail_path))
        logger.warning("Run anyway was not dismissed for %s. Saved debug screenshot: %s", email, fail_path)
    except Exception:
        logger.warning("Run anyway was not dismissed for %s and screenshot failed.", email)
    return False



async def _check_quota_or_errors(page: Page) -> str | None:
    try:
        return await page.evaluate("window.__colabUtils.findElementByPatterns()")
    except Exception as e:
        return f"eval_error: {e}"



async def _check_login_required(page) -> bool:
    # Phat hien trang yeu cau login Google. URL truoc, JS evaluate fallback
    try:
        url = page.url
        login_urls = ["accounts.google.com", "ServiceLogin", "signin", "signup", "consent.google", "/login"]
        for lu in login_urls:
            if lu in url:
                logger.info("Login detected via URL: %s", url)
                return True
    except Exception as e:
        logger.debug("URL check failed: %s", str(e)[:100])

    try:
        js_check = '() => {' + \
            'const text = (document.body && document.body.innerText || "").toLowerCase();' + \
            'const inds = ["sign in to your google", "enter your password", "nhap mat khau", "dang nhap", "wrong password", "use your google account"];' + \
            'for (const i of inds) { if (text.includes(i)) return true; }' + \
            'return !!document.querySelector("input[type=password]");' + \
            '}'
        result = await page.evaluate(js_check)
        return bool(result)
    except Exception as e:
        logger.debug("Login JS check failed: %s", str(e)[:100])
        return False


async def _mark_account_needs_login(email: str) -> None:
    """Đánh dấu account cần login lại (NEEDS_LOGIN status, không cooldown)."""
    try:
        async with async_session() as db:
            await db.execute(
                update(GoogleAccount)
                .where(GoogleAccount.email == email)
                .values(status="NEEDS_LOGIN", quota_reset_at=None)
            )
            await db.commit()
        logger.warning("Account %s marked NEEDS_LOGIN. User must re-login via dashboard.", email)
    except Exception as e:
        logger.error("Failed to mark NEEDS_LOGIN for %s: %s", email, e)


async def _select_gpu_and_connect(page: Page, email: str) -> bool:
    """Select T4, click Connect, queue Run All, then wait for cells to start.

    Flow:
      Connect -> Run All immediately -> wait CELL_START_TIMEOUT_SECONDS for cell execution.
      If no cell starts, treat as quota/connect failure and rotate account.
    """
    logger.info("Starting GPU selection and queued Run All for %s", email)

    if await _check_login_required(page):
        logger.error("Account %s needs login. Stopping automation.", email)
        await _mark_account_needs_login(email)
        raise RuntimeError(f"Account {email} needs manual login")

    try:
        gpu_status = await page.evaluate("window.__colabUtils.checkGpuStatus()")
        if gpu_status == 't4_connected':
            logger.info("Account %s already has T4 connected. Queueing Run All immediately.", email)
            if await _trigger_run_all(page, email):
                if await _wait_for_colab_execution(page, email, CELL_START_TIMEOUT_SECONDS):
                    return True
            await _mark_account_short_backoff(email)
            raise RuntimeError(f"Cell execution did not start within {CELL_START_TIMEOUT_SECONDS}s for {email}")
        logger.info("Account %s status: %s. Proceeding with GPU setup.", email, gpu_status)
    except RuntimeError:
        raise
    except Exception as e:
        logger.warning("Could not check initial GPU status for %s: %s", email, e)

    # Open Runtime -> Change runtime type
    try:
        await page.locator("#runtime-menu-button").click(timeout=3000, force=True)
    except Exception:
        await page.evaluate("window.__colabUtils.findByText(document, ['Runtime', 'Thời gian chạy', 'Thoi gian chay'], null)?.click()")

    await page.wait_for_timeout(100)

    try:
        await page.get_by_text("Change runtime type", exact=True).first.click(timeout=3000, force=True)
    except Exception:
        await page.evaluate("window.__colabUtils.findByText(document, ['Change runtime type', 'Thay đổi loại thời gian chạy'], null)?.click()")

    await page.wait_for_timeout(400)

    gpu_result = await page.evaluate("""() => {
        const mwcDialog = document.querySelector('mwc-dialog, colab-dialog, paper-dialog, [role="dialog"]');
        if (!mwcDialog) return 'no-dialog';
        const selector = mwcDialog.querySelector('colab-runtime-attributes-selector');
        if (!selector?.shadowRoot) return 'no-selector';
        const formfields = selector.shadowRoot.querySelectorAll('mwc-formfield');
        if (formfields.length < 2) return 'no-t4-field';
        const input = formfields[1].querySelector('mwc-radio')?.shadowRoot?.querySelector('input');
        if (!input) return 'no-radio-input';
        input.click();
        input.checked = true;
        input.dispatchEvent(new Event('change', { bubbles: true }));
        return 'ok';
    }""")
    logger.info("GPU select result for %s: %s", email, gpu_result)

    await page.evaluate("""() => {
        const mwcDialog = document.querySelector('mwc-dialog, colab-dialog, paper-dialog, [role="dialog"]');
        const saveBtn = mwcDialog?.querySelector('[dialogAction="ok"], [dialogaction="ok"], button#ok, md-filled-button, paper-button');
        saveBtn?.click();
    }""")
    await page.wait_for_timeout(200)

    logger.info("Clicking Connect for %s, then queueing Run All immediately", email)
    await page.evaluate("""() => {
        const host = document.querySelector('colab-connect-button');
        const shadow = host?.shadowRoot;
        const btn = shadow?.querySelector('#connect, colab-toolbar-button, paper-button, button');
        btn?.click();
    }""")

    await page.wait_for_timeout(300)
    run_all_ok = await _trigger_run_all(page, email)
    logger.info("Queued Run All after Connect for %s: %s", email, run_all_ok)
    await _dismiss_run_anyway_once(page, email)

    if not run_all_ok:
        await _mark_account_short_backoff(email)
        raise RuntimeError(f"Could not queue Run All for {email}")

    if await _wait_for_colab_execution(page, email, CELL_START_TIMEOUT_SECONDS):
        return True

    logger.warning(
        "Cell execution did not start within %ss for %s. Short backoff, will retry later.",
        CELL_START_TIMEOUT_SECONDS,
        email,
    )
    await _mark_account_short_backoff(email)
    raise RuntimeError(f"Cell execution timeout for {email}")

async def _mark_account_quota_reached(email: str) -> None:
    """Tài khoản bị Colab popup hết quota: cooldown 16h, không pickup."""
    try:
        from datetime import datetime, timezone, timedelta
        reset_time = datetime.now(timezone.utc) + timedelta(hours=QUOTA_RESET_HOURS)
        async with async_session() as db:
            await db.execute(
                update(GoogleAccount)
                .where(GoogleAccount.email == email)
                .values(status="COOLDOWN", quota_reset_at=reset_time)
            )
            await db.commit()
        logger.warning("Account %s marked COOLDOWN for %d hours (real quota popup).", email, QUOTA_RESET_HOURS)
    except Exception as e:
        logger.error("Failed to mark quota for %s: %s", email, e)


async def _mark_account_short_backoff(email: str, minutes: int = None) -> None:
    """Cell không start sau timeout (chưa chắc quota): backoff ngắn rồi cho dùng lại."""
    try:
        from datetime import datetime, timezone, timedelta
        backoff = minutes if minutes is not None else CELL_START_BACKOFF_MINUTES
        reset_time = datetime.now(timezone.utc) + timedelta(minutes=backoff)
        async with async_session() as db:
            await db.execute(
                update(GoogleAccount)
                .where(GoogleAccount.email == email)
                .values(status="COOLDOWN", quota_reset_at=reset_time)
            )
            await db.commit()
        logger.info("Account %s short backoff %d minutes (cell timeout, not real quota).", email, backoff)
    except Exception as e:
        logger.error("Failed to mark short backoff for %s: %s", email, e)


async def _is_colab_execution_started(page: Page) -> bool:
    """Return true if at least one Colab code cell looks running or has started."""
    try:
        return bool(await page.evaluate("""() => {
            const cells = Array.from(document.querySelectorAll('colab-cell'));
            for (const cell of cells) {
                const txt = (cell.innerText || cell.textContent || '').trim();
                const cls = cell.className || '';
                if (String(cls).includes('running') || String(cls).includes('executing')) return true;
                if (cell.hasAttribute?.('executing')) return true;
                if (txt.includes('Đang cài đặt') || txt.includes('Running worker') || txt.includes('Clone repo')) return true;
            }
            if (document.querySelector('.cell-execution-indicator, .running, .executing')) return true;
            return false;
        }"""))
    except Exception:
        return False


async def _wait_for_colab_execution(page: Page, email: str, timeout_seconds: int) -> bool:
    """Wait until a Colab cell starts running or produces early output.

    - Auto-dismiss "Run anyway" GitHub warning during wait.
    - If a real quota popup is detected (e.g. "usage limit", "cannot connect"),
      mark the account COOLDOWN 16h and abort by raising RuntimeError.
    - Otherwise return False to let caller apply a short backoff.
    """
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    while asyncio.get_event_loop().time() < deadline:
        quota_err = await _check_quota_or_errors(page)
        if quota_err and "eval_error" not in str(quota_err):
            logger.error("Quota popup detected for %s: %s. Cooldown 16h.", email, quota_err)
            await _mark_account_quota_reached(email)
            raise RuntimeError(f"Colab quota popup for {email}: {quota_err}")

        await _dismiss_run_anyway_once(page, email)

        if await _is_colab_execution_started(page):
            logger.info("Cell execution started for %s", email)
            return True
        await asyncio.sleep(0.5)
    return False


async def _trigger_run_all(page, email) -> bool:
    """Run All cells: click the toolbar Run button (nested shadow DOM).

    XPath structure:
      colab-notebook-toolbar
        > colab-notebook-toolbar-run-button (shadow)
          > colab-toolbar-button (shadow)
            > md-text-button (shadow)
              > button

    Fallback 1: Runtime menu -> "Run all"
    Fallback 2: Ctrl+F9
    """
    logger.info("Triggering Run All for %s", email)

    # === Primary: click toolbar Run button through shadow DOM ===
    for attempt in range(10):
        try:
            result = await page.evaluate("""() => {
                // Navigate nested shadow DOM to reach the Run All button
                const toolbar = document.querySelector('colab-notebook-toolbar');
                if (!toolbar) return 'no-toolbar';

                const runBtnHost = toolbar.querySelector('colab-notebook-toolbar-run-button');
                if (!runBtnHost) return 'no-run-btn-host';

                // First shadow: colab-notebook-toolbar-run-button
                const shadow1 = runBtnHost.shadowRoot;
                if (!shadow1) return 'no-shadow1';

                const colabBtn = shadow1.querySelector('colab-toolbar-button');
                if (!colabBtn) return 'no-colab-btn';

                // Second shadow: colab-toolbar-button
                const shadow2 = colabBtn.shadowRoot;
                if (!shadow2) return 'no-shadow2';

                const mdBtn = shadow2.querySelector('md-text-button, md-filled-button, button');
                if (!mdBtn) return 'no-md-btn';

                // Third shadow: md-text-button
                const shadow3 = mdBtn.shadowRoot;
                if (shadow3) {
                    const innerBtn = shadow3.querySelector('button');
                    if (innerBtn) {
                        innerBtn.click();
                        return 'clicked-inner-button';
                    }
                }

                // Fallback: click the md-text-button itself
                mdBtn.click();
                return 'clicked-md-btn';
            }""")

            if result and 'clicked' in result:
                logger.info("Run All toolbar click OK for %s (attempt %d): %s", email, attempt + 1, result)
                await page.wait_for_timeout(1500)
                return True

            logger.debug("Run All toolbar attempt %d: %s", attempt + 1, result)
        except Exception as exc:
            logger.debug("Run All toolbar attempt %d error: %s", attempt + 1, exc)

        await page.wait_for_timeout(500)

    # === Fallback 1: Runtime menu -> Run all ===
    logger.info("Toolbar failed, trying Runtime menu for %s", email)
    for attempt in range(5):
        try:
            runtime_btn = page.locator("#runtime-menu-button")
            if await runtime_btn.count() > 0 and await runtime_btn.is_visible():
                await runtime_btn.click(timeout=2000, force=True)
            else:
                await page.evaluate(
                    "document.querySelector('#runtime-menu-button')?.click() || "
                    "window.__colabUtils?.findByText(document, ['Runtime'], null)?.click()"
                )
            await page.wait_for_timeout(400)

            menu_result = await page.evaluate("""() => {
                const items = document.querySelectorAll(
                    '[role="menuitem"], .goog-menuitem, .goog-menuitem-content'
                );
                for (const item of items) {
                    const txt = (item.innerText || item.textContent || '').trim();
                    if (txt === 'Run all' || txt === 'Chạy tất cả') {
                        item.click();
                        return 'menu-clicked:' + txt;
                    }
                }
                return 'menu-not-found';
            }""")

            if menu_result and 'clicked' in menu_result:
                logger.info("Run All via menu for %s: %s", email, menu_result)
                await page.wait_for_timeout(1500)
                return True
        except Exception as exc:
            logger.debug("Menu attempt %d failed: %s", attempt + 1, exc)
        await page.wait_for_timeout(300)

    # === Fallback 2: Ctrl+F9 ===
    logger.warning("All UI methods failed for %s, sending Ctrl+F9", email)
    try:
        await page.keyboard.press("Control+F9")
        await page.wait_for_timeout(2000)
        logger.info("Ctrl+F9 sent as final fallback for %s", email)
        return True
    except Exception as exc:
        logger.error("Ctrl+F9 also failed for %s: %s", email, exc)
    return False


async def _check_google_session_for(email: str, ctx: BrowserContext) -> bool:
    """Check whether Google session cookies exist for this account's profile.

    Returns True if valid Google session cookies (SID/SAPISID) are present.
    """
    try:
        cookies = await ctx.cookies("https://accounts.google.com")
        names = {c.get("name") for c in cookies}
        has_session = "SID" in names and ("SAPISID" in names or "HSID" in names)
        if not has_session:
            logger.warning("No valid Google session found in profile for %s", email)
        return has_session
    except Exception as e:
        logger.debug("Session check failed for %s: %s", email, e)
        return False


async def start_colab_worker(email: str, server_url: str, worker_session_id: str = None) -> None:
    """Start a Colab worker: open the notebook, select GPU T4, fill configuration, run-all, and keep-alive."""
    profile_dir = str(PROFILES_DIR / email)
    if not Path(profile_dir).exists():
        raise RuntimeError(f"No profile found for {email}. Login first.")

    # Profile has persisted Chrome cookies from previous login.
    # Trust that the profile is valid. If Google session actually expired,
    # the Colab page will show "Sign in" and Playwright will handle it.
    logger.info("Profile exists for %s, launching worker...", email)

    pw = await async_playwright().start()
    context = None
    try:
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,
            user_agent=user_agent,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-session-crashed-bubble",
                "--disable-infobars",
                "--no-first-run",
                "--colab-role=worker"
            ],
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()
        
        await page.add_init_script(_JS_UTILS)
        await page.add_init_script("delete navigator.__proto__.webdriver;")


        # Check if GitHub settings are default. If so, fallback to local notebook upload.
        is_default_github = (GITHUB_USER == "your-github-username" or GITHUB_REPO == "your-repo-name")
        
        if is_default_github:
            logger.info("GitHub configuration is default. Falling back to uploading local notebook to Colab...")
            await page.goto("https://colab.research.google.com/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)
            
            # Send Ctrl+O to force open the file dialog if it didn't auto-show
            logger.info("Sending Ctrl+O to ensure file dialog is visible...")
            await page.keyboard.press("Control+o")
            await page.wait_for_timeout(2000)
            
            # Click the Upload tab in the welcome dialog
            upload_tab = page.get_by_text("Upload", exact=True).first
            try:
                await upload_tab.wait_for(state="visible", timeout=3000)
            except Exception:
                for selector in [
                    "paper-tab:has-text('Upload')",
                    "span:has-text('Upload')",
                    "div.tab-header-title:has-text('Upload')",
                    "div[role='tab']:has-text('Upload')"
                ]:
                    try:
                        loc = page.locator(selector).first
                        if await loc.count() > 0 and await loc.is_visible():
                            upload_tab = loc
                            break
                    except Exception:
                        pass
            
            await upload_tab.wait_for(state="visible", timeout=10000)
            await upload_tab.click()
            await page.wait_for_timeout(1000)
            
            # Select and upload local worker.ipynb
            from app.config import BASE_DIR
            local_nb_path = str(BASE_DIR / "colab" / "worker.ipynb")
            logger.info("Uploading local notebook from: %s", local_nb_path)
            
            file_input = page.locator("input[type='file']").first
            await file_input.set_input_files(local_nb_path)
            
            # Wait for redirect to the uploaded drive notebook
            logger.info("Waiting for Colab to upload and redirect...")
            await page.wait_for_url("**/drive/**", timeout=60000)
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
            logger.info("Colab notebook uploaded and loaded from Drive!")
        else:
            url = _colab_url()
            logger.info("Opening Colab for %s from GitHub: %s", email, url)
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # Wait a moment for Colab UI to fully render
        await page.wait_for_timeout(2000)
        await page.evaluate(_JS_UTILS)

        # 1. Chọn GPU T4 & Connect trước khi điền tham số
        # 1. Điền form parameters TRƯỚC (đề phòng Run Anyway popup)
        await _fill_colab_param(page, "GITHUB_USER", GITHUB_USER)
        await _fill_colab_param(page, "GITHUB_REPO", GITHUB_REPO)
        await _fill_colab_param(page, "SERVER_URL", server_url)
        await _fill_colab_param(page, "EMAIL", email)
        if worker_session_id:
            await _fill_colab_param(page, "WORKER_SESSION_ID", worker_session_id)

        # 2. Chọn GPU T4, Connect, Run All ngay, chờ cell start tối đa 20s
        run_all_ok = await _select_gpu_and_connect(page, email)

        # 3. Dismiss Run anyway nếu popup còn tồn tại sau cell start
        dismissed = await _dismiss_colab_security_warning(page, email)
        if dismissed:
            logger.info("Run anyway dialog dismissed after queued run for %s", email)

        if dismissed:
            try:
                path = DATA_DIR / "colab_after_dismiss.png"
                await page.screenshot(path=str(path))
                logger.info("Saved debug screenshot to %s", path)
            except Exception as e:
                logger.warning("Failed to save debug screenshot: %s", e)

        # 4. Tiêm JavaScript Keep-Alive để click Connect / Dialog định kỳ
        try:
            await page.evaluate("""() => {
                setInterval(() => {
                    const host = document.querySelector('colab-connect-button');
                    if (host && host.shadowRoot) {
                        const btn = host.shadowRoot.querySelector('#connect, colab-toolbar-button, paper-button');
                        if (btn && (btn.innerText || '').includes('Connect')) {
                            btn.click();
                            console.log('[Antigravity-KeepAlive] Clicked Connect button');
                        }
                    }
                    const runAnyway = Array.from(document.querySelectorAll('button, paper-button, md-text-button, md-filled-button, [role="button"]'))
                        .find(el => ((el.innerText || el.textContent || '').toLowerCase()).includes('run anyway'));
                    if (runAnyway) {
                        runAnyway.click();
                        console.log('[Antigravity-KeepAlive] Dismissed Run anyway dialog');
                    }
                    const okBtn = document.querySelector('paper-button#ok, colab-dialog paper-button, md-filled-button[id*="ok"], md-text-button[id*="ok"]');
                    if (okBtn) {
                        okBtn.click();
                        console.log('[Antigravity-KeepAlive] Dismissed alert dialog');
                    }
                    // Additional check for "Reconnect" button which sometimes appears
                    const reconnectBtn = Array.from(document.querySelectorAll('paper-button, md-text-button'))
                        .find(el => (el.innerText || '').includes('Reconnect'));
                    if (reconnectBtn) reconnectBtn.click();
                }, 30000);
            }""")
            logger.info("Keep-Alive JS injected successfully for %s", email)
        except Exception as e:
            logger.warning("Failed to inject Keep-Alive JS for %s: %s", email, e)

        # Register with centralized registry
        entry = _registry.register(email, role=ROLE_WORKER, pw=pw, context=context, page=page)

        # Start keep-alive task
        task = asyncio.create_task(_keepalive_loop(email))
        _registry.set_keepalive_task(email, task)
        logger.info("Colab worker process started and keep-alive active for %s", email)

    except Exception as exc:
        logger.error("Failed to start Colab worker for %s: %s", email, exc)
        # Capture error screenshot before closing context for debugging
        try:
            if 'page' in locals() and page:
                path = DATA_DIR / "colab_debug_error.png"
                await page.screenshot(path=str(path))
                logger.info("Saved error screenshot to %s", path)
        except Exception as e:
            logger.error("Failed to capture error screenshot: %s", e)
            
        if context:
            await context.close()
        await pw.stop()
        raise




async def stop_colab_worker(email: str) -> None:
    """Stop the Colab worker: cancel keep-alive, close browser."""
    await _registry.stop_one(email)
    try:
        from app.lifecycle.sessions import release_worker_session_after_stop
        from app.database import async_session
        async with async_session() as db:
            await release_worker_session_after_stop(db, email)
    except Exception as e:
        logger.error("Failed to release session in stop_colab_worker: %s", e)


async def _keepalive_loop(email: str) -> None:
    """Periodically interact with the Colab page to prevent idle timeout."""
    while True:
        await asyncio.sleep(WORKER_KEEPALIVE_INTERVAL)
        entry = _registry.get(email)
        if entry is None or entry.page is None:
            break
        try:
            await entry.page.evaluate("window.scrollTo(0, 100)")
            logger.debug("Keep-alive scroll for %s", email)
        except Exception as exc:
            logger.warning("Keep-alive failed for %s: %s", email, exc)
            break
