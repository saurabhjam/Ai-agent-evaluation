import asyncio
import logging
import mimetypes
import os
import sys
import threading
import time
from concurrent.futures import Future
from typing import Any, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.adapters.chat.base import (
    ButtonDisabled,
    ButtonHidden,
    ButtonNotFound,
    BrowserClosed,
    ChatAdapterCapabilities,
    ChatAdapterError,
    ChatAdapterTimeout,
    ChatAdapter,
    ControlDisabled,
    ControlHidden,
    ExpectedTextNotFound,
    FieldNotFound,
    MultipleControlsFound,
    MultipleButtonsFound,
    OptionNotFound,
    UploadFieldNotFound,
    UploadFileNotFound,
)
from app.models.conversation import ConversationMessage, NormalizedConversation, RAGEvidence
from app.rag import extract_rag_evidence

logger = logging.getLogger(__name__)


def _ui_validation_expectations(agent_text: str | None) -> dict[str, bool]:
    text = str(agent_text or "").lower()
    return {
        "expects_form": any(word in text for word in ("form", "fill out", "complete", "provide details")),
        "expects_upload": any(word in text for word in ("upload", "attach", "share", "send", "provide", "include"))
        and any(word in text for word in ("photo", "image", "picture", "screenshot", "file", "document", "video")),
        "expects_otp": any(word in text for word in ("otp", "verification code", "passcode", "one-time")),
        "expects_date": "date" in text,
        "expects_time": "time" in text,
    }


def _ui_validation_result(scan: dict[str, Any], agent_text: str | None) -> dict[str, Any]:
    summary = scan.get("summary") if isinstance(scan.get("summary"), dict) else {}
    expectations = _ui_validation_expectations(agent_text)
    checks: list[bool] = []
    if expectations["expects_form"]:
        checks.append(bool(summary.get("form_detected") or summary.get("fields_detected")))
    if expectations["expects_upload"]:
        checks.append(bool(summary.get("upload_control_detected")))
    if expectations["expects_otp"]:
        checks.append(bool(summary.get("otp_field_detected")))
    if expectations["expects_date"]:
        checks.append(bool(summary.get("date_field_detected")))
    if expectations["expects_time"]:
        checks.append(bool(summary.get("time_field_detected")))

    validation = {
        "forms": scan.get("forms") or [],
        "inputs": scan.get("inputs") or [],
        "buttons": scan.get("buttons") or [],
        "summary": summary,
        "expectations": expectations,
    }
    success = all(checks) if checks else True
    should_emit_evidence = bool(any(expectations.values()))
    evidence = None
    if should_emit_evidence:
        first_form = next((form for form in validation["forms"] if isinstance(form, dict)), {})
        evidence = {
            "interaction_type": "ui_validation",
            "action": "Browser UI validation",
            "success": success,
            "status": "SUCCESS" if success else "FAILED",
            "requested_by_agent": agent_text,
            "form_detected": bool(summary.get("form_detected")),
            "form_name": first_form.get("title") or first_form.get("name"),
            "fields_detected": int(summary.get("fields_detected") or 0),
            "submit_button_detected": bool(summary.get("submit_button_detected")),
            "upload_control_detected": bool(summary.get("upload_control_detected")),
            "accept": summary.get("accept"),
            "camera_available": bool(summary.get("camera_available")),
            "otp_field_detected": bool(summary.get("otp_field_detected")),
            "date_field_detected": bool(summary.get("date_field_detected")),
            "time_field_detected": bool(summary.get("time_field_detected")),
            "search_field_detected": bool(summary.get("search_field_detected")),
            "buttons_detected": int(summary.get("buttons_detected") or 0),
            "ui_validation": validation,
        }
        missing = []
        if expectations["expects_form"] and not (summary.get("form_detected") or summary.get("fields_detected")):
            missing.append("form")
        if expectations["expects_upload"] and not summary.get("upload_control_detected"):
            missing.append("upload control")
        if expectations["expects_otp"] and not summary.get("otp_field_detected"):
            missing.append("otp field")
        if expectations["expects_date"] and not summary.get("date_field_detected"):
            missing.append("date field")
        if expectations["expects_time"] and not summary.get("time_field_detected"):
            missing.append("time field")
        if missing:
            evidence["error"] = "Expected UI not found: " + ", ".join(missing)
    return {"ui_validation": validation, "interaction_evidence": evidence}


def _upload_bytes(upload: dict[str, Any]) -> bytes:
    data = upload.get("buffer", upload.get("data", upload.get("content", b"")))
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    if isinstance(data, str):
        import base64
        try:
            return base64.b64decode(data)
        except Exception:
            return data.encode("utf-8")
    return b""


def _upload_display_name(upload: Any) -> str:
    if isinstance(upload, dict):
        return os.path.basename(str(upload.get("filename") or upload.get("name") or "image"))
    return os.path.basename(str(upload))


def _playwright_upload_value(upload: Any) -> Any:
    if not isinstance(upload, dict):
        return upload
    name = upload.get("filename") or upload.get("name") or "image"
    mime_type = upload.get("mime_type") or upload.get("mimeType") or upload.get("type") or mimetypes.guess_type(str(name))[0]
    return {
        "name": os.path.basename(str(name)),
        "mimeType": mime_type or "application/octet-stream",
        "buffer": _upload_bytes(upload),
    }

class _BrowserThread(threading.Thread):
    """
    Daemon thread that runs a private asyncio event loop compatible with
    Playwright on Windows (ProactorEventLoop) and non-Windows platforms.
    """
    def __init__(self) -> None:
        super().__init__(name="browser-adapter-thread", daemon=True)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()

    def run(self) -> None:
        if sys.platform == "win32":
            self._loop = asyncio.ProactorEventLoop()
        else:
            self._loop = asyncio.new_event_loop()

        asyncio.set_event_loop(self._loop)
        self._ready.set()
        logger.info("BrowserChatAdapter: Playwright thread started (loop=%s)", type(self._loop).__name__)
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()
            logger.info("BrowserChatAdapter: Playwright thread stopped")

    def _ensure_started(self) -> None:
        if not self.is_alive():
            self.start()
            self._ready.wait(timeout=5)

    def dispatch(self, coro) -> Future:
        """Submit a coroutine to the Playwright loop and return a concurrent.futures.Future."""
        self._ensure_started()
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self) -> None:
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)


