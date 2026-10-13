import os
import time
from playwright.sync_api import sync_playwright

def login():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://dev.pms.jointribex.com/sophia")
        
        print("Please log in using the browser window...")
        
        # Wait until the url is the target url and not the login page, or until a specific element is present
        try:
            page.wait_for_selector('div.sophia-chat, input, textarea, button', timeout=60000)
            print("Login successful (detected elements).")
        except:
            print("Timeout waiting for chat interface. Assuming login done if URL is correct.")
        
        # Give a little extra time for cookies to settle
        time.sleep(3)
        context.storage_state(path="auth-state.json")
        print("Saved auth-state.json")
        
        browser.close()

if __name__ == "__main__":
    login()
