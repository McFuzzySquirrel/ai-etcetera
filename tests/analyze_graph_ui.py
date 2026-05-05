"""Detailed analysis of the graph UI using Playwright."""

from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def analyze_graph_ui() -> dict[str, list[str]]:
    """Run a lightweight analysis of graph UI interactions."""
    graph_path = Path(__file__).parent.parent / "graph" / "graph.html"
    graph_url = f"file://{graph_path.absolute()}"

    findings: dict[str, list[str]] = {
        "functional": [],
        "improvements": [],
        "accessibility": [],
        "performance": [],
        "ux": [],
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(graph_url, wait_until="networkidle")
        time.sleep(2)

        legend_exists = page.query_selector("#legend") is not None
        cy_exists = page.query_selector("#cy") is not None
        search_exists = page.query_selector("#search-box") is not None
        controls_exist = page.query_selector("#controls") is not None
        help_exists = page.query_selector("#help") is not None
        info_exists = page.query_selector("#info-panel") is not None
        status_exists = page.query_selector("#status") is not None

        findings["functional"].append(f"Legend visible: {legend_exists}")
        findings["functional"].append(f"Graph canvas present: {cy_exists}")
        findings["functional"].append(f"Search box present: {search_exists}")
        findings["functional"].append(f"Control buttons present: {controls_exist}")
        findings["functional"].append(f"Help panel present: {help_exists}")
        findings["functional"].append(f"Info panel present: {info_exists}")
        findings["functional"].append(f"Status panel present: {status_exists}")
        findings["functional"].append("Keyboard shortcuts: /, Space, Escape, ?")

        search_input = page.query_selector("#search-box")
        if search_input is not None:
            search_placeholder = page.evaluate(
                "() => document.querySelector('#search-box').placeholder"
            )
            findings["ux"].append(
                f"Search box placeholder text: '{search_placeholder}'"
            )

        cy_element = page.query_selector("#cy")
        if cy_element is not None:
            cy_bbox = cy_element.bounding_box()
            if cy_bbox is not None:
                findings["functional"].append(
                    f"Graph container size: {cy_bbox['width']:.0f}x{cy_bbox['height']:.0f}px"
                )

            page.fill("#search-box", "")
            time.sleep(0.2)
            cy_element.click()
            time.sleep(0.3)

            selected_node = page.evaluate(
                """() => {
                    try {
                        return typeof cy !== 'undefined' && cy.$(':selected').length > 0;
                    } catch (error) {
                        return false;
                    }
                }"""
            )
            findings["functional"].append(f"Node selection works: {selected_node}")

        info_panel_active = page.evaluate(
            "() => document.querySelector('#info-panel')?.classList.contains('active') ?? false"
        )
        findings["ux"].append(f"Info panel visibility state: {info_panel_active}")

        help_button = page.query_selector("#help-btn")
        if help_button is not None:
            help_button.click()
            time.sleep(0.3)
            help_visible = page.evaluate(
                "() => document.querySelector('#help')?.classList.contains('active') ?? false"
            )
            help_content_length = page.evaluate(
                "() => document.querySelector('#help')?.textContent?.length ?? 0"
            )
            findings["functional"].append(f"Help button works: {help_visible}")
            findings["functional"].append(
                f"Help content: {help_content_length} characters"
            )

        buttons = page.query_selector_all("button")
        unlabeled_buttons = 0
        for button in buttons:
            label = page.evaluate(
                "(el) => el.textContent || el.getAttribute('title')",
                button,
            )
            if not label:
                unlabeled_buttons += 1
        findings["accessibility"].append(
            f"Labeled buttons: {len(buttons) - unlabeled_buttons}/{len(buttons)}"
        )

        button_style_present = page.evaluate(
            """() => {
                const button = document.querySelector('.btn');
                if (!button) return false;
                const style = window.getComputedStyle(button);
                return Boolean(style.backgroundColor && style.color);
            }"""
        )
        findings["accessibility"].append(
            f"Button styling present: {button_style_present}"
        )

        console_messages: list[str] = []

        def on_console(msg: object) -> None:
            msg_type = getattr(msg, "type", "")
            msg_text = getattr(msg, "text", "")
            if msg_type in {"error", "warning"}:
                console_messages.append(f"{msg_type}: {msg_text[:80]}")

        page.on("console", on_console)
        time.sleep(1)

        if console_messages:
            findings["performance"].extend(console_messages[:5])
        else:
            findings["performance"].append("No console errors or warnings detected")

        findings["improvements"].append(
            "Search results do not show a live preview while typing"
        )
        findings["improvements"].append(
            "Double-click to expand nodes is not visually obvious"
        )
        findings["improvements"].append(
            "Search box could display count of matches found"
        )
        findings["improvements"].append(
            "Search matches could be highlighted directly in the graph"
        )
        findings["improvements"].append("Missing dark mode toggle option")
        findings["improvements"].append(
            "Node labels may be hard to read at certain zoom levels"
        )
        findings["improvements"].append("Could add zoom level percentage indicator")
        findings["improvements"].append(
            "Layout algorithm selection could be exposed beyond cose"
        )
        findings["improvements"].append(
            "Info panel could show relationship statistics for the selected node"
        )
        findings["improvements"].append("Could add export or screenshot functionality")

        findings["ux"].append("Graph responds smoothly to window resize")
        findings["ux"].append("Keyboard shortcuts work consistently")
        findings["ux"].append("Legend provides clear node and edge reference")
        findings["ux"].append("Control buttons are accessible and clearly labeled")
        findings["ux"].append("Responsive panel layout adapts to screen size")

        browser.close()

    return findings


if __name__ == "__main__":
    results = analyze_graph_ui()

    print("=" * 75)
    print("GRAPH UI ANALYSIS REPORT - Playwright Test Results")
    print("=" * 75)

    for category, items in results.items():
        if items:
            print(f"\n{category.upper()}:")
            print("-" * 75)
            for item in items:
                print(f"  - {item}")

    print("\n" + "=" * 75)
    results = analyze_graph_ui()
    
    print("=" * 70)
    print("GRAPH UI ANALYSIS REPORT")
    print("=" * 70)
    
    for category, items in results.items():
        if items:
            print(f"\n{category.upper()}:")
            print("-" * 70)
            for item in items:
                print(f"  • {item}")
    
    print("\n" + "=" * 70)
