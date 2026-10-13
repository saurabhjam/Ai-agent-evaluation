import asyncio

from app.adapters.chat.browser import BrowserChatAdapter
from app.models.conversation import RAGEvidence


class FakeElement:
    def __init__(self, text="", *, visible=True, enabled=True, attrs=None, children=None, raise_on_locator=False):
        self.text = text
        self.visible = visible
        self.enabled = enabled
        self.attrs = attrs or {}
        self.children = children or {}
        self.raise_on_locator = raise_on_locator
        self.clicked = False
        self.waited = False

    def locator(self, selector):
        if self.raise_on_locator:
            raise RuntimeError("bad selector")
        return FakeLocator(self.children.get(selector, []))

    async def inner_text(self):
        return self.text

    async def is_visible(self):
        return self.visible

    async def is_enabled(self):
        return self.enabled

    async def get_attribute(self, attr):
        return self.attrs.get(attr)

    async def click(self, timeout=None):
        self.clicked = True

    async def wait_for(self, state=None, timeout=None):
        self.waited = True


class FakeLocator:
    def __init__(self, elements):
        self.elements = elements

    async def count(self):
        return len(self.elements)

    def nth(self, index):
        return self.elements[index]

    @property
    def first(self):
        if not self.elements:
            return FakeElement(visible=False)
        return self.elements[0]


def _adapter(rag_config=None):
    adapter = BrowserChatAdapter.__new__(BrowserChatAdapter)
    adapter.config = {"rag_config": rag_config} if rag_config is not None else {}
    return adapter


def _response(children):
    return FakeElement("Agent answer", children=children)


def test_browser_rag_extracts_visible_context_from_response_scope():
    adapter = _adapter({"enabled": True, "context_selector": ".source-content"})
    container = _response({".source-content": [FakeElement("Policy paragraph")]})

    evidence = asyncio.run(adapter._extract_rag_evidence_from_response(container))

    assert evidence.contexts == ["Policy paragraph"]
    assert evidence.source == "agent_retrieval"


def test_browser_rag_extracts_multiple_visible_snippets():
    adapter = _adapter({"enabled": True, "context_selector": ".source-content"})
    container = _response({
        ".source-content": [
            FakeElement("Snippet A"),
            FakeElement("Snippet B"),
            FakeElement("Snippet A"),
        ]
    })

    evidence = asyncio.run(adapter._extract_rag_evidence_from_response(container))

    assert evidence.contexts == ["Snippet A", "Snippet B"]


def test_browser_rag_preserves_citation_metadata_with_context():
    citation = FakeElement(
        "Source 1",
        children={
            ".title": [FakeElement("Handbook")],
            "a": [FakeElement("Open", attrs={"href": "https://example.test/handbook"})],
        },
    )
    adapter = _adapter({
        "enabled": True,
        "context_selector": ".source-content",
        "citation_selector": ".citation",
        "citation_title_selector": ".title",
        "citation_url_selector": "a",
    })
    container = _response({
        ".source-content": [FakeElement("Grounding text")],
        ".citation": [citation],
    })

    evidence = asyncio.run(adapter._extract_rag_evidence_from_response(container))

    assert evidence.contexts == ["Grounding text"]
    assert evidence.citations == [
        {"label": "Source 1", "title": "Handbook", "url": "https://example.test/handbook"}
    ]


def test_browser_rag_citation_only_does_not_fabricate_context():
    adapter = _adapter({"enabled": True, "citation_selector": ".citation"})
    container = _response({".citation": [FakeElement("Source only")]})

    evidence = asyncio.run(adapter._extract_rag_evidence_from_response(container))

    assert evidence.available is True
    assert evidence.contexts == []
    assert evidence.citations == [{"label": "Source only"}]


def test_browser_rag_missing_selector_returns_none():
    adapter = _adapter({"enabled": True, "context_selector": ".missing"})

    evidence = asyncio.run(adapter._extract_rag_evidence_from_response(_response({})))

    assert evidence is None


