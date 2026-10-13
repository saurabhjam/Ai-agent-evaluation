"""
tests/test_browser_auth_manager.py
===================================
Unit / integration tests for BrowserAuthManager.

All tests are synchronous — no pytest-asyncio required.  The manager's
public async API is tested at the HTTP level (via TestClient) or through
the _PlaywrightThread sync bridge directly.

Tests cover:
  - _PlaywrightThread uses ProactorEventLoop on Windows
  - start_session_sync() creates a session and returns a session_id
  - session remains available after start returns (registry check)
  - save_session_sync() retrieves the same session, captures storage_state
  - save removes session from registry (cleanup)
  - unknown session_id returns False (not an exception)
  - failures inside the Playwright thread propagate as RuntimeError
  - HTTP endpoint /browser-auth/start returns session_id (mocked)
  - HTTP endpoint /browser-auth/save returns path after verification (mocked)
  - HTTP endpoint /browser-auth/save returns 404 for unknown session
  - HTTP endpoint /browser-auth/start returns 500 on Playwright failure
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import uuid
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# _PlaywrightThread: loop type on Windows
# ---------------------------------------------------------------------------

class TestPlaywrightThreadLoopType:
    def test_uses_proactor_on_windows(self):
        """On Windows the dedicated loop must be ProactorEventLoop."""
        from app.connections.browser_auth import _PlaywrightThread

        t = _PlaywrightThread()
        t.start()
        t._ready.wait(timeout=5)

        try:
            if sys.platform == "win32":
                assert isinstance(t._loop, asyncio.ProactorEventLoop), (
                    f"Expected ProactorEventLoop, got {type(t._loop)}"
                )
            else:
                assert t._loop is not None, "Event loop should be set"
        finally:
            t.shutdown_sync(timeout=5)


# ---------------------------------------------------------------------------
# _PlaywrightThread sync bridge — tested without a real browser
# ---------------------------------------------------------------------------

def _make_fake_session(session_id: str, saved_paths: list):
    """
    Create a _BrowserAuthSession whose async coroutine methods are mocked.
    No real browser is launched.
    """
    from app.connections.browser_auth import _BrowserAuthSession

    session = object.__new__(_BrowserAuthSession)
    session.id = session_id
    session.url = "https://example.com"
    session.playwright = None
    session.browser = None
    session.context = None
    session.page = None

    async def fake_start():
        pass

    async def fake_save(path: str):
        saved_paths.append(path)
        with open(path, "w") as f:
            json.dump({"cookies": [], "origins": []}, f)

    async def fake_close():
        pass

    session.start = fake_start
    session.save = fake_save
    session.close = fake_close
    return session


def _fresh_thread() -> "_PlaywrightThread":
    """Start a fresh _PlaywrightThread and return it (caller owns shutdown)."""
    from app.connections.browser_auth import _PlaywrightThread
    t = _PlaywrightThread()
    t.start()
    t._ready.wait(timeout=5)
    return t


def _insert_session(thread, session):
    """Place a fake session into the thread's sessions dict via its loop."""
    async def _do():
        thread._sessions[session.id] = session

    fut = asyncio.run_coroutine_threadsafe(_do(), thread._loop)
    fut.result(timeout=5)


def _session_exists(thread, session_id: str) -> bool:
    async def _do():
        return session_id in thread._sessions

    fut = asyncio.run_coroutine_threadsafe(_do(), thread._loop)
    return fut.result(timeout=5)


