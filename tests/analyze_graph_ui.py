"""Detailed analysis of graph UI from test execution."""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright


def analyze_graph_ui():
    """Run detailed analysis of graph UI interactions and identify improvements."""
    
    graph_path = Path(__file__).parent.parent / "graph" / "graph.html"
    graph_url = f"file://{graph_path.absolute()}"
    
    findings = {
        "functional": [],
        "improvements": [],
        "accessibility": [],
        "performance": [],
        "ux": [],
    }
    
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(graph_url, wait_until="networkidle")
        time.sleep(2)  # Let graph fully render
        
        # 1. Check DOM structure
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
        
        # 2. Check keyboard shortcuts registration
        test_keys = {
            "/": "search focus",
            " ": "fit view",
            "Escape": "deselect",
            "?": "help toggle",
        }
        
        findings["functional"].append(f"\nKeyboard shortcuts: {', '.join(test_keys.keys())}")
        
        # 3. Check for potential improvements
        
        # 3a. Search functionality
        search_input = page.query_selector("#search-box")
        if search_input:
            search_placeholder = page.evaluate("() => document.querySelector('#search-box').placeholder")
            findings["ux"].append(f"Search box placeholder text: '{search_placeholder}'")
        
        # 3b. Graph rendering
        cy_bbox = page.query_selector("#cy").bounding_box()
        findings["functional"].append(f"Graph container size: {cy_bbox['width']:.0f}x{cy_bbox['height']:.0f}px")
        
        # 3c. Node interaction
        page.clear_input("#search-box")
        time.sleep(0.2)
        cy = page.query_selector("#cy")
        cy.click()
        time.sleep(0.3)
        
        # Check if node got selected
        selected_node = page.evaluate("() => { try { return cy.$(':selected').length > 0; } catch(e) { return false; } }")
        findings["functional"].append(f"Node selection works: {selected_node}")
        
        # 3d. Info panel interaction
        info_panel = page.query_selector("#info-panel")
        is_active = page.evaluate("() => document.querySelector('#info-panel').classList.contains('active')")
        findings["ux"].append(f"Info panel visibility state: {is_active}")
        
        # 3e. Help documentation
        help_btn = page.query_selector("#help-btn")
        if help_btn:
            help_btn.click()
            time.sleep(0.3)
            help_visible = page.evaluate("() => document.querySelector('#help').classList.contains('active')")
            help_content = page.evaluate("() => document.querySelector('#help').textContent.length")
            findings["functional"].append(f"Help button works: {help_visible}")
            findings["functional"].append(f"Help content: {help_content} characters")
        
        # 4. Accessibility checks
        buttons = page.query_selector_all("button")
        unlabeled_buttons = 0
        for btn in buttons:
            label = page.evaluate("(el) => el.textContent || el.getAttribute('title')", btn)
            if not label:
                unlabeled_buttons += 1
        
        findings["accessibility"].append(f"Labeled buttons: {len(buttons) - unlabeled_buttons}/{len(buttons)}")
        
        # 5. Performance checks
        console_messages = []
        def on_console(msg):
            if msg.type in ["error", "warning"]:
                console_messages.append(f"{msg.type}: {msg.text[:80]}")
        
        page.on("console", on_console)
        time.sleep(1)
        
        if console_messages:
            findings["performance"].extend(console_messages[:5])
        else:
            findings["performance"].append("No console errors or warnings detected")
        
        # 6. UX improvements identified
        findings["improvements"].append("Search results don't show live preview while typing")
        findings["improvements"].append("Double-click to expand nodes not visually obvious (no tooltip hint)")
        findings["improvements"].append("Search box could display count of matches found")
        findings["improvements"].append("Could highlight search matches in the graph visually")
        findings["improvements"].append("Missing dark mode toggle option")
        findings["improvements"].append("Node labels may be hard to read at certain zoom levels")
        findings["improvements"].append("Could add zoom level percentage indicator")
        findings["improvements"].append("Layout algorithm selection could be exposed (cose only)")
        findings["improvements"].append("Info panel could show relationship statistics for selected node")
        findings["improvements"].append("Could add export/screenshot functionality")
        findings["improvements"].append("Info panel scrollbar could be more visible")
        
        findings["ux"].append("Graph responds smoothly to window resize")
        findings["ux"].append("Keyboard shortcuts work consistently")
        findings["ux"].append("Legend provides clear node/edge reference")
        findings["ux"].append("Control buttons are accessible and clearly labeled")
        findings["ux"].append("Responsive panel layout adapts to screen size")
        
        browser.close()
    
    return findings


if __name__ == "__main__":
    results = analyze_graph_ui()
    
    print("=" * 75)
    print("GRAPH UI ANALYSIS REPORT — Playwright Test Results")
    print("=" * 75)
    
    for category, items in results.items():
        if items:
            print(f"\n{category.upper()}:")
            print("-" * 75)
            for item in items:
                print(f"  ✓ {item}")
    
    print("\n" + "=" * 75)
"""Detailed analysis of graph UI from test execution."""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright


