"""Playwright automation module for controlling Google Colab workers."""

import asyncio
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from app.config import DATA_DIR, PROFILES_DIR, GITHUB_USER, GITHUB_REPO, COLAB_NOTEBOOK_PATH, WORKER_KEEPALIVE_INTERVAL

logger = logging.getLogger(__name__)

# In-memory store for active browser contexts
_active_contexts: dict[str, tuple] = {}  # email -> (playwright, context)
_active_pages: dict[str, Page] = {}
_keepalive_tasks: dict[str, asyncio.Task] = {}


async def cleanup_zombie_browsers(kill_active: bool = False) -> int:
    """Kill Chromium/Chrome processes launched with this app's profile directory.

    If kill_active is False, keep currently tracked worker profile processes alive.
    """
    profiles_base = str(PROFILES_DIR).lower()
    active_profiles = {
        str(PROFILES_DIR / email).lower()
        for email in _active_contexts.keys()
    }
    killed = 0

    if not sys.platform.startswith("win"):
        return killed

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
            if not pid or profiles_base not in cmd:
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
        logger.warning("cleanup_zombie_browsers failed: %s", exc)

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
                "--disable-blink-features=AutomationControlled"
            ],
            ignore_default_args=["--enable-automation"]
        )
        page = await context.new_page()
        await page.add_init_script("delete navigator.__proto__.webdriver;")
        await _dismiss_chrome_restore_pages(page)
        await page.goto("https://accounts.google.com/")

        # Store references so we can close later
        _active_contexts[email] = (pw, context)  # type: ignore[assignment]
        _active_pages[email] = page
        logger.info("Opened login window for %s", email)
    except Exception as exc:
        await pw.stop()
        logger.error("Failed to open login window for %s: %s", email, exc)
        raise


async def finish_google_account_session(email: str) -> None:
    """Close the login browser window. Cookies are already persisted."""
    entry = _active_contexts.pop(email, None)
    _active_pages.pop(email, None)
    if entry is not None:
        pw, ctx = entry
        try:
            await ctx.close()
        except Exception as exc:
            logger.debug("Failed to close context (possibly already closed): %s", exc)
        try:
            await pw.stop()
        except Exception as exc:
            logger.debug("Failed to stop playwright: %s", exc)
        logger.info("Closed login window for %s", email)


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
        err = await page.evaluate("""() => {
            const patterns = [
                "usage limit", "usage limits", "quota", "gpu limit", "gpu quota",
                "cannot connect to gpu", "cannot connect to a gpu", "no gpu is available",
                "runtime disconnected", "runtime has been disconnected",
                "you cannot currently connect to a gpu", "colab usage limit",
                "worker crash", "cuda is not available", "too many sessions",
                "too many active sessions", "too many runtimes", "nhiều phiên đang hoạt động",
                "usage limit reached"
            ];
            
            // 1. Quét các dialogs đang hiển thị
            const dialogs = document.querySelectorAll('colab-dialog, paper-dialog, mwc-dialog, dialog, [role="dialog"]');
            for (const dlg of dialogs) {
                if (dlg.offsetParent !== null) {
                    const t = (dlg.innerText || dlg.textContent || "").toLowerCase();
                    for (const p of patterns) {
                        if (t.includes(p)) {
                            return `dialog_found: [${p}] ${t.slice(0, 300)}`;
                        }
                    }
                }
            }
            
            // 2. Quét các phần tử thông báo lỗi
            const notifications = document.querySelectorAll('.notification, colab-notification, .error, .warning, [class*="error"], [class*="warning"]');
            for (const el of notifications) {
                if (el.offsetParent !== null) {
                    const t = (el.innerText || el.textContent || "").toLowerCase();
                    for (const p of patterns) {
                        if (t.includes(p)) {
                            return `notification_found: [${p}] ${t.slice(0, 200)}`;
                        }
                    }
                }
            }
            
            // 3. Quét toàn bộ body
            const bodyText = (document.body && document.body.innerText || "").toLowerCase();
            const criticalPatterns = ["usage limit", "cannot connect to a gpu", "no gpu is available", "quá nhiều phiên đang hoạt động", "too many active sessions"];
            for (const cp of criticalPatterns) {
                if (bodyText.includes(cp)) {
                    return `body_text_found: [${cp}]`;
                }
            }
            return null;
        }""")
        return err
    except Exception as e:
        return f"eval_error: {e}"


