"""
Playwright browser tools for Vex.

Gives Vex the ability to interact with web pages: take screenshots,
extract text, and validate links. Uses Playwright's sync API via
a subprocess to keep browser instances isolated.

Tools provided:
  - playwright_screenshot: capture a PNG screenshot of a URL
  - playwright_text: extract visible text from a page
  - playwright_check_links: find broken links on a page

Requires: pip install playwright && playwright install chromium
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def _run_playwright_script(script: str, timeout: int = 30) -> dict:
    """Run a Playwright script in a subprocess and return JSON result."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip() or result.stdout.strip()}
        try:
            return json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            return {"ok": True, "output": result.stdout.strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Timeout after {timeout}s"}
    except FileNotFoundError:
        return {"ok": False, "error": "Playwright not installed. Run: pip install playwright && playwright install chromium"}


def screenshot(url: str, output_path: str = "", full_page: bool = True,
               width: int = 1280, height: int = 720) -> dict:
    """Take a screenshot of a URL. Returns {ok, path, ...}."""
    if not output_path:
        output_path = str(Path(tempfile.gettempdir()) / f"vex_screenshot_{Path(url).name or 'page'}.png")

    script = f'''
import json, sys
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={{"width": {width}, "height": {height}}})
        page.goto("{url}", wait_until="networkidle", timeout=15000)
        page.screenshot(path="{output_path}", full_page={str(full_page).lower()})
        title = page.title()
        url_final = page.url
        browser.close()
    print(json.dumps({{"ok": True, "path": "{output_path}", "title": title, "url": url_final}}))
except Exception as e:
    print(json.dumps({{"ok": False, "error": str(e)}}))
'''
    return _run_playwright_script(script, timeout=30)


def get_text(url: str, max_chars: int = 10000) -> dict:
    """Extract visible text content from a URL. Returns {ok, text, title, url}."""
    script = f'''
import json, sys
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("{url}", wait_until="networkidle", timeout=15000)
        text = page.inner_text("body")
        title = page.title()
        url_final = page.url
        browser.close()
    text = text[:{max_chars}]
    print(json.dumps({{"ok": True, "text": text, "title": title, "url": url_final, "truncated": len(text) >= {max_chars}}}))
except Exception as e:
    print(json.dumps({{"ok": False, "error": str(e)}}))
'''
    return _run_playwright_script(script, timeout=30)


def check_links(url: str, same_origin: bool = True) -> dict:
    """Check all links on a page, report broken ones. Returns {ok, total, broken, results}."""
    script = f'''
import json, sys
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("{url}", wait_until="networkidle", timeout=15000)
        links = page.eval_on_selector_all("a[href]", "els => els.map(el => ({{href: el.href, text: el.innerText}}))")
        browser.close()

    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError

    results = []
    broken = 0
    checked = 0
    for link in links[:50]:  # cap at 50 links
        href = link.get("href", "")
        if not href.startswith("http"):
            continue
        if {str(same_origin).lower()} and not href.startswith("{url}"):
            continue
        checked += 1
        try:
            req = Request(href, method="HEAD")
            urlopen(req, timeout=5)
            results.append({{"href": href, "text": link.get("text", "")[:80], "status": "ok"}})
        except HTTPError as e:
            broken += 1
            results.append({{"href": href, "text": link.get("text", "")[:80], "status": e.code}})
        except Exception:
            results.append({{"href": href, "text": link.get("text", "")[:80], "status": "unreachable"}})

    print(json.dumps({{"ok": True, "total_links": len(links), "checked": checked, "broken": broken, "results": results}}))
except Exception as e:
    print(json.dumps({{"ok": False, "error": str(e)}}))
'''
    return _run_playwright_script(script, timeout=60)
