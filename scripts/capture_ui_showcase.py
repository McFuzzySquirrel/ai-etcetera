"""Capture a UI showcase for the React graph app using Playwright.

The script serves frontend/dist locally, drives a few key interactions,
and writes screenshots to frontend/showcase.
"""

from __future__ import annotations

import argparse
import base64
import http.server
import socket
import socketserver
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = REPO_ROOT / "frontend" / "dist"
SHOWCASE_DIR = REPO_ROOT / "frontend" / "showcase"
DEFAULT_HERO_FILES = [
    "01-overview.png",
    "03-selection-story.png",
    "06-legend-multiselect.png",
    "08-mobile-overview.png",
]
CAPTION_BY_FILE = {
    "01-overview.png": "Overview dashboard",
    "02-search-results.png": "Search rail and live results",
    "03-selection-story.png": "Selection details with story summary",
    "04-origin-filter.png": "Origin relation filter",
    "05-llm-compose-filter.png": "Composition filter (LLM reviewed)",
    "06-legend-multiselect.png": "Legend multi-select spotlight",
    "07-desktop-dark.png": "Desktop dark color-scheme snapshot",
    "08-mobile-overview.png": "Mobile overview",
    "09-mobile-search.png": "Mobile search rail",
    "10-mobile-dark.png": "Mobile dark color-scheme snapshot",
}


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        # Keep showcase output clean.
        return


@contextmanager
def run_static_server(directory: Path, host: str = "127.0.0.1", port: int = 4174):
    class _ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True

    handler = lambda *args, **kwargs: _QuietHandler(*args, directory=str(directory), **kwargs)
    server = _ThreadedTCPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    deadline = time.time() + 5
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex((host, port)) == 0:
                break
        time.sleep(0.05)

    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def shot(page: Page, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path), full_page=True)


def click_if_visible(page: Page, selector: str) -> None:
    elem = page.locator(selector)
    if elem.count() > 0 and elem.first.is_visible():
        elem.first.click()


def apply_theme(page: Page, theme: str) -> None:
    if theme == "dark":
        page.emulate_media(color_scheme="dark")
        page.add_init_script("window.localStorage.setItem('dirk-ui-theme', 'dark');")
    elif theme == "light":
        page.emulate_media(color_scheme="light")
        page.add_init_script("window.localStorage.setItem('dirk-ui-theme', 'light');")


