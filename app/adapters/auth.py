import abc
import base64
import json
import logging
import os
import re
import requests
import time
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

from app.connections.browser_token import resolve_browser_token_strategy
from app.session import BrowserSession

def _decode_jwt_iat_exp(header_value: Any) -> tuple[Optional[int], Optional[int]]:
    token = str(header_value or "").strip()
    if token.lower().startswith("bearer "):
        token = token.split(" ", 1)[1].strip()
    if token.lower().startswith("bearer "):
        token = token.split(" ", 1)[1].strip()
    parts = token.split(".")
    if len(parts) < 2:
        return None, None
    try:
        payload_segment = parts[1]
        padding = "=" * (-len(payload_segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode((payload_segment + padding).encode("ascii")).decode("utf-8"))
        iat = payload.get("iat")
        exp = payload.get("exp")
        return int(iat) if iat is not None else None, int(exp) if exp is not None else None
    except Exception:
        logger.warning("[JWT LIFECYCLE] Failed to decode JWT iat/exp without verification.")
        return None, None

def _is_legacy_sophia_browser_token(config: dict[str, Any], auth: dict[str, Any]) -> bool:
    if auth.get("type") != "browser_token":
        return False
    endpoint = str(config.get("endpoint") or config.get("base_url") or "")
    return "tribe-gateway.archietech.co/owners/api/v1/admin/sophia/ask" in endpoint

def _parse_path(path: str) -> list:
    path = re.sub(r'\[(\d+)\]', r'.\1', path)
    return [int(k) if isinstance(k, str) and k.isdigit() else k for k in path.split('.') if k]

def get_by_path(d: Any, path: str, default: Any = None) -> Any:
    if not path:
        return default
    keys = _parse_path(path)
    current = d
    for i, key in enumerate(keys):
        if isinstance(current, dict):
            if isinstance(key, str) and key.endswith("[]"):
                actual_key = key[:-2]
                if actual_key in current and isinstance(current[actual_key], list):
                    remaining_path = ".".join(str(k) for k in keys[i+1:]) if i + 1 < len(keys) else ""
                    if not remaining_path:
                        return current[actual_key]
                    for item in current[actual_key]:
                        val = get_by_path(item, remaining_path, default=None)
                        if val is not None and val != "":
                            return val
                    return default
                else:
                    return default
            elif key in current:
                current = current[key]
            else:
                return default
        elif isinstance(current, list):
            if isinstance(key, int) and 0 <= key < len(current):
                current = current[key]
            else:
                return default
        else:
            return default
    return current


class AuthProvider(abc.ABC):
    @abc.abstractmethod
    def get_headers(self) -> dict[str, str]:
        """Returns headers required for authentication."""
        pass
        
    @abc.abstractmethod
    def refresh_if_needed(self) -> None:
        """Refreshes the token if it is close to expiration."""
        pass


class StaticAuthProvider(AuthProvider):
    def __init__(self, auth_config: dict[str, Any], adapter_config: dict[str, Any]):
        self.headers = {}
        auth_type = auth_config.get("type")
        auth_val = auth_config.get("value")
        
        resolved_val = auth_val
        if auth_val and isinstance(auth_val, str) and auth_val.startswith("env:"):
            env_key = auth_val[4:]
            resolved_val = os.environ.get(env_key)
            if not resolved_val:
                raise ValueError(f"Authentication configuration error: Environment variable '{env_key}' not found.")
        
        if resolved_val:
            if auth_type == "bearer":
                self.headers["Authorization"] = f"Bearer {resolved_val}"
            elif auth_type == "api_key":
                api_key_header = adapter_config.get("api_key_header", "Authorization")
                self.headers[api_key_header] = resolved_val

    def get_headers(self) -> dict[str, str]:
        return self.headers
        
    def refresh_if_needed(self) -> None:
        pass


class DynamicRestProvider(AuthProvider):
    def __init__(self, auth_config: dict[str, Any], adapter_config: dict[str, Any]):
        self.auth_config = auth_config
        self.adapter_config = adapter_config
        self.header_name = auth_config.get("header_name", "Authorization")
        self.header_format = auth_config.get("header_format", "Bearer {token}")
        self.headers = {}
        self._resolve_token()
        
    def _resolve_token(self):
        storage_state = self.auth_config.get("storage_state") or self.adapter_config.get("storage_state")
        if storage_state and not os.path.exists(storage_state):
            logger.warning(f"Browser storage state file not found: {storage_state}")
            
        cookies = {}
        if storage_state and os.path.exists(storage_state):
            try:
                with open(storage_state, 'r') as f:
                    state_data = json.load(f)
                    for c in state_data.get("cookies", []):
                        cookies[c["name"]] = c["value"]
            except Exception as e:
                logger.error(f"Failed to read storage state for dynamic auth: {e}")
        
        variables = {}
        token = None
        
        steps = self.auth_config.get("steps", [])
        for i, step in enumerate(steps):
            url = step.get("url", "")
            for k, v in variables.items():
                url = url.replace(f"{{{k}}}", str(v))
                
            method = step.get("method", "GET")
            step_headers = step.get("headers", {})
            payload = step.get("body")
            
            logger.info(f"[DIAGNOSTIC] Dynamic auth step {i+1}: {method} {url}")
            
            try:
                res = requests.request(method, url, json=payload, headers=step_headers, cookies=cookies, timeout=self.adapter_config.get("timeout", 30))
                res.raise_for_status()
                data = res.json()
                
                extract_vars = step.get("extract", {})
                for var_name, path in extract_vars.items():
                    val = get_by_path(data, path)
                    if val is not None:
                        variables[var_name] = val
                        
                token_path = step.get("extract_token")
                if token_path:
                    token = get_by_path(data, token_path)
            except Exception as e:
                logger.error(f"Dynamic auth step {i+1} failed: {e}")
                raise ValueError(f"Dynamic token fetching failed at step {i+1}: {e}")
                
        if token:
            self.headers[self.header_name] = self.header_format.replace("{token}", str(token))
            logger.info(f"[DIAGNOSTIC] Successfully resolved dynamic token")
        else:
            raise ValueError("Failed to extract dynamic token from steps")

    def get_headers(self) -> dict[str, str]:
        return self.headers

    def refresh_if_needed(self) -> None:
        # Dynamic REST logic might need refresh eventually, but keeping backward compatibility
        pass


class BrowserTokenProvider(AuthProvider):
    def __init__(
        self,
        auth_config: dict[str, Any],
        adapter_config: dict[str, Any],
        browser_session: BrowserSession,
    ):
        if browser_session is None:
            raise ValueError("BrowserTokenProvider requires a BrowserSession.")
        self.auth_config = auth_config
        self.adapter_config = adapter_config
        self.effective_auth = self._browser_token_compat_auth(auth_config)
        self.browser_session = browser_session
        self.header_name = self.effective_auth.get("header_name") or "Authorization"
        self.header_format = self.effective_auth.get("header_format") or "Bearer {token}"
        self.headers = {}
        self.exp = None
        self.iat = None
        
        token = self._extract_browser_token(self.effective_auth)
        self._set_token(token, source="initial")

    def _browser_token_compat_auth(self, auth: dict) -> dict:
        if not _is_legacy_sophia_browser_token(self.adapter_config, auth):
            return auth

        compat = dict(auth)
        compat.pop("script", None)
        compat["intercept_pattern"] = "*://tribe-gateway.archietech.co/owners/api/v1/admin/*"
        compat["token_path"] = "header:authorization"
        compat["header_name"] = auth.get("header_name") or "Authorization"
        compat["header_format"] = auth.get("header_format") or "Bearer {token}"
        logger.info("[DIAGNOSTIC] Using legacy Sophia browser-token header capture compatibility path.")
        return compat

    def _extract_browser_token(self, effective_auth: dict) -> Any:
        url = self.adapter_config.get("browser_login_url") or effective_auth.get("url")
        storage_state = effective_auth.get("storage_state") or self.adapter_config.get("storage_state")
        if not url:
            raise ValueError("Browser token auth requires 'url'")

        extraction = resolve_browser_token_strategy(effective_auth)
        trigger_script = effective_auth.get("trigger_script")
        delete_cookies = effective_auth.get("delete_cookies")

        return self.browser_session.get_token(
            url=url,
            storage_state=storage_state,
            script=extraction.script if extraction.strategy == "script" else None,
            intercept_pattern=extraction.intercept_pattern if extraction.strategy == "network" else None,
            token_path=extraction.token_path if extraction.strategy == "network" else None,
            trigger_script=trigger_script if extraction.strategy == "network" else None,
            delete_cookies=delete_cookies,
            strategy=extraction.strategy,
        )

    def _set_token(self, token: Any, *, source: str) -> None:
        if token:
            header_val = self.header_format.replace("{token}", str(token))
            self.headers[self.header_name] = header_val
            self.iat, self.exp = _decode_jwt_iat_exp(header_val)
            logger.info(
                "[JWT LIFECYCLE] Browser token resolved source=%s iat=%s exp=%s",
                source,
                self.iat,
                self.exp,
            )
            print(f"[JWT LIFECYCLE] token source={source} iat={self.iat} exp={self.exp}")
            logger.info(f"[DIAGNOSTIC] Successfully resolved browser token")
        else:
            raise ValueError("Failed to extract browser token")

    def get_headers(self) -> dict[str, str]:
        return self.headers

    def refresh_if_needed(self) -> None:
        now = int(time.time())
        exp = self.exp
        seconds_remaining = exp - now if exp is not None else None
        current_utc = datetime.now(timezone.utc).isoformat()
        logger.info(
            "[JWT LIFECYCLE] pre_request utc=%s exp=%s seconds_remaining=%s",
            current_utc,
            exp,
            seconds_remaining,
        )
        print(f"[JWT LIFECYCLE] utc={current_utc} exp={exp} seconds_remaining={seconds_remaining}")

        # If token has no exp claim and we already have a token in headers, don't attempt blind refresh
        if exp is None and self.headers.get(self.header_name):
            return

        if exp is not None and seconds_remaining is not None and seconds_remaining >= 10:
            return
            
        logger.info("[JWT LIFECYCLE] Refreshing browser token before request; exp=%s seconds_remaining=%s", exp, seconds_remaining)
        try:
            token = self._extract_browser_token(self.effective_auth)
            if token:
                self._set_token(token, source="refresh")
            else:
                logger.warning("[JWT LIFECYCLE] Token refresh returned None; checking existing token")
                if not self.headers.get(self.header_name):
                    raise ValueError("Failed to extract browser token")
        except Exception as exc:
            logger.error("[JWT LIFECYCLE] Failed to refresh browser token: %s", exc)
            if not self.headers.get(self.header_name):
                raise ValueError("Failed to extract browser token") from exc


def create_auth_provider(
    adapter_config: dict[str, Any],
    browser_session: BrowserSession | None = None,
) -> Optional[AuthProvider]:
    auth = adapter_config.get("auth", {})
    if not auth:
        return None
        
    auth_type = auth.get("type")
    
    if auth_type == "dynamic_rest":
        return DynamicRestProvider(auth, adapter_config)
    elif auth_type == "browser_token":
        if browser_session is None:
            raise ValueError("BrowserTokenProvider requires a BrowserSession.")
        return BrowserTokenProvider(auth, adapter_config, browser_session=browser_session)
    else:
        return StaticAuthProvider(auth, adapter_config)
