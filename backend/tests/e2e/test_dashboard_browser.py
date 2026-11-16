"""Step 5b browser acceptance: the dashboard in a real Chromium.

Runs against a live uvicorn subprocess (real BGE-M3 + PostgreSQL; no LLM is
needed — the dashboard never chats). Covers login + session persistence,
document upload and delete through the UI, confirm dialogs on destructive
actions, viewer read-only access, Arabic RTL / French labels, the
settings page (snippet, domains, key rotation), the evaluation tab
(golden counts per language, owner-only run button), and the website tab
(crawl a local fixture site, crawled documents, delete, viewer read-only).

Run: PLAYWRIGHT_BROWSERS_PATH=... pytest -m e2e (see README).
"""

import asyncio
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from tests.conftest import ENV_KEYS

_HF_HOME = os.environ.get("HF_HOME", "")
_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://sanad:sanad@localhost:5432/sanad"
)
_PLAYWRIGHT_BROWSERS_PATH = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")

BACKEND_DIR = Path(__file__).resolve().parents[2]
ADMIN_KEY = "e2e-dashboard-admin"

OWNER_PASSWORD = "owner-password-1"
VIEWER_PASSWORD = "viewer-password-1"

POLICY_EN = """# Refund policy
Customers may request a full refund within 30 days of purchase. Refunds are issued
to the original payment method within 5 business days.
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def dashboard_server(tmp_path_factory):
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = {k: v for k, v in os.environ.items() if k not in ENV_KEYS}
    env.update(
        {
            "ADMIN_API_KEY": ADMIN_KEY,
            "DATABASE_URL": _DATABASE_URL,
            "DATA_DIR": str(tmp_path_factory.mktemp("dashboard-data")),
            "PYTHONIOENCODING": "utf-8",
            # Limits are covered by dedicated tests; keep browser runs deterministic.
            "RATE_LIMIT_PER_IP": "0",
            "RATE_LIMIT_PER_SITE": "0",
            "DAILY_CAP_PER_COMPANY": "0",
            "LOGIN_RATE_LIMIT_PER_MINUTE": "0",
            # The crawl test targets a loopback fixture site.
            "CRAWL_ALLOW_PRIVATE": "true",
            "CRAWL_RESYNC_HOURS": "0",
        }
    )
    if _HF_HOME:
        env["HF_HOME"] = _HF_HOME
    log_path = tmp_path_factory.mktemp("dashboard-log") / "uvicorn.log"
    with open(log_path, "w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn", "app.main:app",
                "--host", "127.0.0.1", "--port", str(port),
            ],
            cwd=str(BACKEND_DIR),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 90
        ready = False
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                if httpx.get(f"{base}/health", timeout=2, trust_env=False).status_code == 200:
                    ready = True
                    break
            except (httpx.HTTPError, OSError):
                pass
            time.sleep(0.5)
        if not ready:
            process.kill()
            tail = log_path.read_text(encoding="utf-8")[-2000:]
            pytest.skip(f"Dashboard server did not start. Log tail:\n{tail}")
    yield {"base": base, "admin": ADMIN_KEY}
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


@pytest.fixture
async def browser(monkeypatch):
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        pytest.skip("playwright not installed. Run: pip install -e '.[browser]'")
    if _PLAYWRIGHT_BROWSERS_PATH:
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", _PLAYWRIGHT_BROWSERS_PATH)
    playwright = await async_playwright().start()
    try:
        instance = await playwright.chromium.launch(headless=True)
    except Exception as exc:
        await playwright.stop()
        pytest.skip(
            f"Chromium not available ({exc}). Run: python -m playwright install chromium "
            "(set PLAYWRIGHT_BROWSERS_PATH to keep browsers outside C:)."
        )
    yield instance
    await instance.close()
    await playwright.stop()


@pytest.fixture
async def page(browser):
    context = await browser.new_context(viewport={"width": 1280, "height": 900})
    instance = await context.new_page()
    yield instance
    await context.close()


async def create_company_with_owner(server: dict) -> dict:
    # Emails are globally unique and the dev DB persists between runs.
    suffix = uuid4().hex[:8]
    email = f"owner-{suffix}@dashboard-e2e.example"
    async with httpx.AsyncClient(
        base_url=server["base"], timeout=30, trust_env=False
    ) as client:
        response = await client.post(
            "/api/v1/companies",
            json={
                "name": f"Dashboard Co {suffix}",
                "owner_email": email,
                "owner_password": OWNER_PASSWORD,
            },
            headers={"X-Admin-Key": server["admin"]},
        )
        assert response.status_code == 201, response.text
        company = response.json()
    return {"email": email, "company": company}


async def login(page, base: str, email: str, password: str) -> None:
    await page.goto(f"{base}/dashboard/")
    await page.locator("#login-email").fill(email)
    await page.locator("#login-password").fill(password)
    await page.locator("button[type=submit]").click()
    await page.locator("header.top").wait_for(state="visible", timeout=15_000)


def auto_dialog(page) -> dict:
    # One handler per page; tests flip the flag before each confirm().
    state = {"accept": False}
    page.on(
        "dialog",
        lambda dialog: asyncio.ensure_future(
            dialog.accept() if state["accept"] else dialog.dismiss()
        ),
    )
    return state


async def test_login_error_then_owner_session_persists(page, dashboard_server):
    base = dashboard_server["base"]
    account = await create_company_with_owner(dashboard_server)
    await page.goto(f"{base}/dashboard/")
    await page.locator("#login-email").fill(account["email"])
    await page.locator("#login-password").fill("wrong-password")
    await page.locator("button[type=submit]").click()
    error = page.locator(".login-card .banner.error")
    await error.wait_for(state="visible")
    assert "Invalid email or password" in await error.inner_text()

    await page.locator("#login-password").fill(OWNER_PASSWORD)
    await page.locator("button[type=submit]").click()
    header = page.locator("header.top")
    await header.wait_for(state="visible")
    assert account["company"]["name"] in await header.inner_text()

    # The httpOnly cookie survives a reload: no second login needed.
    await page.reload()
    await page.locator("header.top").wait_for(state="visible")
    assert await page.locator("#login-email").count() == 0

    await page.get_by_role("button", name="Failed questions").click()
    await page.get_by_text("No refused questions").wait_for(state="visible")
    await page.get_by_role("button", name="Ratings").click()
    await page.get_by_text("No ratings yet").wait_for(state="visible")


async def test_upload_and_delete_document_with_confirm(page, dashboard_server, tmp_path):
    base = dashboard_server["base"]
    account = await create_company_with_owner(dashboard_server)
    await login(page, base, account["email"], OWNER_PASSWORD)

    doc = tmp_path / "refund-policy.md"
    doc.write_text(POLICY_EN, encoding="utf-8")
    await page.locator("#doc-file").set_input_files(str(doc))
    await page.locator("#doc-upload").click()
    row = page.locator("tr", has_text="refund-policy.md")
    await row.wait_for(state="visible", timeout=15_000)
    await row.locator(".badge.ready").wait_for(state="visible", timeout=180_000)
    assert await row.locator(".badge.ready").inner_text() == "ready"

    # Dismissing the confirm keeps the document.
    dialog = auto_dialog(page)
    await row.get_by_role("button", name="Delete").click()
    await page.wait_for_timeout(500)
    assert await page.locator("tr", has_text="refund-policy.md").count() == 1

    # Accepting the confirm removes it.
    dialog["accept"] = True
    await row.get_by_role("button", name="Delete").click()
    await page.locator("tr", has_text="refund-policy.md").wait_for(state="detached")
    await page.get_by_text("No documents yet").wait_for(state="visible")


async def test_viewer_added_through_ui_is_read_only(page, dashboard_server):
    base = dashboard_server["base"]
    account = await create_company_with_owner(dashboard_server)
    # Emails are globally unique; derive one per test company so re-runs work.
    viewer_email = account["email"].replace("owner", "viewer", 1)
    await login(page, base, account["email"], OWNER_PASSWORD)

    await page.get_by_role("button", name="Settings", exact=True).click()
    await page.locator("#viewer-email").fill(viewer_email)
    await page.locator("#viewer-password").fill(VIEWER_PASSWORD)
    await page.locator("#add-viewer").click()
    await page.locator("tr", has_text=viewer_email).wait_for(state="visible")

    await page.get_by_role("button", name="Sign out").click()
    await page.locator("#login-email").wait_for(state="visible")
    await login(page, base, viewer_email, VIEWER_PASSWORD)
    assert "Read-only access" in await page.locator("header.top").inner_text()

    # No mutation controls anywhere for a viewer.
    assert await page.locator("#doc-upload").count() == 0
    await page.get_by_role("button", name="Settings", exact=True).click()
    assert await page.locator("#rotate-keys").count() == 0
    assert await page.locator("#delete-conversations").count() == 0
    assert await page.locator("#add-viewer").count() == 0
    assert await page.locator("#save-settings").count() == 0
    await page.locator("#allowed-domains").wait_for(state="visible")
    assert await page.locator("#allowed-domains").is_disabled()
    # The snippet is still visible: viewers can copy it to the website.
    assert "/widget.js" in await page.locator("#widget-snippet").inner_text()


async def test_arabic_rtl_and_french_labels(page, dashboard_server):
    base = dashboard_server["base"]
    account = await create_company_with_owner(dashboard_server)
    await login(page, base, account["email"], OWNER_PASSWORD)

    picker = page.get_by_label("Language")
    await picker.select_option("ar")
    assert await page.evaluate("document.documentElement.dir") == "rtl"
    assert await page.evaluate("document.documentElement.lang") == "ar"
    assert await page.get_by_role("button", name="الوثائق").count() == 1
    assert await page.get_by_role("button", name="تسجيل الخروج").count() == 1

    await picker.select_option("fr")
    assert await page.evaluate("document.documentElement.dir") == "ltr"
    assert await page.get_by_role("button", name="Paramètres").count() == 1

    # The choice survives a reload (localStorage).
    await page.reload()
    await page.locator("header.top").wait_for(state="visible")
    assert await page.evaluate("document.documentElement.lang") == "fr"


async def test_settings_snippet_domains_and_rotation_confirm(page, dashboard_server):
    base = dashboard_server["base"]
    account = await create_company_with_owner(dashboard_server)
    await login(page, base, account["email"], OWNER_PASSWORD)
    await page.get_by_role("button", name="Settings", exact=True).click()

    await page.locator("#widget-snippet").wait_for(state="visible")
    snippet = await page.locator("#widget-snippet").inner_text()
    assert account["company"]["site_key"] in snippet
    assert f"{base}/widget.js" in snippet

    await page.locator("#allowed-domains").fill("example.com\n*.example.com")
    await page.locator("#save-settings").click()
    await page.get_by_text("Saved.", exact=True).wait_for(state="visible")
    await page.reload()
    await page.get_by_role("button", name="Settings", exact=True).click()
    value = await page.locator("#allowed-domains").input_value()
    assert "example.com" in value and "*.example.com" in value

    # Dismissing the rotation confirm changes nothing.
    dialog = auto_dialog(page)
    await page.locator("#rotate-keys").click()
    await page.wait_for_timeout(500)
    assert await page.locator("#new-api-key").count() == 0

    # Accepting shows both new keys once and refreshes the snippet.
    dialog["accept"] = True
    await page.locator("#rotate-keys").click()
    await page.locator("#new-api-key").wait_for(state="visible")
    new_api_key = await page.locator("#new-api-key").inner_text()
    new_site_key = await page.locator("#new-site-key").inner_text()
    assert new_api_key.startswith("sk-")
    assert new_site_key.startswith("pk-")
    assert new_site_key != account["company"]["site_key"]
    await page.wait_for_function(
        "key => document.getElementById('widget-snippet').textContent.includes(key)",
        arg=new_site_key,
    )


async def test_evaluation_tab_counts_and_owner_only_run(page, dashboard_server):
    base = dashboard_server["base"]
    account = await create_company_with_owner(dashboard_server)
    await login(page, base, account["email"], OWNER_PASSWORD)

    await page.get_by_role("button", name="Evaluation", exact=True).click()
    await page.locator("#golden-languages").wait_for(state="visible")
    for code in ("en", "fr", "ar"):
        row = page.locator("#golden-languages tr", has_text=code)
        assert "11" in await row.inner_text()
    await page.get_by_text("Demo documents missing").wait_for(state="visible")
    await page.get_by_text("No evaluation yet").wait_for(state="visible")
    assert await page.locator("#run-eval").count() == 1

    # Add a viewer through the API (UI path is covered by its own test).
    me = await page.request.get(f"{base}/api/v1/auth/me")
    csrf = (await me.json())["csrf_token"]
    viewer_email = account["email"].replace("owner", "viewer", 1)
    added = await page.request.post(
        f"{base}/api/v1/dashboard/users",
        data={"email": viewer_email, "password": VIEWER_PASSWORD},
        headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    assert added.status == 201, await added.text()

    await page.get_by_role("button", name="Sign out").click()
    await page.locator("#login-email").wait_for(state="visible")
    await login(page, base, viewer_email, VIEWER_PASSWORD)
    await page.get_by_role("button", name="Evaluation", exact=True).click()
    await page.locator("#golden-languages").wait_for(state="visible")
    assert await page.locator("#run-eval").count() == 0


@pytest.fixture
def crawl_site():
    pages = {
        "/robots.txt": ("text/plain", "User-agent: *\nDisallow: /private\n"),
        "/": (
            "text/html",
            "<html><head><title>Acme</title></head><body>"
            '<a href="/refunds">Refunds</a> <a href="/shipping">Shipping</a> '
            '<a href="/private/secret">Secret</a></body></html>',
        ),
        "/refunds": (
            "text/html",
            "<html><head><title>Refunds</title></head><body>"
            "<p>Refunds are issued within 30 days of purchase.</p></body></html>",
        ),
        "/shipping": (
            "text/html",
            "<html><head><title>Shipping</title></head><body>"
            "<p>Shipping takes 5 business days.</p></body></html>",
        ),
        "/private/secret": ("text/html", "<html><body><p>Never crawl me.</p></body></html>"),
    }
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            requests.append(self.path)
            entry = pages.get(self.path)
            if entry is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            ctype, body = entry
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield {"url": f"http://127.0.0.1:{server.server_address[1]}/", "requests": requests}
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


async def test_website_tab_crawl_delete_and_viewer_read_only(
    page, dashboard_server, crawl_site
):
    base = dashboard_server["base"]
    account = await create_company_with_owner(dashboard_server)
    await login(page, base, account["email"], OWNER_PASSWORD)

    await page.get_by_role("button", name="Website", exact=True).click()
    await page.get_by_text("No crawl sources yet").wait_for(state="visible")
    await page.locator("#crawl-url").fill(crawl_site["url"])
    await page.locator("#crawl-add").click()
    row = page.locator("#crawl-sources tr", has_text=crawl_site["url"])
    await row.wait_for(state="visible", timeout=15_000)
    # Real BGE-M3 ingestion of the crawled pages runs in the background.
    await row.locator(".badge.ready").wait_for(state="visible", timeout=180_000)
    cells = row.locator("td")
    assert await cells.nth(2).inner_text() == "3"
    assert await cells.nth(3).inner_text() != "never"
    assert "/private/secret" not in crawl_site["requests"]

    # Crawled pages appear as documents.
    await page.get_by_role("button", name="Documents", exact=True).click()
    await page.locator("tr", has_text="refunds-").wait_for(state="visible")
    await page.locator("tr", has_text="shipping-").wait_for(state="visible")
    assert await page.locator("table .badge.ready").count() == 3

    # A viewer sees the source but has no mutation controls.
    me = await page.request.get(f"{base}/api/v1/auth/me")
    csrf = (await me.json())["csrf_token"]
    viewer_email = account["email"].replace("owner", "viewer", 1)
    added = await page.request.post(
        f"{base}/api/v1/dashboard/users",
        data={"email": viewer_email, "password": VIEWER_PASSWORD},
        headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    assert added.status == 201, await added.text()
    await page.get_by_role("button", name="Sign out").click()
    await page.locator("#login-email").wait_for(state="visible")
    await login(page, base, viewer_email, VIEWER_PASSWORD)
    await page.get_by_role("button", name="Website", exact=True).click()
    await page.locator("#crawl-sources").wait_for(state="visible")
    assert await page.locator("#crawl-add").count() == 0
    assert await page.get_by_role("button", name="Sync now").count() == 0
    assert await page.get_by_role("button", name="Delete").count() == 0

    # Owner deletes the source: crawled documents go with it.
    await page.get_by_role("button", name="Sign out").click()
    await page.locator("#login-email").wait_for(state="visible")
    await login(page, base, account["email"], OWNER_PASSWORD)
    await page.get_by_role("button", name="Website", exact=True).click()
    await page.locator("#crawl-sources").wait_for(state="visible")
    dialog = auto_dialog(page)
    await page.get_by_role("button", name="Delete").click()
    await page.wait_for_timeout(500)
    assert await page.locator("#crawl-sources").count() == 1
    dialog["accept"] = True
    await page.get_by_role("button", name="Delete").click()
    await page.get_by_text("No crawl sources yet").wait_for(state="visible")
    await page.get_by_role("button", name="Documents", exact=True).click()
    await page.get_by_text("No documents yet").wait_for(state="visible")