def test_browser_rag_empty_visible_context_returns_none():
    adapter = _adapter({"enabled": True, "context_selector": ".source-content"})
    container = _response({".source-content": [FakeElement("  ")]})

    evidence = asyncio.run(adapter._extract_rag_evidence_from_response(container))

    assert evidence is None


def test_browser_rag_hidden_context_is_ignored():
    adapter = _adapter({"enabled": True, "context_selector": ".source-content"})
    container = _response({".source-content": [FakeElement("Hidden text", visible=False)]})

    evidence = asyncio.run(adapter._extract_rag_evidence_from_response(container))

    assert evidence is None


def test_browser_rag_extraction_exception_is_non_fatal():
    adapter = _adapter({"enabled": True, "context_selector": ".source-content"})

    evidence = asyncio.run(adapter._extract_rag_evidence_from_response(FakeElement(raise_on_locator=True)))

    assert evidence is None


def test_browser_rag_without_config_remains_plain_response():
    adapter = _adapter()

    evidence = asyncio.run(adapter._extract_rag_evidence_from_response(
        _response({".source-content": [FakeElement("Unused")]})
    ))

    assert evidence is None


def test_browser_rag_two_turns_remain_strictly_scoped_to_each_response():
    adapter = _adapter({"enabled": True, "context_selector": ".source-content"})
    first = _response({".source-content": [FakeElement("Context 1")]})
    second = _response({".source-content": [FakeElement("Context 2")]})

    evidence_one = asyncio.run(adapter._extract_rag_evidence_from_response(first))
    evidence_two = asyncio.run(adapter._extract_rag_evidence_from_response(second))

    assert evidence_one.contexts == ["Context 1"]
    assert evidence_two.contexts == ["Context 2"]


def test_browser_rag_waits_for_configured_evidence_selector():
    source = FakeElement("Delayed context")
    adapter = _adapter({"enabled": True, "context_selector": ".source-content", "evidence_timeout_ms": 250})
    container = _response({".source-content": [source]})

    evidence = asyncio.run(adapter._extract_rag_evidence_from_response(container))

    assert source.waited is True
    assert evidence.contexts == ["Delayed context"]


def test_browser_rag_optional_expand_selector_is_best_effort():
    expander = FakeElement("Sources")
    adapter = _adapter({
        "enabled": True,
        "expand_selector": ".show-sources",
        "context_selector": ".source-content",
    })
    container = _response({
        ".show-sources": [expander],
        ".source-content": [FakeElement("Expanded context")],
    })

    evidence = asyncio.run(adapter._extract_rag_evidence_from_response(container))

    assert expander.clicked is True
    assert evidence.contexts == ["Expanded context"]


class CompletedFuture:
    def __init__(self, values):
        self.values = values

    def result(self, timeout=None):
        response, evidence = self.values.pop(0)
        return response


class TranscriptThread:
    def __init__(self, values, adapter):
        self.values = values
        self.adapter = adapter

    def dispatch(self, coro):
        if hasattr(coro, "close"):
            coro.close()
        response, evidence = self.values[0]
        self.adapter._last_response_rag_evidence = evidence
        return CompletedFuture(self.values)


def test_browser_rag_evidence_is_attached_to_current_agent_turn():
    adapter = BrowserChatAdapter.__new__(BrowserChatAdapter)
    adapter.interaction = {}
    adapter.transcript = []
    values = [
        ("Answer 1", RAGEvidence(available=True, source="agent_retrieval", contexts=["C1"])),
        ("Answer 2", RAGEvidence(available=True, source="agent_retrieval", contexts=["C2"])),
    ]
    adapter._thread = TranscriptThread(values, adapter)

    adapter.send_message("Question 1")
    adapter.send_message("Question 2")

    assert adapter.transcript[1].rag_evidence.contexts == ["C1"]
    assert adapter.transcript[3].rag_evidence.contexts == ["C2"]
