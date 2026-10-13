
import asyncio
import sys
from playwright.async_api import async_playwright

async def main():
    print('Starting playwright')
    p = await async_playwright().start()
    print('Launching browser')
    b = await p.chromium.launch(headless=False)
    print('New context')
    c = await b.new_context()
    print('New page')
    page = await c.new_page()
    print('Goto')
    try:
        await page.goto('http://example.com', wait_until='domcontentloaded')
    except Exception as e:
        print(f'Exception: {type(e).__name__} - {e}')
    print('Done')
    await b.close()
    await p.stop()

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
asyncio.run(main())
