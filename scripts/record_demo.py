"""Record the demo GIFs for the README — real stack, real answers.

Starts a private uvicorn + static site, creates a demo company, uploads the
trilingual samples, then drives real Chromium with Playwright: the widget
answers in English, French and Arabic (with citations, RTL and a thumbs-up),
then shows the contextual "Talk to a human" offer on a related-but-not-covered
question, and the dashboard tours its tabs. Screenshots are assembled into GIFs
with Pillow. Nothing is uploaded anywhere; output lands in docs/.

Run (from backend/, with the live stack available):
    HF_HOME=F:/sanad/models/hf PLAYWRIGHT_BROWSERS_PATH=F:/sanad/models/playwright \
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe ../scripts/record_demo.py

Needs: Ollama with the tier model, BGE-M3 weights, PostgreSQL + pgvector,
pip install -e ".[dev,embeddings,browser,ocr]" (Pillow comes with ocr).
"""

import io
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DOCS = ROOT / "docs"
DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://sanad:sanad@localhost:5432/sanad"
)
ADMIN_KEY = "demo-record-admin"
PASSWORD = "demo-password-1"

QUESTIONS = [
    ("en", "How many days do I have to request a refund?"),
    ("fr", "Combien de jours ai-je pour demander un remboursement ?"),
    ("ar", "كم يوما لدي لطلب استرجاع المبلغ؟"),
]

# A company-related question the demo policies do not cover, used to showcase
# the contextual handoff offer. The English gift-wrapping case is golden-proven
# to refuse as not_covered (the Arabic equivalent is the small tier's one known
# miss), so the inline "Talk to a human" button reliably appears.
NOT_COVERED_QUESTION = "Do you offer gift wrapping for orders?"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_api(tmp: Path) -> tuple[subprocess.Popen, str]:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ)
    env.update(
        {
            "ADMIN_API_KEY": ADMIN_KEY,
            "DATABASE_URL": DATABASE_URL,
            "DATA_DIR": str(tmp / "data"),
            "PYTHONIOENCODING": "utf-8",
            "RATE_LIMIT_PER_IP": "0",
            "RATE_LIMIT_PER_SITE": "0",
            "DAILY_CAP_PER_COMPANY": "0",
            "LOGIN_RATE_LIMIT_PER_MINUTE": "0",
            "BOT_CHECK_MIN_SECONDS": "0",
            "CRAWL_RESYNC_HOURS": "0",
        }
    )
    log = open(tmp / "uvicorn.log", "w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port)],
        cwd=str(BACKEND), env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"API died; log: {(tmp / 'uvicorn.log').read_text()[-2000:]}")
        try:
            if httpx.get(f"{base}/health", timeout=2, trust_env=False).status_code == 200:
                return process, base
        except (httpx.HTTPError, OSError):
            pass
        time.sleep(0.5)
    process.kill()
    raise RuntimeError("API did not start within 120s")


