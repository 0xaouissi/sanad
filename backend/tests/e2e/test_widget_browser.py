"""Step 4 browser acceptance: the widget on a blank page, in a real Chromium.

Runs against a live uvicorn subprocess (real Ollama + BGE-M3 + PostgreSQL) and
a local static server, so the browser sends a real Origin header. Covers RTL
Arabic, mobile full-screen, streaming, clickable citations, thumbs feedback,
themes/config, domain blocking, injection-safe rendering of a malicious
document, and the human-handoff form (real local SMTP sink).

Run: PLAYWRIGHT_BROWSERS_PATH=... pytest -m e2e (see README).
"""

import asyncio
import base64
import functools
import http.server
import os
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import asyncpg
import httpx
import pytest

from tests.conftest import ENV_KEYS

# Captured at import, before the autouse clean_env fixture strips them.
_HF_HOME = os.environ.get("HF_HOME", "")
_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://sanad:sanad@localhost:5432/sanad"
)
_PLAYWRIGHT_BROWSERS_PATH = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")

BACKEND_DIR = Path(__file__).resolve().parents[2]
ADMIN_KEY = "e2e-browser-admin"
OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

POLICY_EN = """# Refund policy
Customers may request a full refund within 30 days of purchase. Refunds are issued
to the original payment method within 5 business days.

# Shipping policy
We ship worldwide. Standard delivery takes 5 to 7 business days and includes tracking.
"""

POLICY_FR = """# Politique de remboursement
Les clients peuvent demander un remboursement complet dans les 30 jours suivant
l'achat. Les remboursements sont effectués sur le moyen de paiement d'origine
sous 5 jours ouvrables.

# Politique de livraison
Nous livrons dans le monde entier. La livraison standard prend 5 à 7 jours
ouvrables et inclut un suivi.
"""

XSS_HEADING = '<img src=x onerror="window.__xss=1">'
MALICIOUS_DOC = (
    f"# {XSS_HEADING}\n"
    "Customers may request a full refund within 30 days of purchase.\n"
    "<script>window.__xss=1</script>\n"
)

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _SMTPSinkHandler(socketserver.StreamRequestHandler):
    """Minimal SMTP dialogue: captures every DATA payload, no auth, no TLS."""

    def handle(self):
        self.wfile.write(b"220 sink ready\r\n")
        in_data = False
        lines: list[bytes] = []
        while True:
            line = self.rfile.readline()
            if not line:
                break
            if in_data:
                if line == b".\r\n":
                    in_data = False
                    self.server.messages.append(b"".join(lines))
                    lines = []
                    self.wfile.write(b"250 OK\r\n")
                else:
                    lines.append(line)
                continue
            cmd = line.strip().upper()
            if cmd.startswith(b"DATA"):
                in_data = True
                self.wfile.write(b"354 go ahead\r\n")
            elif cmd.startswith(b"QUIT"):
                self.wfile.write(b"221 bye\r\n")
                break
            else:
                self.wfile.write(b"250 OK\r\n")


@pytest.fixture(scope="module")
def smtp_sink():
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SMTPSinkHandler)
    server.messages = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def widget_server(tmp_path_factory, smtp_sink):
    try:
        httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3, trust_env=False).raise_for_status()
    except (httpx.HTTPError, OSError) as exc:
        pytest.skip(f"Live Ollama unavailable ({exc}). Start it and pull the tier model.")

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = {k: v for k, v in os.environ.items() if k not in ENV_KEYS}
    env.update(
        {
            "ADMIN_API_KEY": ADMIN_KEY,
            "DATABASE_URL": _DATABASE_URL,
            "DATA_DIR": str(tmp_path_factory.mktemp("widget-data")),
            "PYTHONIOENCODING": "utf-8",
            # Limits are covered by dedicated tests; keep browser runs deterministic.
            "RATE_LIMIT_PER_IP": "0",
            "RATE_LIMIT_PER_SITE": "0",
            "DAILY_CAP_PER_COMPANY": "0",
            # Timing enforcement is covered by integration tests; the widget
            # still sends opened_at and the honeypot stays active here.
            "BOT_CHECK_MIN_SECONDS": "0",
            # Handoff email goes to the local sink; Telegram stays unconfigured.
            "SMTP_HOST": "127.0.0.1",
            "SMTP_PORT": str(smtp_sink.server_address[1]),
            "SMTP_FROM": "widget@sanad.test",
            "SMTP_STARTTLS": "false",
        }
    )
    if _HF_HOME:
        env["HF_HOME"] = _HF_HOME
    log_path = tmp_path_factory.mktemp("widget-log") / "uvicorn.log"
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
            pytest.skip(f"Widget server did not start. Log tail:\n{tail}")
    yield {"base": base, "admin": ADMIN_KEY}
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def blank_site(tmp_path_factory):
    site_dir = tmp_path_factory.mktemp("blank-site")
    (site_dir / "logo.png").write_bytes(PNG_1PX)
    handler = functools.partial(_QuietHandler, directory=str(site_dir))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    yield site_dir, f"http://localhost:{port}", f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