class BrowserChatAdapter(ChatAdapter):
    """
    Generic Browser Adapter interface using Playwright Async API inside a dedicated thread.
    This architecture prevents "Sync API inside the asyncio loop" errors when called
    from FastAPI endpoints.
    """
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.url = self.config.get("url") or self.config.get("base_url")
        self.selectors = self.config.get("selectors", {})
        self.browser_config = self.config.get("browser", {})
        self.interaction = self.config.get("interaction", {})
        
        self.input_selector = self.selectors.get("input")
        self.submit_selector = self.selectors.get("submit")
        self.response_selector = self.selectors.get("response")
        self.launcher_selector = self.selectors.get("launcher")
        
        self.transcript: list[ConversationMessage] = []
        self.run_id = "browser-run"
        self.session_id = "browser-session"
        self._last_response_rag_evidence: Optional[RAGEvidence] = None
        
        # Async Playwright state (accessed only via the _BrowserThread)
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        
        # Dedicated thread for playwright execution
        self._thread = _BrowserThread()
        
        # Validate config
        if not self.url or not self.input_selector or not self.response_selector:
            missing = []
            if not self.url: missing.append("url")
            if not self.input_selector: missing.append("selectors.input")
            if not self.response_selector: missing.append("selectors.response")
            raise ValueError(f"Browser adapter requires: {', '.join(missing)}")

    @property
    def capabilities(self) -> ChatAdapterCapabilities:
        caps = ChatAdapterCapabilities()
        caps.supports_browser = True
        caps.supports_session_history = True
        caps.supports_click_button = True
        caps.supports_select_dropdown = True
        caps.supports_select_radio = True
        caps.supports_select_checkbox = True
        caps.supports_select_multi_select = True
        caps.supports_file_upload = True
        caps.supports_upload_file = True
        caps.supports_upload_image = True
        caps.supports_enter_otp = True
        caps.supports_pick_date = True
        caps.supports_pick_time = True
        caps.supports_search = True
        caps.supports_wait_for_text = True
        return caps

    async def _async_connect(self) -> None:
        logger.info(f"BrowserChatAdapter connecting to {self.url}...")
            
        self.playwright = await async_playwright().start()
        headless = self.browser_config.get("headless", True)
        self.browser = await self.playwright.chromium.launch(headless=headless)
        
        context_kwargs = {}
        storage_state = self.browser_config.get("storage_state") or self.config.get("storage_state")
        if storage_state:
            if os.path.exists(storage_state):
                context_kwargs["storage_state"] = storage_state
            else:
                logger.warning(f"Browser storage state file not found: {storage_state}")
                
        self.context = await self.browser.new_context(**context_kwargs)
        
        cookies = self.browser_config.get("cookies") or self.config.get("cookies")
        if cookies:
            await self.context.add_cookies(cookies)
            
        self.page = await self.context.new_page()
        
        try:
            timeout_ms = self.browser_config.get("timeout_ms", 30000)
            await self.page.goto(self.url, timeout=timeout_ms, wait_until="domcontentloaded")
            
            # Diagnostic logging after navigation
            final_url = self.page.url
            title = await self.page.title()
            input_count = await self.page.locator(self.input_selector).count()
            
            logger.info(f"[DIAGNOSTIC] After goto - Final URL: {final_url}")
            logger.info(f"[DIAGNOSTIC] After goto - Title: {title}")
            logger.info(f"[DIAGNOSTIC] After goto - Input count: {input_count}")
            
            # Redirect to login check
            if "login" in final_url.lower() or "signin" in final_url.lower() or "auth" in final_url.lower():
                raise ValueError("Browser authentication state is not valid or the target redirected to login.")
            
            if self.launcher_selector:
                logger.info(f"Clicking launcher selector: {self.launcher_selector}")
                await self.page.click(self.launcher_selector, timeout=timeout_ms)
                
            # Generic readiness: wait for input to be attached and visible
            logger.info(f"[DIAGNOSTIC] Waiting for input '{self.input_selector}' to become visible...")
            input_loc = self.page.locator(self.input_selector).first
            await input_loc.wait_for(state="visible", timeout=timeout_ms)
        except PlaywrightTimeoutError as e:
            await self._async_close()
            raise ValueError(f"Failed to load URL and become ready within timeout: {e}")
        except Exception as e:
            import traceback
            logger.error(f"Failed to load URL or become ready: {traceback.format_exc()}")
            await self._async_close()
            raise
            
        logger.info("Browser connection established and page is ready.")

    def connect(self) -> None:
        future = self._thread.dispatch(self._async_connect())
        future.result(timeout=self.browser_config.get("timeout_ms", 30000) / 1000.0 + 10)

    async def _wait_for_new_response(self, initial_count: int, initial_text: str, timeout_ms: int) -> str:
        if not self.page:
            raise RuntimeError("Browser page is not connected.")

        loc = self.page.locator(self.response_selector)
        start_time = time.time()
        response_text = ""
        response_loc = None

        while time.time() - start_time < (timeout_ms / 1000.0):
            await self.page.wait_for_timeout(500)
            current_count = await loc.count()

            if current_count > initial_count:
                response_loc = loc.last
                response_text = await response_loc.inner_text()
                response_text = response_text.strip()
                break
            elif current_count > 0:
                response_loc = loc.last
                current_text = await response_loc.inner_text()
                current_text = current_text.strip()
                if current_text and current_text != initial_text:
                    response_text = current_text
                    break

        if not response_text:
            raise ChatAdapterTimeout("Response timeout or empty agent response after browser interaction.")

        wait_ms = self.interaction.get("response_wait_ms", 0)
        if wait_ms > 0:
            await self.page.wait_for_timeout(wait_ms)
            response_loc = loc.last
            response_text = await response_loc.inner_text()
            response_text = response_text.strip()

        self._last_response_rag_evidence = await self._extract_rag_evidence_from_response(response_loc)
        return response_text

    async def _extract_rag_evidence_from_response(self, response_loc) -> Optional[RAGEvidence]:
        config = getattr(self, "config", {}) or {}
        rag_config = config.get("rag_config") or config.get("rag") or {}
        if not rag_config or rag_config.get("enabled") is False or response_loc is None:
            return None

        try:
            await self._expand_rag_sources(response_loc, rag_config)
            await self._wait_for_rag_evidence(response_loc, rag_config)
            contexts = await self._collect_visible_texts(response_loc, rag_config.get("context_selector"))
            citations = await self._collect_citations(response_loc, rag_config)

            if not contexts and not citations:
                return None

            source = str(rag_config.get("source_type") or rag_config.get("source") or "agent_retrieval")
            metadata = {
                key: value
                for key, value in rag_config.items()
                if key not in {
                    "enabled",
                    "context_selector",
                    "citation_selector",
                    "citation_title_selector",
                    "citation_url_selector",
                    "citation_label_selector",
                    "expand_selector",
                    "evidence_timeout_ms",
                    "timeout_ms",
                }
            }

            if contexts:
                evidence = extract_rag_evidence(
                    {"contexts": contexts, "citations": citations},
                    {
                        "rag_config": {
                            "enabled": True,
                            "context_path": "contexts",
                            "citation_path": "citations",
                            "source_type": source,
                            **metadata,
                        }
                    },
                )
                if evidence:
                    return evidence

            return RAGEvidence(
                available=True,
                source=source,
                contexts=[],
                citations=citations or None,
                metadata=metadata or None,
            )
        except Exception as exc:
            logger.warning("Browser RAG evidence extraction failed: %s", type(exc).__name__)
            return None

    async def _expand_rag_sources(self, response_loc, rag_config: dict[str, Any]) -> None:
        expand_selector = rag_config.get("expand_selector")
        if not expand_selector:
            return
        try:
            expand = response_loc.locator(expand_selector).first
            if await expand.is_visible() and await expand.is_enabled():
                await expand.click(timeout=int(rag_config.get("expand_timeout_ms") or 1000))
        except Exception as exc:
            logger.debug("Browser RAG source expansion skipped: %s", type(exc).__name__)

    async def _wait_for_rag_evidence(self, response_loc, rag_config: dict[str, Any]) -> None:
        timeout_ms = int(rag_config.get("evidence_timeout_ms") or rag_config.get("timeout_ms") or 0)
        selector = rag_config.get("context_selector") or rag_config.get("citation_selector")
        if timeout_ms <= 0 or not selector:
            return
        try:
            await response_loc.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
        except Exception as exc:
            logger.debug("Browser RAG evidence wait ended without visible evidence: %s", type(exc).__name__)

    async def _collect_visible_texts(self, response_loc, selector: Optional[str]) -> list[str]:
        if not selector:
            return []
        locator = response_loc.locator(selector)
        count = await locator.count()
        texts: list[str] = []
        seen: set[str] = set()
        for index in range(count):
            item = locator.nth(index)
            if not await item.is_visible():
                continue
            text = (await item.inner_text()).strip()
            if text and text not in seen:
                seen.add(text)
                texts.append(text)
        return texts

    async def _collect_citations(self, response_loc, rag_config: dict[str, Any]) -> list[dict[str, Any]]:
        selector = rag_config.get("citation_selector")
        if not selector:
            return []
        locator = response_loc.locator(selector)
        count = await locator.count()
        citations: list[dict[str, Any]] = []
        for index in range(count):
            item = locator.nth(index)
            if not await item.is_visible():
                continue
            label = await self._first_visible_text(item, rag_config.get("citation_label_selector"))
            title = await self._first_visible_text(item, rag_config.get("citation_title_selector"))
            url = await self._first_attribute(item, rag_config.get("citation_url_selector"), "href")
            fallback_text = (await item.inner_text()).strip()

            citation = {
                key: value
                for key, value in {
                    "label": label or fallback_text or None,
                    "title": title,
                    "url": url,
                }.items()
                if value
            }
            if citation:
                citations.append(citation)
        return citations

    async def _first_visible_text(self, item, selector: Optional[str]) -> Optional[str]:
        if not selector:
            return None
        locator = item.locator(selector)
        count = await locator.count()
        if count == 0:
            return None
        first = locator.first
        if not await first.is_visible():
            return None
        text = (await first.inner_text()).strip()
        return text or None

    async def _first_attribute(self, item, selector: Optional[str], attr: str) -> Optional[str]:
        if not selector:
            return None
        locator = item.locator(selector)
        count = await locator.count()
        if count == 0:
            return None
        first = locator.first
        if not await first.is_visible():
            return None
        value = await first.get_attribute(attr)
        return value.strip() if isinstance(value, str) and value.strip() else None

    async def _async_scan_ui_validation(self, agent_text: str | None) -> dict[str, Any]:
        if not self.page:
            raise BrowserClosed("Browser page is not connected.")

        await self.page.wait_for_timeout(int(self.interaction.get("ui_validation_stability_ms") or 300))
        scan = await self.page.evaluate(
            """() => {
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const box = el.getBoundingClientRect();
                    return style.display !== "none" && style.visibility !== "hidden" && box.width > 0 && box.height > 0;
                };
                const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
                const labelFor = (el) => {
                    const aria = clean(el.getAttribute("aria-label"));
                    if (aria) return aria;
                    if (el.labels && el.labels.length) {
                        const text = clean(Array.from(el.labels).map(label => label.innerText).join(" "));
                        if (text) return text;
                    }
                    const wrappingLabel = el.closest("label");
                    if (wrappingLabel) {
                        const text = clean(wrappingLabel.innerText);
                        if (text) return text;
                    }
                    const placeholder = clean(el.getAttribute("placeholder"));
                    if (placeholder) return placeholder;
                    return clean(el.getAttribute("name") || el.id || el.getAttribute("data-testid"));
                };
                const fieldType = (el) => {
                    const tag = el.tagName.toLowerCase();
                    const rawType = tag === "textarea" ? "textarea" : (tag === "select" ? "dropdown" : clean(el.getAttribute("type") || "text").toLowerCase());
                    const haystack = clean([labelFor(el), el.getAttribute("name"), el.id, el.getAttribute("autocomplete")].join(" ")).toLowerCase();
                    if (rawType === "file") {
                        const accept = clean(el.getAttribute("accept")).toLowerCase();
                        if (accept.includes("image")) return "image_upload";
                        if (accept.includes("video")) return "video_upload";
                        if (accept.includes("audio")) return "audio_upload";
                        return "file_upload";
                    }
                    if (haystack.includes("otp") || haystack.includes("verification code") || haystack.includes("passcode")) return "otp";
                    return rawType;
                };
                const inputNodes = Array.from(document.querySelectorAll("input, textarea, select")).filter(visible);
                const inputs = inputNodes.map((el) => ({
                    label: labelFor(el),
                    name: clean(el.getAttribute("name")),
                    id: clean(el.id),
                    type: fieldType(el),
                    required: !!el.required || el.getAttribute("aria-required") === "true",
                    placeholder: clean(el.getAttribute("placeholder")),
                    accept: clean(el.getAttribute("accept")),
                    capture: clean(el.getAttribute("capture")),
                    disabled: !!el.disabled || el.getAttribute("aria-disabled") === "true"
                }));
                const buttonNodes = Array.from(document.querySelectorAll("button, [role='button'], input[type='button'], input[type='submit'], input[type='reset']")).filter(visible);
                const buttons = buttonNodes.map((el) => ({
                    text: clean(el.innerText || el.value || el.getAttribute("aria-label")),
                    type: clean(el.getAttribute("type") || el.getAttribute("role") || "button"),
                    disabled: !!el.disabled || el.getAttribute("aria-disabled") === "true"
                })).filter((button) => button.text);
                const forms = Array.from(document.querySelectorAll("form")).filter(visible).map((form) => {
                    const titleNode = form.querySelector("legend, h1, h2, h3, [data-title], [aria-label]");
                    const fields = Array.from(form.querySelectorAll("input, textarea, select")).filter(visible).map((el) => ({
                        label: labelFor(el),
                        name: clean(el.getAttribute("name")),
                        type: fieldType(el),
                        required: !!el.required || el.getAttribute("aria-required") === "true",
                        accept: clean(el.getAttribute("accept"))
                    }));
                    const submit = Array.from(form.querySelectorAll("button, input[type='submit'], [role='button']")).filter(visible).map((el) => clean(el.innerText || el.value || el.getAttribute("aria-label"))).find(Boolean) || "";
                    return {
                        title: clean(titleNode && (titleNode.innerText || titleNode.getAttribute("aria-label") || titleNode.getAttribute("data-title"))),
                        fields,
                        submit_button: submit
                    };
                });
                const uploadInputs = inputs.filter((field) => ["file_upload", "image_upload", "video_upload", "audio_upload"].includes(field.type));
                const accept = uploadInputs.map((field) => field.accept).filter(Boolean).join(", ");
                return {
                    forms,
                    inputs,
                    buttons,
                    summary: {
                        form_detected: forms.length > 0,
                        fields_detected: inputs.length,
                        submit_button_detected: buttons.some((button) => /submit|send|continue|next|done|finish/i.test(button.text)) || forms.some((form) => form.submit_button),
                        upload_control_detected: uploadInputs.length > 0,
                        accept,
                        camera_available: uploadInputs.some((field) => field.capture || field.accept.includes("image")),
                        otp_field_detected: inputs.some((field) => field.type === "otp"),
                        date_field_detected: inputs.some((field) => field.type === "date" || field.type === "datetime-local"),
                        time_field_detected: inputs.some((field) => field.type === "time" || field.type === "datetime-local"),
                        search_field_detected: inputs.some((field) => field.type === "search"),
                        buttons_detected: buttons.length
                    }
                };
            }"""
        )
        if not isinstance(scan, dict):
            scan = {}
        return _ui_validation_result(scan, agent_text)

    def _agent_metadata(self, response_text: str) -> dict[str, Any] | None:
        if self.interaction.get("ui_validation_enabled", True) is False or not self.page:
            return None
        timeout_ms = int(self.interaction.get("ui_validation_timeout_ms") or 2000)
        try:
            future = self._thread.dispatch(self._async_scan_ui_validation(response_text))
            result = future.result(timeout=(timeout_ms / 1000.0) + 2)
        except Exception as exc:
            logger.warning("Browser UI validation scan failed: %s", type(exc).__name__)
            result = {
                "ui_validation": {"error": str(exc)},
                "interaction_evidence": {
                    "interaction_type": "ui_validation",
                    "action": "Browser UI validation",
                    "success": False,
                    "status": "FAILED",
                    "requested_by_agent": response_text,
                    "error": str(exc),
                },
            }
        metadata = {"ui_validation": result.get("ui_validation")}
        evidence = result.get("interaction_evidence")
        if evidence:
            metadata["interaction_evidence"] = evidence
        return metadata

    async def _async_send_message(self, message: str, timeout_ms: int) -> str:
        if not self.page:
            raise RuntimeError("Browser page is not connected.")
            
        logger.info(f"Sending message via Browser: {message}")
        
        try:
            # 1. Count existing response elements
            loc = self.page.locator(self.response_selector)
            initial_count = await loc.count()
            initial_text = await loc.last.inner_text() if initial_count > 0 else ""
            initial_text = initial_text.strip()
            
            # Diagnostics before fill
            input_loc = self.page.locator(self.input_selector).first
            input_visible = await input_loc.is_visible() if await input_loc.count() > 0 else False
            input_enabled = await input_loc.is_enabled() if input_visible else False
            
            logger.info(f"[DIAGNOSTIC] _async_send_message - URL: {self.page.url}")
            logger.info(f"[DIAGNOSTIC] _async_send_message - Title: {await self.page.title()}")
            logger.info(f"[DIAGNOSTIC] _async_send_message - Input visible: {input_visible}, enabled: {input_enabled}")
            logger.info(f"[DIAGNOSTIC] _async_send_message - Storage config: {self.browser_config.get('storage_state') or self.config.get('storage_state')}")

            if not input_visible:
                # Capture screenshot
                screenshot_path = "debug_screenshot.png"
                await self.page.screenshot(path=screenshot_path)
                logger.error(f"Input is not visible! Saved screenshot to {screenshot_path}")

            # 2. Type message
            await self.page.fill(self.input_selector, message, timeout=timeout_ms)
            
            # 3. Submit
            submit_mode = self.interaction.get("submit_mode", "click")
            if submit_mode == "enter":
                await self.page.press(self.input_selector, "Enter", timeout=timeout_ms)
            else:
                if not self.submit_selector:
                    raise ValueError("submit selector is required for click mode")
                await self.page.click(self.submit_selector, timeout=timeout_ms)

            return await self._wait_for_new_response(initial_count, initial_text, timeout_ms)
            
        except PlaywrightTimeoutError as e:
            raise ChatAdapterTimeout(f"Browser interaction timeout: {e}")
        except Exception as e:
            import traceback
            logger.error(f"Browser interaction failed: {traceback.format_exc()}")
            raise

    async def _async_click_button(self, *, text: Optional[str], selector: Optional[str], timeout_ms: int) -> str:
        if not self.page:
            raise RuntimeError("Browser page is not connected.")

        loc = self.page.locator(self.response_selector)
        initial_count = await loc.count()
        initial_text = await loc.last.inner_text() if initial_count > 0 else ""
        initial_text = initial_text.strip()

        if selector:
            button = self.page.locator(selector)
            lookup_description = f"selector '{selector}'"
        elif text:
            button = self.page.get_by_role("button", name=text, exact=True)
            if await button.count() == 0:
                button = self.page.get_by_role("button").filter(has_text=text)
            lookup_description = f"text '{text}'"
        else:
            raise ButtonNotFound("click_button requires either selector or text.")

        count = await button.count()
        if count == 0:
            raise ButtonNotFound(f"Button not found for {lookup_description}.")
        if count > 1:
            raise MultipleButtonsFound(f"Multiple buttons matched {lookup_description}: {count}.")

        target = button.first
        if not await target.is_visible():
            raise ButtonHidden(f"Button matched {lookup_description} but is hidden.")
        if not await target.is_enabled():
            raise ButtonDisabled(f"Button matched {lookup_description} but is disabled.")

        try:
            await target.click(timeout=timeout_ms)
        except PlaywrightTimeoutError as e:
            raise ChatAdapterTimeout(f"Timed out clicking button for {lookup_description}: {e}") from e

        return await self._wait_for_new_response(initial_count, initial_text, timeout_ms)

    def _control_lookup_description(
        self,
        *,
        selector: Optional[str],
        field: Optional[str],
        placeholder: Optional[str],
        name: Optional[str] = None,
    ) -> str:
        if selector:
            return f"selector '{selector}'"
        if field:
            return f"label '{field}'"
        if placeholder:
            return f"placeholder '{placeholder}'"
        if name:
            return f"name '{name}'"
        return "unspecified field"

    async def _locate_control(
        self,
        *,
        selector: Optional[str],
        field: Optional[str],
        placeholder: Optional[str] = None,
        name: Optional[str] = None,
    ):
        if not self.page:
            raise RuntimeError("Browser page is not connected.")

        if selector:
            control = self.page.locator(selector)
        elif field:
            control = self.page.get_by_label(field, exact=True)
            if await control.count() == 0:
                control = self.page.get_by_label(field)
        elif placeholder:
            control = self.page.get_by_placeholder(placeholder, exact=True)
            if await control.count() == 0:
                control = self.page.get_by_placeholder(placeholder)
        elif name:
            control = self.page.locator(f'[name="{name}"]')
        else:
            raise FieldNotFound("Control lookup requires selector, label, placeholder, or name.")

        description = self._control_lookup_description(selector=selector, field=field, placeholder=placeholder, name=name)
        count = await control.count()
        if count == 0:
            raise FieldNotFound(f"Control not found for {description}.")
        if count > 1:
            raise MultipleControlsFound(f"Multiple controls matched {description}: {count}.")

        target = control.first
        if not await target.is_visible():
            raise ControlHidden(f"Control matched {description} but is hidden.")
        if not await target.is_enabled():
            raise ControlDisabled(f"Control matched {description} but is disabled.")
        return target, description

    async def _option_locator(self, value: str):
        if not self.page:
            raise RuntimeError("Browser page is not connected.")
        option = self.page.get_by_role("option", name=value, exact=True)
        if await option.count() == 0:
            option = self.page.get_by_text(value, exact=True)
        if await option.count() == 0:
            option = self.page.get_by_text(value)
        return option

    async def _select_native_option(self, control, value: str | list[str]) -> bool:
        try:
            tag_name = await control.evaluate("el => el.tagName.toLowerCase()")
        except Exception:
            return False
        if tag_name != "select":
            return False

        try:
            if isinstance(value, list):
                await control.select_option([{"label": item} for item in value])
            else:
                await control.select_option(label=value)
        except Exception:
            try:
                if isinstance(value, list):
                    await control.select_option(value=value)
                else:
                    await control.select_option(value=value)
            except Exception as exc:
                raise OptionNotFound(f"Option not found: {value}.") from exc
        return True

    async def _async_select_dropdown(
        self,
        *,
        field: Optional[str],
        value: str,
        selector: Optional[str],
        placeholder: Optional[str],
        name: Optional[str],
        timeout_ms: int,
    ) -> str:
        control, description = await self._locate_control(selector=selector, field=field, placeholder=placeholder, name=name)
        if await self._select_native_option(control, value):
            return f"{field or selector or placeholder or name} = {value}"

        try:
            await control.click(timeout=timeout_ms)
            option = await self._option_locator(value)
            count = await option.count()
            if count == 0:
                raise OptionNotFound(f"Option '{value}' not found for {description}.")
            if count > 1:
                raise MultipleControlsFound(f"Multiple options matched '{value}' for {description}: {count}.")
            target = option.first
            if not await target.is_visible():
                raise ControlHidden(f"Option '{value}' for {description} is hidden.")
            if not await target.is_enabled():
                raise ControlDisabled(f"Option '{value}' for {description} is disabled.")
            await target.click(timeout=timeout_ms)
        except ChatAdapterError:
            raise
        except PlaywrightTimeoutError as e:
            raise ChatAdapterTimeout(f"Timed out selecting '{value}' for {description}: {e}") from e
        return f"{field or selector or placeholder or name} = {value}"

    async def _async_select_radio(
        self,
        *,
        field: Optional[str],
        value: str,
        selector: Optional[str],
        name: Optional[str],
        timeout_ms: int,
    ) -> str:
        if selector:
            control, description = await self._locate_control(selector=selector, field=field, name=name)
        elif name:
            control, description = await self._locate_control(selector=None, field=None, name=name)
        else:
            control, description = await self._locate_control(selector=None, field=value or field)
        try:
            await control.check(timeout=timeout_ms)
        except AttributeError:
            await control.click(timeout=timeout_ms)
        except PlaywrightTimeoutError as e:
            raise ChatAdapterTimeout(f"Timed out selecting radio '{value}' for {description}: {e}") from e
        return f"{field or selector} = {value}"

    async def _async_select_checkbox(
        self,
        *,
        field: Optional[str],
        value: bool,
        selector: Optional[str],
        name: Optional[str],
        timeout_ms: int,
    ) -> str:
        control, description = await self._locate_control(selector=selector, field=field, name=name)
        try:
            await control.set_checked(bool(value), timeout=timeout_ms)
        except AttributeError:
            checked = False
            try:
                checked = bool(await control.is_checked())
            except Exception:
                pass
            if checked != bool(value):
                await control.click(timeout=timeout_ms)
        except PlaywrightTimeoutError as e:
            raise ChatAdapterTimeout(f"Timed out setting checkbox for {description}: {e}") from e
        return f"{field or selector} = {str(bool(value)).lower()}"

    async def _async_select_multi_select(
        self,
        *,
        field: Optional[str],
        values: list[str],
        selector: Optional[str],
        placeholder: Optional[str],
        name: Optional[str],
        timeout_ms: int,
    ) -> str:
        control, description = await self._locate_control(selector=selector, field=field, placeholder=placeholder, name=name)
        if await self._select_native_option(control, values):
            return f"{field or selector or placeholder or name} = {','.join(values)}"

        try:
            await control.click(timeout=timeout_ms)
            for value in values:
                option = await self._option_locator(value)
                count = await option.count()
                if count == 0:
                    raise OptionNotFound(f"Option '{value}' not found for {description}.")
                if count > 1:
                    raise MultipleControlsFound(f"Multiple options matched '{value}' for {description}: {count}.")
                target = option.first
                if not await target.is_visible():
                    raise ControlHidden(f"Option '{value}' for {description} is hidden.")
                if not await target.is_enabled():
                    raise ControlDisabled(f"Option '{value}' for {description} is disabled.")
                await target.click(timeout=timeout_ms)
        except ChatAdapterError:
            raise
        except PlaywrightTimeoutError as e:
            raise ChatAdapterTimeout(f"Timed out selecting multiple values for {description}: {e}") from e
        return f"{field or selector or placeholder or name} = {','.join(values)}"

    async def _locate_upload_control(
        self,
        *,
        selector: Optional[str],
        field: Optional[str],
        name: Optional[str],
    ):
        if not self.page:
            raise RuntimeError("Browser page is not connected.")

        description = "first visible input[type=file]"
        if selector:
            control = self.page.locator(selector)
            description = f"selector '{selector}'"
        elif field:
            control = self.page.get_by_label(field, exact=True)
            if await control.count() == 0:
                control = self.page.get_by_label(field)
            description = f"label '{field}'"
        elif name:
            control = self.page.locator(f'input[type="file"][name="{name}"]')
            description = f"name '{name}'"
        else:
            control = self.page.locator('input[type="file"]:visible')

        count = await control.count()
        if count == 0:
            raise UploadFieldNotFound(f"Upload field not found for {description}.")
        if count > 1:
            raise MultipleControlsFound(f"Multiple upload fields matched {description}: {count}.")

        target = control.first
        if not await target.is_visible():
            raise ControlHidden(f"Upload field matched {description} but is hidden.")
        if not await target.is_enabled():
            raise ControlDisabled(f"Upload field matched {description} but is disabled.")
        return target, description

    def send_message(self, message: str, agent_prompt: Optional[str] = None, attachments: Optional[list[str]] = None) -> str:
        if attachments:
            raise NotImplementedError("BrowserChatAdapter does not currently support attachments")
            
        timeout_ms = self.interaction.get("response_timeout_ms", 30000)
        future = self._thread.dispatch(self._async_send_message(message, timeout_ms))
        response_text = future.result(timeout=(timeout_ms / 1000.0) + 10)

        # Append turns chronologically
        self.transcript.append(ConversationMessage(
            turn_index=len(self.transcript),
            role="simulated_user", 
            content=message
        ))
        self.transcript.append(ConversationMessage(
            turn_index=len(self.transcript),
            role="agent", 
            content=response_text,
            metadata=self._agent_metadata(response_text),
            rag_evidence=self._last_response_rag_evidence,
        ))
        self._last_response_rag_evidence = None
        
        return response_text

    def _append_control_evidence(
        self,
        *,
        action: str,
        label: str,
        value: str,
        metadata: dict[str, Any],
    ) -> None:
        self.transcript.append(ConversationMessage(
            turn_index=len(self.transcript),
            role="simulated_user",
            content=f"{action}\n{label} = {value}",
            metadata=metadata,
        ))

    def _upload_metadata(self, path: Any) -> dict[str, Any]:
        if isinstance(path, dict):
            data = path.get("buffer", path.get("data", path.get("content", b"")))
            if isinstance(data, str):
                import base64
                try:
                    data = base64.b64decode(data)
                except Exception:
                    data = data.encode("utf-8")
            if data is None:
                data = b""
            name = path.get("filename") or path.get("name") or "image"
            mime_type = path.get("mime_type") or path.get("mimeType") or path.get("type") or mimetypes.guess_type(str(name))[0]
            return {
                "file_name": os.path.basename(str(name)),
                "mime_type": mime_type or "application/octet-stream",
                "size": len(data),
            }
        if not os.path.exists(path) or not os.access(path, os.R_OK):
            raise UploadFileNotFound(f"Upload file not found or not readable: {os.path.basename(path)}")
        mime_type, _ = mimetypes.guess_type(path)
        return {
            "file_name": os.path.basename(path),
            "mime_type": mime_type or "application/octet-stream",
            "size": os.path.getsize(path),
        }

    def click_button(self, text: str | None = None, *, metadata: dict[str, Any] | None = None) -> str:
        metadata = metadata or {}
        selector = metadata.get("selector")
        timeout_ms = int(metadata.get("timeout_ms") or self.interaction.get("response_timeout_ms", 30000))
        label = text or selector or "button"

        future = self._thread.dispatch(
            self._async_click_button(text=text, selector=selector, timeout_ms=timeout_ms)
        )
        response_text = future.result(timeout=(timeout_ms / 1000.0) + 10)

        turn_index = len(self.transcript)
        self.transcript.append(ConversationMessage(
            turn_index=turn_index,
            role="simulated_user",
            content=f"Click Button\n{label}",
            metadata={
                "action": "click_button",
                "text": text,
                "selector": selector,
            },
        ))
        self.transcript.append(ConversationMessage(
            turn_index=turn_index + 1,
            role="agent",
            content=response_text,
            metadata=self._agent_metadata(response_text),
            rag_evidence=self._last_response_rag_evidence,
        ))
        self._last_response_rag_evidence = None

        return response_text

    def select_dropdown(self, field: str, value: str, *, metadata: dict[str, Any] | None = None) -> str:
        metadata = metadata or {}
        selector = metadata.get("selector")
        placeholder = metadata.get("placeholder")
        name = metadata.get("name")
        timeout_ms = int(metadata.get("timeout_ms") or self.interaction.get("response_timeout_ms", 30000))
        future = self._thread.dispatch(self._async_select_dropdown(
            field=field,
            value=value,
            selector=selector,
            placeholder=placeholder,
            name=name,
            timeout_ms=timeout_ms,
        ))
        result = future.result(timeout=(timeout_ms / 1000.0) + 10)
        self._append_control_evidence(
            action="Select Dropdown",
            label=field or selector or placeholder or "dropdown",
            value=value,
            metadata={"action": "select_dropdown", "field": field, "value": value, "selector": selector},
        )
        return result

    def select_radio(self, field: str, value: str, *, metadata: dict[str, Any] | None = None) -> str:
        metadata = metadata or {}
        selector = metadata.get("selector")
        name = metadata.get("name")
        timeout_ms = int(metadata.get("timeout_ms") or self.interaction.get("response_timeout_ms", 30000))
        future = self._thread.dispatch(self._async_select_radio(
            field=field,
            value=value,
            selector=selector,
            name=name,
            timeout_ms=timeout_ms,
        ))
        result = future.result(timeout=(timeout_ms / 1000.0) + 10)
        self._append_control_evidence(
            action="Radio",
            label=field or selector or "radio",
            value=value,
            metadata={"action": "select_radio", "field": field, "value": value, "selector": selector},
        )
        return result

    def select_checkbox(self, field: str, value: bool = True, *, metadata: dict[str, Any] | None = None) -> str:
        metadata = metadata or {}
        selector = metadata.get("selector")
        name = metadata.get("name")
        timeout_ms = int(metadata.get("timeout_ms") or self.interaction.get("response_timeout_ms", 30000))
        future = self._thread.dispatch(self._async_select_checkbox(
            field=field,
            value=value,
            selector=selector,
            name=name,
            timeout_ms=timeout_ms,
        ))
        result = future.result(timeout=(timeout_ms / 1000.0) + 10)
        value_text = str(bool(value)).lower()
        self._append_control_evidence(
            action="Checkbox",
            label=field or selector or "checkbox",
            value=value_text,
            metadata={"action": "select_checkbox", "field": field, "value": bool(value), "selector": selector},
        )
        return result

    def select_multi_select(self, field: str, values: list[str], *, metadata: dict[str, Any] | None = None) -> str:
        metadata = metadata or {}
        selector = metadata.get("selector")
        placeholder = metadata.get("placeholder")
        name = metadata.get("name")
        timeout_ms = int(metadata.get("timeout_ms") or self.interaction.get("response_timeout_ms", 30000))
        future = self._thread.dispatch(self._async_select_multi_select(
            field=field,
            values=values,
            selector=selector,
            placeholder=placeholder,
            name=name,
            timeout_ms=timeout_ms,
        ))
        result = future.result(timeout=(timeout_ms / 1000.0) + 10)
        value_text = ",".join(values)
        self._append_control_evidence(
            action="Multi Select",
            label=field or selector or placeholder or "multi_select",
            value=value_text,
            metadata={"action": "select_multi_select", "field": field, "values": values, "selector": selector},
        )
        return result

    async def _async_upload_file(
        self,
        *,
        file: Any,
        selector: Optional[str],
        field: Optional[str],
        name: Optional[str],
        timeout_ms: int,
    ) -> str:
        target, _ = await self._locate_upload_control(selector=selector, field=field, name=name)
        upload_value = _playwright_upload_value(file)
        try:
            await target.set_input_files(upload_value, timeout=timeout_ms)
        except PlaywrightTimeoutError as e:
            raise ChatAdapterTimeout(f"Timed out uploading file '{_upload_display_name(file)}': {e}") from e
        return "Success"

    def upload_file(self, file: Any, *, field: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        metadata = metadata or {}
        upload_meta = self._upload_metadata(file)
        selector = metadata.get("selector")
        name = metadata.get("name")
        timeout_ms = int(metadata.get("timeout_ms") or self.interaction.get("response_timeout_ms", 30000))
        future = self._thread.dispatch(self._async_upload_file(
            file=file,
            selector=selector,
            field=field,
            name=name,
            timeout_ms=timeout_ms,
        ))
        result = future.result(timeout=(timeout_ms / 1000.0) + 10)

        self.transcript.append(ConversationMessage(
            turn_index=len(self.transcript),
            role="simulated_user",
            content=f"Upload File\n{upload_meta['file_name']}\nResult\n{result}\nMime Type\n{upload_meta['mime_type']}\nSize\n{upload_meta['size']}",
            attachments=[file] if isinstance(file, str) else None,
            metadata={"action": "upload_file", "field": field, "selector": selector, **upload_meta},
        ))
        return result

    def upload_image(self, image: Any, *, field: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        metadata = metadata or {}
        upload_meta = self._upload_metadata(image)
        result = self.upload_file(image, field=field, metadata=metadata)
        if self.transcript:
            self.transcript[-1].content = (
                f"Upload Image\n{upload_meta['file_name']}\nResult\n{result}\n"
                f"Mime Type\n{upload_meta['mime_type']}\nSize\n{upload_meta['size']}"
            )
            self.transcript[-1].metadata = {"action": "upload_image", "field": field, "selector": metadata.get("selector"), **upload_meta}
        return result

    async def _async_fill_control(
        self,
        *,
        action: str,
        value: str,
        selector: Optional[str],
        field: Optional[str],
        placeholder: Optional[str],
        name: Optional[str],
        timeout_ms: int,
    ) -> str:
        target, description = await self._locate_control(
            selector=selector,
            field=field,
            placeholder=placeholder,
            name=name,
        )
        try:
            await target.fill(value, timeout=timeout_ms)
        except AttributeError:
            try:
                await target.click(timeout=timeout_ms)
                await target.press("Control+A", timeout=timeout_ms)
                await target.type(value, timeout=timeout_ms)
            except AttributeError as exc:
                raise FieldNotFound(f"{action} control for {description} cannot accept typed input.") from exc
        except PlaywrightTimeoutError as e:
            raise ChatAdapterTimeout(f"Timed out entering {action} for {description}: {e}") from e
        return "Success"

    def enter_otp(self, value: str, *, field: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        metadata = metadata or {}
        selector = metadata.get("selector")
        placeholder = metadata.get("placeholder")
        name = metadata.get("name")
        timeout_ms = int(metadata.get("timeout_ms") or self.interaction.get("response_timeout_ms", 30000))
        future = self._thread.dispatch(self._async_fill_control(
            action="OTP",
            value=str(value),
            selector=selector,
            field=field,
            placeholder=placeholder,
            name=name,
            timeout_ms=timeout_ms,
        ))
        result = future.result(timeout=(timeout_ms / 1000.0) + 10)
        self.transcript.append(ConversationMessage(
            turn_index=len(self.transcript),
            role="simulated_user",
            content="Entered OTP\n******",
            metadata={
                "action": "enter_otp",
                "field": field,
                "selector": selector,
                "masked": True,
                "length": len(str(value)),
            },
        ))
        return result

    def pick_date(self, field: str, value: str, *, metadata: dict[str, Any] | None = None) -> str:
        metadata = metadata or {}
        selector = metadata.get("selector")
        placeholder = metadata.get("placeholder")
        name = metadata.get("name")
        timeout_ms = int(metadata.get("timeout_ms") or self.interaction.get("response_timeout_ms", 30000))
        future = self._thread.dispatch(self._async_fill_control(
            action="date",
            value=str(value),
            selector=selector,
            field=field,
            placeholder=placeholder,
            name=name,
            timeout_ms=timeout_ms,
        ))
        result = future.result(timeout=(timeout_ms / 1000.0) + 10)
        self._append_control_evidence(
            action="Date",
            label=field or selector or placeholder or name or "date",
            value=str(value),
            metadata={"action": "pick_date", "field": field, "value": str(value), "selector": selector},
        )
        return result

    def pick_time(self, field: str, value: str, *, metadata: dict[str, Any] | None = None) -> str:
        metadata = metadata or {}
        selector = metadata.get("selector")
        placeholder = metadata.get("placeholder")
        name = metadata.get("name")
        timeout_ms = int(metadata.get("timeout_ms") or self.interaction.get("response_timeout_ms", 30000))
        future = self._thread.dispatch(self._async_fill_control(
            action="time",
            value=str(value),
            selector=selector,
            field=field,
            placeholder=placeholder,
            name=name,
            timeout_ms=timeout_ms,
        ))
        result = future.result(timeout=(timeout_ms / 1000.0) + 10)
        self._append_control_evidence(
            action="Time",
            label=field or selector or placeholder or name or "time",
            value=str(value),
            metadata={"action": "pick_time", "field": field, "value": str(value), "selector": selector},
        )
        return result

    def search(self, query: str, *, field: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        metadata = metadata or {}
        selector = metadata.get("selector")
        placeholder = metadata.get("placeholder")
        name = metadata.get("name")
        timeout_ms = int(metadata.get("timeout_ms") or self.interaction.get("response_timeout_ms", 30000))
        future = self._thread.dispatch(self._async_fill_control(
            action="search",
            value=str(query),
            selector=selector,
            field=field,
            placeholder=placeholder,
            name=name,
            timeout_ms=timeout_ms,
        ))
        result = future.result(timeout=(timeout_ms / 1000.0) + 10)
        self._append_control_evidence(
            action="Search",
            label=field or selector or placeholder or name or "search",
            value=str(query),
            metadata={"action": "search", "field": field, "query": str(query), "selector": selector},
        )
        return result

    async def _async_wait_for_text(self, *, text: str, timeout_ms: int) -> float:
        if not self.page:
            raise BrowserClosed("Browser page is not connected.")

        started = time.perf_counter()
        try:
            await self.page.get_by_text(text).first.wait_for(state="visible", timeout=timeout_ms)
        except PlaywrightTimeoutError as e:
            raise ExpectedTextNotFound(f"Expected text not found before timeout: {text}") from e
        return time.perf_counter() - started

    def wait_for_text(self, text: str, *, timeout: float | None = None, metadata: dict[str, Any] | None = None) -> str:
        if not text:
            raise ExpectedTextNotFound("wait_for_text requires non-empty text.")

        metadata = metadata or {}
        timeout_seconds = float(timeout or metadata.get("timeout") or 30)
        timeout_ms = int(timeout_seconds * 1000)
        future = self._thread.dispatch(self._async_wait_for_text(text=text, timeout_ms=timeout_ms))
        duration = future.result(timeout=timeout_seconds + 10)
        duration_text = f"{duration:.2f}"

        self.transcript.append(ConversationMessage(
            turn_index=len(self.transcript),
            role="simulated_user",
            content=f"Wait For\n{text}\nResult\nSuccess\nDuration\n{duration_text} seconds",
            metadata={
                "action": "wait_for",
                "type": "text",
                "text": text,
                "duration_seconds": duration,
                "timeout_seconds": timeout_seconds,
            },
        ))
        return "Success"

    def get_transcript(self) -> list[ConversationMessage]:
        return self.transcript

    def get_conversation(self) -> NormalizedConversation:
        return NormalizedConversation(
            run_id=self.run_id,
            session_id=self.session_id,
            channel="chatbot",
            messages=self.transcript
        )

    async def _async_close(self) -> None:
        if self.page:
            try: await self.page.close()
            except: pass
            self.page = None
        if self.context:
            try: await self.context.close()
            except: pass
            self.context = None
        if self.browser:
            try: await self.browser.close()
            except: pass
            self.browser = None
        if self.playwright:
            try: await self.playwright.stop()
            except: pass
            self.playwright = None

    def close(self) -> None:
        if self._thread.is_alive():
            future = self._thread.dispatch(self._async_close())
            try:
                future.result(timeout=5)
            except Exception:
                pass
            self._thread.stop()
            self._thread.join(timeout=2)
        logger.info("BrowserChatAdapter closed")