def make_company(base: str) -> dict:
    with httpx.Client(base_url=base, timeout=300, trust_env=False) as client:
        email = f"demo-{uuid4().hex[:8]}@sanad.example"
        response = client.post(
            "/api/v1/companies",
            json={"name": "Sanad Demo", "owner_email": email, "owner_password": PASSWORD},
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        response.raise_for_status()
        company = response.json()
        company["owner_email"] = email
        secret = {"X-API-Key": company["api_key"]}
        client.put(
            "/api/v1/companies/domains", json={"domains": ["localhost"]}, headers=secret
        ).raise_for_status()
        for path in sorted((ROOT / "samples").glob("*")):
            if path.is_file():
                client.post(
                    "/api/v1/documents",
                    files={"file": (path.name, path.read_bytes())},
                    headers=secret,
                ).raise_for_status()
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            listing = client.get("/api/v1/documents", headers=secret).json()
            if listing and all(d["status"] == "ready" for d in listing):
                return company
            if any(d["status"] == "failed" for d in listing):
                raise RuntimeError(f"ingestion failed: {listing}")
            time.sleep(1)
    raise RuntimeError("ingestion timed out")


def save_gif(frames: list[tuple[Image.Image, int]], path: Path, width: int) -> None:
    scaled = []
    for image, duration in frames:
        if image.width > width:
            image = image.resize(
                (width, round(image.height * width / image.width)), Image.LANCZOS
            )
        scaled.append((image.convert("P", palette=Image.ADAPTIVE), duration))
    scaled[0][0].save(
        path,
        save_all=True,
        append_images=[img for img, _ in scaled[1:]],
        duration=[d for _, d in scaled],
        loop=0,
        optimize=True,
    )
    print(f"{path.name}: {len(frames)} frames, {path.stat().st_size / 1e6:.2f} MB")


def shoot(page, frames: list, duration: int) -> None:
    frames.append((Image.open(io.BytesIO(page.screenshot())), duration))


def record_widget(page, site_url: str, frames: list) -> None:
    page.goto(f"{site_url}/index.html")
    page.locator(".sanad-fab").click()
    page.locator(".sanad-panel").wait_for(state="visible")
    page.wait_for_timeout(600)
    shoot(page, frames, 2000)
    for index, (_, question) in enumerate(QUESTIONS):
        page.locator(".sanad-input").fill(question)
        shoot(page, frames, 900)
        page.locator(".sanad-send").click()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if page.locator(".sanad-feedback").count() >= index + 1:
                break
            page.wait_for_timeout(700)
            shoot(page, frames, 700)
        page.locator(".sanad-feedback").nth(index).wait_for(state="visible", timeout=90_000)
        shoot(page, frames, 2600)
        if index == 0:
            page.locator(".sanad-chip").first.click()
            page.locator(".sanad-source").wait_for(state="visible")
            shoot(page, frames, 2200)
            page.locator(".sanad-chip").first.click()
            page.locator(".sanad-rate").first.click()
            page.locator(".sanad-rate-note").wait_for(state="visible")
            shoot(page, frames, 1800)

    # Contextual handoff offer: a related-but-not-covered question gets the
    # "couldn't find" refusal plus an inline "Talk to a human" button that opens
    # the form with the question prefilled. The visitor must still press Send —
    # no ticket is ever submitted automatically.
    page.locator(".sanad-input").fill(NOT_COVERED_QUESTION)
    shoot(page, frames, 900)
    page.locator(".sanad-send").click()
    page.locator(".sanad-handoff-offer").wait_for(state="visible", timeout=90_000)
    shoot(page, frames, 2600)
    page.locator(".sanad-handoff-offer").click()
    page.locator(".sanad-handoff-view").wait_for(state="visible")
    page.wait_for_timeout(400)
    shoot(page, frames, 2400)
    page.locator(".sanad-handoff-back").click()
    page.locator(".sanad-handoff-view").wait_for(state="hidden")


def record_dashboard(page, base: str, company: dict, frames: list) -> None:
    page.goto(f"{base}/dashboard/")
    page.locator("#login-email").fill(company["owner_email"])
    page.locator("#login-password").fill(PASSWORD)
    shoot(page, frames, 1400)
    page.locator("button[type=submit]").click()
    page.locator("header.top").wait_for(state="visible", timeout=15_000)
    page.locator(".badge.ready").first.wait_for(state="visible", timeout=30_000)
    shoot(page, frames, 2400)
    for tab, wait in [
        ("Evaluation", ".panel"),
        ("Handoffs", ".panel"),
        ("Settings", "#widget-snippet"),
    ]:
        page.get_by_role("button", name=tab, exact=True).click()
        page.locator(wait).first.wait_for(state="visible")
        page.wait_for_timeout(500)
        shoot(page, frames, 2400)
    page.get_by_label("Language").select_option("ar")
    page.wait_for_timeout(600)
    shoot(page, frames, 2600)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="sanad-demo-") as tmp_name:
        tmp = Path(tmp_name)
        process, base = start_api(tmp)
        site_dir = tmp / "site"
        site_dir.mkdir()
        handler = partial(SimpleHTTPRequestHandler, directory=str(site_dir))
        site = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=site.serve_forever, daemon=True).start()
        site_url = f"http://localhost:{site.server_address[1]}"
        try:
            company = make_company(base)
            print(f"demo company ready: {company['owner_email']}")
            (site_dir / "index.html").write_text(
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                "<title>Sanad demo</title></head><body>"
                f"<script src='{base}/widget.js' data-site-key='{company['site_key']}' "
                f"data-api-url='{base}' defer></script></body></html>",
                encoding="utf-8",
            )
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                widget_context = browser.new_context(viewport={"width": 460, "height": 760})
                widget_page = widget_context.new_page()
                widget_frames: list = []
                record_widget(widget_page, site_url, widget_frames)
                widget_context.close()
                dash_context = browser.new_context(viewport={"width": 1280, "height": 800})
                dash_page = dash_context.new_page()
                dash_frames: list = []
                record_dashboard(dash_page, base, company, dash_frames)
                dash_context.close()
                browser.close()
            DOCS.mkdir(exist_ok=True)
            save_gif(widget_frames, DOCS / "demo-widget.gif", 460)
            save_gif(dash_frames, DOCS / "demo-dashboard.gif", 960)
        finally:
            site.shutdown()
            site.server_close()
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()