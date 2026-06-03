"""Playwright automation module for controlling Google Colab workers."""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from app.config import PROFILES_DIR, GITHUB_USER, GITHUB_REPO, COLAB_NOTEBOOK_PATH, WORKER_KEEPALIVE_INTERVAL

logger = logging.getLogger(__name__)

# In-memory store for active browser contexts
_active_contexts: dict[str, tuple] = {}  # email -> (playwright, context)
_active_pages: dict[str, Page] = {}
_keepalive_tasks: dict[str, asyncio.Task] = {}


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
        await ctx.close()
        await pw.stop()
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
                logger.info("Filled parameter %s using selector: %s", param_name, sel)
                return True
        except Exception:
            pass
    return False


async def _shadow_click(page: Page, js_expr: str) -> str:
    try:
        res = await page.evaluate(js_expr)
        return res or "no-result"
    except Exception as e:
        return f"err:{type(e).__name__}"


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
    await page.wait_for_timeout(1000)
    
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
    await page.wait_for_timeout(2000)
    
    # Bước 3: Chọn T4 GPU trong dialog
    try:
        await page.get_by_text("T4", exact=True).first.click(timeout=5000, force=True)
        gpu_result = "T4-clicked:playwright-force"
    except Exception as exc:
        gpu_result = f"t4-click-fail:{type(exc).__name__}: {exc}"
    logger.info("GPU select result for %s: %s", email, gpu_result)
    await page.wait_for_timeout(1000)
    
    # Bước 4: Click Save
    save_result = "no-save-btn"
    for save_text in ["Save", "Lưu", "Lưu lại"]:
        try:
            loc = page.get_by_role("button", name=save_text, exact=False)
            if await loc.count() == 0:
                loc = page.get_by_text(save_text, exact=True)
            if await loc.count() > 0:
                await loc.first.click(timeout=5000, force=True)
                save_result = f"save-clicked:{save_text}"
                break
        except Exception as exc:
            save_result = f"save-click-fail:{save_text}:{type(exc).__name__}: {exc}"
    logger.info("Save runtime result for %s: %s", email, save_result)
    await page.wait_for_timeout(3000)
    
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
    
    # Chờ runtime connected (RAM/Disk indicator xuất hiện)
    connected = False
    for i in range(20):
        await page.wait_for_timeout(3000)
        quota_err = await _check_quota_or_errors(page)
        if quota_err:
            logger.error("Quota error while waiting connect for %s: %s", email, quota_err)
            raise RuntimeError(f"Colab quota or limit reached: {quota_err}")
            
        try:
            ram_visible = await page.evaluate("""() => {
                const indicators = document.querySelectorAll('colab-usage-meter, .memory-display, [title*="RAM"], [title*="Disk"]');
                if (indicators.length > 0) return 'connected';
                const host = document.querySelector('colab-connect-button');
                if (!host) return 'no-host';
                const shadow = host.shadowRoot;
                if (!shadow) return 'no-shadow';
                const txt = shadow.innerText || '';
                if (txt.includes('Connected') || txt.includes('RAM') || txt.includes('RAM/Disk')) return 'connected';
                if (shadow.querySelector('colab-usage-meter')) return 'connected';
                return 'waiting';
            }""")
            if ram_visible == "connected":
                connected = True
                logger.info("Runtime connected after %ds for %s", (i+1)*3, email)
                break
        except Exception:
            pass
            
    if not connected:
        logger.warning("Runtime connection timed out for %s, will try to Run All anyway", email)


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
                "--disable-blink-features=AutomationControlled"
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
        await page.wait_for_timeout(5000)

        # 1. Chọn GPU T4 & Connect trước khi điền tham số
        await _select_gpu_and_connect(page, email)

        # 2. Điền form parameters (SERVER_URL và EMAIL)
        await _fill_colab_param(page, "SERVER_URL", server_url)
        await _fill_colab_param(page, "EMAIL", email)

        # 3. Gửi Ctrl+F9 để Run All cells
        logger.info("Sending Run All (Ctrl+F9) for %s", email)
        await page.keyboard.press("Control+F9")

        # Google Colab shows the security dialog *after* you trigger execution.
        try:
            await page.wait_for_selector("#ok", timeout=5000)
            run_anyway_btn = page.locator("#ok")
            await run_anyway_btn.click()
            logger.info("Dismissed Colab security warning dialog for %s", email)
        except Exception:
            pass

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
                import os
                os.makedirs(r"d:\Colab\data", exist_ok=True)
                await page.screenshot(path=r"d:\Colab\data\colab_debug_error.png")
                logger.info("Saved error screenshot to d:\\Colab\\data\\colab_debug_error.png")
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