def write_blank_page(
    site_dir: Path, server: dict, company: dict, attrs: str = ""
) -> None:
    html = (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Blank page</title></head>\n"
        "<body>\n"
        f'<script src="{server["base"]}/widget.js" data-site-key="{company["site_key"]}" '
        f'data-api-url="{server["base"]}" {attrs} defer></script>\n'
        "</body></html>\n"
    )
    (site_dir / "index.html").write_text(html, encoding="utf-8")


async def setup_company(
    server: dict,
    domains: list[str] | None = None,
    filename: str = "policy-en.md",
    text: str = POLICY_EN,
) -> dict:
    async with httpx.AsyncClient(
        base_url=server["base"], timeout=180, trust_env=False
    ) as client:
        response = await client.post(
            "/api/v1/companies",
            json={"name": "Widget Co"},
            headers={"X-Admin-Key": server["admin"]},
        )
        assert response.status_code == 201, response.text
        company = response.json()
        headers = {"X-API-Key": company["api_key"]}
        response = await client.put(
            "/api/v1/companies/domains",
            json={"domains": domains if domains is not None else ["localhost"]},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        response = await client.post(
            "/api/v1/documents", files={"file": (filename, text.encode())}, headers=headers
        )
        assert response.status_code == 202, response.text
        for _ in range(180):
            listing = (await client.get("/api/v1/documents", headers=headers)).json()
            if all(d["status"] == "ready" for d in listing):
                return company
            if any(d["status"] == "failed" for d in listing):
                raise AssertionError(f"ingestion failed: {listing}")
            await asyncio.sleep(1)
    raise AssertionError("ingestion timed out")


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


async def _open_widget(page, site_url: str) -> None:
    await page.goto(f"{site_url}/index.html")
    await page.locator(".sanad-fab").click()
    await page.locator(".sanad-panel").wait_for(state="visible")


async def _ask(page, question: str) -> None:
    await page.locator(".sanad-input").fill(question)
    await page.locator(".sanad-send").click()


async def _wait_answer(page) -> str:
    await page.locator(".sanad-feedback").wait_for(state="visible", timeout=90_000)
    return await page.locator(".sanad-bot .sanad-content").last.inner_text()


def _has_arabic(text: str) -> bool:
    return any("؀" <= ch <= "ۿ" for ch in text)


async def test_widget_opens_on_blank_page_with_welcome(page, widget_server, blank_site):
    site_dir, site_url, _ = blank_site
    company = await setup_company(widget_server)
    write_blank_page(site_dir, widget_server, company)
    await _open_widget(page, site_url)
    welcome = await page.locator(".sanad-bot .sanad-content").first.inner_text()
    assert "Ask me anything" in welcome
    assert await page.locator(".sanad-input").is_enabled()


async def test_arabic_answer_streams_with_rtl(page, widget_server, blank_site):
    site_dir, site_url, _ = blank_site
    company = await setup_company(widget_server)
    write_blank_page(site_dir, widget_server, company)
    await _open_widget(page, site_url)
    await _ask(page, "كم يوما لدي لطلب استرجاع المبلغ؟")
    await page.locator(".sanad-typing").wait_for(state="visible", timeout=30_000)
    answer = await _wait_answer(page)
    assert _has_arabic(answer), answer
    assert "30" in answer
    direction = await page.evaluate(
        "document.getElementById('sanad-widget-host').shadowRoot.querySelector('.sanad-root').dir"
    )
    assert direction == "rtl"
    messages_dir = await page.evaluate(
        "getComputedStyle(document.getElementById('sanad-widget-host').shadowRoot"
        ".querySelector('.sanad-messages')).direction"
    )
    assert messages_dir == "rtl"
    assert await page.locator(".sanad-chip").count() >= 1


async def test_mobile_panel_is_full_screen(browser, widget_server, blank_site):
    site_dir, site_url, _ = blank_site
    company = await setup_company(widget_server)
    write_blank_page(site_dir, widget_server, company)
    context = await browser.new_context(
        viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
    )
    mobile_page = await context.new_page()
    try:
        await _open_widget(mobile_page, site_url)
        box = await mobile_page.locator(".sanad-panel").bounding_box()
        assert box is not None
        assert abs(box["width"] - 390) <= 1, box
        assert abs(box["height"] - 844) <= 1, box
        assert box["x"] <= 1 and box["y"] <= 1
        await mobile_page.locator(".sanad-fab").wait_for(state="hidden")
        await _ask(mobile_page, "How many days do I have to request a refund?")
        answer = await _wait_answer(mobile_page)
        assert "30" in answer
    finally:
        await context.close()


async def test_citation_chip_opens_source_popover(page, widget_server, blank_site):
    site_dir, site_url, _ = blank_site
    company = await setup_company(widget_server)
    write_blank_page(site_dir, widget_server, company)
    await _open_widget(page, site_url)
    await _ask(page, "How many days do I have to request a refund?")
    await _wait_answer(page)
    chip = page.locator(".sanad-chip").first
    assert "policy-en.md" in await chip.inner_text()
    await chip.click()
    popover = page.locator(".sanad-source")
    await popover.wait_for(state="visible")
    text = await popover.inner_text()
    assert "policy-en.md" in text
    assert "Refund policy" in text
    await chip.click()
    await popover.wait_for(state="detached")


async def test_thumbs_up_stores_feedback(page, widget_server, blank_site):
    site_dir, site_url, _ = blank_site
    company = await setup_company(widget_server)
    write_blank_page(site_dir, widget_server, company)
    await _open_widget(page, site_url)
    await _ask(page, "How many days do I have to request a refund?")
    await _wait_answer(page)
    await page.locator(".sanad-rate").first.click()
    await page.locator(".sanad-rate-note").wait_for(state="visible")
    assert "Thanks" in await page.locator(".sanad-rate-note").inner_text()
    assert await page.locator(".sanad-rate").first.is_disabled()
    dsn = _DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        rows = await conn.fetch(
            "SELECT f.rating FROM feedback f JOIN companies c ON c.id = f.company_id "
            "WHERE c.site_key = $1",
            company["site_key"],
        )
    finally:
        await conn.close()
    assert [r["rating"] for r in rows] == ["up"]


async def test_manual_language_switch_answers_in_french(page, widget_server, blank_site):
    site_dir, site_url, _ = blank_site
    company = await setup_company(widget_server, filename="policy-fr.md", text=POLICY_FR)
    write_blank_page(site_dir, widget_server, company)
    await _open_widget(page, site_url)
    await page.locator(".sanad-lang").select_option("fr")
    assert await page.locator(".sanad-input").get_attribute("placeholder") == "Posez une question…"
    # French document + French question: the small 3B is unreliable when the
    # source, question and answer languages differ, so this test pins the
    # widget's language-switch mechanics on the same-language path.
    await _ask(page, "Combien de jours ai-je pour demander un remboursement ?")
    answer = await _wait_answer(page)
    assert "30" in answer
    assert not _has_arabic(answer)
    assert "jour" in answer.lower() or "remboursement" in answer.lower(), answer
    direction = await page.evaluate(
        "document.getElementById('sanad-widget-host').shadowRoot.querySelector('.sanad-root').dir"
    )
    assert direction == "ltr"


async def test_configurable_welcome_color_logo_and_dark_theme(page, widget_server, blank_site):
    site_dir, site_url, _ = blank_site
    company = await setup_company(widget_server)
    write_blank_page(
        site_dir,
        widget_server,
        company,
        attrs=(
            'data-welcome="Bienvenue chez Acme !" data-color="#ff0000" '
            f'data-logo="{site_url}/logo.png" data-theme="dark"'
        ),
    )
    await _open_widget(page, site_url)
    welcome = await page.locator(".sanad-bot .sanad-content").first.inner_text()
    assert welcome == "Bienvenue chez Acme !"
    fab_color = await page.evaluate(
        "getComputedStyle(document.getElementById('sanad-widget-host').shadowRoot"
        ".querySelector('.sanad-fab')).backgroundColor"
    )
    assert fab_color == "rgb(255, 0, 0)"
    panel_color = await page.evaluate(
        "getComputedStyle(document.getElementById('sanad-widget-host').shadowRoot"
        ".querySelector('.sanad-panel')).backgroundColor"
    )
    assert panel_color == "rgb(31, 41, 55)"
    await page.locator(".sanad-logo").wait_for(state="visible")


async def test_malicious_document_cannot_inject_html(page, widget_server, blank_site):
    site_dir, site_url, _ = blank_site
    company = await setup_company(
        widget_server, filename="xss-policy.md", text=MALICIOUS_DOC
    )
    write_blank_page(site_dir, widget_server, company)
    dialogs = []
    page.on("dialog", lambda dialog: dialogs.append(dialog))
    await _open_widget(page, site_url)
    await _ask(page, "How many days do I have to request a refund?")
    await _wait_answer(page)
    await page.locator(".sanad-chip").first.click()
    popover = page.locator(".sanad-source")
    await popover.wait_for(state="visible")
    # The payload must appear as literal text, never as markup.
    assert XSS_HEADING in await popover.inner_text()
    injected = await page.evaluate(
        "document.getElementById('sanad-widget-host').shadowRoot"
        ".querySelectorAll('.sanad-messages img, .sanad-messages script').length"
    )
    assert injected == 0
    assert await page.evaluate("window.__xss") is None
    assert dialogs == []


async def test_wrong_domain_shows_actionable_error(page, widget_server, blank_site):
    site_dir, _, ip_url = blank_site
    company = await setup_company(widget_server, domains=["localhost"])
    write_blank_page(site_dir, widget_server, company)
    # Browsing via 127.0.0.1 sends Origin host 127.0.0.1, which is not allowed.
    await _open_widget(page, ip_url)
    await _ask(page, "How many days do I have to request a refund?")
    error = page.locator(".sanad-bubble.sanad-error")
    await error.wait_for(state="visible", timeout=30_000)
    text = await error.inner_text()
    assert "not allowed" in text
    assert "PUT /api/v1/companies/domains" in text

async def test_honeypot_field_is_hidden_from_visitors(page, widget_server, blank_site):
    site_dir, site_url, _ = blank_site
    company = await setup_company(widget_server)
    write_blank_page(site_dir, widget_server, company)
    await _open_widget(page, site_url)
    honeypot = page.locator(".sanad-website")
    assert await honeypot.count() == 1
    assert await honeypot.get_attribute("tabindex") == "-1"
    assert await honeypot.get_attribute("aria-hidden") == "true"
    box = await honeypot.bounding_box()
    assert box is not None and box["x"] < -9000  # parked far off-screen


async def test_filled_honeypot_shows_bot_check_error(page, widget_server, blank_site):
    site_dir, site_url, _ = blank_site
    company = await setup_company(widget_server)
    write_blank_page(site_dir, widget_server, company)
    await _open_widget(page, site_url)
    await page.locator(".sanad-website").evaluate(
        "el => { el.value = 'http://spam.example'; }"
    )
    await _ask(page, "How many days do I have to request a refund?")
    error = page.locator(".sanad-bubble.sanad-error")
    await error.wait_for(state="visible", timeout=30_000)
    assert "Bot check failed" in await error.inner_text()


async def _enable_handoff(server: dict, company: dict, email: str) -> None:
    """Give the company an owner and set its handoff destination via the API."""
    owner_email = f"owner-{uuid4().hex[:8]}@handoff.test"
    async with httpx.AsyncClient(
        base_url=server["base"], timeout=60, trust_env=False
    ) as client:
        response = await client.post(
            "/api/v1/companies",
            json={
                "name": "Handoff Co",
                "owner_email": owner_email,
                "owner_password": "owner-password-1",
            },
            headers={"X-Admin-Key": server["admin"]},
        )
        assert response.status_code == 201, response.text
        owned = response.json()
        response = await client.put(
            "/api/v1/companies/domains",
            json={"domains": ["localhost"]},
            headers={"X-API-Key": owned["api_key"]},
        )
        assert response.status_code == 200, response.text
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": owner_email, "password": "owner-password-1"},
        )
        assert login.status_code == 200, login.text
        response = await client.put(
            "/api/v1/dashboard/settings",
            json={"handoff_email": email},
            headers={"X-CSRF-Token": login.json()["csrf_token"]},
        )
        assert response.status_code == 200, response.text
    company.update(owned)


