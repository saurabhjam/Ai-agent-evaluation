import pytest
from unittest.mock import patch, MagicMock

from app.orchestrator import run_scenario
from app.schemas import TestScenario, AgentConfig, Persona
from app.models.conversation import ToolCallInfo
from app.adapters.chat.fake import FakeChatAdapter
from app.adapters.chat.rest import RestChatAdapter

@pytest.fixture
def sample_scenario():
    return TestScenario(
        scenario_id="test_universal_adapter",
        agent=AgentConfig(channel="chatbot", adapter="fake"),
        persona=Persona(
            name="Alice",
            goal="I want a refund for order A1029",
            tone="polite",
            edge_case=""
        ),
        max_turns=3,
        pass_threshold=0.5
    )

def test_evaluation_with_fake_adapter(sample_scenario):
    """
    Test the full evaluation pipeline using the FakeChatAdapter.
    Also tests tool call normalization.
    """
    with patch("app.orchestrator.AdapterFactory.create") as mock_create, \
         patch("app.orchestrator.generate_next_user_turn") as mock_gen_turn:
         
        adapter = FakeChatAdapter()
        
        def mock_send_message(message: str, agent_prompt=None, attachments=None):
            from app.models.conversation import ConversationMessage
            from datetime import datetime, timezone
            
            adapter.transcript.append(
                ConversationMessage(
                    role="simulated_user",
                    content=message,
                    turn_index=adapter._turn_index,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
            )
            
            tool_calls = None
            if "A1029" in message:
                tool_calls = [
                    ToolCallInfo(
                        tool_name="check_order_status",
                        tool_input={"order_id": "A1029"},
                        tool_output={"status": "Delivered", "damage": "Damaged"}
                    )
                ]
                reply = "Please upload a clear photo of the damaged product."
            elif "photo" in message.lower():
                reply = "I can help with a refund or replacement."
            else:
                reply = "Sorry about that. May I have your order number?"
                
            adapter.transcript.append(
                ConversationMessage(
                    role="agent",
                    content=reply,
                    turn_index=adapter._turn_index,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    tool_calls=tool_calls
                )
            )
            adapter._turn_index += 1
            return reply
            
        adapter.send_message = mock_send_message
        mock_create.return_value = adapter
        
        mock_gen_turn.side_effect = [
            {"message": "I received my order damaged.", "attachments": None},
            {"message": "It's A1029", "attachments": None},
            {"message": "Here is the photo.", "attachments": None},
            {"message": "[END_CONVERSATION]", "attachments": None}
        ]
        
        with patch("app.evaluator._build_metrics") as mock_build_metrics:
            mock_metric = MagicMock()
            mock_metric.score = 1.0
            mock_metric.success = True
            mock_metric.reason = "Good"
            mock_metric.name = "Goal Completion"
            mock_build_metrics.return_value = [mock_metric]
            
            result = run_scenario(sample_scenario)
            
            assert result.passed is True
            assert result.overall_score == 1.0
            assert len(result.transcript) == 6
            
            # Check the normalized conversation
            assert result.transcript[0].role == "simulated_user"
            assert result.transcript[1].role == "agent"
            assert result.transcript[1].content == "Sorry about that. May I have your order number?"
            
            # Check tool call normalization on the second agent response (index 3)
            assert result.transcript[3].role == "agent"
            assert result.transcript[3].tool_calls is not None
            assert len(result.transcript[3].tool_calls) == 1
            tool_call = result.transcript[3].tool_calls[0]
            assert tool_call.tool_name == "check_order_status"
            assert tool_call.tool_input == {"order_id": "A1029"}
            
            # Check capabilities
            assert adapter.capabilities.supports_tool_calls is False 
            
def test_rest_adapter_mapping_and_headers(sample_scenario):
    """
    Test the RestChatAdapter request/response mapping and header resolution.
    """
    import os
    os.environ["CLIENT_API_KEY"] = "secret-token-123"
    
    sample_scenario.agent = AgentConfig(
        channel="chatbot", 
        adapter="rest",
        config={
            "endpoint": "http://mock-server/chat",
            "headers": {
                "Authorization": "env:CLIENT_API_KEY",
                "Content-Type": "application/json"
            },
            "request_mapping": {
                "message_field": "payload.text",
                "session_id_field": "metadata.session",
                "static_fields": {
                    "bot_id": "test-bot"
                }
            },
            "response_mapping": {
                "reply_field": "data.reply.text",
                "tool_calls_field": "data.tools"
            }
        }
    )
    
    with patch("requests.request") as mock_req, \
         patch("app.orchestrator.generate_next_user_turn") as mock_gen_turn:
         
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "reply": {
                    "text": "Please upload a photo."
                },
                "tools": [
                    {
                        "name": "check_order",
                        "input": {"id": "A1029"},
                        "output": "Damaged"
                    }
                ]
            }
        }
        mock_req.return_value = mock_response
        
        mock_gen_turn.side_effect = [
            {"message": "My order is damaged.", "attachments": None},
            {"message": "[END_CONVERSATION]", "attachments": None}
        ]
        
        # Patch evaluation so we don't call real LLM
        with patch("app.evaluator._build_metrics") as mock_build_metrics:
            class DummyMetric:
                def __init__(self):
                    self.score = 1.0
                    self.success = True
                    self.reason = "Good"
                    self.name = "Goal Completion"
                def measure(self, tc): pass
            
            mock_metric = DummyMetric()
            mock_build_metrics.return_value = [mock_metric]
            
            result = run_scenario(sample_scenario)
            
            assert mock_req.call_count == 1
            args, kwargs = mock_req.call_args
            assert kwargs["url"] == "http://mock-server/chat"
            assert kwargs["headers"]["Authorization"] == "secret-token-123"
            assert kwargs["headers"]["Content-Type"] == "application/json"
            
            # Check the generated payload
            payload = kwargs["json"]
            assert payload["payload"]["text"] == "My order is damaged."
            assert "session" in payload["metadata"]
            assert payload["bot_id"] == "test-bot"
            
            # Check the normalized conversation extracted from the response
            agent_msg = result.transcript[1]
            assert agent_msg.role == "agent"
            assert agent_msg.content == "Please upload a photo."
            assert agent_msg.tool_calls is not None
            assert agent_msg.tool_calls[0].tool_name == "check_order"
            assert agent_msg.tool_calls[0].tool_input == {"id": "A1029"}
            
    # Cleanup env
    del os.environ["CLIENT_API_KEY"]
