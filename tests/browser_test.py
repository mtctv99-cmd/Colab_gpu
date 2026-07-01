"""Playwright test — full user flow on real site http://192.168.1.117:3355"""
from playwright.sync_api import sync_playwright, expect
import time, json

BASE = "http://192.168.1.117:3355"
EMAIL = f"bt_{int(time.time())}@x.com"
PASS = "pass123"

from sqlalchemy import create_engine, text
_engine = create_engine("sqlite:///data/db.sqlite3")
_n = 0

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("console", lambda msg: errors.append({"type": msg.type, "text": msg.text}))
        page.on("pageerror", lambda err: errors.append({"type": "error", "text": str(err)}))

        print("=" * 60)
        print("PLAYWRIGHT E2E — http://192.168.1.117:3355")
        print("=" * 60)
        n = 0

        def ok(label):
            global _n; _n += 1
            print(f"  [{_n:2d}] ✅ {label}")

        # ── 1. Homepage ──
        page.goto(BASE); page.wait_for_load_state("networkidle")
        assert "TTS Dubbing" in page.title()
        ok("Homepage loads")

        # ── 2. Signup ──
        page.goto(f"{BASE}/signup"); page.wait_for_load_state("networkidle")
        page.fill("input[type='email']", EMAIL)
        page.fill("input[type='password']", PASS)
        page.click("button[type='submit']")
        page.wait_for_url("**/dashboard", timeout=10000)
        ok(f"Signup → dashboard ({EMAIL})")

        # ── 3. Dashboard: sidebar ──
        page.wait_for_load_state("networkidle"); time.sleep(1)
        page.get_by_role("button", name="Tổng quan").wait_for(state="visible", timeout=5000)
        ok("Dashboard sidebar loaded")
        assert page.get_by_text("Số dư").is_visible()
        ok("Balance section visible")

        # ── 4. API Keys ──
        page.get_by_role("button", name="API Keys").click(); page.wait_for_timeout(1500)
        assert page.get_by_text("Chưa có API key nào").is_visible()
        ok("API Keys empty state")
        page.get_by_role("button", name="Tạo key").first.click()
        page.wait_for_timeout(300)
        page.fill("input[placeholder*='vd: Production']", "Playwright Test Key")
        page.locator("form").get_by_role("button", name="Tạo key").click()
        page.wait_for_timeout(1500)
        assert page.get_by_text("Copy key").is_visible()
        ok("API key created")
        page.locator(".fixed.right-0 button:has(svg)").first.click()
        page.wait_for_timeout(500)

        # ── 5. Usage ──
        page.get_by_role("button", name="Lịch sử").click(); page.wait_for_timeout(1500)
        assert page.get_by_role("heading", name="Lịch sử sử dụng").is_visible()
        ok("Usage page")

        # ── 6. TTS Overview ──
        page.get_by_role("button", name="Tổng quan").click(); page.wait_for_timeout(1500)
        ok("TTS Overview tab")

        # ── 7. Playground ──
        page.get_by_role("button", name="Chat Playground").click(); page.wait_for_timeout(2000)
        assert page.get_by_text("System Prompt").is_visible()
        ok("Chat Playground visible")
        page.locator("textarea").last.fill("Hello!")
        page.locator("button:has(svg.lucide-send)").click()
        page.wait_for_timeout(2000)
        ok("Chat message sent")

        # ── 8. Settings ──
        page.get_by_role("button", name="Cài đặt").click(); page.wait_for_timeout(1500)
        assert page.locator("h2").filter(has_text="Cài đặt").is_visible()
        ok("Settings page")

        # ── 9. Promote to admin ──
        with _engine.connect() as conn:
            conn.execute(text("UPDATE users SET role='admin', balance=99999 WHERE email=:e"), {"e": EMAIL})
            conn.commit()
        page.evaluate("localStorage.clear()")
        page.goto(f"{BASE}/login"); page.wait_for_load_state("networkidle")
        page.fill("input[type='email']", EMAIL)
        page.fill("input[type='password']", PASS)
        page.click("button[type='submit']")
        page.wait_for_url("**/admin", timeout=10000)
        page.wait_for_load_state("networkidle")
        ok("Admin login → /admin")

        # ── 10. Admin overview ──
        assert page.get_by_text("Tổng quan hệ thống").is_visible()
        ok("Admin overview")

        # ── 11. Admin: Tasks ──
        page.goto(f"{BASE}/admin/tasks"); page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)
        assert page.get_by_text("Tác vụ").first.is_visible()
        ok("Admin Tasks page")


        # ── 12. Admin: Workers ──
        page.goto(f"{BASE}/admin/workers"); page.wait_for_load_state("networkidle")
        assert page.get_by_text("Worker Sessions").is_visible()
        ok("Admin Workers page")

        # ── 13. Admin: Accounts ──
        page.goto(f"{BASE}/admin/accounts"); page.wait_for_load_state("networkidle")
        assert page.get_by_text("Tài khoản Google/Colab").is_visible()
        ok("Admin Accounts page")

        # ── 14. Docs ──
        page.goto(f"{BASE}/docs"); page.wait_for_load_state("networkidle")
        ok("API Docs page")

        # ── 15. Login page ──
        page.goto(f"{BASE}/login"); page.wait_for_load_state("networkidle")
        ok("Login page")

        # ── 16. Console errors ──
        js_errors = [e for e in errors if e["type"] == "error"]
        if js_errors:
            print(f"  ⚠️ {len(js_errors)} JS errors:")
            for e in js_errors[:5]:
                print(f"     {e['text'][:120]}")
        else:
            ok("No JS errors")

        print(f"\n{'=' * 60}")
        print(f"RESULT: {_n} checks passed, {len(js_errors)} JS errors")
        print(f"{'=' * 60}")
        browser.close()

if __name__ == "__main__":
    main()