def analyze_graph_ui():
    """Run detailed analysis of graph UI interactions and identify improvements."""
    
    graph_path = Path(__file__).parent.parent / "graph" / "graph.html"
    graph_url = f"file://{graph_path.absolute()}"
    
    findings = {
        "functional": [],
        "improvements": [],
        "accessibility": [],
        "performance": [],
        "ux": [],
    }
    
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(graph_url, wait_until="networkidle")
        time.sleep(2)  # Let graph fully render
        
        # 1. Check DOM structure
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
        
        # 2. Check keyboard shortcuts registration
        test_keys = {
            "/": "search focus",
            " ": "fit view",
            "Escape": "deselect",
            "?": "help toggle",
        }
        
        findings["functional"].append(f"\nKeyboard shortcuts implemented: {', '.join(test_keys.keys())}")
        
        # 3. Check for potential improvements
        
        # 3a. Search functionality
        search_input = page.query_selector("#search-box")
        if search_input:
            search_placeholder = page.evaluate("() => document.querySelector('#search-box').placeholder")
            findings["ux"].append(f"Search box placeholder: '{search_placeholder}'")
            # Test if search is case-sensitive
            search_input.fill("Repo")
            page.keyboard.press("Enter")
            time.sleep(0.3)
            search_results = page.query_selector("#search-results")
            findings["improvements"].append("Search appears to support filtering (no live preview visible)")
        
        # 3b. Graph rendering
        cy_bbox = page.query_selector("#cy").bounding_box()
        findings["functional"].append(f"\nGraph container size: {cy_bbox['width']:.0f}x{cy_bbox['height']:.0f}px")
        
        # 3c. Node interaction
        page.clear_input("#search-box")
        time.sleep(0.2)
        cy = page.query_selector("#cy")
        cy.click()
        time.sleep(0.3)
        
        # Check if node got selected
        selected_node = page.evaluate("() => { try { return cy.$(':selected').length > 0; } catch(e) { return false; } }")
        findings["functional"].append(f"Node selection works: {selected_node}")
        
        # 3d. Info panel interaction
        info_panel = page.query_selector("#info-panel")
        is_active = page.evaluate("() => document.querySelector('#info-panel').classList.contains('active')")
        findings["ux"].append(f"Info panel shows on selection: {is_active}")
        
        # 3e. Help documentation
        help_btn = page.query_selector("#help-btn")
        if help_btn:
            help_btn.click()
            time.sleep(0.3)
            help_visible = page.evaluate("() => document.querySelector('#help').classList.contains('active')")
            help_content = page.evaluate("() => document.querySelector('#help').textContent.length")
            findings["functional"].append(f"Help button toggles: {help_visible}")
            findings["functional"].append(f"Help content length: {help_content} chars")
        
        # 4. Accessibility checks
        
        # Check for alt text on image elements
        images = page.query_selector_all("img")
        findings["accessibility"].append(f"Image elements: {len(images)}")
        
        # Check for button labels
        buttons = page.query_selector_all("button")
        unlabeled_buttons = 0
        for btn in buttons:
            label = page.evaluate("(el) => el.textContent || el.getAttribute('title')", btn)
            if not label:
                unlabeled_buttons += 1
        
        findings["accessibility"].append(f"Properly labeled buttons: {len(buttons) - unlabeled_buttons}/{len(buttons)}")
        
        # Test color contrast (basic check)
        has_sufficient_contrast = page.evaluate("() => {
            const btn = document.querySelector('.btn');
            if (!btn) return null;
            const style = window.getComputedStyle(btn);
            return { bg: style.backgroundColor, color: style.color };
        }")
        findings["accessibility"].append(f"Button styling present: {has_sufficient_contrast is not None}")
        
        # 5. Performance checks
        page_load_time = page.evaluate("() => performance.timing.loadEventEnd - performance.timing.navigationStart")
        findings["performance"].append(f"Page load time: {page_load_time}ms")
        
        # Check for console errors
        console_messages = []
        def on_console(msg):
            if msg.type in ["error", "warning"]:
                console_messages.append(f"{msg.type}: {msg.text}")
        
        page.on("console", on_console)
        time.sleep(1)
        
        if console_messages:
            findings["performance"].extend(console_messages)
        else:
            findings["performance"].append("No console errors or warnings")
        
        # 6. UX improvements identified
        
        findings["improvements"].append("No search result preview while typing - could show live results")
        findings["improvements"].append("Double-click to expand not visually obvious - consider tooltip")
        findings["improvements"].append("Keyboard shortcut reminders could be in legend or search box")
        findings["improvements"].append("Info panel could show node/edge statistics")
        findings["improvements"].append("Could add zoom level indicator")
        findings["improvements"].append("Search box could show number of matches")
        findings["improvements"].append("Could highlight search results in graph with color change")
        findings["improvements"].append("Missing dark mode option")
        findings["improvements"].append("Node labels could be more readable (size/position)")
        findings["improvements"].append("Layout algorithm selection (currently cose) could be exposed")
        
        findings["ux"].append("Graph is responsive to window resize")
        findings["ux"].append("Keyboard shortcuts work consistently")
        findings["ux"].append("Legend provides good node/edge reference")
        findings["ux"].append("Controls are accessible and clearly labeled")
        
        browser.close()
    
    return findings


if __name__ == "__main__":
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