def capture_showcase(base_url: str, theme: str = "both") -> list[Path]:
    SHOWCASE_DIR.mkdir(parents=True, exist_ok=True)

    screenshots: list[Path] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # Desktop interaction sequence.
        page = browser.new_page(viewport={"width": 1600, "height": 980})
        if theme in {"dark", "light"}:
            apply_theme(page, theme)

        page.goto(base_url, wait_until="networkidle")
        page.wait_for_selector("#graph-canvas")
        time.sleep(1)

        path = SHOWCASE_DIR / "01-overview.png"
        shot(page, path)
        screenshots.append(path)

        page.fill("#search-input", "repo")
        time.sleep(0.4)
        path = SHOWCASE_DIR / "02-search-results.png"
        shot(page, path)
        screenshots.append(path)

        click_if_visible(page, ".result-item")
        time.sleep(0.5)
        click_if_visible(page, "button:has-text('Explain this neighborhood')")
        time.sleep(0.2)
        path = SHOWCASE_DIR / "03-selection-story.png"
        shot(page, path)
        screenshots.append(path)

        click_if_visible(page, "button:has-text('Origin only')")
        time.sleep(0.35)
        path = SHOWCASE_DIR / "04-origin-filter.png"
        shot(page, path)
        screenshots.append(path)

        click_if_visible(page, "button:has-text('LLM reviewed only')")
        time.sleep(0.35)
        path = SHOWCASE_DIR / "05-llm-compose-filter.png"
        shot(page, path)
        screenshots.append(path)

        click_if_visible(page, ".legend-button:has-text('Repo')")
        click_if_visible(page, ".legend-button:has-text('Concept')")
        time.sleep(0.45)
        path = SHOWCASE_DIR / "06-legend-multiselect.png"
        shot(page, path)
        screenshots.append(path)

        page.close()

        if theme == "both":
            # Dedicated desktop dark snapshot.
            page_dark = browser.new_page(viewport={"width": 1600, "height": 980})
            apply_theme(page_dark, "dark")
            page_dark.goto(base_url, wait_until="networkidle")
            page_dark.wait_for_selector("#graph-canvas")
            time.sleep(0.8)
            path = SHOWCASE_DIR / "07-desktop-dark.png"
            shot(page_dark, path)
            screenshots.append(path)
            page_dark.close()

        # Mobile interaction sequence.
        page_mobile = browser.new_page(
            viewport={"width": 430, "height": 932},
            is_mobile=True,
            has_touch=True,
        )
        if theme in {"dark", "light"}:
            apply_theme(page_mobile, theme)
        page_mobile.goto(base_url, wait_until="networkidle")
        page_mobile.wait_for_selector("#graph-canvas")
        time.sleep(0.8)
        path = SHOWCASE_DIR / "08-mobile-overview.png"
        shot(page_mobile, path)
        screenshots.append(path)

        page_mobile.fill("#search-input", "repo")
        time.sleep(0.35)
        path = SHOWCASE_DIR / "09-mobile-search.png"
        shot(page_mobile, path)
        screenshots.append(path)
        page_mobile.close()

        if theme == "both":
            # Dedicated mobile dark snapshot.
            page_mobile_dark = browser.new_page(
                viewport={"width": 430, "height": 932},
                is_mobile=True,
                has_touch=True,
            )
            apply_theme(page_mobile_dark, "dark")
            page_mobile_dark.goto(base_url, wait_until="networkidle")
            page_mobile_dark.wait_for_selector("#graph-canvas")
            time.sleep(0.8)
            path = SHOWCASE_DIR / "10-mobile-dark.png"
            shot(page_mobile_dark, path)
            screenshots.append(path)
            page_mobile_dark.close()

        browser.close()

    return screenshots


