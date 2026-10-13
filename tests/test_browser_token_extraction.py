import pytest
import asyncio
from unittest.mock import AsyncMock, patch
import json

from app.connections.browser_auth import BrowserAuthManager

class PageMock(AsyncMock):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._handlers = {"request": [], "response": []}
    
    def on(self, event, handler):
        if event in self._handlers:
            self._handlers[event].append(handler)
            
    async def simulate_response(self, url, json_data=None, throws_json=False):
        res = AsyncMock()
        res.url = url
        if throws_json:
            res.json.side_effect = Exception("Malformed JSON")
        else:
            res.json.return_value = json_data or {}
        for h in self._handlers["response"]:
            await h(res)
            
    async def simulate_request(self, url, headers):
        req = AsyncMock()
        req.url = url
        req.headers = headers
        for h in self._handlers["request"]:
            await h(req)
            
    async def goto(self, url, **kwargs):
        # Sleep to keep the goto task pending while we simulate responses
        await asyncio.sleep(1.0)


@pytest.fixture
def mock_playwright():
    with patch("app.connections.browser_auth._new_context_with_extended_storage", new_callable=AsyncMock) as mock_new_ctx:
        with patch("playwright.async_api.async_playwright") as mock_pw:
            mock_pw_context = AsyncMock()
            mock_pw.return_value.start = AsyncMock(return_value=mock_pw_context)
            
            mock_browser = AsyncMock()
            mock_pw_context.chromium.launch.return_value = mock_browser
            
            mock_context = AsyncMock()
            mock_new_ctx.return_value = mock_context
            
            mock_page = PageMock()
            mock_context.new_page.return_value = mock_page
            
            # Prevent long timeouts during tests by patching wait_for if needed
            # Or we can just let it finish immediately when token_future is set
            
            yield {
                "page": mock_page
            }


def test_1_oauth_session_refresh_no_tokens_in_url(mock_playwright):
    async def run_test():
        page = mock_playwright["page"]
        manager = BrowserAuthManager()
        
        async def run_simulation():
            await asyncio.sleep(0.1)
            await page.simulate_response(
                url="https://client.example.com/oauth/session/refresh",
                json_data={"data": {"token": "secret123"}}
            )
        
        asyncio.create_task(run_simulation())
        
        token = await manager._thread._async_extract_browser_token(
            url="https://example.com",
            storage_state=None,
            intercept_pattern="*/oauth/session/*",
            token_path="data.token"
        )
        
        assert token == "secret123"
    asyncio.run(run_test())

def test_2_non_matching_response_ignored(mock_playwright):
    async def run_test():
        page = mock_playwright["page"]
        manager = BrowserAuthManager()
        
        with patch("asyncio.wait", return_value=([AsyncMock()], [])), \
             patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
             
            async def run_simulation():
                await asyncio.sleep(0.1)
                await page.simulate_response(
                    url="https://client.example.com/api/profile",
                    json_data={"data": {"token": "wrong_token"}}
                )
            
            asyncio.create_task(run_simulation())
            
            token = await manager._thread._async_extract_browser_token(
                url="https://example.com",
                storage_state=None,
                intercept_pattern="*/oauth/session/*",
                token_path="data.token"
            )
            
            assert token is None
    asyncio.run(run_test())

def test_3_existing_pattern_with_tokens_still_works(mock_playwright):
    async def run_test():
        page = mock_playwright["page"]
        manager = BrowserAuthManager()
        
        async def run_simulation():
            await asyncio.sleep(0.1)
            await page.simulate_response(
                url="https://api.sophia.com/v1/tokens/refresh",
                json_data={"jwt": "sophia_secret"}
            )
        
        asyncio.create_task(run_simulation())
        
        token = await manager._thread._async_extract_browser_token(
            url="https://example.com",
            storage_state=None,
            intercept_pattern="*tokens*",
            token_path="jwt"
        )
        
        assert token == "sophia_secret"
    asyncio.run(run_test())

def test_4_multiple_responses_only_matching_inspected(mock_playwright):
    async def run_test():
        page = mock_playwright["page"]
        manager = BrowserAuthManager()
        
        async def run_simulation():
            await asyncio.sleep(0.1)
            await page.simulate_response(
                url="https://api.client.com/status",
                json_data={"jwt": "bad_token"}
            )
            await page.simulate_response(
                url="https://api.client.com/metrics",
                json_data={"jwt": "worse_token"}
            )
            await page.simulate_response(
                url="https://api.client.com/auth/login",
                json_data={"jwt": "good_token"}
            )
        
        asyncio.create_task(run_simulation())
        
        token = await manager._thread._async_extract_browser_token(
            url="https://example.com",
            storage_state=None,
            intercept_pattern="*/auth/login",
            token_path="jwt"
        )
        
        assert token == "good_token"
    asyncio.run(run_test())

def test_5_matching_response_missing_token_path(mock_playwright):
    async def run_test():
        page = mock_playwright["page"]
        manager = BrowserAuthManager()
        
        with patch("asyncio.wait", return_value=([AsyncMock()], [])), \
             patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
             
            async def run_simulation():
                await asyncio.sleep(0.1)
                await page.simulate_response(
                    url="https://api.client.com/auth/login",
                    json_data={"other_field": "val"}
                )
            
            asyncio.create_task(run_simulation())
            
            token = await manager._thread._async_extract_browser_token(
                url="https://example.com",
                storage_state=None,
                intercept_pattern="*/auth/login",
                token_path="jwt"
            )
            
            assert token is None
    asyncio.run(run_test())

def test_6_matching_malformed_json_safe_failure(mock_playwright):
    async def run_test():
        page = mock_playwright["page"]
        manager = BrowserAuthManager()
        
        with patch("asyncio.wait", return_value=([AsyncMock()], [])), \
             patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
             
            async def run_simulation():
                await asyncio.sleep(0.1)
                await page.simulate_response(
                    url="https://api.client.com/auth/login",
                    throws_json=True
                )
            
            asyncio.create_task(run_simulation())
            
            token = await manager._thread._async_extract_browser_token(
                url="https://example.com",
                storage_state=None,
                intercept_pattern="*/auth/login",
                token_path="jwt"
            )
            
            assert token is None
    asyncio.run(run_test())

def test_7_token_not_logged(mock_playwright, caplog):
    async def run_test():
        page = mock_playwright["page"]
        manager = BrowserAuthManager()
        
        async def run_simulation():
            await asyncio.sleep(0.1)
            await page.simulate_response(
                url="https://api.client.com/auth/login",
                json_data={"jwt": "SUPER_SECRET_TOKEN_123"}
            )
        
        asyncio.create_task(run_simulation())
        
        token = await manager._thread._async_extract_browser_token(
            url="https://example.com",
            storage_state=None,
            intercept_pattern="*/auth/login",
            token_path="jwt"
        )
        
        assert token == "SUPER_SECRET_TOKEN_123"
        
        assert "SUPER_SECRET_TOKEN_123" not in caplog.text
        assert "DIAGNOSTIC" not in caplog.text
    asyncio.run(run_test())
