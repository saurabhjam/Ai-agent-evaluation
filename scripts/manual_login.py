import asyncio
import importlib.util
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "browser_auth_direct",
    ROOT / "app" / "connections" / "browser_auth.py",
)
browser_auth_direct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = browser_auth_direct
spec.loader.exec_module(browser_auth_direct)
BrowserAuthCheck = browser_auth_direct.BrowserAuthCheck
browser_auth_manager = browser_auth_direct.browser_auth_manager


TARGET_URL = os.getenv("SOPHIA_AUTH_URL", "https://dev.pms.jointribex.com/sophia")
SAVE_PATH = os.getenv("SOPHIA_AUTH_STATE_PATH", "auth-state-Sophia_AI.json")
AUTHENTICATED_SELECTOR = os.getenv("SOPHIA_AUTH_SELECTOR", 'input[aria-label="Ask Sophia"]')
EXPECTED_URL = os.getenv("SOPHIA_AUTH_EXPECTED_URL") or None
REQUIRED_COOKIE = os.getenv("SOPHIA_AUTH_REQUIRED_COOKIE") or None
TIMEOUT_SECONDS = float(os.getenv("SOPHIA_AUTH_TIMEOUT_SECONDS", "180"))


async def run():
    print("Opening visible browser for manual login...")
    print(f"Target URL: {TARGET_URL}")
    print("Complete login and OTP in the opened browser window.")
    print("Waiting until configured authentication evidence is detected.")

    session_id = await browser_auth_manager.start_session(TARGET_URL)
    result = await browser_auth_manager.save_verified_session(
        session_id=session_id,
        save_path=SAVE_PATH,
        auth_check=BrowserAuthCheck(
            expected_url=EXPECTED_URL,
            authenticated_selector=AUTHENTICATED_SELECTOR,
            required_cookie=REQUIRED_COOKIE,
            timeout_seconds=TIMEOUT_SECONDS,
        ),
    )

    print(f"A. authentication detected before save: {'YES' if result.authentication_detected_before_save else 'NO'}")
    print(f"B. storage_state saved: {'YES' if result.storage_state_saved else 'NO'}")
    print(f"C. fresh context restored from saved state: {'YES' if result.fresh_context_restored else 'NO'}")
    print(f"D. authenticated UI detected after restore: {'YES' if result.authenticated_ui_detected_after_restore else 'NO'}")

    if result.success:
        print("Authentication saved successfully.")
        print(f"Saved storage state path: {SAVE_PATH}")
    else:
        print(f"Authentication save failed: {result.error or 'verification failed'}")

    await browser_auth_manager.shutdown()
    return result.success


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(run())
