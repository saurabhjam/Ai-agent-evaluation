import json
from unittest.mock import patch
from app.adapters.chat.rest import RestChatAdapter
from app.models.conversation import ConversationMessage

config = {
    "endpoint": "http://example.com/api",
    "request_mapping": {
        "history_field": "contents",
        "history_item_template": {
            "role": "{{role}}",
            "parts": [{"text": "{{content}}"}]
        },
        "history_role_map": {
            "user": "user",
            "agent": "model",
            "simulated_user": "user"
        }
    },
    "response_mapping": {
        "reply_field": "candidates[0].content.parts[0].text"
    }
}

adapter = RestChatAdapter(config)
adapter.transcript = [
    ConversationMessage(role="simulated_user", content="Hello", turn_index=0),
    ConversationMessage(role="agent", content="Hello! How can I help?", turn_index=1),
]

with patch("requests.request") as mock_req:
    mock_req.return_value.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "I'm sorry your product arrived damaged."}]}}]
    }
    mock_req.return_value.status_code = 200
    
    reply = adapter.send_message("My product is damaged.")
    
    kwargs = mock_req.call_args.kwargs
    print(json.dumps(kwargs["json"], indent=2))
    print("\nReply received:", reply)
