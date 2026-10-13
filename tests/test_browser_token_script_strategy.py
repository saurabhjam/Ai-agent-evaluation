import asyncio
import inspect
import json
import sys
import types

import pytest

from app.connections.browser_auth import (
    BrowserTokenScriptError,
    BrowserTokenScriptReturnedNoToken,
    _PlaywrightThread,
)


class _FakePage:
    def __init__(self, token="script-token", raise_on_evaluate=None):
        self.token = token
        self.raise_on_evaluate = raise_on_evaluate
        self.events = {}
        self.evaluated_script = None
        self.goto_calls = []

    def on(self, event, handler):
        self.events[event] = handler

    async def goto(self, url, wait_until=None, timeout=None):
        self.goto_calls.append({"url": url, "wait_until": wait_until, "timeout": timeout})

    async def wait_for_load_state(self, state, timeout=None):
        return None

    async def evaluate(self, script):
        self.evaluated_script = script
        if self.raise_on_evaluate:
            raise self.raise_on_evaluate
        if inspect.isawaitable(self.token):
            return await self.token
        return self.token


class _FakeContext:
    def __init__(self, page):
        self.page = page
        self.closed = False

    async def new_page(self):
        return self.page

    async def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self, page):
        self.page = page
        self.contexts = []
        self.closed = False

    async def new_context(self, **kwargs):
        context = _FakeContext(self.page)
        self.contexts.append({"context": context, "kwargs": kwargs})
        return context

    async def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, browser):
        self.browser = browser

    async def launch(self, headless=True):
        return self.browser


class _FakePlaywright:
    def __init__(self, browser):
        self.chromium = _FakeChromium(browser)
        self.stopped = False

    async def stop(self):
        self.stopped = True


def _install_fake_playwright(monkeypatch, page):
    browser = _FakeBrowser(page)
    playwright = _FakePlaywright(browser)

    class _Starter:
        async def start(self):
            return playwright

    fake_async_api = types.ModuleType("playwright.async_api")
    fake_async_api.async_playwright = lambda: _Starter()
    fake_playwright = types.ModuleType("playwright")
    fake_playwright.async_api = fake_async_api
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_async_api)
    return playwright, browser


def _storage_state(tmp_path):
    path = tmp_path / "auth-state.json"
    path.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")
    return path


def test_script_strategy_no_network_request_extracts_token(monkeypatch, tmp_path):
    page = _FakePage(token="script-token")
    _install_fake_playwright(monkeypatch, page)
    state_path = _storage_state(tmp_path)
    before = state_path.read_text(encoding="utf-8")

    token = asyncio.run(
        _PlaywrightThread()._async_extract_browser_token(
            url="https://app.example.test",
            storage_state=str(state_path),
            script="window.Clerk.session.getToken()",
            intercept_pattern=None,
            token_path=None,
            strategy="script",
        )
    )

    assert token == "script-token"
    assert "response" not in page.events
    assert "request" not in page.events
    assert page.evaluated_script == "window.Clerk.session.getToken()"
    assert state_path.read_text(encoding="utf-8") == before


def test_script_strategy_awaits_promise_return(monkeypatch, tmp_path):
    class _Promise:
        def __await__(self):
            async def _resolve():
                return "promise-token"
            return _resolve().__await__()

    page = _FakePage(token=_Promise())
    _install_fake_playwright(monkeypatch, page)

    token = asyncio.run(
        _PlaywrightThread()._async_extract_browser_token(
            url="https://app.example.test",
            storage_state=str(_storage_state(tmp_path)),
            script="Promise.resolve('promise-token')",
            strategy="script",
        )
    )

    assert token == "promise-token"


def test_script_strategy_null_token_has_clear_error(monkeypatch, tmp_path):
    page = _FakePage(token=None)
    _install_fake_playwright(monkeypatch, page)

    with pytest.raises(BrowserTokenScriptReturnedNoToken, match="returned no token"):
        asyncio.run(
            _PlaywrightThread()._async_extract_browser_token(
                url="https://app.example.test",
                storage_state=str(_storage_state(tmp_path)),
                script="null",
                strategy="script",
            )
        )


def test_script_strategy_exception_has_clear_error(monkeypatch, tmp_path):
    page = _FakePage(raise_on_evaluate=RuntimeError("boom-secret-token"))
    _install_fake_playwright(monkeypatch, page)

    with pytest.raises(BrowserTokenScriptError, match="script failed"):
        asyncio.run(
            _PlaywrightThread()._async_extract_browser_token(
                url="https://app.example.test",
                storage_state=str(_storage_state(tmp_path)),
                script="throw new Error('boom')",
                strategy="script",
            )
        )
