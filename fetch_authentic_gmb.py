import asyncio, json
from playwright.async_api import async_playwright

async def get_all():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        # Direct URL to reviews tab of RAIS Agencies
        url = "https://www.google.com/maps/place/RAIS+Agencies/@14.059359,78.759402,17z/data=!4m8!3m7!1s0x3bb30318ccf76259:0x47c3e259f30654fa!8m2!3d14.059359!4d78.759402!9m1!1b1!16s%2Fg%2F11npc8m4rr"
        print("Opening:", url)
        await page.goto(url, timeout=45000)
        await page.wait_for_timeout(4000)

        # Expand all "More" buttons
        more_buttons = await page.query_selector_all('button.w8nwRe')
        for mb in more_buttons:
            try:
                await mb.click()
            except Exception:
                pass
        await page.wait_for_timeout(1000)

        # Query all review cards
        cards = await page.query_selector_all('div.jftiEf')
        print("Found review cards:", len(cards))
        reviews = []
        for c in cards:
            author_el = await c.query_selector('div.d4r55')
            author = (await author_el.inner_text()).strip() if author_el else ""
            rating_el = await c.query_selector('span.kvMYJc')
            rating = (await rating_el.get_attribute('aria-label')).strip() if rating_el else ""
            text_el = await c.query_selector('span.wiI7pd')
            text = (await text_el.inner_text()).strip() if text_el else ""
            time_el = await c.query_selector('span.rsqaWe')
            time_str = (await time_el.inner_text()).strip() if time_el else ""

            if author:
                reviews.append({
                    "author": author,
                    "rating": rating,
                    "text": text,
                    "date": time_str
                })

        with open("rais_authentic_reviews.json", "w", encoding="utf-8") as f:
            json.dump(reviews, f, indent=2, ensure_ascii=False)
        print("Done! Dumped", len(reviews), "reviews to rais_authentic_reviews.json")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(get_all())
