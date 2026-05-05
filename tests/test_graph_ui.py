"""Playwright tests for the React graph viewer UI."""

from pathlib import Path
import socket
import subprocess
import time

import pytest
from playwright.sync_api import sync_playwright


@pytest.fixture(scope="session")
def graph_html_path() -> Path:
    return Path(__file__).parent.parent / "graph" / "graph.html"


@pytest.fixture(scope="session")
def graph_server(graph_html_path: Path):
    repo_root = graph_html_path.parent.parent
    host = "127.0.0.1"
    port = 8765

    # Ensure port is free before starting a server.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex((host, port)) == 0:
            pytest.fail(f"Port {port} is already in use; cannot start test server")

    process = subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--bind", host],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                if sock.connect_ex((host, port)) == 0:
                    break
            time.sleep(0.1)
        else:
            pytest.fail("Timed out waiting for local HTTP server to start")

        yield f"http://{host}:{port}/graph/graph.html"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture(scope="session")
def graph_url(graph_server: str) -> str:
    return graph_server


@pytest.fixture
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def page(browser, graph_url: str):
    page = browser.new_page()
    page.goto(graph_url, wait_until="networkidle")
    page.wait_for_selector("#graph-canvas")
    yield page
    page.close()


def test_page_loads(page):
    assert page.title() == "Dirk Graph UI"
    assert page.query_selector("#graph-canvas") is not None


def test_search_input_present(page):
    search_input = page.query_selector("#search-input")
    assert search_input is not None
    assert search_input.get_attribute("placeholder") == "Repo, concept, technology..."


def test_shortcut_focuses_search(page):
    page.keyboard.press("/")
    focused = page.evaluate("() => document.activeElement?.id")
    assert focused == "search-input"


def test_search_filters_results(page):
    search_input = page.query_selector("#search-input")
    search_input.fill("dirk")
    result_items = page.query_selector_all(".result-item")
    assert len(result_items) >= 1


def test_search_match_counter_changes(page):
    counter_before = page.query_selector(".rail-header span").text_content()
    page.fill("#search-input", "zzzz-no-match")
    counter_after = page.query_selector(".rail-header span").text_content()
    assert counter_before != counter_after


def test_help_toggle_shortcut(page):
    assert page.query_selector("#help-panel") is None
    page.evaluate(
        """() => {
            window.dispatchEvent(new KeyboardEvent('keydown', {
                key: '?',
                code: 'Slash',
                shiftKey: true,
                bubbles: true
            }));
        }"""
    )
    page.wait_for_selector("#help-panel")
    assert page.query_selector("#help-panel") is not None


def test_fit_and_reset_buttons_present(page):
    buttons = page.query_selector_all(".button-row .ghost-button")
    labels = [button.text_content() for button in buttons]
    assert any("Fit" in (label or "") for label in labels)
    assert any("Reset" in (label or "") for label in labels)


def test_escape_clears_search(page):
    page.fill("#search-input", "repo")
    page.keyboard.press("Escape")
    value = page.input_value("#search-input")
    assert value == ""


def test_click_result_updates_details(page):
    first_result = page.query_selector(".result-item")
    assert first_result is not None
    first_result.click()

    detail_heading = page.query_selector(".detail-heading strong")
    assert detail_heading is not None
    assert len(detail_heading.text_content().strip()) > 0


def test_details_show_connection_summary(page):
    first_result = page.query_selector(".result-item")
    first_result.click()

    chips = page.query_selector_all(".summary-chips span")
    assert len(chips) >= 1


def test_legend_visible(page):
    legend_title = page.query_selector(".legend-card h2")
    assert legend_title is not None
    assert "Legend" in legend_title.text_content()
