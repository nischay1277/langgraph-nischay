"""Optional real-browser smoke check. Requires Playwright and installed Chrome."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path=os.getenv(
                "ATLAS_CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe"
            ),
        )
        page = browser.new_page(
            viewport={"width": 1440, "height": 1080}, device_scale_factor=1
        )
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8765", wait_until="networkidle")
        expect(page.locator("#service")).to_have_value("atlas-api")
        expect(page.locator("#version")).to_have_value("2.4")
        with page.expect_response("**/api/run") as response:
            page.locator("#run-button").click()
        assert response.value.status == 200
        expect(page.locator("#claims .claim")).to_have_count(1)
        expect(page.locator("#trace [data-stage=recover]")).to_have_count(1)
        expect(page.locator("#result-status")).to_have_text("Sources cited")
        expect(page.locator("#toast")).to_be_hidden(timeout=10000)
        page.screenshot(path=str(OUT / "console-desktop.png"), full_page=True)
        page.locator("#recovery").uncheck()
        with page.expect_response("**/api/run"):
            page.locator("#run-button").click()
        expect(page.locator("#result-status")).to_have_text("Abstained")
        page.locator('[data-page="history"]').click()
        expect(page.locator("#history-rows tr").first).to_be_visible()
        page.locator('[data-page="corpus"]').click()
        expect(page.locator("#document-list .document-card")).to_have_count(7)
        expect(page.locator("#toast")).to_be_hidden(timeout=10000)
        page.screenshot(path=str(OUT / "library-desktop.png"), full_page=True)
        page.locator('[data-page="evaluation"]').click()
        with page.expect_response("**/api/evaluate") as response:
            page.locator("#evaluate-button").click()
        assert response.value.status == 200
        expect(page.locator("#eval-cases tr")).to_have_count(14)
        expect(page.locator("#toast")).to_be_hidden(timeout=10000)
        page.screenshot(path=str(OUT / "evaluation-desktop.png"), full_page=True)
        page.locator('[data-page="console"]').click()
        page.locator("#recovery").check()
        with page.expect_response("**/api/run"):
            page.locator("#run-button").click()
        expect(page.locator("#result-status")).to_have_text("Sources cited")
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.locator("#toast")).to_be_hidden(timeout=10000)
        page.screenshot(path=str(OUT / "console-mobile.png"), full_page=True)
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        ), "Horizontal overflow on mobile"
        assert not errors, errors
        print(
            json.dumps(
                {"ui": "passed", "javascript_errors": errors, "screenshots": str(OUT)}
            )
        )
        browser.close()


if __name__ == "__main__":
    main()
