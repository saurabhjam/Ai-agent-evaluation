import os

import pytest

from app.adapters.chat.base import MultipleControlsFound, UploadFieldNotFound, UploadFileNotFound
from app.adapters.chat.browser import BrowserChatAdapter


class FakeFileInput:
    def __init__(self, *, visible=True, enabled=True):
        self.visible = visible
        self.enabled = enabled
        self.files = []

    async def is_visible(self):
        return self.visible

    async def is_enabled(self):
        return self.enabled

    async def set_input_files(self, file, timeout=None):
        self.files.append(file)


class FakeLocator:
    def __init__(self, elements):
        self.elements = elements

    async def count(self):
        return len(self.elements)

    @property
    def first(self):
        return self.elements[0]


class FakePage:
    def __init__(self, *, selectors=None, labels=None, names=None, visible_inputs=None):
        self.selectors = selectors or {}
        self.labels = labels or {}
        self.names = names or {}
        self.visible_inputs = visible_inputs or []

    def locator(self, selector):
        if selector.startswith('input[type="file"][name="') and selector.endswith('"]'):
            return FakeLocator(self.names.get(selector[25:-2], []))
        if selector == 'input[type="file"]:visible':
            return FakeLocator(self.visible_inputs)
        return FakeLocator(self.selectors.get(selector, []))

    def get_by_label(self, label, exact=None):
        return FakeLocator(self.labels.get(label, []))


class ImmediateThread:
    def dispatch(self, coro):
        import asyncio
        from concurrent.futures import Future

        future = Future()
        try:
            future.set_result(asyncio.run(coro))
        except Exception as exc:
            future.set_exception(exc)
        return future


def _adapter(page):
    adapter = BrowserChatAdapter.__new__(BrowserChatAdapter)
    adapter.page = page
    adapter.interaction = {}
    adapter.transcript = []
    adapter._thread = ImmediateThread()
    return adapter


def test_image_upload_by_selector(tmp_path):
    file_path = tmp_path / "damage.jpg"
    file_path.write_bytes(b"jpg")
    control = FakeFileInput()
    adapter = _adapter(FakePage(selectors={"#damage": [control]}))

    result = adapter.upload_image(str(file_path), metadata={"selector": "#damage"})

    assert result == "Success"
    assert control.files == [str(file_path)]
    assert "Upload Image\ndamage.jpg" in adapter.transcript[0].content


def test_pdf_upload_by_field_label(tmp_path):
    file_path = tmp_path / "policy.pdf"
    file_path.write_bytes(b"pdf")
    control = FakeFileInput()
    adapter = _adapter(FakePage(labels={"Insurance Document": [control]}))

    result = adapter.upload_file(str(file_path), field="Insurance Document")

    assert result == "Success"
    assert control.files == [str(file_path)]
    assert "Upload File\npolicy.pdf" in adapter.transcript[0].content


def test_generic_upload_uses_first_visible_input(tmp_path):
    file_path = tmp_path / "data.json"
    file_path.write_text("{}")
    control = FakeFileInput()
    adapter = _adapter(FakePage(visible_inputs=[control]))

    result = adapter.upload_file(str(file_path))

    assert result == "Success"
    assert control.files == [str(file_path)]


def test_upload_missing_file():
    adapter = _adapter(FakePage(visible_inputs=[FakeFileInput()]))

    with pytest.raises(UploadFileNotFound):
        adapter.upload_file("does-not-exist.pdf")


def test_upload_field_missing(tmp_path):
    file_path = tmp_path / "policy.pdf"
    file_path.write_bytes(b"pdf")
    adapter = _adapter(FakePage())

    with pytest.raises(UploadFieldNotFound):
        adapter.upload_file(str(file_path), field="Insurance Document")


def test_multiple_upload_fields(tmp_path):
    file_path = tmp_path / "policy.pdf"
    file_path.write_bytes(b"pdf")
    adapter = _adapter(FakePage(visible_inputs=[FakeFileInput(), FakeFileInput()]))

    with pytest.raises(MultipleControlsFound):
        adapter.upload_file(str(file_path))
