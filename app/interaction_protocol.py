"""Evaluation-scoped pause/resume protocol for real-time interactions."""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.config import settings


class InteractionManager:
    def __init__(self, default_timeout_seconds: float | None = None) -> None:
        self._lock = threading.Lock()
        self._listeners: dict[str, set[tuple[asyncio.Queue, asyncio.AbstractEventLoop]]] = defaultdict(set)
        self._pending: dict[str, dict[str, Any]] = {}
        self._queues: dict[str, list[str]] = defaultdict(list)
        self.default_timeout_seconds = float(default_timeout_seconds or settings.interaction_timeout_seconds)

    def subscribe(self, evaluation_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        with self._lock:
            self._listeners[evaluation_id].add((queue, loop))
            pending = self._current_pending_locked(evaluation_id)
            if pending:
                loop.call_soon_threadsafe(queue.put_nowait, pending["request"])
        return queue

    def unsubscribe(self, evaluation_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            for item in list(self._listeners.get(evaluation_id, set())):
                if item[0] is queue:
                    self._listeners[evaluation_id].remove(item)

    def request_interaction(
        self,
        *,
        evaluation_id: str,
        interaction_type: str,
        prompt: str,
        component: dict[str, Any],
        timeout_seconds: float | None = None,
    ) -> dict[str, Any] | None:
        interaction_id = f"interaction_{uuid.uuid4().hex}"
        event = threading.Event()
        requested_at = datetime.now(timezone.utc)
        request = {
            "type": "interaction_request",
            "interaction_id": interaction_id,
            "evaluation_id": evaluation_id,
            "interaction_type": interaction_type,
            "prompt": prompt,
            "component": _json_safe(component),
            "created_at": requested_at.isoformat(),
            "requested_at": requested_at.isoformat(),
            "timeout_seconds": float(timeout_seconds or self.default_timeout_seconds),
        }

        with self._lock:
            self._pending[interaction_id] = {
                "event": event,
                "response": None,
                "evaluation_id": evaluation_id,
                "request": request,
                "requested_at": requested_at,
                "delivered": False,
            }
            self._queues[evaluation_id].append(interaction_id)
            self._dispatch_next_locked(evaluation_id)

        if not event.wait(float(timeout_seconds or self.default_timeout_seconds)):
            self._complete(
                interaction_id,
                {
                    "cancelled": True,
                    "error": "User did not respond",
                    "reason": "User did not respond",
                    "status": "TIMED_OUT",
                },
                evaluation_id=evaluation_id,
            )

        with self._lock:
            pending = self._pending.pop(interaction_id, None)
            self._remove_from_queue_locked(evaluation_id, interaction_id)
            self._dispatch_next_locked(evaluation_id)
        return pending.get("response") if pending else None

    def respond(self, interaction_id: str, payload: dict[str, Any], *, evaluation_id: str | None = None) -> bool:
        return self._complete(interaction_id, payload, evaluation_id=evaluation_id)

    def _complete(self, interaction_id: str, payload: dict[str, Any], *, evaluation_id: str | None = None) -> bool:
        with self._lock:
            pending = self._pending.get(interaction_id)
            if not pending:
                return False
            if evaluation_id is not None and pending["evaluation_id"] != evaluation_id:
                return False
            response = dict(payload or {})
            responded_at = datetime.now(timezone.utc)
            requested_at = pending["requested_at"]
            response.setdefault("status", "CANCELLED" if response.get("cancelled") else "SUCCESS")
            response.setdefault("requested_at", requested_at.isoformat())
            response.setdefault("responded_at", responded_at.isoformat())
            response.setdefault("duration_ms", int((responded_at - requested_at).total_seconds() * 1000))
            pending["response"] = payload
            pending["response"] = response
            pending["event"].set()
            return True

    def _current_pending_locked(self, evaluation_id: str) -> dict[str, Any] | None:
        for interaction_id in self._queues.get(evaluation_id, []):
            pending = self._pending.get(interaction_id)
            if pending:
                return pending
        return None

    def _dispatch_next_locked(self, evaluation_id: str) -> None:
        pending = self._current_pending_locked(evaluation_id)
        if not pending or pending.get("delivered"):
            return
        listeners = list(self._listeners.get(evaluation_id, set()))
        if not listeners:
            return
        pending["delivered"] = True
        for queue, loop in listeners:
            loop.call_soon_threadsafe(queue.put_nowait, pending["request"])

    def _remove_from_queue_locked(self, evaluation_id: str, interaction_id: str) -> None:
        queue = self._queues.get(evaluation_id)
        if not queue:
            return
        if interaction_id in queue:
            queue.remove(interaction_id)
        if not queue:
            self._queues.pop(evaluation_id, None)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
            if key not in {"buffer", "content", "data", "file_object", "blob"}
        }
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


interaction_manager = InteractionManager()
