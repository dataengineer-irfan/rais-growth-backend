import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        url = "https://www.google.com/maps/place/RAIS+Agencies/@14.059359,78.759402,17z/data=!3m1!4b1!4m6!3m5!1s0x3bb30318ccf76259:0x47c3e259f30654fa!8m2!3d14.059359!4d78.759402!16s%2Fg%2F11npc8m4rr"
        print("Navigating to:", url)
        await page.goto(url, timeout=45000)
        await page.wait_for_timeout(4000)

        # Look for buttons that say Reviews
        buttons = await page.query_selector_all("button")
        for btn in buttons:
            txt = (await btn.inner_text()).strip()
            if "Reviews" in txt or "reviews" in txt:
                print("Clicking review button:", txt)
                await btn.click()
                await page.wait_for_timeout(4000)
                break

        await page.screenshot(path="rais_gmb_maps_screen.png", full_page=False)
        print("Screenshot saved to rais_gmb_maps_screen.png")

        # Extract review containers
        # Common Google Maps review container classes: .jJc9Ad, div[data-review-id]
        reviews_data = []
        review_nodes = await page.query_selector_all("div[data-review-id]")
        print("Found data-review-id elements:", len(review_nodes))

        if not review_nodes:
            # Fallback to searching all text
            body_text = await page.inner_text("body")
            with open("maps_body_text.txt", "w", encoding="utf-8") as f:
                f.write(body_text)
            print("Wrote body text to maps_body_text.txt")
        else:
            for node in review_nodes:
                author_el = await node.query_selector(".d4r55")
                author = (await author_el.inner_text()).strip() if author_el else "Unknown"
                rating_el = await node.query_selector(".kvMYJc")
                rating_label = await rating_el.get_attribute("aria-label") if rating_el else ""
                text_el = await node.query_selector(".wiI7pd")
                text = (await text_el.inner_text()).strip() if text_el else ""
                time_el = await node.query_selector(".rsqaWe")
                date_str = (await time_el.inner_text()).strip() if time_el else ""
                reviews_data.append({
                    "author": author,
                    "rating": rating_label,
                    "comment": text,
                    "date": date_str
                })
            print("Extracted reviews:", reviews_data)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
