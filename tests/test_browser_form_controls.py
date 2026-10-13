import asyncio

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.adapters.chat.base import ExpectedTextNotFound, FieldNotFound, OptionNotFound
from app.adapters.chat.browser import BrowserChatAdapter


class FakeControl:
    def __init__(self, label="", *, visible=True, enabled=True, tag="input", wait_times_out=False):
        self.label = label
        self.visible = visible
        self.enabled = enabled
        self.tag = tag
        self.wait_times_out = wait_times_out
        self.selected = None
        self.checked = False
        self.clicked = False
        self.filled = None

    async def is_visible(self):
        return self.visible

    async def is_enabled(self):
        return self.enabled

    async def evaluate(self, script):
        return self.tag

    async def select_option(self, label=None, value=None):
        selected = label if label is not None else value
        if selected == "Missing":
            raise ValueError("missing option")
        if isinstance(selected, list) and selected and isinstance(selected[0], dict):
            selected = [item.get("label") or item.get("value") for item in selected]
        self.selected = selected

    async def check(self, timeout=None):
        self.checked = True

    async def set_checked(self, value, timeout=None):
        self.checked = bool(value)

    async def is_checked(self):
        return self.checked

    async def click(self, timeout=None):
        self.clicked = True

    async def fill(self, value, timeout=None):
        self.filled = value

    async def wait_for(self, state=None, timeout=None):
        if self.wait_times_out:
            raise PlaywrightTimeoutError("timeout")

    async def inner_text(self):
        return self.label


class FakeLocator:
    def __init__(self, elements):
        self.elements = elements

    async def count(self):
        return len(self.elements)

    @property
    def first(self):
        if not self.elements:
            return FakeControl(wait_times_out=True)
        return self.elements[0]

    @property
    def last(self):
        return self.elements[-1]


class FakePage:
    def __init__(self, *, labels=None, selectors=None, placeholders=None, names=None, options=None, texts=None):
        self.labels = labels or {}
        self.selectors = selectors or {}
        self.placeholders = placeholders or {}
        self.names = names or {}
        self.options = options or {}
        self.texts = texts or {}

    def locator(self, selector):
        if selector.startswith('[name="') and selector.endswith('"]'):
            return FakeLocator(self.names.get(selector[7:-2], []))
        return FakeLocator(self.selectors.get(selector, []))

    def get_by_label(self, label, exact=None):
        return FakeLocator(self.labels.get(label, []))

    def get_by_placeholder(self, placeholder, exact=None):
        return FakeLocator(self.placeholders.get(placeholder, []))

    def get_by_role(self, role, name=None, exact=None):
        if role == "option":
            return FakeLocator(self.options.get(name, []))
        return FakeLocator([])

    def get_by_text(self, text, exact=None):
        return FakeLocator(self.texts.get(text, self.options.get(text, [])))


def _adapter(page):
    adapter = BrowserChatAdapter.__new__(BrowserChatAdapter)
    adapter.page = page
    adapter.interaction = {}
    adapter.transcript = []
    return adapter


def test_dropdown_selection_by_label():
    control = FakeControl(tag="select")
    adapter = _adapter(FakePage(labels={"City": [control]}))

    result = asyncio.run(adapter._async_select_dropdown(
        field="City",
        value="Pune",
        selector=None,
        placeholder=None,
        name=None,
        timeout_ms=1000,
    ))

    assert result == "City = Pune"
    assert control.selected == "Pune"


def test_selector_priority_for_dropdown():
    label_control = FakeControl(tag="select")
    selector_control = FakeControl(tag="select")
    adapter = _adapter(FakePage(labels={"City": [label_control]}, selectors={"#city": [selector_control]}))

    asyncio.run(adapter._async_select_dropdown(
        field="City",
        value="Pune",
        selector="#city",
        placeholder=None,
        name=None,
        timeout_ms=1000,
    ))

    assert selector_control.selected == "Pune"
    assert label_control.selected is None


def test_radio_selection_by_label():
    control = FakeControl()
    adapter = _adapter(FakePage(labels={"Health": [control]}))

    result = asyncio.run(adapter._async_select_radio(
        field="Insurance Type",
        value="Health",
        selector=None,
        name=None,
        timeout_ms=1000,
    ))

    assert result == "Insurance Type = Health"
    assert control.checked is True


