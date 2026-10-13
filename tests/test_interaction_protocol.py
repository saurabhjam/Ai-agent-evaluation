import threading
import time

from app.interaction_protocol import InteractionManager


def test_interaction_request_without_listener_returns_none():
    manager = InteractionManager(default_timeout_seconds=0.01)

    result = manager.request_interaction(
        evaluation_id="eval-none",
        interaction_type="image_upload",
        prompt="Image required",
        component={"type": "image_upload"},
    )

    assert result["status"] == "TIMED_OUT"
    assert result["reason"] == "User did not respond"


def test_interaction_request_resumes_when_response_arrives():
    manager = InteractionManager()
    captured = {}

    def run_request():
        captured["response"] = manager.request_interaction(
            evaluation_id="eval-1",
            interaction_type="image_upload",
            prompt="Image required",
            component={"type": "image_upload"},
            timeout_seconds=1,
        )

    # Simulate an already-connected frontend listener without needing a real WebSocket.
    class Loop:
        def call_soon_threadsafe(self, callback, *args):
            callback(*args)

    class Queue:
        def put_nowait(self, item):
            captured["request"] = item

    manager._listeners["eval-1"].add((Queue(), Loop()))

    thread = threading.Thread(target=run_request)
    thread.start()

    for _ in range(50):
        if "request" in captured:
            break
        time.sleep(0.01)

    assert captured["request"]["type"] == "interaction_request"
    manager.respond(
        captured["request"]["interaction_id"],
        {"source": "device", "file": {"name": "photo.jpg", "content": "abc"}},
    )
    thread.join(timeout=2)

    assert captured["response"]["source"] == "device"
    assert captured["response"]["file"]["name"] == "photo.jpg"
    assert captured["response"]["status"] == "SUCCESS"
    assert "requested_at" in captured["response"]
    assert "responded_at" in captured["response"]
    assert captured["response"]["duration_ms"] >= 0


def test_pending_interaction_replays_on_reconnect():
    manager = InteractionManager(default_timeout_seconds=1)
    captured = {}

    def run_request():
        captured["response"] = manager.request_interaction(
            evaluation_id="eval-reconnect",
            interaction_type="image_upload",
            prompt="Image required",
            component={"type": "image_upload"},
        )

    thread = threading.Thread(target=run_request)
    thread.start()
    time.sleep(0.05)

    class Loop:
        def call_soon_threadsafe(self, callback, *args):
            callback(*args)

    class Queue:
        def put_nowait(self, item):
            captured["request"] = item

    manager._listeners["eval-reconnect"].add((Queue(), Loop()))
    with manager._lock:
        pending = manager._current_pending_locked("eval-reconnect")
        pending["delivered"] = False
        manager._dispatch_next_locked("eval-reconnect")

    assert captured["request"]["evaluation_id"] == "eval-reconnect"
    manager.respond(captured["request"]["interaction_id"], {"source": "device"}, evaluation_id="eval-reconnect")
    thread.join(timeout=2)
    assert captured["response"]["source"] == "device"


def test_concurrent_evaluations_are_isolated():
    manager = InteractionManager(default_timeout_seconds=1)
    captured = {}

    class Loop:
        def call_soon_threadsafe(self, callback, *args):
            callback(*args)

    class Queue:
        def __init__(self, name):
            self.name = name

        def put_nowait(self, item):
            captured[self.name] = item

    manager._listeners["eval-a"].add((Queue("a"), Loop()))
    manager._listeners["eval-b"].add((Queue("b"), Loop()))

    responses = {}
    threads = [
        threading.Thread(target=lambda: responses.setdefault("a", manager.request_interaction(
            evaluation_id="eval-a", interaction_type="image_upload", prompt="A", component={}
        ))),
        threading.Thread(target=lambda: responses.setdefault("b", manager.request_interaction(
            evaluation_id="eval-b", interaction_type="otp", prompt="B", component={}
        ))),
    ]
    for thread in threads:
        thread.start()

    for _ in range(50):
        if "a" in captured and "b" in captured:
            break
        time.sleep(0.01)

    assert captured["a"]["evaluation_id"] == "eval-a"
    assert captured["b"]["evaluation_id"] == "eval-b"
    assert manager.respond(captured["a"]["interaction_id"], {"ok": "wrong"}, evaluation_id="eval-b") is False
    assert manager.respond(captured["a"]["interaction_id"], {"ok": "a"}, evaluation_id="eval-a") is True
    assert manager.respond(captured["b"]["interaction_id"], {"ok": "b"}, evaluation_id="eval-b") is True
    for thread in threads:
        thread.join(timeout=2)
    assert responses["a"]["ok"] == "a"
    assert responses["b"]["ok"] == "b"


def test_interaction_queue_delivers_fifo():
    manager = InteractionManager(default_timeout_seconds=1)
    delivered = []

    class Loop:
        def call_soon_threadsafe(self, callback, *args):
            callback(*args)

    class Queue:
        def put_nowait(self, item):
            delivered.append(item)

    manager._listeners["eval-q"].add((Queue(), Loop()))
    responses = {}
    first_thread = threading.Thread(target=lambda: responses.setdefault("first", manager.request_interaction(
            evaluation_id="eval-q", interaction_type="image_upload", prompt="First", component={}
        )))
    first_thread.start()

    for _ in range(50):
        if delivered:
            break
        time.sleep(0.01)

    assert len(delivered) == 1
    assert delivered[0]["prompt"] == "First"

    second_thread = threading.Thread(target=lambda: responses.setdefault("second", manager.request_interaction(
        evaluation_id="eval-q", interaction_type="otp", prompt="Second", component={}
    )))
    second_thread.start()
    time.sleep(0.05)
    assert len(delivered) == 1

    manager.respond(delivered[0]["interaction_id"], {"done": "first"}, evaluation_id="eval-q")

    for _ in range(50):
        if len(delivered) == 2:
            break
        time.sleep(0.01)

    assert delivered[1]["prompt"] == "Second"
    manager.respond(delivered[1]["interaction_id"], {"done": "second"}, evaluation_id="eval-q")
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)
    assert responses["first"]["done"] == "first"
    assert responses["second"]["done"] == "second"
