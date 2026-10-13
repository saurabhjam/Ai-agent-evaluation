import asyncio

import pytest

from app.adapters.chat.base import ButtonDisabled, ButtonHidden, ButtonNotFound, MultipleButtonsFound
from app.adapters.chat.browser import BrowserChatAdapter
from app.models.conversation import ConversationMessage


class FakeElement:
    def __init__(self, text="", *, visible=True, enabled=True):
        self.text = text
        self.visible = visible
        self.enabled = enabled
        self.clicked = False

    async def inner_text(self):
        return self.text

    async def is_visible(self):
        return self.visible

    async def is_enabled(self):
        return self.enabled

    async def click(self, timeout=None):
        self.clicked = True


class FakeLocator:
    def __init__(self, elements):
        self.elements = elements

    async def count(self):
        return len(self.elements)

    @property
    def first(self):
        return self.elements[0]

    @property
    def last(self):
        return self.elements[-1]

    def filter(self, has_text=None):
        return FakeLocator([item for item in self.elements if has_text in item.text])


class FakePage:
    def __init__(self, *, selector_buttons=None, role_buttons=None):
        self.selector_buttons = selector_buttons or {}
        self.role_buttons = role_buttons or []
        self.used_role_lookup = False
        self.response = FakeElement("Initial")
        self.clicked = False

    def locator(self, selector):
        if selector == ".response":
            return FakeLocator([self.response])
        return FakeLocator(self.selector_buttons.get(selector, []))

    def get_by_role(self, role, name=None, exact=None):
        self.used_role_lookup = True
        if role != "button":
            return FakeLocator([])
        if name is None:
            return FakeLocator(self.role_buttons)
        if exact:
            return FakeLocator([item for item in self.role_buttons if item.text == name])
        return FakeLocator([item for item in self.role_buttons if name in item.text])

    async def wait_for_timeout(self, timeout):
        self.clicked = any(item.clicked for item in self.role_buttons)
        for elements in self.selector_buttons.values():
            self.clicked = self.clicked or any(item.clicked for item in elements)
        if self.clicked:
            self.response.text = "Agent response"


def _adapter(page):
    adapter = BrowserChatAdapter.__new__(BrowserChatAdapter)
    adapter.page = page
    adapter.response_selector = ".response"
    adapter.interaction = {}
    adapter.transcript = []
    return adapter


def test_click_button_prefers_selector_over_text():
    selector_button = FakeElement("Selector Button")
    text_button = FakeElement("Book Appointment")
    page = FakePage(selector_buttons={"#book": [selector_button]}, role_buttons=[text_button])
    adapter = _adapter(page)

    response = asyncio.run(adapter._async_click_button(text="Book Appointment", selector="#book", timeout_ms=1000))

    assert response == "Agent response"
    assert selector_button.clicked is True
    assert text_button.clicked is False
    assert page.used_role_lookup is False


def test_click_button_finds_exact_visible_text():
    button = FakeElement("Book Appointment")
    adapter = _adapter(FakePage(role_buttons=[button]))

    response = asyncio.run(adapter._async_click_button(text="Book Appointment", selector=None, timeout_ms=1000))

    assert response == "Agent response"
    assert button.clicked is True


def test_click_button_falls_back_to_partial_visible_text():
    button = FakeElement("Book Appointment Now")
    adapter = _adapter(FakePage(role_buttons=[button]))

    response = asyncio.run(adapter._async_click_button(text="Book Appointment", selector=None, timeout_ms=1000))

    assert response == "Agent response"
    assert button.clicked is True


def test_click_button_not_found():
    adapter = _adapter(FakePage(role_buttons=[]))

    with pytest.raises(ButtonNotFound):
        asyncio.run(adapter._async_click_button(text="Book Appointment", selector=None, timeout_ms=1000))


def test_click_button_multiple_matches():
    adapter = _adapter(FakePage(role_buttons=[FakeElement("Book"), FakeElement("Book")]))

    with pytest.raises(MultipleButtonsFound):
        asyncio.run(adapter._async_click_button(text="Book", selector=None, timeout_ms=1000))


def test_click_button_hidden():
    adapter = _adapter(FakePage(role_buttons=[FakeElement("Book", visible=False)]))

    with pytest.raises(ButtonHidden):
        asyncio.run(adapter._async_click_button(text="Book", selector=None, timeout_ms=1000))


def test_click_button_disabled():
    adapter = _adapter(FakePage(role_buttons=[FakeElement("Book", enabled=False)]))

    with pytest.raises(ButtonDisabled):
        asyncio.run(adapter._async_click_button(text="Book", selector=None, timeout_ms=1000))
