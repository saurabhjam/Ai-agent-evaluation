from app.adapters.auth import BrowserTokenProvider
from app.session import BrowserSession
from concurrent.futures import TimeoutError as FutureTimeoutError
import asyncio
import pytest


def test_browser_session_uses_browser_auth_manager_as_coroutine_executor():
    class Manager:
        def __init__(self):
            self.calls = []

        def run_coroutine_sync(self, coro, timeout=45.0):
            self.calls.append({"coro": coro, "timeout": timeout})
            coro.close()
            return "token-123"

    manager = Manager()
    session = BrowserSession(
        storage_state="saved-state.json",
        connection_config={"name": "test"},
        browser_auth_manager=manager,
    )

    token = session.get_token(
        url="https://example.test",
        intercept_pattern="*/token",
        token_path="jwt",
        strategy="network",
    )

    assert token == "token-123"
    assert len(manager.calls) == 1
    assert manager.calls[0]["timeout"] == 45.0


def test_browser_session_timeout_names_the_blocked_step():
    class Manager:
        def run_coroutine_sync(self, coro, timeout=90.0):
            coro.close()
            raise FutureTimeoutError()

    session = BrowserSession(
        storage_state="saved-state.json",
        connection_config={},
        browser_auth_manager=Manager(),
    )
    session._auth_stage = "waiting for matching Authorization request"

    with pytest.raises(TimeoutError, match="waiting for matching Authorization request"):
        session.get_token(url="https://example.test", strategy="network")


def test_browser_cleanup_continues_after_page_close_hangs(monkeypatch):
    class Resource:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    page, context, browser = Resource(), Resource(), Resource()
    session = BrowserSession(storage_state=None, connection_config={})
    session.page, session.context, session.browser = page, context, browser
    original_wait_for = asyncio.wait_for
    calls = 0

    async def wait_for(coro, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            coro.close()
            raise asyncio.TimeoutError()
        return await original_wait_for(coro, timeout)

    monkeypatch.setattr("app.session.browser_session.asyncio.wait_for", wait_for)
    asyncio.run(session._async_close())

    assert calls == 3
    assert context.closed and browser.closed
    assert session.page is None and session.context is None and session.browser is None


def test_browser_token_provider_uses_supplied_browser_session():
    class Session:
        def __init__(self):
            self.calls = []

        def get_token(self, **kwargs):
            self.calls.append(kwargs)
            return "abc.def.ghi"

    session = Session()
    provider = BrowserTokenProvider(
        {
            "type": "browser_token",
            "url": "https://example.test",
            "intercept_pattern": "*/token",
            "token_path": "jwt",
        },
        {},
        browser_session=session,
    )

    assert provider.get_headers()["Authorization"] == "Bearer abc.def.ghi"
    assert session.calls[0]["url"] == "https://example.test"
    assert session.calls[0]["intercept_pattern"] == "*/token"
    assert session.calls[0]["token_path"] == "jwt"


def test_browser_token_provider_requires_browser_session():
    try:
        BrowserTokenProvider(
            {
                "type": "browser_token",
                "url": "https://example.test",
                "intercept_pattern": "*/token",
                "token_path": "jwt",
            },
            {},
            browser_session=None,
        )
    except ValueError as exc:
        assert "requires a BrowserSession" in str(exc)
        pass
    else:
        raise AssertionError("BrowserTokenProvider should not create BrowserSession")

