"""
BrowserAuthManager — Windows-compatible interactive Playwright authentication.

Architecture
============
Playwright spawns a subprocess via asyncio.create_subprocess_exec, which
requires a ProactorEventLoop on Windows.  Uvicorn / FastAPI runs on a
SelectorEventLoop (the default on Windows), so any async Playwright call
made directly inside a FastAPI handler raises NotImplementedError.

Solution
--------
  ┌─────────────────────────────────────────────────────┐
  │  FastAPI / Uvicorn thread  (SelectorEventLoop)       │
  │                                                      │
  │  await browser_auth_manager.start_session(url)  ─┐  │
  │  await browser_auth_manager.save_session(id, p) ─┤  │
  └──────────────────────────────────────────────────│──┘
                                                     │  run_coroutine_threadsafe
  ┌──────────────────────────────────────────────────▼──┐
  │  _PlaywrightThread  (daemon thread)                  │
  │    loop = ProactorEventLoop  (Windows) /             │
  │           new_event_loop    (other OS)               │
  │    async_playwright → Chromium → sessions dict       │
  └─────────────────────────────────────────────────────┘

All Playwright objects (Playwright, Browser, BrowserContext, Page) are
created, used, and destroyed exclusively inside _PlaywrightThread.  They
are never moved to another loop or thread.

Public API  (unchanged — api.py calls these with await)
----------
  session_id = await manager.start_session(url)
  ok         = await manager.save_session(session_id, save_path)
  await      manager.shutdown()          # called on app teardown
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import uuid
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


SESSION_STORAGE_KEY = "_evalforge_sessionStorage"


async def _new_context_with_extended_storage(
    browser,
    storage_state: Optional[str] = None,
    *,
    on_browser_recreated=None,
    retry_launch_options: Optional[dict[str, Any]] = None,
):
    """Create a context from Playwright storage_state plus optional sessionStorage."""

    ctx_kwargs = {}
    session_storage_by_origin = {}

    if storage_state:
        if not os.path.exists(storage_state):
            raise BrowserStorageStateLoadError("Saved browser authentication state could not be loaded.")
        try:
            with open(storage_state, "r", encoding="utf-8") as f:
                state_data = json.load(f)
        except Exception as exc:
            raise BrowserStorageStateLoadError("Saved browser authentication state could not be loaded.") from exc
        ctx_kwargs["storage_state"] = {
            "cookies": state_data.get("cookies", []),
            "origins": state_data.get("origins", []),
        }
        session_storage_by_origin = {
            entry.get("origin"): entry.get("sessionStorage", [])
            for entry in state_data.get(SESSION_STORAGE_KEY, [])
            if entry.get("origin")
        }

    try:
        context = await browser.new_context(**ctx_kwargs)
    except Exception as exc:
        if "TargetClosedError" not in type(exc).__name__:
            raise
        original_exc = exc
        try:
            logger.warning("Browser target closed while creating context; recreating browser and retrying once.")
            browser = await browser.browser_type.launch(**(retry_launch_options or {"headless": True}))
            if callable(on_browser_recreated):
                on_browser_recreated(browser)
            context = await browser.new_context(**ctx_kwargs)
        except Exception:
            raise original_exc
    if session_storage_by_origin:
        await context.add_init_script(
            """
            storage => {
              const items = storage[window.location.origin] || [];
              for (const item of items) {
                window.sessionStorage.setItem(item.name, item.value);
              }
            }
            """,
            session_storage_by_origin,
        )
    return context


@dataclass
class BrowserAuthCheck:
    """Configurable, secret-safe evidence that a browser context is signed in."""

    expected_url: Optional[str] = None
    authenticated_selector: Optional[str] = None
    required_cookie: Optional[str] = None
    timeout_seconds: float = 180.0


@dataclass
class BrowserAuthSaveResult:
    """Outcome of a verified browser auth save."""

    session_found: bool
    authentication_detected_before_save: bool = False
    storage_state_saved: bool = False
    fresh_context_restored: bool = False
    authenticated_ui_detected_after_restore: bool = False
    storage_state_path: Optional[str] = None
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return (
            self.session_found
            and self.authentication_detected_before_save
            and self.storage_state_saved
            and self.fresh_context_restored
            and self.authenticated_ui_detected_after_restore
        )


class BrowserTokenExtractionError(RuntimeError):
    """Base error for browser token extraction failures."""


class BrowserTokenNavigationTimeout(BrowserTokenExtractionError):
    """Raised when the browser page cannot navigate in time."""


class BrowserTokenNetworkTimeout(BrowserTokenExtractionError):
    """Raised when the configured network token response is not observed."""


class BrowserTokenScriptError(BrowserTokenExtractionError):
    """Raised when the configured token extraction script fails."""


class BrowserTokenScriptReturnedNoToken(BrowserTokenExtractionError):
    """Raised when the configured token extraction script returns no token."""


class BrowserStorageStateLoadError(BrowserTokenExtractionError):
    """Raised when a saved storage_state cannot be loaded."""


# ---------------------------------------------------------------------------
# Per-session state — lives entirely inside _PlaywrightThread's loop
# ---------------------------------------------------------------------------

class _BrowserAuthSession:
    """Holds all Playwright objects for one interactive login session."""

    def __init__(self, url: str) -> None:
        self.id: str = str(uuid.uuid4())
        self.url: str = url
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def start(self) -> None:
        from playwright.async_api import async_playwright  # local import — stays in worker loop
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=False)
        self.context = await _new_context_with_extended_storage(
            self.browser,
            None,
            on_browser_recreated=lambda browser: setattr(self, "browser", browser),
            retry_launch_options={"headless": False},
        )
        self.page = await self.context.new_page()
        await self.page.goto(self.url, wait_until="domcontentloaded")
        logger.info("BrowserAuth: session %s opened at %s", self.id, self.url)

    async def save(self, path: str) -> None:
        if self.context is None:
            raise RuntimeError("Session context is not available (already closed?)")
        await self.context.storage_state(path=path)
        await self._append_session_storage(path)
        logger.info("BrowserAuth: session %s storage_state saved to %s", self.id, path)

    async def _append_session_storage(self, path: str) -> None:
        if self.context is None:
            return

        captured = {}
        for page in self.context.pages:
            for frame in page.frames:
                try:
                    origin = await frame.evaluate("window.location.origin")
                    items = await frame.evaluate(
                        """
                        () => Object.keys(window.sessionStorage).map(name => ({
                          name,
                          value: window.sessionStorage.getItem(name)
                        }))
                        """
                    )
                except Exception:
                    continue
                if origin and items:
                    captured[origin] = items

        if not captured:
            return

        with open(path, "r", encoding="utf-8") as f:
            state_data = json.load(f)
        state_data[SESSION_STORAGE_KEY] = [
            {"origin": origin, "sessionStorage": items}
            for origin, items in sorted(captured.items())
        ]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2)

    async def _has_required_cookie(self, required_cookie: Optional[str]) -> bool:
        if not required_cookie:
            return True
        if self.context is None:
            return False
        cookies = await self.context.cookies()
        return any(cookie.get("name") == required_cookie for cookie in cookies)

    async def auth_matches(self, check: BrowserAuthCheck, page=None) -> bool:
        if self.context is None:
            return False

        active_page = page or self.page
        if active_page is None:
            return False

        if check.expected_url and check.expected_url not in active_page.url:
            return False

        if not await self._has_required_cookie(check.required_cookie):
            return False

        if check.authenticated_selector:
            try:
                locator = active_page.locator(check.authenticated_selector).first
                if await locator.count() == 0:
                    return False
                if not await locator.is_visible(timeout=1000):
                    return False
            except Exception:
                return False

        return True

    async def wait_for_auth(self, check: BrowserAuthCheck) -> bool:
        deadline = asyncio.get_event_loop().time() + check.timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            if await self.auth_matches(check):
                return True
            await asyncio.sleep(1.0)
        return False

    async def verify_saved_state(self, path: str, check: BrowserAuthCheck) -> bool:
        if not os.path.exists(path) or self.playwright is None:
            return False

        browser = await self.playwright.chromium.launch(headless=True)
        browser_ref = {"browser": browser}
        context = await _new_context_with_extended_storage(
            browser,
            path,
            on_browser_recreated=lambda new_browser: browser_ref.update({"browser": new_browser}),
        )
        page = await context.new_page()
        verifier = _BrowserAuthSession(self.url)
        verifier.playwright = self.playwright
        verifier.browser = browser_ref["browser"]
        verifier.context = context
        verifier.page = page
        try:
            await page.goto(self.url, wait_until="domcontentloaded")
            verify_check = BrowserAuthCheck(
                expected_url=check.expected_url,
                authenticated_selector=check.authenticated_selector,
                required_cookie=check.required_cookie,
                timeout_seconds=min(check.timeout_seconds, 30.0),
            )
            return await verifier.wait_for_auth(verify_check)
        finally:
            await context.close()
            await verifier.browser.close()

    async def close(self) -> None:
        for attr, method in [
            ("page", "close"),
            ("context", "close"),
            ("browser", "close"),
        ]:
            obj = getattr(self, attr, None)
            if obj is not None:
                try:
                    await getattr(obj, method)()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("BrowserAuth: error closing %s: %s", attr, exc)
                finally:
                    setattr(self, attr, None)
        logger.info("BrowserAuth: session %s closed", self.id)


# ---------------------------------------------------------------------------
# Dedicated Playwright thread — owns a ProactorEventLoop on Windows
# ---------------------------------------------------------------------------

class _PlaywrightThread(threading.Thread):
    """
    Daemon thread that runs a private asyncio event loop compatible with
    Playwright on Windows (ProactorEventLoop) and non-Windows platforms.
    """

    def __init__(self) -> None:
        super().__init__(name="playwright-auth-thread", daemon=True)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()
        self._sessions: Dict[str, _BrowserAuthSession] = {}

    # ---- thread entry -------------------------------------------------------

    def run(self) -> None:
        if sys.platform == "win32":
            self._loop = asyncio.ProactorEventLoop()
        else:
            self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        logger.info("BrowserAuth: Playwright thread started (loop=%s)", type(self._loop).__name__)
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()
            logger.info("BrowserAuth: Playwright thread stopped")

    # ---- internal helpers ---------------------------------------------------

    def _ensure_started(self) -> None:
        if not self.is_alive():
            self.start()
            self._ready.wait(timeout=5)

    def _dispatch(self, coro) -> Future:
        self._ensure_started()
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    # ---- async session operations (run INSIDE the Playwright loop) ----------

    async def _async_start(self, url: str) -> str:
        session = _BrowserAuthSession(url)
        await session.start()
        self._sessions[session.id] = session
        return session.id

    async def _async_save(self, session_id: str, save_path: str) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        try:
            await session.save(save_path)
            return True
        finally:
            await session.close()
            self._sessions.pop(session_id, None)

    async def _async_save_verified(
        self,
        session_id: str,
        save_path: str,
        auth_check: BrowserAuthCheck,
    ) -> BrowserAuthSaveResult:
        session = self._sessions.get(session_id)
        if session is None:
            return BrowserAuthSaveResult(session_found=False, error="Session not found or already closed")

        result = BrowserAuthSaveResult(session_found=True, storage_state_path=save_path)
        try:
            result.authentication_detected_before_save = await session.wait_for_auth(auth_check)
            if not result.authentication_detected_before_save:
                result.error = "Authentication was not detected before timeout"
                return result

            await session.save(save_path)
            result.storage_state_saved = os.path.exists(save_path)
            if not result.storage_state_saved:
                result.error = "storage_state file was not written"
                return result

            result.fresh_context_restored = True
            result.authenticated_ui_detected_after_restore = await session.verify_saved_state(save_path, auth_check)
            if not result.authenticated_ui_detected_after_restore:
                result.error = "Saved storage_state did not restore an authenticated browser context"
                if os.path.exists(save_path):
                    os.remove(save_path)

            return result
        finally:
            await session.close()
            self._sessions.pop(session_id, None)

    async def _async_shutdown(self) -> None:
        session_ids = list(self._sessions.keys())
        for sid in session_ids:
            s = self._sessions.pop(sid, None)
            if s:
                await s.close()
        if self._loop and self._loop.is_running():
            self._loop.stop()

    async def _async_evaluate_script(self, url: str, script: str, storage_state: str = None) -> Any:
        from playwright.async_api import async_playwright
        import os
        playwright = await async_playwright().start()
        headless = True
        browser = await playwright.chromium.launch(headless=headless)
        browser_ref = {"browser": browser}
        context = await _new_context_with_extended_storage(
            browser,
            storage_state,
            on_browser_recreated=lambda new_browser: browser_ref.update({"browser": new_browser}),
        )
        browser = browser_ref["browser"]
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded")
            result = await page.evaluate(script)
            return result
        finally:
            await context.close()
            await browser.close()
            await playwright.stop()

    async def _async_extract_browser_token(self, url: str, storage_state: str, script: str = None, intercept_pattern: str = None, token_path: str = None, trigger_script: str = None, delete_cookies: list = None, strategy: str = None) -> Any:
        import builtins
        def _log_trace(msg):
            builtins.print(msg)
            with open('trace.txt', 'a') as f:
                f.write(msg + "\n")
        
        from playwright.async_api import async_playwright
        import fnmatch
        import asyncio

        _log_trace("[TRACE-DEADLOCK] ENTER coroutine")
        strategy = strategy or ("script" if script else "network")
        logger.info(f"[browser-token-diag] starting async_playwright.start()")
        playwright = await async_playwright().start()
        headless = True
        logger.info(f"[browser-token-diag] launching chromium headless={headless}")
        browser = await playwright.chromium.launch(headless=headless)
        browser_ref = {"browser": browser}
        _log_trace(f"[TRACE] 1. Browser launched")
        logger.info(f"[browser-token-diag] loading storage state: {storage_state}")
        context = await _new_context_with_extended_storage(
            browser,
            storage_state,
            on_browser_recreated=lambda new_browser: browser_ref.update({"browser": new_browser}),
        )
        browser = browser_ref["browser"]
        _log_trace(f"[TRACE] 2. Storage state loaded: {storage_state}")
        
        if delete_cookies:
            logger.info(f"[browser-token-diag] clearing specified cookies")
            cookies = await context.cookies()
            new_cookies = [c for c in cookies if c["name"] not in delete_cookies]
            await context.clear_cookies()
            await context.add_cookies(new_cookies)
            
        logger.info(f"[browser-token-diag] opening new page")
        page = await context.new_page()

        if strategy == "script":
            try:
                logger.info(f"[browser-token-diag] navigating for script strategy: {url}")
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                except asyncio.TimeoutError:
                    raise BrowserTokenNavigationTimeout("Browser navigation timed out during browser-token script extraction.") from None
                except Exception as exc:
                    if "timeout" in type(exc).__name__.lower() or "timeout" in str(exc).lower():
                        raise BrowserTokenNavigationTimeout("Browser navigation timed out during browser-token script extraction.") from None
                    raise

                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    logger.debug("Browser token script extraction continued before networkidle.")

                logger.info("[browser-token-diag] evaluating browser token script")
                try:
                    extracted_token = await page.evaluate(script)
                except Exception:
                    raise BrowserTokenScriptError("Browser token extraction script failed.") from None

                if not extracted_token:
                    raise BrowserTokenScriptReturnedNoToken("Browser token extraction script returned no token.")
                logger.info("[browser-token-diag] browser token script returned a token: yes")
                return extracted_token
            finally:
                logger.info(f"[browser-token-diag] cleaning up playwright")
                await context.close()
                await browser.close()
                await playwright.stop()

        extracted_token = None
        token_future = asyncio.Future()
        
        request_count = 0
        auth_header_found = False
        matched_any = False
        
        async def handle_response(response):
            if intercept_pattern:
                matched = fnmatch.fnmatch(response.url, intercept_pattern)
                if matched:
                    logger.info(f"[browser-token-diag] response matched intercept pattern: yes")
                if not matched:
                    return

                if not token_future.done():
                    try:
                        json_data = await response.json()
                        keys = token_path.split('.') if token_path else []
                        curr = json_data
                        for k in keys:
                            if isinstance(curr, dict):
                                curr = curr.get(k)
                            else:
                                curr = None
                                break
                                
                        if curr:
                            _log_trace(f"[TRACE] 14. Token extraction executed (response): found")
                            _log_trace("[TRACE-DEADLOCK] TOKEN FOUND")
                            logger.info(f"[browser-token-diag] token path found: yes")
                            token_future.set_result(curr)
                        else:
                            _log_trace(f"[TRACE] 14. Token extraction executed (response): not found")
                            logger.info(f"[browser-token-diag] token path found: no")
                    except Exception as e:
                        logger.error(f"[browser-token-diag] error parsing json: {e}")
        
        async def handle_request(req):
            nonlocal request_count, auth_header_found, matched_any
            if request_count < 20:
                _log_trace(f"[TRACE] 9. Request observed: {req.url}")
                request_count += 1
                
            auth_val = req.headers.get("authorization")
            if auth_val and not auth_header_found:
                auth_header_found = True
                _log_trace(f"[TRACE] 10. First request containing Authorization header: {req.url}")
                
            if intercept_pattern:
                matched = fnmatch.fnmatch(req.url, intercept_pattern)
                if matched and not matched_any:
                    matched_any = True
                    _log_trace(f"[TRACE] 12. intercept_pattern matched request: {req.url}")
                if matched and token_path and token_path.lower().startswith("header:") and not token_future.done():
                    logger.info(f"[browser-token-diag] request matched intercept pattern: yes")
                    _log_trace(f"[TRACE] 14. Token extraction executed (request header)")
                    header_name = token_path.split(":", 1)[1].strip().lower()
                    val = req.headers.get(header_name)
                    if val:
                        if val.lower().startswith("bearer "):
                            val = val[7:]
                        logger.info(f"[browser-token-diag] token header found: yes")
                        _log_trace("[TRACE-DEADLOCK] TOKEN FOUND")
                        token_future.set_result(val)
        
        _log_trace(f"[TRACE] 7. request listener registered")
        page.on("request", handle_request)
        
        if intercept_pattern:
            _log_trace(f"[TRACE] 8. response listener registered")
            page.on("response", handle_response)
            
        try:
            if intercept_pattern:
                logger.info(f"[browser-token-diag] navigating to login URL: {url}")
                goto_task = asyncio.create_task(page.goto(url, wait_until="domcontentloaded"))
                logger.info(f"[browser-token-diag] waiting for goto and token_future (25s)")
                done, pending = await asyncio.wait(
                    [goto_task, token_future], 
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=25.0
                )
                
                if goto_task in done:
                    try:
                        logger.info(f"[browser-token-diag] navigation completed")
                        goto_task.result()
                        if trigger_script:
                            logger.info(f"[browser-token-diag] evaluating trigger_script")
                            trig_tok = await page.evaluate(trigger_script)
                            if trig_tok and not token_future.done():
                                token_future.set_result(trig_tok)
                    except Exception as e:
                        logger.error(f"[browser-token-diag] page.goto or trigger_script raised exception: {e}")
                else:
                    logger.info(f"[browser-token-diag] navigation not completed within 25s")
                
                if token_future in done:
                    logger.info(f"[browser-token-diag] token_future is done in first wait")
                    extracted_token = token_future.result()
                else:
                    logger.info(f"[browser-token-diag] token_future not done, waiting 10s more")
                    try:
                        extracted_token = await asyncio.wait_for(token_future, timeout=10.0)
                    except asyncio.TimeoutError:
                        logger.info(f"[browser-token-diag] token_future wait timed out")
                        pass

                if not token_future.done():
                    try:
                        clerk_tok = await page.evaluate(
                            "window.Clerk && window.Clerk.session ? window.Clerk.session.getToken() : null"
                        )
                        if clerk_tok:
                            logger.info(f"[browser-token-diag] post-navigation fallback resolved token from window.Clerk")
                            extracted_token = clerk_tok
                    except Exception:
                        pass

                if not extracted_token and not token_future.done() and script:
                    try:
                        script_tok = await page.evaluate(script)
                        if script_tok:
                            logger.info(f"[browser-token-diag] post-navigation fallback resolved token from script")
                            extracted_token = script_tok
                    except Exception:
                        pass
                        
                if not goto_task.done():
                    logger.info(f"[browser-token-diag] cancelling goto_task")
                    goto_task.cancel()
                    
            elif script:
                logger.info(f"[browser-token-diag] navigating (networkidle) for script: {url}")
                await page.goto(url, wait_until="networkidle")
                logger.info(f"[browser-token-diag] evaluating script")
                extracted_token = await page.evaluate(script)
                
            logger.info(f"[browser-token-diag] returning token (is_none={extracted_token is None})")
            _log_trace("[TRACE-DEADLOCK] RETURN ABOUT TO EXECUTE")
            return extracted_token
        except Exception as e:
            logger.error(f"Error in extract_browser_token: {e}")
            return extracted_token
        finally:
            _log_trace("[TRACE-DEADLOCK] ENTER finally")
            logger.info(f"[browser-token-diag] cleaning up playwright")
            if 'context' in locals() and context:
                await context.close()
            if 'browser' in locals() and browser:
                await browser.close()
            if 'playwright' in locals() and playwright:
                _log_trace("[TRACE-DEADLOCK] BEFORE playwright.stop()")
                await playwright.stop()
                _log_trace("[TRACE-DEADLOCK] AFTER playwright.stop()")


    # ---- public synchronous bridge (called from any thread) -----------------

    def start_session_sync(self, url: str, timeout: float = 90.0) -> str:
        """Dispatch start into the Playwright loop; block until done."""
        logger.info(f"[DIAGNOSTIC] start_session_sync: entering for URL {url}")
        future = self._dispatch(self._async_start(url))
        try:
            res = future.result(timeout=timeout)
            logger.info(f"[DIAGNOSTIC] start_session_sync: exiting normally")
            return res
        except Exception as e:
            logger.exception(f"[DIAGNOSTIC] start_session_sync: timeout or exception: {e}")
            raise
        
    def extract_browser_token_sync(self, url: str, storage_state: str = None, script: str = None, intercept_pattern: str = None, token_path: str = None, trigger_script: str = None, delete_cookies: list = None, strategy: str = None, timeout: float = 45.0) -> Any:
        future = self._dispatch(self._async_extract_browser_token(url, storage_state, script, intercept_pattern, token_path, trigger_script, delete_cookies, strategy))
        return future.result(timeout=timeout)

    def save_session_sync(self, session_id: str, save_path: str, timeout: float = 30.0) -> bool:
        """Dispatch save into the Playwright loop; block until done."""
        future = self._dispatch(self._async_save(session_id, save_path))
        return future.result(timeout=timeout)

    def save_verified_session_sync(
        self,
        session_id: str,
        save_path: str,
        auth_check: BrowserAuthCheck,
        timeout: Optional[float] = None,
    ) -> BrowserAuthSaveResult:
        future = self._dispatch(self._async_save_verified(session_id, save_path, auth_check))
        wait_timeout = timeout or (auth_check.timeout_seconds + 60.0)
        return future.result(timeout=wait_timeout)

    def shutdown_sync(self, timeout: float = 10.0) -> None:
        if self._loop and self._loop.is_running():
            future = self._dispatch(self._async_shutdown())
            try:
                future.result(timeout=timeout)
            except Exception:  # noqa: BLE001
                pass

    def evaluate_script_sync(self, url: str, script: str, storage_state: str = None, timeout: float = 30.0) -> Any:
        future = self._dispatch(self._async_evaluate_script(url, script, storage_state))
        return future.result(timeout=timeout)


# ---------------------------------------------------------------------------
# BrowserAuthManager — public singleton (async façade over _PlaywrightThread)
# ---------------------------------------------------------------------------

class BrowserAuthManager:
    """
    Singleton used by FastAPI endpoints.  All public methods are async so
    they can be awaited directly.  Internally they delegate to
    _PlaywrightThread via run_in_executor so the FastAPI event loop is not
    blocked during browser launch/save.
    """

    _instance: Optional["BrowserAuthManager"] = None

    def __new__(cls) -> "BrowserAuthManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._thread = _PlaywrightThread()
        return cls._instance

    async def start_session(self, url: str) -> str:
        """
        Launch a visible Chromium window and navigate to *url*.
        Returns a session_id the caller must pass to save_session().
        Runs the Playwright work in the dedicated Playwright thread.
        """
        loop = asyncio.get_event_loop()
        thread = self._thread
        session_id: str = await loop.run_in_executor(
            None, thread.start_session_sync, url
        )
        return session_id

    async def save_session(self, session_id: str, save_path: str) -> bool:
        """
        Capture storage_state from the open browser session, save it to
        *save_path*, then close the browser.  Returns True on success.
        """
        loop = asyncio.get_event_loop()
        thread = self._thread
        ok: bool = await loop.run_in_executor(
            None, thread.save_session_sync, session_id, save_path
        )
        return ok

    async def save_verified_session(
        self,
        session_id: str,
        save_path: str,
        auth_check: BrowserAuthCheck,
    ) -> BrowserAuthSaveResult:
        """
        Wait for configured authentication evidence, save storage_state from
        the same BrowserContext, then prove that state in a fresh context.
        """
        loop = asyncio.get_event_loop()
        thread = self._thread
        result: BrowserAuthSaveResult = await loop.run_in_executor(
            None,
            thread.save_verified_session_sync,
            session_id,
            save_path,
            auth_check,
            auth_check.timeout_seconds + 60.0,
        )
        return result

    async def shutdown(self) -> None:
        """Gracefully close all open sessions and stop the Playwright thread."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._thread.shutdown_sync)

    async def evaluate_script(self, url: str, script: str, storage_state: str = None) -> Any:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._thread.evaluate_script_sync, url, script, storage_state, 30.0)

    def evaluate_script_sync(self, url: str, script: str, storage_state: str = None) -> Any:
        """Synchronous bridge for RestChatAdapter"""
        return self._thread.evaluate_script_sync(url, script, storage_state, timeout=30.0)

    def run_coroutine_sync(self, coro, timeout: float = 90.0) -> Any:
        future = self._thread._dispatch(coro)
        return future.result(timeout=timeout)

    def extract_browser_token_sync(self, url: str, storage_state: str = None, script: str = None, intercept_pattern: str = None, token_path: str = None, trigger_script: str = None, delete_cookies: list = None, strategy: str = None) -> Any:
        """Synchronous bridge for RestChatAdapter to extract a generic browser token."""
        return self._thread.extract_browser_token_sync(url, storage_state, script, intercept_pattern, token_path, trigger_script, delete_cookies, strategy, timeout=90.0)


# Module-level singleton — imported by api.py
browser_auth_manager = BrowserAuthManager()