async def _select_gpu_and_connect(page: Page, email: str) -> None:
    logger.info("Starting GPU selection and connection for %s", email)
    
    _SHADOW_FIND_BY_TEXT = """
        function findByText(root, texts, tags) {
            const tagSet = tags ? new Set(tags.map(t => t.toUpperCase())) : null;
            for (const el of root.querySelectorAll('*')) {
                if (tagSet && !tagSet.has(el.tagName)) {
                    if (el.shadowRoot) {
                        const r = findByText(el.shadowRoot, texts, tags);
                        if (r) return r;
                    }
                    continue;
                }
                const txt = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
                if (texts.some(t => txt === t || txt.startsWith(t))) return el;
                if (el.shadowRoot) {
                    const r = findByText(el.shadowRoot, texts, tags);
                    if (r) return r;
                }
            }
            return null;
        }
    """
    
    # Bước 1: Mở Runtime menu
    try:
        await page.locator("#runtime-menu-button").click(timeout=5000, force=True)
        runtime_menu = "runtime-menu:#runtime-menu-button"
    except Exception:
        runtime_menu = await _shadow_click(page, f"""() => {{
            {_SHADOW_FIND_BY_TEXT}
            const el = findByText(document, ['Runtime', 'Thời gian chạy', 'Thoi gian chay'], null);
            if (el) {{ el.click(); return 'runtime-menu:' + el.tagName + '/' + el.id; }}
            return 'runtime-menu-not-found';
        }}""")
    logger.info("Runtime menu action for %s: %s", email, runtime_menu)
    await page.wait_for_timeout(300)
    
    # Bước 2: Click "Change runtime type"
    try:
        await page.get_by_text("Change runtime type", exact=True).first.click(timeout=5000, force=True)
        change_rt = "change-rt:text"
    except Exception:
        change_rt = await _shadow_click(page, f"""() => {{
            {_SHADOW_FIND_BY_TEXT}
            const el = findByText(document, ['Change runtime type', 'Thay đổi loại thời gian chạy', 'Thay doi loai thoi gian chay'], null);
            if (el) {{ el.click(); return 'change-rt:' + el.tagName; }}
            return 'change-rt-not-found';
        }}""")
    logger.info("Change runtime type action for %s: %s", email, change_rt)
    await page.wait_for_timeout(500)
    
    # Bước 3: Chọn T4 GPU trong dialog bằng DOM selector chính xác
    gpu_result = await _shadow_click(page, """() => {
        try {
            const mwcDialog = document.querySelector('mwc-dialog, colab-dialog, paper-dialog, [role="dialog"]');
            if (!mwcDialog) return 'no-dialog-found';
            
            // Đi vào colab-runtime-attributes-selector
            const selector = mwcDialog.querySelector('colab-runtime-attributes-selector');
            if (!selector || !selector.shadowRoot) return 'no-attributes-selector';
            
            // Tìm mwc-formfield thứ 2 (cho T4 GPU)
            const formfields = selector.shadowRoot.querySelectorAll('mwc-formfield');
            if (formfields.length < 2) return 'insufficient-formfields:' + formfields.length;
            
            const t4FormField = formfields[1]; // index 1 là T4 GPU
            const mwcRadio = t4FormField.querySelector('mwc-radio');
            if (!mwcRadio || !mwcRadio.shadowRoot) return 'no-mwc-radio';
            
            const input = mwcRadio.shadowRoot.querySelector('input');
            if (!input) return 'no-input-found';
            
            input.click();
            input.checked = true;
            input.dispatchEvent(new Event('change', { bubbles: true }));
            return 't4-radio-clicked-successfully';
        } catch (e) {
            return 'error-selecting-t4:' + e.message;
        }
    }""")
    logger.info("GPU select result for %s: %s", email, gpu_result)
    await page.wait_for_timeout(300)
    
    # Bước 4: Click Save trong mwc-dialog
    save_result = await _shadow_click(page, """() => {
        try {
            const mwcDialog = document.querySelector('mwc-dialog, colab-dialog, paper-dialog, [role="dialog"]');
            if (!mwcDialog) return 'no-dialog-found';
            
            // Nút Save trong mwc-dialog thường nằm ở phần slot="primaryAction" hoặc có dialogAction="ok"
            const saveBtn = mwcDialog.querySelector('[dialogAction="ok"], [dialogaction="ok"], button#ok, md-filled-button, paper-button');
            if (saveBtn) {
                saveBtn.click();
                return 'save-clicked-successfully:' + saveBtn.tagName;
            }
            
            // Fallback tìm tất cả các nút trong dialog chứa chữ Save hoặc Lưu
            const buttons = mwcDialog.querySelectorAll('button, paper-button, md-filled-button, [role="button"]');
            for (const btn of buttons) {
                const txt = (btn.innerText || btn.textContent || '').trim().toLowerCase();
                if (txt === 'save' || txt === 'lưu' || txt === 'lưu lại' || txt === 'ok') {
                    btn.click();
                    return 'save-clicked-via-text-fallback:' + btn.tagName;
                }
            }
            return 'save-button-not-found';
        } catch (e) {
            return 'error-clicking-save:' + e.message;
        }
    }""")
    logger.info("Save runtime result for %s: %s", email, save_result)
    await page.wait_for_timeout(500)
    
    # Kiểm tra quota trước khi kết nối
    quota_err = await _check_quota_or_errors(page)
    if quota_err:
        logger.error("Quota or error detected before connect for %s: %s", email, quota_err)
        raise RuntimeError(f"Colab quota or limit reached: {quota_err}")
        
    # Bước 5: Click Connect
    logger.info("Connecting runtime for %s...", email)
    connect_result = await _shadow_click(page, """() => {
        const host = document.querySelector('colab-connect-button');
        if (!host) return 'no-connect-button';
        const shadow = host.shadowRoot;
        if (shadow) {
            const txt = shadow.innerText || '';
            if (txt.includes('Connected') || txt.includes('RAM') || txt.includes('RAM/Disk') || shadow.querySelector('colab-usage-meter')) {
                return 'already-connected';
            }
            const btn = shadow.querySelector('#connect, colab-toolbar-button, paper-button, md-filled-button');
            if (btn) { btn.click(); return 'shadow-btn:' + btn.tagName; }
        }
        host.click();
        return 'host-clicked';
    }""")
    logger.info("Connect action result for %s: %s", email, connect_result)
    
    # Chờ runtime connected ngắn. Colab có thể queue Run All trong lúc runtime đang connect,
    # nên không cần block 30s ở đây.
    connected = False
    for i in range(12):
        await page.wait_for_timeout(500)
        quota_err = await _check_quota_or_errors(page)
        if quota_err:
            logger.error("Quota error while waiting connect for %s: %s", email, quota_err)
            raise RuntimeError(f"Colab quota or limit reached: {quota_err}")
            
        try:
            ram_visible = await page.evaluate("""() => {
                function findElement(root, selectors) {
                    if (!root) return null;
                    for (const sel of selectors) {
                        try {
                            const el = root.querySelector(sel);
                            if (el) return el;
                        } catch(e){}
                    }
                    if (root.shadowRoot) {
                        const el = findElement(root.shadowRoot, selectors);
                        if (el) return el;
                    }
                    if (root.children) {
                        for (let i = 0; i < root.children.length; i++) {
                            const el = findElement(root.children[i], selectors);
                            if (el) return el;
                        }
                    }
                    return null;
                }
                
                const el = findElement(document.body, ['colab-usage-meter', '.memory-display', '[title*="RAM"]', '[title*="Disk"]', 'colab-connect-button']);
                if (el) {
                    if (el.tagName === 'COLAB-CONNECT-BUTTON') {
                        const shadow = el.shadowRoot;
                        if (shadow) {
                            const txt = shadow.innerText || '';
                            if (txt.includes('Connected') || txt.includes('RAM') || txt.includes('RAM/Disk') || shadow.querySelector('colab-usage-meter')) {
                                return 'connected';
                            }
                        }
                    } else {
                        return 'connected';
                    }
                }
                return 'waiting';
            }""")
            if ram_visible == "connected":
                connected = True
                logger.info("Runtime connected after %.1fs for %s", (i + 1) * 0.5, email)
                break
        except Exception:
            pass
            
    if not connected:
        logger.warning("Runtime not connected after 6s for %s, running all anyway", email)


