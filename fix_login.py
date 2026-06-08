import re
path = r"app\automation\play_runner.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Find the function and replace it
START_MARKER = "async def _check_login_required(page) -> bool:"
END_MARKER = "async def _mark_account_needs_login"

start_idx = content.find(START_MARKER)
end_idx = content.find(END_MARKER)

if start_idx == -1 or end_idx == -1:
    print("ERROR: Markers not found")
    exit(1)

new_func_lines = [
    "async def _check_login_required(page) -> bool:",
    "    # Phat hien trang yeu cau login Google. URL truoc, JS evaluate fallback",
    "    try:",
    "        url = page.url",
    "        login_urls = [\"accounts.google.com\", \"ServiceLogin\", \"signin\", \"signup\", \"consent.google\", \"/login\"]",
    "        for lu in login_urls:",
    "            if lu in url:",
    "                logger.info(\"Login detected via URL: %s\", url)",
    "                return True",
    "    except Exception as e:",
    "        logger.debug(\"URL check failed: %s\", str(e)[:100])",
    "",
    "    try:",
    "        js_check = '() => {' + \\",
    "            'const text = (document.body && document.body.innerText || \"\").toLowerCase();' + \\",
    "            'const inds = [\"sign in to your google\", \"enter your password\", \"nhap mat khau\", \"dang nhap\", \"wrong password\", \"use your google account\"];' + \\",
    "            'for (const i of inds) { if (text.includes(i)) return true; }' + \\",
    "            'return !!document.querySelector(\"input[type=password]\");' + \\",
    "            '}'",
    "        result = await page.evaluate(js_check)",
    "        return bool(result)",
    "    except Exception as e:",
    "        logger.debug(\"Login JS check failed: %s\", str(e)[:100])",
    "        return False",
    "",
    ""
]

new_func = "\n".join(new_func_lines) + "\n"
content = content[:start_idx] + new_func + content[end_idx:]

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Fixed login detection function")