async def test_handoff_form_delivers_email_and_shows_success(
    page, widget_server, blank_site, smtp_sink
):
    site_dir, site_url, _ = blank_site
    company: dict = {}
    await _enable_handoff(widget_server, company, "support@handoff.test")
    write_blank_page(site_dir, widget_server, company)
    await _open_widget(page, site_url)

    button = page.locator(".sanad-handoff")
    assert await button.inner_text() == "Talk to a human"
    await button.click()
    await page.locator(".sanad-handoff-view").wait_for(state="visible")
    assert await page.locator(".sanad-form").is_hidden()
    notice = await page.locator(".sanad-handoff-notice").inner_text()
    assert "shared with this website's team" in notice

    await page.locator(".sanad-handoff-view input[type='email']").fill("visitor@example.com")
    await page.locator(".sanad-handoff-textarea").fill("Please call me back")
    await page.locator(".sanad-handoff-submit").click()
    await page.locator(".sanad-handoff-view").wait_for(state="hidden", timeout=30_000)
    await page.locator(".sanad-form").wait_for(state="visible")
    success = await page.locator(".sanad-bot .sanad-content").last.inner_text()
    assert "request was sent" in success

    deadline = time.monotonic() + 15
    while not smtp_sink.messages and time.monotonic() < deadline:
        await asyncio.sleep(0.2)
    assert smtp_sink.messages, "SMTP sink received no message"
    raw = smtp_sink.messages[-1].decode("utf-8", "replace")
    assert "visitor@example.com" in raw
    assert "Please call me back" in raw
    assert "support@handoff.test" in raw

    dsn = _DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        rows = await conn.fetch(
            "SELECT h.email, h.email_status, h.telegram_status FROM handoff_requests h "
            "JOIN companies c ON c.id = h.company_id WHERE c.site_key = $1",
            company["site_key"],
        )
    finally:
        await conn.close()
    assert len(rows) == 1
    assert rows[0]["email"] == "visitor@example.com"
    assert rows[0]["email_status"] == "SENT"
    assert rows[0]["telegram_status"] == "SKIPPED"