def write_showcase_md(screenshots: list[Path], theme: str) -> Path:
    out_path = REPO_ROOT / "UI_SHOWCASE.md"
    rel = lambda p: p.relative_to(REPO_ROOT).as_posix()

    lines: list[str] = []
    lines.append("# UI Showcase")
    lines.append("")
    lines.append("Generated with Playwright from the built React graph UI.")
    if theme in {"dark", "light"}:
        lines.append("")
        lines.append(f"Theme: `{theme}` only.")
    lines.append("")
    lines.append("## Scenes")
    lines.append("")

    for idx, image_path in enumerate(screenshots, start=1):
        caption = CAPTION_BY_FILE.get(image_path.name, image_path.name)
        lines.append(f"### {idx}. {caption}")
        lines.append("")
        lines.append(f"![{caption}]({rel(image_path)})")
        lines.append("")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def write_hero_showcase_md(hero_files: list[str], theme: str) -> Path:
    out_path = REPO_ROOT / "UI_SHOWCASE_HERO.md"
    lines: list[str] = []
    lines.append("# UI Showcase Hero Set")
    lines.append("")
    lines.append("A presentation-focused subset of the strongest screenshots.")
    if theme in {"dark", "light"}:
        lines.append("")
        lines.append(f"Theme: `{theme}` only.")
    lines.append("")
    lines.append("## Hero Shots")
    lines.append("")

    default_captions = {
        "01-overview.png": "Overview dashboard",
        "03-selection-story.png": "Selection story narrative",
        "06-legend-multiselect.png": "Legend multi-select spotlight",
        "08-mobile-overview.png": "Mobile overview",
    }

    for idx, name in enumerate(hero_files, start=1):
        caption = default_captions.get(name, name)
        lines.append(f"### {idx}. {caption}")
        lines.append("")
        lines.append(f"![{caption}](frontend/showcase/{name})")
        lines.append("")

    lines.append("## Contact Sheet")
    lines.append("")
    lines.append("![UI Contact Sheet](frontend/showcase/contact-sheet.png)")
    lines.append("")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def create_contact_sheet_png(hero_files: list[str]) -> Path:
        out_path = SHOWCASE_DIR / "contact-sheet.png"
        cards: list[str] = []

        for index, name in enumerate(hero_files, start=1):
                image_path = SHOWCASE_DIR / name
                if not image_path.exists():
                        continue
                encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
                cards.append(
                        """
                        <figure class=\"card\">
                            <img src=\"data:image/png;base64,{encoded}\" alt=\"Hero {index}\" />
                            <figcaption>{index}. {name}</figcaption>
                        </figure>
                        """.strip().format(encoded=encoded, index=index, name=name)
                )

        html = f"""
        <!doctype html>
        <html>
            <head>
                <meta charset=\"utf-8\" />
                <style>
                    body {{
                        margin: 0;
                        font-family: "Segoe UI", Arial, sans-serif;
                        background: linear-gradient(135deg, #eef3fb 0%, #dde8f9 100%);
                        color: #1d2c42;
                    }}
                    .wrap {{
                        padding: 28px;
                    }}
                    h1 {{
                        margin: 0 0 10px;
                        font-size: 28px;
                    }}
                    p {{
                        margin: 0 0 18px;
                        color: #4b607b;
                    }}
                    .grid {{
                        display: grid;
                        grid-template-columns: 1fr 1fr;
                        gap: 14px;
                    }}
                    .card {{
                        margin: 0;
                        background: #fff;
                        border: 1px solid rgba(24, 33, 47, 0.12);
                        border-radius: 12px;
                        overflow: hidden;
                        box-shadow: 0 12px 32px rgba(35, 57, 84, 0.15);
                    }}
                    img {{
                        display: block;
                        width: 100%;
                        height: 280px;
                        object-fit: cover;
                    }}
                    figcaption {{
                        padding: 10px 12px;
                        font-size: 14px;
                        color: #405776;
                    }}
                </style>
            </head>
            <body>
                <div class=\"wrap\">
                    <h1>Dirk Graph UI - Contact Sheet</h1>
                    <p>Presentation-ready hero screenshots generated by Playwright.</p>
                    <section class=\"grid\">{''.join(cards)}</section>
                </div>
            </body>
        </html>
        """

        with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": 1680, "height": 980})
                page.set_content(html, wait_until="load")
                page.screenshot(path=str(out_path), full_page=True)
                browser.close()

        return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture UI showcase screenshots with Playwright")
    parser.add_argument(
        "--url",
        help="Use an existing URL instead of serving frontend/dist",
        default="",
    )
    parser.add_argument(
        "--hero",
        help=(
            "Comma-separated hero screenshot names from frontend/showcase "
            "(example: 01-overview.png,06-legend-multiselect.png)"
        ),
        default="",
    )
    parser.add_argument(
        "--theme",
        choices=["both", "light", "dark"],
        default="both",
        help="Capture screenshots in one theme only, or both variants.",
    )
    args = parser.parse_args()

    hero_files = DEFAULT_HERO_FILES
    if args.hero.strip():
        hero_files = [item.strip() for item in args.hero.split(",") if item.strip()]

    if not args.url and not DIST_DIR.exists():
        raise SystemExit(
            "frontend/dist does not exist. Run 'npm run build' in frontend first, "
            "or pass --url to an already running app."
        )

    if args.url:
        shots = capture_showcase(args.url, theme=args.theme)
    else:
        with run_static_server(DIST_DIR) as base_url:
            shots = capture_showcase(base_url, theme=args.theme)

    out_md = write_showcase_md(shots, args.theme)
    hero_md = write_hero_showcase_md(hero_files, args.theme)
    contact_sheet = create_contact_sheet_png(hero_files)
    print(f"Captured {len(shots)} screenshots")
    print(f"Showcase markdown: {out_md}")
    print(f"Hero showcase markdown: {hero_md}")
    print(f"Contact sheet: {contact_sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
