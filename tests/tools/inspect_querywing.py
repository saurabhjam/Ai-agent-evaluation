from playwright.sync_api import sync_playwright

def inspect_querywing():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://querywing.com/demo", timeout=60000)
        
        page.wait_for_load_state("load", timeout=30000)
        page.wait_for_timeout(5000) # give JS widgets time to initialize
        
        # Click launcher if exists
        try:
            page.click(".qw2-launcher", timeout=3000)
            page.wait_for_timeout(2000)
        except Exception:
            pass
            
        print("\n--- Input Elements ---")
        inputs = page.query_selector_all("input[type='text'], textarea")
        for i in inputs:
            print(f"Tag: {i.evaluate('el => el.tagName')}, ID: {i.get_attribute('id')}, Class: {i.get_attribute('class')}, Placeholder: {i.get_attribute('placeholder')}")
            
        print("\n--- Button Elements ---")
        buttons = page.query_selector_all("button, input[type='submit'], [role='button']")
        for b in buttons:
            txt = b.inner_text().strip()
            if not txt:
                txt = b.get_attribute('aria-label') or "No text"
            txt = txt.encode('ascii', 'replace').decode('ascii')
            print(f"Tag: {b.evaluate('el => el.tagName')}, ID: {b.get_attribute('id')}, Class: {b.get_attribute('class')}, Text: {txt}")
            
        print("\n--- Message Containers ---")
        # common class names for messages
        msgs = page.query_selector_all("[class*='message'], [class*='chat'], [class*='msg']")
        for m in msgs:
            # only print a few to avoid spam
            cls = m.get_attribute('class')
            id_ = m.get_attribute('id')
            try:
                txt = m.inner_text().strip()
                txt = txt.encode('ascii', 'replace').decode('ascii')
                if len(txt) > 0 and len(txt) < 150:
                    print(f"Tag: {m.evaluate('el => el.tagName')}, ID: {id_}, Class: {cls}, Text snippet: {txt[:50]}")
            except Exception:
                pass
        
        browser.close()

if __name__ == "__main__":
    inspect_querywing()
