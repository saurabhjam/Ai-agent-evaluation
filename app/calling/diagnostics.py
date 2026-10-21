"""Optional calling diagnostics. Free text never enters ordinary logs."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
import hashlib
import hmac
import json
import inspect
import re
import secrets
import time

from app.config import settings
from app.log_stream import log_manager


@dataclass
class Trace:
    evaluation_id: str
    session_id: str = ""
    turn_id: str | None = None
    outbound: list[tuple[str, str]] = field(default_factory=list)


_trace: ContextVar[Trace | None] = ContextVar("calling_diagnostics", default=None)
_key = secrets.token_bytes(32)
_secret = re.compile(r"key|secret|token|password|authorization|credential|header", re.I)


def fingerprint(text):
    return hmac.new(_key, str(text).encode("utf-8"), hashlib.sha256).hexdigest()


def masked(value):
    if isinstance(value, dict):
        return {str(k): "[SECRET OMITTED]" if _secret.search(str(k)) else masked(v)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [masked(v) for v in value]
    if value is None:
        return None
    text = str(value)
    return {"redacted": True, "length": len(text), "fingerprint": fingerprint(text)}


def _private_payload(value):
    """Remove credential fields and known secrets even from embedded prompt text."""
    secret_values = []

    def collect(item):
        if isinstance(item, dict):
            for key, val in item.items():
                if _secret.search(str(key)) and isinstance(val, str) and val:
                    secret_values.append(val)
                collect(val)
        elif isinstance(item, (list, tuple)):
            for val in item:
                collect(val)

    collect(value)
    for name in type(settings).model_fields:
        if _secret.search(name):
            val = getattr(settings, name)
            val = val.get_secret_value() if hasattr(val, "get_secret_value") else val
            if isinstance(val, str) and val:
                secret_values.append(val)

    def scrub(item):
        if isinstance(item, dict):
            return {str(k): "[SECRET OMITTED]" if _secret.search(str(k)) else scrub(v)
                    for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [scrub(v) for v in item]
        if isinstance(item, str):
            for secret in secret_values:
                item = item.replace(secret, "[SECRET OMITTED]")
        return item

    return scrub(value)


def evaluation_id():
    trace = _trace.get()
    return trace.evaluation_id if trace else None


def control_snapshot(transport):
    if not settings.calling_diagnostics_enabled or _trace.get() is None:
        return None
    try:
        controls = getattr(transport, "control_messages", None)
        return (controls, len(controls)) if isinstance(controls, list) else None
    except Exception:
        return None


def observe_controls(snapshot):
    if snapshot is None:
        return
    try:
        controls, start = snapshot
        for event in controls[start:]:
            emit("utterance.control_observed", "transport_control_buffer", event,
                 event_time_known=False)
    except Exception:
        pass


def emit(stage, source, payload=None, *, duration_ms=None, **metadata):
    trace = _trace.get()
    if trace is None or not settings.calling_diagnostics_enabled:
        return
    # Diagnostics must never change the outcome of a call, even if the sink fails.
    try:
        event = {
            "schema": "calling.turn.v1", "evaluation_id": trace.evaluation_id,
            "session_id": trace.session_id, "turn_id": trace.turn_id,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "monotonic_ns": time.monotonic_ns(), "stage": stage, "source": source,
            "duration_ms": duration_ms, "data": masked(payload), **metadata,
        }
        if settings.calling_diagnostics_encrypted_text and payload is not None:
            try:
                from cryptography.fernet import Fernet

                key = settings.calling_diagnostics_encryption_key.get_secret_value()
                event["encrypted_data"] = Fernet(key.encode("ascii")).encrypt(
                    json.dumps(_private_payload(payload)).encode("utf-8")
                ).decode("ascii")
            except Exception:
                event["encrypted_capture_failed"] = True
        log_manager.add_log(trace.evaluation_id, {
            "timestamp": event["timestamp"], "level": "DEBUG",
            "logger": "app.calling.diagnostics", "message": json.dumps(event),
        })
    except Exception:
        pass


@contextmanager
def stage(name, source, payload=None):
    if _trace.get() is None:
        yield
        return
    start = time.perf_counter()
    emit(name + ".start", source, payload)
    try:
        yield
    except Exception as exc:
        emit(name + ".error", source, {"exception_type": type(exc).__name__},
             duration_ms=(time.perf_counter() - start) * 1000)
        raise
    finally:
        emit(name + ".end", source, duration_ms=(time.perf_counter() - start) * 1000)


def traced_evaluation(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not settings.calling_diagnostics_enabled:
            return fn(*args, **kwargs)
        from app.evaluation_store import new_evaluation_id
        token = _trace.set(Trace(new_evaluation_id()))
        try:
            with stage("evaluation", "calling_api"):
                result = fn(*args, **kwargs)
                if hasattr(result, "model_copy") and not getattr(result, "evaluation_id", None):
                    result = result.model_copy(update={"evaluation_id": evaluation_id()})
                emit("evaluation.result", "calling_api", {"status": result.status})
                return result
        finally:
            _trace.reset(token)
    # FastAPI must resolve the original module's forward annotations.
    wrapped.__signature__ = inspect.signature(fn, eval_str=True)
    return wrapped


def traced_conversation(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not settings.calling_diagnostics_enabled:
            return fn(*args, **kwargs)
        parent = _trace.get()
        token = _trace.set(Trace(parent.evaluation_id if parent else kwargs["run_id"], kwargs["session_id"]))
        try:
            with stage("conversation", "calling_runner", {"provider_call_id": kwargs["session"].transport_call_id}):
                return fn(*args, **kwargs)
        finally:
            child = _trace.get()
            if parent is not None:
                parent.session_id = child.session_id
                parent.outbound.extend(child.outbound)
            _trace.reset(token)
    return wrapped


def begin_turn(index):
    trace = _trace.get()
    if trace:
        trace.turn_id = f"{trace.session_id}:{index}"


def customer_text(text):
    trace = _trace.get()
    if trace:
        trace.outbound.append((trace.turn_id, fingerprint(text)))
    emit("customer.selected", "simulator_return", {"text": text})


def provider_transcript(transcript):
    trace = _trace.get()
    if trace is None or transcript is None:
        return
    original_turn = trace.turn_id
    customer_index = 0
    try:
        for index, turn in enumerate(transcript.turns):
            speaker = getattr(turn.speaker, "value", turn.speaker)
            candidate = None
            if speaker == "customer":
                if customer_index < len(trace.outbound):
                    candidate = trace.outbound[customer_index]
                customer_index += 1
            trace.turn_id = candidate[0] if candidate else None
            emit("provider.transcript", "provider_transcription", {"text": turn.text, "transcript_source": transcript.source},
                 provider_turn_index=index, speaker=speaker,
                 correlation="ordinal_candidate" if candidate else "unaligned",
                 exact_text_match=(fingerprint(turn.text) == candidate[1]) if candidate else None,
                 evalforge_copy_is_independent=False)
    finally:
        trace.turn_id = original_turn
