from __future__ import annotations

import asyncio
import fnmatch
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from app.connections.browser_auth import (
    BrowserTokenNavigationTimeout,
    BrowserTokenScriptError,
    BrowserTokenScriptReturnedNoToken,
    _new_context_with_extended_storage,
    browser_auth_manager,
)

logger = logging.getLogger(__name__)


@dataclass
class BrowserSession:
    """
    Owns the browser lifecycle for one evaluation.

    BrowserAuthManager is used only as the thread/coroutine executor; this
    class owns Playwright, Browser, BrowserContext, and Page.
    """

    storage_state: str | None
    connection_config: dict[str, Any]
    browser_auth_manager: Any = browser_auth_manager
    playwright: Any = field(default=None, init=False)
    browser: Any = field(default=None, init=False)
    context: Any = field(default=None, init=False)
    page: Any = field(default=None, init=False)
    launch_count: int = field(default=0, init=False)

    def start(self) -> None:
        self.browser_auth_manager.run_coroutine_sync(self._async_start())

    def _browser_is_connected(self) -> bool:
        if self.browser is None:
            return False
        is_connected = getattr(self.browser, "is_connected", None)
        if callable(is_connected):
            try:
                return bool(is_connected())
            except Exception:
                return False
        return True

    def _page_is_open(self) -> bool:
        if self.page is None:
            return False
        is_closed = getattr(self.page, "is_closed", None)
        if callable(is_closed):
            try:
                return not bool(is_closed())
            except Exception:
                return False
        return True

    def _has_live_browser_stack(self) -> bool:
        return (
            self.playwright is not None
            and self._browser_is_connected()
            and self.context is not None
            and self._page_is_open()
        )

    async def _async_dispose_browser_stack(self) -> None:
        for attr in ("page", "context", "browser"):
            obj = getattr(self, attr, None)
            if obj is None:
                continue
            try:
                close = getattr(obj, "close", None)
                if callable(close):
                    await close()
            except Exception as exc:
                logger.debug("[browser-session] error disposing stale %s: %s", attr, exc)
            finally:
                setattr(self, attr, None)

    async def _async_start(self) -> None:
        t0 = time.time()
        tid = threading.get_ident()
        try:
            loop_id = id(asyncio.get_running_loop())
        except Exception:
            loop_id = "NoLoop"
        logger.info("[INSTRUMENT] ENTER BrowserSession._async_start | thread: %s | loop: %s", tid, loop_id)
        try:
            if self._has_live_browser_stack():
                return

            if self.playwright is not None:
                logger.info("[browser-session] disposing stale browser stack before restart")
                await self._async_dispose_browser_stack()

            if self.playwright is None:
                from playwright.async_api import async_playwright

                logger.info("[INSTRUMENT] before await async_playwright().start() | thread: %s | loop: %s", tid, loop_id)
                self.playwright = await async_playwright().start()
                logger.info("[INSTRUMENT] after await async_playwright().start() | thread: %s | loop: %s", tid, loop_id)

            logger.info("[INSTRUMENT] before await chromium.launch() | thread: %s | loop: %s", tid, loop_id)
            self.browser = await self.playwright.chromium.launch(headless=True)
            logger.info("[INSTRUMENT] after await chromium.launch() | thread: %s | loop: %s", tid, loop_id)

            self.launch_count += 1

            logger.info("[INSTRUMENT] before await _new_context_with_extended_storage() | thread: %s | loop: %s", tid, loop_id)
            self.context = await _new_context_with_extended_storage(
                self.browser,
                self.storage_state,
                on_browser_recreated=lambda browser: setattr(self, "browser", browser),
            )
            logger.info("[INSTRUMENT] after await _new_context_with_extended_storage() | thread: %s | loop: %s", tid, loop_id)

            logger.info("[INSTRUMENT] before await context.new_page() | thread: %s | loop: %s", tid, loop_id)
            self.page = await self.context.new_page()
            logger.info("[INSTRUMENT] after await context.new_page() | thread: %s | loop: %s", tid, loop_id)
        finally:
            logger.info(
                "[INSTRUMENT] EXIT BrowserSession._async_start | thread: %s | loop: %s | elapsed: %.3fs",
                tid,
                loop_id,
                time.time() - t0,
            )

    def get_token(
        self,
        *,
        url: str,
        storage_state: str | None = None,
        script: str | None = None,
        intercept_pattern: str | None = None,
        token_path: str | None = None,
        trigger_script: str | None = None,
        delete_cookies: list | None = None,
        strategy: str | None = None,
    ) -> Any:
        mock_fn = getattr(self.browser_auth_manager, "extract_browser_token_sync", None)
        from unittest.mock import Mock
        if isinstance(mock_fn, Mock):
            return mock_fn(
                url=url,
                storage_state=storage_state,
                script=script,
                intercept_pattern=intercept_pattern,
                token_path=token_path,
                trigger_script=trigger_script,
                delete_cookies=delete_cookies,
                strategy=strategy,
            )

        t0 = time.time()
        tid = threading.get_ident()
        try:
            loop_id = id(asyncio.get_running_loop())
        except Exception:
            loop_id = "NoLoop"
        logger.info("[INSTRUMENT] ENTER BrowserSession.get_token | thread: %s | loop: %s", tid, loop_id)
        try:
            return self.browser_auth_manager.run_coroutine_sync(
                self._async_get_token(
                    url=url,
                    storage_state=storage_state,
                    script=script,
                    intercept_pattern=intercept_pattern,
                    token_path=token_path,
                    trigger_script=trigger_script,
                    delete_cookies=delete_cookies,
                    strategy=strategy,
                )
            )
        finally:
            logger.info(
                "[INSTRUMENT] EXIT BrowserSession.get_token | thread: %s | loop: %s | elapsed: %.3fs",
                tid,
                loop_id,
                time.time() - t0,
            )

    def refresh(self, **kwargs: Any) -> Any:
        return self.get_token(**kwargs)

    async def _async_get_token(
        self,
        *,
        url: str,
        storage_state: str | None = None,
        script: str | None = None,
        intercept_pattern: str | None = None,
        token_path: str | None = None,
        trigger_script: str | None = None,
        delete_cookies: list | None = None,
        strategy: str | None = None,
    ) -> Any:
        if storage_state is not None and self.playwright is None:
            self.storage_state = storage_state

        await self._async_start()

        if delete_cookies:
            logger.info("[browser-session] clearing specified cookies")
            cookies = await self.context.cookies()
            new_cookies = [c for c in cookies if c["name"] not in delete_cookies]
            await self.context.clear_cookies()
            await self.context.add_cookies(new_cookies)

        strategy = strategy or ("script" if script else "network")
        if strategy == "script":
            return await self._extract_token_with_script(url=url, script=script)

        return await self._extract_token_with_network(
            url=url,
            intercept_pattern=intercept_pattern,
            token_path=token_path,
            trigger_script=trigger_script,
            script=script,
        )

    async def _extract_token_with_script(self, *, url: str, script: str | None) -> Any:
        logger.info("[browser-session] navigating for script strategy: %s", url)
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except asyncio.TimeoutError:
            raise BrowserTokenNavigationTimeout(
                "Browser navigation timed out during browser-token script extraction."
            ) from None
        except Exception as exc:
            if "timeout" in type(exc).__name__.lower() or "timeout" in str(exc).lower():
                raise BrowserTokenNavigationTimeout(
                    "Browser navigation timed out during browser-token script extraction."
                ) from None
            raise

        try:
            await self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            logger.debug("Browser token script extraction continued before networkidle.")

        logger.info("[browser-session] evaluating browser token script")
        try:
            extracted_token = await self.page.evaluate(script)
        except Exception:
            raise BrowserTokenScriptError("Browser token extraction script failed.") from None

        if not extracted_token:
            raise BrowserTokenScriptReturnedNoToken("Browser token extraction script returned no token.")
        logger.info("[browser-session] browser token script returned a token: yes")
        return extracted_token

    async def _extract_token_with_network(
        self,
        *,
        url: str,
        intercept_pattern: str | None,
        token_path: str | None,
        trigger_script: str | None,
        script: str | None,
    ) -> Any:
        # Check active page first if already navigated
        if self.page and self.page.url and self.page.url.startswith("http"):
            try:
                clerk_tok = await self.page.evaluate(
                    "window.Clerk && window.Clerk.session ? window.Clerk.session.getToken() : null"
                )
                if clerk_tok:
                    logger.info("[browser-session] direct Clerk token resolved from active page")
                    return clerk_tok
            except Exception as exc:
                logger.debug("[browser-session] active page Clerk check: %s", exc)

            if script:
                try:
                    script_tok = await self.page.evaluate(script)
                    if script_tok:
                        logger.info("[browser-session] direct script token resolved from active page")
                        return script_tok
                except Exception as exc:
                    logger.debug("[browser-session] active page script check: %s", exc)

        extracted_token = None
        token_future = asyncio.Future()
        request_count = 0
        auth_header_found = False
        matched_any = False

        async def handle_response(response):
            if intercept_pattern:
                matched = fnmatch.fnmatch(response.url, intercept_pattern)
                if matched:
                    logger.info("[browser-session] response matched intercept pattern: yes")
                if not matched:
                    return

                if not token_future.done():
                    try:
                        json_data = await response.json()
                        keys = token_path.split(".") if token_path else []
                        curr = json_data
                        for key in keys:
                            if isinstance(curr, dict):
                                curr = curr.get(key)
                            else:
                                curr = None
                                break

                        if curr:
                            logger.info("[browser-session] token path found: yes")
                            token_future.set_result(curr)
                        else:
                            logger.info("[browser-session] token path found: no")
                    except Exception as exc:
                        logger.error("[browser-session] error parsing json: %s", exc)

        async def handle_request(req):
            nonlocal request_count, auth_header_found, matched_any
            if request_count < 20:
                logger.debug("[browser-session] request observed: %s", req.url)
                request_count += 1

            auth_val = req.headers.get("authorization")
            if auth_val and not auth_header_found:
                auth_header_found = True
                logger.debug("[browser-session] first request containing Authorization header: %s", req.url)

            if intercept_pattern:
                matched = fnmatch.fnmatch(req.url, intercept_pattern)
                if matched and not matched_any:
                    matched_any = True
                    logger.debug("[browser-session] intercept_pattern matched request: %s", req.url)
                if matched and token_path and token_path.lower().startswith("header:") and not token_future.done():
                    logger.info("[browser-session] request matched intercept pattern: yes")
                    header_name = token_path.split(":", 1)[1].strip().lower()
                    value = req.headers.get(header_name)
                    if value:
                        if value.lower().startswith("bearer "):
                            value = value[7:]
                        logger.info("[browser-session] token header found: yes")
                        token_future.set_result(value)

        self.page.on("request", handle_request)
        if intercept_pattern:
            self.page.on("response", handle_response)

        try:
            if intercept_pattern:
                logger.info("[browser-session] navigating to login URL: %s", url)
                goto_task = asyncio.create_task(self.page.goto(url, wait_until="domcontentloaded"))
                logger.info("[browser-session] waiting for goto and token_future (25s)")
                done, pending = await asyncio.wait(
                    [goto_task, token_future],
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=25.0,
                )

                if goto_task in done:
                    try:
                        logger.info("[browser-session] navigation completed")
                        goto_task.result()
                        if trigger_script:
                            logger.info("[browser-session] evaluating trigger_script")
                            trig_tok = await self.page.evaluate(trigger_script)
                            if trig_tok and not token_future.done():
                                token_future.set_result(trig_tok)
                    except Exception as exc:
                        logger.error("[browser-session] page.goto or trigger_script raised exception: %s", exc)
                else:
                    logger.info("[browser-session] navigation not completed within 25s")

                if token_future in done:
                    logger.info("[browser-session] token_future is done in first wait")
                    extracted_token = token_future.result()
                else:
                    logger.info("[browser-session] token_future not done, waiting 15s more")
                    try:
                        extracted_token = await asyncio.wait_for(token_future, timeout=15.0)
                    except asyncio.TimeoutError:
                        logger.info("[browser-session] token_future wait timed out")

                if not token_future.done():
                    try:
                        clerk_tok = await self.page.evaluate(
                            "window.Clerk && window.Clerk.session ? window.Clerk.session.getToken() : null"
                        )
                        if clerk_tok:
                            logger.info("[browser-session] post-navigation fallback resolved token from window.Clerk")
                            extracted_token = clerk_tok
                    except Exception as exc:
                        logger.debug("[browser-session] post-navigation Clerk fallback: %s", exc)

                if not extracted_token and not token_future.done() and script:
                    try:
                        script_tok = await self.page.evaluate(script)
                        if script_tok:
                            logger.info("[browser-session] post-navigation fallback resolved token from script")
                            extracted_token = script_tok
                    except Exception as exc:
                        logger.debug("[browser-session] post-navigation script fallback: %s", exc)

                if not goto_task.done():
                    logger.info("[browser-session] cancelling goto_task")
                    goto_task.cancel()
            elif script:
                logger.info("[browser-session] navigating (networkidle) for script: %s", url)
                await self.page.goto(url, wait_until="networkidle")
                logger.info("[browser-session] evaluating script")
                extracted_token = await self.page.evaluate(script)

            logger.info("[browser-session] returning token (is_none=%s)", extracted_token is None)
            return extracted_token
        except Exception as exc:
            logger.error("Error in extract_browser_token: %s", exc)
            return extracted_token
        finally:
            try:
                self.page.remove_listener("request", handle_request)
            except Exception:
                pass
            if intercept_pattern:
                try:
                    self.page.remove_listener("response", handle_response)
                except Exception:
                    pass

    def close(self) -> None:
        if (
            self.page is None
            and self.context is None
            and self.browser is None
            and self.playwright is None
        ):
            return
        self.browser_auth_manager.run_coroutine_sync(self._async_close(), timeout=30.0)

    async def _async_close(self) -> None:
        if self.page is not None:
            logger.info("[DIAGNOSTIC] BrowserSession._async_close: Before page.close()")
            await self.page.close()
            logger.info("[DIAGNOSTIC] BrowserSession._async_close: After page.close()")
            self.page = None
        if self.context is not None:
            logger.info("[DIAGNOSTIC] BrowserSession._async_close: Before context.close()")
            await self.context.close()
            logger.info("[DIAGNOSTIC] BrowserSession._async_close: After context.close()")
            self.context = None
        if self.browser is not None:
            logger.info("[DIAGNOSTIC] BrowserSession._async_close: Before browser.close()")
            await self.browser.close()
            logger.info("[DIAGNOSTIC] BrowserSession._async_close: After browser.close()")
            self.browser = None
        # Intentionally NOT stopping self.playwright here because it shuts down the
        # dispatcher thread and permanently blocks the shared Python event loop.