def test_checkbox_selection_by_label():
    control = FakeControl()
    adapter = _adapter(FakePage(labels={"Accept Terms": [control]}))

    result = asyncio.run(adapter._async_select_checkbox(
        field="Accept Terms",
        value=True,
        selector=None,
        name=None,
        timeout_ms=1000,
    ))

    assert result == "Accept Terms = true"
    assert control.checked is True


def test_multi_select_selection():
    control = FakeControl(tag="select")
    adapter = _adapter(FakePage(labels={"Languages": [control]}))

    result = asyncio.run(adapter._async_select_multi_select(
        field="Languages",
        values=["English", "Hindi"],
        selector=None,
        placeholder=None,
        name=None,
        timeout_ms=1000,
    ))

    assert result == "Languages = English,Hindi"
    assert control.selected == ["English", "Hindi"]


def test_field_not_found():
    adapter = _adapter(FakePage())

    with pytest.raises(FieldNotFound):
        asyncio.run(adapter._async_select_dropdown(
            field="City",
            value="Pune",
            selector=None,
            placeholder=None,
            name=None,
            timeout_ms=1000,
        ))


def test_option_not_found():
    control = FakeControl(tag="select")
    adapter = _adapter(FakePage(labels={"City": [control]}))

    with pytest.raises(OptionNotFound):
        asyncio.run(adapter._async_select_dropdown(
            field="City",
            value="Missing",
            selector=None,
            placeholder=None,
            name=None,
            timeout_ms=1000,
        ))


def test_name_attribute_lookup():
    control = FakeControl(tag="select")
    adapter = _adapter(FakePage(names={"city": [control]}))

    result = asyncio.run(adapter._async_select_dropdown(
        field=None,
        value="Pune",
        selector=None,
        placeholder=None,
        name="city",
        timeout_ms=1000,
    ))

    assert result == "city = Pune"
    assert control.selected == "Pune"


def test_otp_fill_by_selector():
    control = FakeControl()
    adapter = _adapter(FakePage(selectors={"#otp": [control]}))

    result = asyncio.run(adapter._async_fill_control(
        action="OTP",
        value="123456",
        selector="#otp",
        field=None,
        placeholder=None,
        name=None,
        timeout_ms=1000,
    ))

    assert result == "Success"
    assert control.filled == "123456"


def test_date_fill_by_label():
    control = FakeControl()
    adapter = _adapter(FakePage(labels={"Appointment Date": [control]}))

    asyncio.run(adapter._async_fill_control(
        action="date",
        value="2026-10-15",
        selector=None,
        field="Appointment Date",
        placeholder=None,
        name=None,
        timeout_ms=1000,
    ))

    assert control.filled == "2026-10-15"


def test_time_fill_by_placeholder():
    control = FakeControl()
    adapter = _adapter(FakePage(placeholders={"HH:MM": [control]}))

    asyncio.run(adapter._async_fill_control(
        action="time",
        value="14:30",
        selector=None,
        field=None,
        placeholder="HH:MM",
        name=None,
        timeout_ms=1000,
    ))

    assert control.filled == "14:30"


def test_search_fill_by_name():
    control = FakeControl()
    adapter = _adapter(FakePage(names={"city_search": [control]}))

    asyncio.run(adapter._async_fill_control(
        action="search",
        value="Pune",
        selector=None,
        field=None,
        placeholder=None,
        name="city_search",
        timeout_ms=1000,
    ))

    assert control.filled == "Pune"


def test_wait_for_text_appears():
    adapter = _adapter(FakePage(texts={"Appointment Confirmed": [FakeControl()]}))

    duration = asyncio.run(adapter._async_wait_for_text(text="Appointment Confirmed", timeout_ms=1000))

    assert duration >= 0


def test_wait_for_text_timeout_raises_expected_text_not_found():
    adapter = _adapter(FakePage(texts={"Appointment Confirmed": [FakeControl(wait_times_out=True)]}))

    with pytest.raises(ExpectedTextNotFound):
        asyncio.run(adapter._async_wait_for_text(text="Appointment Confirmed", timeout_ms=1000))


def test_wait_for_text_missing_raises_expected_text_not_found():
    adapter = _adapter(FakePage())

    with pytest.raises(ExpectedTextNotFound):
        asyncio.run(adapter._async_wait_for_text(text="Appointment Confirmed", timeout_ms=1000))
