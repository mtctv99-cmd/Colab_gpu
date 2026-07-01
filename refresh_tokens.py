"""Auto OAuth — mỗi account 1 profile riêng."""
import json, os, re, signal, sqlite3, subprocess, time, tempfile
from urllib.parse import urlparse, parse_qs

TOKEN_DIR = os.path.expanduser("~/.config/colab-cli")
PROFILE_DIR = os.path.join(TOKEN_DIR, "profiles")
os.makedirs(TOKEN_DIR, exist_ok=True)
os.makedirs(PROFILE_DIR, exist_ok=True)

SCOPES = [
    "openid","https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/colaboratory",
    "https://www.googleapis.com/auth/drive.file",
]
REMOTE_URI = "https://sdk.cloud.google.com/applicationdefaultauthcode.html"

def token_path(email):
    safe = email.replace("@", "_at_").replace(".", "_")
    return os.path.join(TOKEN_DIR, f"token_{safe}.json")

def profile_path(email):
    safe = email.replace("@", "_at_").replace(".", "_")
    return os.path.join(PROFILE_DIR, safe)

def main():
    db = sqlite3.connect("data/db.sqlite3")
    accounts = db.execute("SELECT id, email FROM google_accounts ORDER BY id").fetchall()
    db.close()

    cfg = os.path.expanduser("~/.colab-cli-oauth-config.json")
    if not os.path.exists(cfg):
        cfg = os.path.join(os.path.dirname(__file__), "app/colab_cli/oauth_config.json")
    client_config = json.load(open(cfg))

    from google_auth_oauthlib.flow import InstalledAppFlow
    from playwright.sync_api import sync_playwright

    done = 0
    with sync_playwright() as pw:
        for aid, email in accounts:
            tpath = token_path(email)
            if os.path.exists(tpath) and json.load(open(tpath)).get("refresh_token"):
                print(f"[SKIP] {email}")
                continue

            print(f"\n[{aid}/8] {email}")
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            flow.redirect_uri = REMOTE_URI
            auth_url, _ = flow.authorization_url(
                prompt="consent", token_usage="remote",
                access_type="offline", include_granted_scopes="true",
            )

            prof_path = profile_path(email)
            os.makedirs(prof_path, exist_ok=True)

            # Mỗi account 1 profile riêng, headless=True + xvfb
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=prof_path,
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-sandbox",
                ],
                no_viewport=True,
            )

            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(auth_url, wait_until="domcontentloaded", timeout=30000)

            code = None
            deadline = time.time() + 120
            while time.time() < deadline and not code:
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except:
                    pass
                try:
                    cur = page.url
                    qs = parse_qs(urlparse(cur).query)
                    if qs.get("code"):
                        code = qs["code"][0]
                        break
                    if "sdk.cloud.google.com" in cur:
                        txt = page.evaluate("document.body.innerText")
                        m = re.search(r'(4/0[A-Za-z0-9_-]+)', txt)
                        if m:
                            code = m.group(1)
                            print(f"  + code from page text")
                            break

                    # Account chooser - click đúng email
                    if "Sign in" in page.title() or "accountchooser" in cur:
                        # Có field input email không?
                        email_input = page.query_selector("input[type='email']")
                        if email_input:
                            # Đang ở màn login, cần user tự login lần đầu
                            pass
                        acct = page.query_selector(f'[data-identifier="{email}"]')
                        if acct and acct.is_visible():
                            acct.click()
                            time.sleep(2)
                            continue

                    # Consent page - click Allow/Continue
                    for sel in [
                        "#submit_approve_access",
                        "button:has-text('Continue')",
                        "button:has-text('Allow')",
                        "button:has-text('Accept')",
                        "button:has-text('Next')",
                        "form[action*='Consent'] input[type=submit]",
                    ]:
                        btn = page.query_selector(sel)
                        if btn and btn.is_visible():
                            print(f"  click: {sel}")
                            btn.click()
                            time.sleep(2)
                            break
                except Exception as ex:
                    print(f"  err: {type(ex).__name__}")
                time.sleep(1)

            page.close()
            ctx.close()

            if code:
                try:
                    flow.fetch_token(code=code)
                    with open(tpath, "w") as f:
                        f.write(flow.credentials.to_json())
                    print(f"  [OK] Saved")
                    done += 1
                except Exception as e:
                    print(f"  [FAIL] Exchange: {e}")
            else:
                print(f"  [FAIL] No code — session broken")
                print(f"  Profile saved at: {prof_path}")
                print(f"  Mở Chrome và đăng nhập email này vào profile đó:")
                print(f"    google-chrome --user-data-dir={prof_path}")
                with open(tpath.replace(".json", ".url.txt"), "w") as f:
                    f.write(auth_url)

    print(f"\n=== {done}/{len(accounts)} OK ===")

if __name__ == "__main__":
    main()