async def test_handoff_form_arabic_labels_and_not_configured_error(
    page, widget_server, blank_site
):
    site_dir, site_url, _ = blank_site
    company = await setup_company(widget_server)  # no handoff destination set
    write_blank_page(site_dir, widget_server, company)
    await _open_widget(page, site_url)
    await page.locator(".sanad-lang").select_option("ar")

    button = page.locator(".sanad-handoff")
    assert await button.inner_text() == "التحدث إلى موظف"
    await button.click()
    await page.locator(".sanad-handoff-view").wait_for(state="visible")
    direction = await page.evaluate(
        "document.getElementById('sanad-widget-host').shadowRoot.querySelector('.sanad-root').dir"
    )
    assert direction == "rtl"
    assert "سيتم مشاركة" in await page.locator(".sanad-handoff-notice").inner_text()

    await page.locator(".sanad-handoff-view input[type='email']").fill("visitor@example.com")
    await page.locator(".sanad-handoff-textarea").fill("أريد التحدث إلى موظف")
    await page.locator(".sanad-handoff-submit").click()
    note = page.locator(".sanad-handoff-note")
    await note.wait_for(state="visible", timeout=30_000)
    assert "Settings" in await note.inner_text()

    await page.locator(".sanad-handoff-back").click()
    await page.locator(".sanad-handoff-view").wait_for(state="hidden")
    await page.locator(".sanad-input").wait_for(state="visible")