class TestPlaywrightThreadSyncBridge:

    def test_start_creates_session(self):
        """start_session_sync returns a non-empty session_id."""
        thread = _fresh_thread()
        fake_id = str(uuid.uuid4())
        saved = []
        fake_session = _make_fake_session(fake_id, saved)

        async def patched_async_start(url: str) -> str:
            thread._sessions[fake_session.id] = fake_session
            return fake_session.id

        thread._async_start = patched_async_start

        try:
            session_id = thread.start_session_sync("https://example.com", timeout=15)
            assert session_id == fake_id
        finally:
            thread.shutdown_sync(timeout=5)

    def test_session_available_after_start(self):
        """Session must remain in the registry after start_session_sync returns."""
        thread = _fresh_thread()
        fake_id = str(uuid.uuid4())
        saved = []
        fake_session = _make_fake_session(fake_id, saved)

        async def patched_async_start(url: str) -> str:
            thread._sessions[fake_session.id] = fake_session
            return fake_session.id

        thread._async_start = patched_async_start

        try:
            session_id = thread.start_session_sync("https://example.com", timeout=15)
            assert _session_exists(thread, session_id), (
                "Session should still be in registry after start"
            )
        finally:
            thread.shutdown_sync(timeout=5)

    def test_save_writes_storage_state(self, tmp_path):
        """save_session_sync calls session.save() and writes the file."""
        thread = _fresh_thread()
        fake_id = str(uuid.uuid4())
        saved_paths: list = []
        fake_session = _make_fake_session(fake_id, saved_paths)
        _insert_session(thread, fake_session)

        save_path = str(tmp_path / "auth-state-test.json")
        try:
            ok = thread.save_session_sync(fake_id, save_path, timeout=15)
        finally:
            thread.shutdown_sync(timeout=5)

        assert ok is True
        assert save_path in saved_paths, "session.save() was not called"
        assert os.path.exists(save_path), "storage_state file was not written"
        with open(save_path) as f:
            data = json.load(f)
        assert "cookies" in data

    def test_save_removes_session_from_registry(self, tmp_path):
        """save_session_sync cleans up the session after saving."""
        thread = _fresh_thread()
        fake_id = str(uuid.uuid4())
        saved: list = []
        fake_session = _make_fake_session(fake_id, saved)
        _insert_session(thread, fake_session)

        save_path = str(tmp_path / "auth-state-cleanup.json")
        try:
            thread.save_session_sync(fake_id, save_path, timeout=15)
            assert not _session_exists(thread, fake_id), (
                "Session should be removed after save"
            )
        finally:
            thread.shutdown_sync(timeout=5)

    def test_save_unknown_session_returns_false(self):
        """save_session_sync with a bad ID must return False, not raise."""
        thread = _fresh_thread()
        try:
            ok = thread.save_session_sync("nonexistent-id", "/tmp/x.json", timeout=15)
            assert ok is False
        finally:
            thread.shutdown_sync(timeout=5)

    def test_failure_in_start_propagates(self):
        """Exceptions raised inside the Playwright loop propagate to callers."""
        thread = _fresh_thread()

        async def patched_async_start(url: str) -> str:
            raise RuntimeError("Simulated Playwright failure")

        thread._async_start = patched_async_start

        try:
            with pytest.raises(RuntimeError, match="Simulated Playwright failure"):
                thread.start_session_sync("https://example.com", timeout=15)
        finally:
            thread.shutdown_sync(timeout=5)


# ---------------------------------------------------------------------------
# FastAPI endpoint integration — mocks the module-level manager singleton
# ---------------------------------------------------------------------------

class TestBrowserAuthEndpoints:
    """Verify the /connections/browser-auth/* HTTP endpoints end-to-end."""

    def test_start_endpoint_returns_session_id(self):
        from fastapi.testclient import TestClient
        from app.main import app

        fake_id = str(uuid.uuid4())

        async def mock_start(url: str) -> str:
            return fake_id

        with patch("app.connections.api.browser_auth_manager") as mock_mgr:
            mock_mgr.start_session = mock_start
            client = TestClient(app)
            resp = client.post(
                "/connections/browser-auth/start",
                json={"url": "https://example.com"}
            )

        assert resp.status_code == 200
        assert resp.json()["session_id"] == fake_id

    def test_save_endpoint_returns_path(self, tmp_path):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.connections.browser_auth import BrowserAuthSaveResult

        fake_id = str(uuid.uuid4())

        async def mock_save(session_id: str, path: str, auth_check) -> BrowserAuthSaveResult:
            with open(path, "w") as f:
                json.dump({"cookies": [], "origins": []}, f)
            return BrowserAuthSaveResult(
                session_found=True,
                authentication_detected_before_save=True,
                storage_state_saved=True,
                fresh_context_restored=True,
                authenticated_ui_detected_after_restore=True,
                storage_state_path=path,
            )

        with patch("app.connections.api.browser_auth_manager") as mock_mgr:
            mock_mgr.save_verified_session = mock_save
            client = TestClient(app)
            resp = client.post(
                "/connections/browser-auth/save",
                json={
                    "session_id": fake_id,
                    "connection_name": "My Chatbot",
                    "authenticated_selector": "#app",
                }
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "storage_state_path" in data
        assert data["storage_state_path"] == "auth-state-My_Chatbot.json"
        assert data["authentication_detected_before_save"] is True
        assert data["fresh_context_restored"] is True
        assert data["authenticated_ui_detected_after_restore"] is True

    def test_save_endpoint_unknown_session_returns_404(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.connections.browser_auth import BrowserAuthSaveResult

        async def mock_save(session_id: str, path: str, auth_check) -> BrowserAuthSaveResult:
            return BrowserAuthSaveResult(session_found=False)

        with patch("app.connections.api.browser_auth_manager") as mock_mgr:
            mock_mgr.save_verified_session = mock_save
            client = TestClient(app)
            resp = client.post(
                "/connections/browser-auth/save",
                json={"session_id": "bad-id", "connection_name": "x", "authenticated_selector": "#app"}
            )

        assert resp.status_code == 404

    def test_save_endpoint_requires_auth_check(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        resp = client.post(
            "/connections/browser-auth/save",
            json={"session_id": "session-id", "connection_name": "x"}
        )

        assert resp.status_code == 422

    def test_start_endpoint_500_on_error(self):
        from fastapi.testclient import TestClient
        from app.main import app

        async def mock_start(url: str) -> str:
            raise RuntimeError("Playwright crashed")

        with patch("app.connections.api.browser_auth_manager") as mock_mgr:
            mock_mgr.start_session = mock_start
            client = TestClient(app)
            resp = client.post(
                "/connections/browser-auth/start",
                json={"url": "https://example.com"}
            )

        assert resp.status_code == 500
