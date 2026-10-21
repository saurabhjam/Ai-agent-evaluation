"""
Generic Scenario Execution Layer.

Executes a TestScenario against a saved AgentConnection.

Independent from DeepEval or any vendor-specific logic.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import inspect
from typing import Any, Optional
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.models.connection import AgentConnection, AgentType
from app.connections.manager import ConnectionManager
from app.config import settings
from app.interactive.orchestrator import ConversationOrchestrator
from app.interaction_dispatcher import dispatch_interaction
from app.schemas import TestScenario
from app.simulator import generate_next_user_turn
from app.session import BrowserSession, EvaluationSession
from app.voice.persona import VoicePersonaEngine
from app.voice.converter import voice_to_normalized_conversation
from app.adapters.chat.base import ChatAdapterError, FieldNotFound

logger = logging.getLogger(__name__)

def deep_merge(dict1: dict, dict2: dict) -> dict:
    """Deep merge dict2 into dict1."""
    import copy
    result = copy.deepcopy(dict1)
    for k, v in dict2.items():
        if isinstance(v, dict) and k in result and isinstance(result[k], dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _resolve_storage_state(config: dict[str, Any]) -> str | None:
    auth = config.get("auth") or {}
    return auth.get("storage_state") or config.get("storage_state")


def _message_attr(message: Any, name: str, default: Any = None) -> Any:
    if isinstance(message, dict):
        return message.get(name, default)
    return getattr(message, name, default)


def _latest_agent_message(transcript: list[Any]) -> Any | None:
    for message in reversed(transcript):
        if _message_attr(message, "role") == "agent":
            return message
    return None


def _component_text(component: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = component.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _selectable_component_message(component: dict[str, Any]) -> str | None:
    component_type = str(component.get("type") or "").lower()
    component_subtype = str(component.get("subtype") or "").lower()
    if component_type not in {"button", "quick_reply", "option"} and component_subtype != "quick_reply":
        return None

    return _component_text(
        component,
        ("message", "value", "payload", "text", "label", "title", "id"),
    ) or None


def _tokenize_for_option_selection(text: str) -> set[str]:
    import re

    stop_words = {
        "a", "an", "and", "are", "as", "at", "be", "for", "from", "how",
        "i", "in", "is", "it", "me", "my", "of", "on", "or", "please",
        "the", "this", "to", "what", "which", "with", "you", "your",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in stop_words
    }


def _choose_interactive_option(scenario: TestScenario, transcript: list[Any]) -> str | None:
    latest_agent = _latest_agent_message(transcript)
    if latest_agent is None:
        return None

    metadata = _message_attr(latest_agent, "metadata") or {}
    if not isinstance(metadata, dict):
        return None

    raw_components = metadata.get("components") or metadata.get("rich_components") or []
    if not isinstance(raw_components, list):
        return None

    options: list[tuple[dict[str, Any], str]] = []
    for component in raw_components:
        if not isinstance(component, dict):
            continue
        message = _selectable_component_message(component)
        if message:
            options.append((component, message))

    if not options:
        return None

    goal_text = " ".join(
        part
        for part in [
            scenario.persona.goal,
            scenario.persona.tone,
            scenario.persona.edge_case or "",
            _message_attr(latest_agent, "content", "") or "",
        ]
        if part
    )
    goal_tokens = _tokenize_for_option_selection(goal_text)

    best_message = options[0][1]
    best_score = -1
    for component, message in options:
        option_text = " ".join(
            str(value)
            for value in [
                component.get("label"),
                component.get("message"),
                component.get("value"),
                component.get("text"),
                component.get("title"),
                component.get("id"),
            ]
            if value not in (None, "")
        )
        option_tokens = _tokenize_for_option_selection(option_text)
        score = len(goal_tokens & option_tokens)
        if score > best_score:
            best_score = score
            best_message = message

    return best_message


class ExecutionResult(BaseModel):
    """
    Normalized result of executing a scenario against an AgentConnection.
    """

    success: bool
    connection_id: str
    agent_type: str
    adapter: str
    session_id: Optional[str] = None
    transcript: Optional[list[Any]] = None
    voice_conversation: Optional[Any] = Field(default=None, exclude=True)
    error: Optional[str] = None
    started_at: str
    completed_at: str


class ScenarioExecutor:
    """
    Executes a scenario against an agent connection.

    Resolves the correct adapter, runs the conversation, and returns
    a normalized result.

    Does NOT perform evaluation.

    The saved AgentConnection is the canonical source of truth for
    connection/transport configuration. The scenario defines the
    test behavior, persona, goals, and other test-specific data.
    """

    def __init__(
        self,
        connection_manager: Optional[ConnectionManager] = None,
    ) -> None:
        self.manager = connection_manager or ConnectionManager()

    def execute(
        self,
        connection: AgentConnection,
        scenario: TestScenario,
    ) -> ExecutionResult:
        """
        Execute the scenario.

        Handles both chatbot and voice modalities automatically.

        IMPORTANT:
        The exact saved AgentConnection is passed to the adapter.
        We do not deep-merge scenario.agent.config into the connection
        and we do not clone/reconstruct the connection.

        This ensures that TEST and EVALUATE use the same canonical
        connection configuration, including authentication,
        request mappings, response mappings, headers, and endpoint.
        """

        started_at = datetime.now(timezone.utc).isoformat()

        if not connection.enabled:
            return ExecutionResult(
                success=False,
                connection_id=connection.id,
                agent_type=connection.type.value,
                adapter=connection.adapter,
                error="Connection is disabled",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

        # ---------------------------------------------------------
        # We deep-merge scenario.agent.config into a copy of connection.config
        # to support legacy scenarios that still pass connection config (or TTS/STT).
        # ---------------------------------------------------------
        try:
            import copy
            merged_config = copy.deepcopy(connection.config)
            if scenario.agent and scenario.agent.config:
                merged_config = deep_merge(merged_config, scenario.agent.config)
                
            logger.warning(f"[UI FLOW DIAGNOSTIC] Merged config storage_state: {merged_config.get('storage_state', 'NOT FOUND')}")
                
            merged_connection = connection.model_copy(update={"config": merged_config})
            browser_session = BrowserSession(
                storage_state=_resolve_storage_state(merged_config),
                connection_config=merged_config,
            )
            evaluation_session = EvaluationSession.create(
                merged_connection,
                browser_session=browser_session,
            )
            adapter = self._create_adapter(
                merged_connection,
                evaluation_session=evaluation_session,
            )

        except Exception as e:
            logger.exception(
                "Failed to instantiate adapter for connection %s",
                connection.id,
            )
            if "evaluation_session" in locals():
                try:
                    evaluation_session.cleanup()
                except Exception:
                    logger.exception("Adapter initialization cleanup failed for connection %s", connection.id)

            return ExecutionResult(
                success=False,
                connection_id=connection.id,
                agent_type=connection.type.value,
                adapter=connection.adapter,
                error=f"Adapter instantiation failed: {type(e).__name__}: {str(e) or repr(e)}",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

        try:
            if connection.type == AgentType.chatbot:
                return self._execute_chatbot(
                    connection=connection,
                    adapter=adapter,
                    scenario=scenario,
                    started_at=started_at,
                )

            elif connection.type == AgentType.voice:
                return self._execute_voice(
                    connection=connection,
                    adapter=adapter,
                    scenario=scenario,
                    started_at=started_at,
                )

            else:
                raise ValueError(
                    f"Unsupported agent type: {connection.type}"
                )

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.exception(
                "Scenario execution failed for connection %s",
                connection.id,
            )

            return ExecutionResult(
                success=False,
                connection_id=connection.id,
                agent_type=connection.type.value,
                adapter=connection.adapter,
                error=f"Execution failed: {type(e).__name__}: {str(e) or repr(e)}\n\nTraceback:\n{tb}",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
        finally:
            evaluation_session.cleanup()

    def _create_adapter(
        self,
        connection: AgentConnection,
        evaluation_session: EvaluationSession,
    ) -> Any:
        try:
            signature = inspect.signature(self.manager.create_adapter)
        except (TypeError, ValueError):
            signature = None

        if signature and "evaluation_session" in signature.parameters:
            return self.manager.create_adapter(
                connection,
                evaluation_session=evaluation_session,
            )

        return self.manager.create_adapter(connection)

    def _execute_chatbot(
        self,
        connection: AgentConnection,
        adapter: Any,
        scenario: TestScenario,
        started_at: str,
    ) -> ExecutionResult:
        """
        Execute a chatbot scenario.

        The scenario controls the simulated customer's behavior.
        The adapter controls communication with the target chatbot.
        """

        END_TOKEN = "[END_CONVERSATION]"

        adapter.connect()

        try:
            if settings.enable_user_action_engine:
                orchestrator = ConversationOrchestrator()
                seen_turns = set()
                for _ in range(scenario.max_turns):
                    turn = orchestrator.run_turn(
                        adapter=adapter,
                        adapter_name=connection.adapter,
                        scenario=scenario,
                        agent_prompt=scenario.agent_prompt,
                    )
                    if not turn.should_continue:
                        break
                        
                    if turn.user_message:
                        normalized_message = turn.user_message.strip().lower()
                        if normalized_message in seen_turns:
                            break
                        seen_turns.add(normalized_message)
            elif scenario.steps:
                step_error = self._execute_chatbot_steps(
                    adapter=adapter,
                    scenario=scenario,
                )
                if step_error:
                    conversation = adapter.get_conversation()
                    return ExecutionResult(
                        success=False,
                        connection_id=connection.id,
                        agent_type=AgentType.chatbot.value,
                        adapter=connection.adapter,
                        transcript=conversation.messages,
                        error=step_error,
                        started_at=started_at,
                        completed_at=datetime.now(timezone.utc).isoformat(),
                    )
            else:
                seen_turns = set()
                for _ in range(scenario.max_turns):
                    transcript = adapter.get_transcript()

                    if dispatch_interaction(adapter=adapter, scenario=scenario, transcript=transcript):
                        continue

                    interactive_message = _choose_interactive_option(
                        scenario,
                        transcript,
                    )
                    if interactive_message:
                        user_message = interactive_message
                        user_attachments = None
                    else:
                        user_turn = generate_next_user_turn(
                            scenario.persona,
                            transcript,
                        )

                        user_message = user_turn["message"]
                        user_attachments = user_turn.get("attachments")

                    if END_TOKEN in user_message or not user_message:
                        break

                    normalized_message = user_message.strip().lower()
                    if normalized_message in seen_turns:
                        break
                    seen_turns.add(normalized_message)

                    adapter.send_message(
                        user_message,
                        agent_prompt=scenario.agent_prompt,
                        attachments=user_attachments,
                    )

        finally:
            adapter.close()

        conversation = adapter.get_conversation()

        return ExecutionResult(
            success=True,
            connection_id=connection.id,
            agent_type=AgentType.chatbot.value,
            adapter=connection.adapter,
            transcript=conversation.messages,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    def _execute_chatbot_steps(
        self,
        *,
        adapter: Any,
        scenario: TestScenario,
    ) -> str | None:
        for index, step in enumerate(scenario.steps or [], start=1):
            try:
                if "send" in step:
                    payload = step["send"]
                    message = payload.get("text") if isinstance(payload, dict) else payload
                    if not message:
                        return f"Step {index} failed: send requires a non-empty message."
                    adapter.send_message(
                        str(message),
                        agent_prompt=scenario.agent_prompt,
                        attachments=payload.get("attachments") if isinstance(payload, dict) else None,
                    )
                    self._execute_step_wait(adapter=adapter, payload=payload)
                    continue

                if "click_button" in step:
                    payload = step["click_button"]
                    if not isinstance(payload, dict):
                        return f"Step {index} failed: click_button requires an object with text or selector."
                    text = payload.get("text")
                    selector = payload.get("selector")
                    if not text and not selector:
                        return f"Step {index} failed: click_button requires text or selector."
                    adapter.click_button(
                        text=text,
                        metadata={
                            "selector": selector,
                            "timeout_ms": payload.get("timeout_ms"),
                        },
                    )
                    self._execute_step_wait(adapter=adapter, payload=payload)
                    continue

                if "select" in step:
                    payload = step["select"]
                    if not isinstance(payload, dict):
                        return f"Step {index} failed: select requires an object with field/selector and value."
                    field = payload.get("field")
                    selector = payload.get("selector")
                    value = payload.get("value")
                    if not value:
                        return f"Step {index} failed: select requires value."
                    if not field and not selector:
                        return f"Step {index} failed: select requires field or selector."
                    adapter.select_dropdown(
                        field=field,
                        value=str(value),
                        metadata={
                            "selector": selector,
                            "placeholder": payload.get("placeholder"),
                            "timeout_ms": payload.get("timeout_ms"),
                        },
                    )
                    self._execute_step_wait(adapter=adapter, payload=payload)
                    continue

                if "radio" in step:
                    payload = step["radio"]
                    if not isinstance(payload, dict):
                        return f"Step {index} failed: radio requires an object with field/selector and value."
                    field = payload.get("field")
                    selector = payload.get("selector")
                    value = payload.get("value")
                    if not value:
                        return f"Step {index} failed: radio requires value."
                    if not field and not selector:
                        return f"Step {index} failed: radio requires field or selector."
                    adapter.select_radio(
                        field=field,
                        value=str(value),
                        metadata={
                            "selector": selector,
                            "timeout_ms": payload.get("timeout_ms"),
                        },
                    )
                    self._execute_step_wait(adapter=adapter, payload=payload)
                    continue

                if "checkbox" in step:
                    payload = step["checkbox"]
                    if not isinstance(payload, dict):
                        return f"Step {index} failed: checkbox requires an object with field/selector and value."
                    field = payload.get("field")
                    selector = payload.get("selector")
                    if "value" not in payload:
                        return f"Step {index} failed: checkbox requires value."
                    if not field and not selector:
                        return f"Step {index} failed: checkbox requires field or selector."
                    adapter.select_checkbox(
                        field=field,
                        value=self._coerce_step_bool(payload.get("value")),
                        metadata={
                            "selector": selector,
                            "timeout_ms": payload.get("timeout_ms"),
                        },
                    )
                    self._execute_step_wait(adapter=adapter, payload=payload)
                    continue

                if "multi_select" in step:
                    payload = step["multi_select"]
                    if not isinstance(payload, dict):
                        return f"Step {index} failed: multi_select requires an object with field/selector and values."
                    field = payload.get("field")
                    selector = payload.get("selector")
                    values = payload.get("values")
                    if not values or not isinstance(values, list):
                        return f"Step {index} failed: multi_select requires values list."
                    if not field and not selector:
                        return f"Step {index} failed: multi_select requires field or selector."
                    adapter.select_multi_select(
                        field=field,
                        values=[str(value) for value in values],
                        metadata={
                            "selector": selector,
                            "placeholder": payload.get("placeholder"),
                            "timeout_ms": payload.get("timeout_ms"),
                        },
                    )
                    self._execute_step_wait(adapter=adapter, payload=payload)
                    continue

                if "upload" in step:
                    payload = step["upload"]
                    if not isinstance(payload, dict):
                        return f"Step {index} failed: upload requires an object with file and optional field/selector."
                    file_path = payload.get("file")
                    if not file_path:
                        return f"Step {index} failed: upload requires file."
                    field = payload.get("field")
                    selector = payload.get("selector")
                    metadata = {
                        "selector": selector,
                        "name": payload.get("name"),
                        "timeout_ms": payload.get("timeout_ms"),
                        "mode": payload.get("mode", "scenario"),
                    }
                    if self._is_image_upload(str(file_path)):
                        adapter.upload_image(str(file_path), field=field, metadata=metadata)
                    else:
                        adapter.upload_file(str(file_path), field=field, metadata=metadata)
                    self._execute_step_wait(adapter=adapter, payload=payload)
                    continue

                if "otp" in step:
                    payload = step["otp"]
                    if not isinstance(payload, dict):
                        return f"Step {index} failed: otp requires an object with field/selector and value."
                    value = payload.get("value")
                    field = payload.get("field")
                    selector = payload.get("selector")
                    if value is None or value == "":
                        return f"Step {index} failed: otp requires value."
                    if not field and not selector:
                        return f"Step {index} failed: otp requires field or selector."
                    adapter.enter_otp(
                        str(value),
                        field=field,
                        metadata={
                            "selector": selector,
                            "placeholder": payload.get("placeholder"),
                            "name": payload.get("name"),
                            "timeout_ms": payload.get("timeout_ms"),
                        },
                    )
                    self._execute_step_wait(adapter=adapter, payload=payload)
                    continue

                if "date" in step:
                    payload = step["date"]
                    if not isinstance(payload, dict):
                        return f"Step {index} failed: date requires an object with field/selector and value."
                    value = payload.get("value")
                    field = payload.get("field")
                    selector = payload.get("selector")
                    if not value:
                        return f"Step {index} failed: date requires value."
                    if not field and not selector:
                        return f"Step {index} failed: date requires field or selector."
                    adapter.pick_date(
                        field=field,
                        value=str(value),
                        metadata={
                            "selector": selector,
                            "placeholder": payload.get("placeholder"),
                            "name": payload.get("name"),
                            "timeout_ms": payload.get("timeout_ms"),
                        },
                    )
                    self._execute_step_wait(adapter=adapter, payload=payload)
                    continue

                if "time" in step:
                    payload = step["time"]
                    if not isinstance(payload, dict):
                        return f"Step {index} failed: time requires an object with field/selector and value."
                    value = payload.get("value")
                    field = payload.get("field")
                    selector = payload.get("selector")
                    if not value:
                        return f"Step {index} failed: time requires value."
                    if not field and not selector:
                        return f"Step {index} failed: time requires field or selector."
                    adapter.pick_time(
                        field=field,
                        value=str(value),
                        metadata={
                            "selector": selector,
                            "placeholder": payload.get("placeholder"),
                            "name": payload.get("name"),
                            "timeout_ms": payload.get("timeout_ms"),
                        },
                    )
                    self._execute_step_wait(adapter=adapter, payload=payload)
                    continue

                if "search" in step:
                    payload = step["search"]
                    if not isinstance(payload, dict):
                        return f"Step {index} failed: search requires an object with field/selector and value."
                    value = payload.get("value")
                    field = payload.get("field")
                    selector = payload.get("selector")
                    if value is None or value == "":
                        return f"Step {index} failed: search requires value."
                    if not field and not selector:
                        return f"Step {index} failed: search requires field or selector."
                    adapter.search(
                        str(value),
                        field=field,
                        metadata={
                            "selector": selector,
                            "placeholder": payload.get("placeholder"),
                            "name": payload.get("name"),
                            "timeout_ms": payload.get("timeout_ms"),
                        },
                    )
                    self._execute_step_wait(adapter=adapter, payload=payload)
                    continue

                if "form" in step:
                    payload = step["form"]
                    if not isinstance(payload, dict):
                        return f"Step {index} failed: form requires an object of fields."
                    form_error = self._execute_form_step(
                        adapter=adapter,
                        payload={key: value for key, value in payload.items() if key != "wait_for"},
                        agent_prompt=scenario.agent_prompt,
                    )
                    if form_error:
                        return f"Step {index} failed: {form_error}"
                    self._execute_step_wait(adapter=adapter, payload=payload)
                    continue

                return f"Step {index} failed: unsupported step action. Supported actions: send, click_button, select, radio, checkbox, multi_select, upload, otp, date, time, search, form."
            except ChatAdapterError as exc:
                return f"Step {index} failed: {type(exc).__name__}: {exc}"
            except Exception as exc:  # noqa: BLE001
                return f"Step {index} failed: {type(exc).__name__}: {str(exc) or repr(exc)}"

        return None

    def _execute_step_wait(self, *, adapter: Any, payload: Any) -> None:
        if not isinstance(payload, dict):
            return

        wait_for = payload.get("wait_for")
        if not wait_for:
            return
        if not isinstance(wait_for, dict):
            raise ValueError("wait_for requires an object.")

        expected_text = wait_for.get("text")
        if not expected_text:
            raise ValueError("wait_for currently requires text.")

        timeout = wait_for.get("timeout")
        adapter.wait_for_text(
            str(expected_text),
            timeout=float(timeout) if timeout is not None else None,
            metadata={"wait_for": wait_for},
        )

    def _execute_form_step(self, *, adapter: Any, payload: dict[str, Any], agent_prompt: str | None = None) -> str | None:
        for raw_field, raw_spec in payload.items():
            field_spec = self._normalise_form_field(raw_field, raw_spec)
            if field_spec["type"] == "hidden":
                continue

            try:
                self._execute_form_field(adapter=adapter, spec=field_spec, agent_prompt=agent_prompt)
            except FieldNotFound as exc:
                if field_spec["required"]:
                    return f"Required field missing: {field_spec['label']} ({type(exc).__name__}: {exc})"
                logger.info("Optional form field not found, continuing: %s", field_spec["label"])
            except ChatAdapterError as exc:
                return f"{type(exc).__name__}: {exc}"
            except Exception as exc:  # noqa: BLE001
                return f"{type(exc).__name__}: {str(exc) or repr(exc)}"
        return None

    def _normalise_form_field(self, raw_field: str, raw_spec: Any) -> dict[str, Any]:
        if isinstance(raw_spec, dict):
            value = raw_spec.get("value")
            explicit_type = raw_spec.get("type")
            required = bool(raw_spec.get("required", True))
            selector = raw_spec.get("selector")
            label = raw_spec.get("label") or self._humanize_field_name(raw_field)
            placeholder = raw_spec.get("placeholder")
            name = raw_spec.get("name") or raw_field
        else:
            value = raw_spec
            explicit_type = None
            required = True
            selector = None
            label = self._humanize_field_name(raw_field)
            placeholder = None
            name = raw_field

        return {
            "key": raw_field,
            "label": label,
            "value": value,
            "type": self._infer_form_field_type(raw_field, value, explicit_type),
            "required": required,
            "selector": selector,
            "placeholder": placeholder,
            "name": name,
        }

    def _execute_form_field(self, *, adapter: Any, spec: dict[str, Any], agent_prompt: str | None = None) -> None:
        field_type = spec["type"]
        value = spec["value"]
        label = spec["label"]
        metadata = {
            "selector": spec.get("selector"),
            "placeholder": spec.get("placeholder"),
            "name": spec.get("name"),
        }

        if field_type in {"text", "textarea", "email", "phone", "number", "password", "url", "search"}:
            if value is None or value == "":
                raise ValueError(f"Invalid value for field '{label}'.")
            adapter.send_message(f"Form\n{label} = {value}", agent_prompt=agent_prompt, attachments=None)
            return

        if field_type == "dropdown":
            adapter.select_dropdown(field=label, value=str(value), metadata=metadata)
            return

        if field_type == "radio":
            adapter.select_radio(field=label, value=str(value), metadata=metadata)
            return

        if field_type == "checkbox":
            adapter.select_checkbox(field=label, value=self._coerce_step_bool(value), metadata=metadata)
            return

        if field_type == "multi_select":
            if not isinstance(value, list):
                raise ValueError(f"Invalid value for multi-select field '{label}': expected list.")
            adapter.select_multi_select(field=label, values=[str(item) for item in value], metadata=metadata)
            return

        raise ValueError(f"Unsupported field type '{field_type}' for field '{label}'.")

    def _infer_form_field_type(self, field: str, value: Any, explicit_type: Any) -> str:
        if explicit_type:
            normalized = str(explicit_type).strip().lower().replace("-", "_")
            aliases = {
                "select": "dropdown",
                "dropdown": "dropdown",
                "radio": "radio",
                "checkbox": "checkbox",
                "multi_select": "multi_select",
                "multiselect": "multi_select",
                "textarea": "textarea",
                "text_area": "textarea",
            }
            return aliases.get(normalized, normalized)

        normalized_field = field.strip().lower()
        if isinstance(value, bool):
            return "checkbox"
        if isinstance(value, list):
            return "multi_select"
        if normalized_field in {"city", "state", "country", "language", "languages"}:
            return "dropdown"
        if "insurance" in normalized_field or normalized_field.endswith("_type"):
            return "radio"
        if any(token in normalized_field for token in ["accept", "terms", "consent", "agree"]):
            return "checkbox"
        if "email" in normalized_field:
            return "email"
        if "phone" in normalized_field or "mobile" in normalized_field:
            return "phone"
        if "url" in normalized_field or "website" in normalized_field:
            return "url"
        if "password" in normalized_field:
            return "password"
        if "search" in normalized_field:
            return "search"
        return "text"

    def _humanize_field_name(self, field: str) -> str:
        return " ".join(part.capitalize() for part in field.replace("-", "_").split("_") if part)

    def _is_image_upload(self, file_path: str) -> bool:
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type and mime_type.startswith("image/"):
            return True
        return os.path.splitext(file_path)[1].lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

    def _coerce_step_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return bool(value)

    def _execute_voice(
        self,
        connection: AgentConnection,
        adapter: Any,
        scenario: TestScenario,
        started_at: str,
    ) -> ExecutionResult:
        """
        Execute a voice scenario.

        The voice adapter remains responsible for the actual voice
        transport. The persona engine generates the simulated
        customer's behavior.
        """

        tts = getattr(adapter, "_tts", None)

        engine = VoicePersonaEngine(
            persona=scenario.persona,
            adapter=adapter,
            tts_provider=tts,
            max_turns=scenario.max_turns,
            max_session_duration_seconds=900,
        )

        vc = engine.run_automated_session()

        normalized = voice_to_normalized_conversation(vc)

        session_id = (
            vc.session.session_id
            if vc.session
            else None
        )

        return ExecutionResult(
            success=True,
            connection_id=connection.id,
            agent_type=AgentType.voice.value,
            adapter=connection.adapter,
            session_id=session_id,
            transcript=normalized.messages,
            voice_conversation=vc,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
