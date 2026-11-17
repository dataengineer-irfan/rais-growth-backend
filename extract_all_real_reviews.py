from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://www.google.com/maps/place/RAIS+Agencies/@14.059359,78.759402,17z/data=!3m1!4b1!4m6!3m5!1s0x3bb30318ccf76259:0x47c3e259f30654fa!8m2!3d14.059359!4d78.759402!16s%2Fg%2F11npc8m4rr")
    page.wait_for_timeout(3000)
    
    # Click reviews tab
    reviews_btn = page.locator('button:has-text("Reviews")').first
    if reviews_btn.count() > 0:
        reviews_btn.click()
        page.wait_for_timeout(3000)
        
    # Scroll review list to load all
    scrollable = page.locator('div[role="main"]')
    for _ in range(5):
        page.mouse.wheel(0, 1000)
        page.wait_for_timeout(1000)
        
    items = page.locator('div[data-review-id]')
    count = items.count()
    print("Total review elements after scroll:", count)
    
    seen_ids = set()
    results = []
    for i in range(count):
        el = items.nth(i)
        r_id = el.get_attribute("data-review-id")
        if not r_id or r_id in seen_ids:
            continue
        seen_ids.add(r_id)
        
        # Click more text if truncated
        more_btn = el.locator('button:has-text("More")')
        if more_btn.count() > 0:
            try:
                more_btn.first.click()
            except Exception:
                pass
                
        author = el.locator('.d4r55').inner_text() if el.locator('.d4r55').count() > 0 else "Customer"
        rating = el.locator('.kvMYJc').get_attribute('aria-label') if el.locator('.kvMYJc').count() > 0 else "5 stars"
        comment = el.locator('.wiI7pd').inner_text() if el.locator('.wiI7pd').count() > 0 else ""
        date_str = el.locator('.rsqaWe').inner_text() if el.locator('.rsqaWe').count() > 0 else ""
        
        results.append({
            "id": r_id,
            "author": author,
            "rating": rating,
            "comment": comment,
            "date": date_str
        })
        
    import json
    with open("real_extracted_reviews.json", "w", encoding="utf-8") as out:
        json.dump(results, out, indent=2, ensure_ascii=False)
        
    print("Saved", len(results), "reviews to real_extracted_reviews.json")
    for r in results:
        print(f"[{r['author']}] ({r['rating']}) - {r['date']}: {r['comment']}")
        
    browser.close()