async def start_colab_worker(email: str, server_url: str) -> None:
    """Start a Colab worker: open the notebook, select GPU T4, fill configuration, run-all, and keep-alive."""
    profile_dir = str(PROFILES_DIR / email)
    if not Path(profile_dir).exists():
        raise RuntimeError(f"No profile found for {email}. Login first.")

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
                "--no-first-run"
            ],
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()
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

        # 1. Chọn GPU T4 & Connect trước khi điền tham số
        await _select_gpu_and_connect(page, email)

        # 2. Điền form parameters (SERVER_URL và EMAIL)
        await _fill_colab_param(page, "SERVER_URL", server_url)
        await _fill_colab_param(page, "EMAIL", email)

        # 3. Gửi Ctrl+F9 để Run All cells
        logger.info("Sending Run All (Ctrl+F9) for %s", email)
        await page.keyboard.press("Control+F9")

        dismissed = await _dismiss_colab_security_warning(page, email)

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
                    const okBtn = document.querySelector('paper-button#ok, colab-dialog paper-button, md-filled-button[id*="ok"]');
                    if (okBtn) {
                        okBtn.click();
                        console.log('[Antigravity-KeepAlive] Dismissed alert dialog');
                    }
                }, 30000);
            }""")
            logger.info("Keep-Alive JS injected successfully for %s", email)
        except Exception as e:
            logger.warning("Failed to inject Keep-Alive JS for %s: %s", email, e)

        # Store references
        _active_contexts[email] = (pw, context)  # type: ignore[assignment]
        _active_pages[email] = page

        # Start keep-alive task
        task = asyncio.create_task(_keepalive_loop(email))
        _keepalive_tasks[email] = task
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
    keepalive = _keepalive_tasks.pop(email, None)
    if keepalive is not None:
        keepalive.cancel()
        try:
            await keepalive
        except asyncio.CancelledError:
            pass

    entry = _active_contexts.pop(email, None)
    _active_pages.pop(email, None)
    if entry is not None:
        pw, ctx = entry
        await ctx.close()
        await pw.stop()
        logger.info("Stopped Colab worker for %s", email)


async def _keepalive_loop(email: str) -> None:
    """Periodically interact with the Colab page to prevent idle timeout."""
    while True:
        await asyncio.sleep(WORKER_KEEPALIVE_INTERVAL)
        page = _active_pages.get(email)
        if page is None:
            break
        try:
            await page.evaluate("window.scrollTo(0, 100)")
            logger.debug("Keep-alive scroll for %s", email)
        except Exception as exc:
            logger.warning("Keep-alive failed for %s: %s", email, exc)
            break
