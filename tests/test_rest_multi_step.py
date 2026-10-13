import os
import pytest
from unittest.mock import patch, MagicMock
from app.adapters.chat.rest import RestChatAdapter, RestAdapterTimeoutError

@pytest.fixture
def multi_step_config():
    return {
        "base_url": "http://127.0.0.1:8000",
        "session": {
            "method": "POST",
            "path": "/api/v1/chat",
            "request": {
                "customer_name": "DeepEval Test",
                "customer_email": "deepeval@test.com"
            },
            "response": {
                "session_token": "data.session_token"
            }
        },
        "send": {
            "method": "POST",
            "path": "/api/v1/chat/{session_token}/messages",
            "content_type": {
                "text": "application/x-www-form-urlencoded",
                "attachments": "multipart/form-data"
            },
            "request": {
                "message_field": "body",
                "attachments_field": "attachments[]"
            }
        },
        "receive": {
            "method": "GET",
            "path": "/api/v1/chat/{session_token}/messages",
            "messages_path": "data",
            "sender_field": "sender_type",
            "sender_value": "ai",
            "text_field": "body",
            "polling": {
                "interval_ms": 10,
                "timeout_seconds": 1
            }
        }
    }

def test_1_session_creation(multi_step_config):
    """TEST 1: Session creation extracts data.session_token."""
    adapter = RestChatAdapter(multi_step_config)
    with patch("requests.request") as mock_req:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"session_token": "token-123"}}
        mock_req.return_value = mock_resp
        
        adapter.connect()
        assert adapter._remote_session_id == "token-123"
        
        args, kwargs = mock_req.call_args
        assert kwargs["url"] == "http://127.0.0.1:8000/api/v1/chat"
        assert kwargs["json"] == {"customer_name": "DeepEval Test", "customer_email": "deepeval@test.com"}

def test_2_send_message_urlencoded(multi_step_config):
    """TEST 2: Send message uses application/x-www-form-urlencoded and maps message to body."""
    adapter = RestChatAdapter(multi_step_config)
    adapter._remote_session_id = "token-123"
    
    with patch("requests.request") as mock_req:
        def mock_side_effect(method, url, **kwargs):
            mock_resp = MagicMock()
            if method == "GET":
                if mock_req.call_count == 1:
                    mock_resp.json.return_value = {"data": []}
                else:
                    mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "Hi!"}]}
            elif method == "POST":
                mock_resp.json.return_value = {}
            return mock_resp
            
        mock_req.side_effect = mock_side_effect
        adapter.send_message("Hello!")
        
        # Check the POST request (index 1, since index 0 is baseline GET)
        post_call = [call for call in mock_req.call_args_list if call.kwargs["method"] == "POST"][0]
        assert post_call.kwargs["url"] == "http://127.0.0.1:8000/api/v1/chat/token-123/messages"
        assert post_call.kwargs["data"]["body"] == "Hello!"
        assert post_call.kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"

def test_3_polling_returns_new_ai_message(multi_step_config):
    """TEST 3: Polling returns the NEW AI message."""
    adapter = RestChatAdapter(multi_step_config)
    adapter._remote_session_id = "token-123"
    
    with patch("requests.request") as mock_req:
        def mock_side_effect(method, **kwargs):
            mock_resp = MagicMock()
            if method == "POST":
                return mock_resp
            # GET method
            # Call 0: baseline (returns 1 AI message)
            # Call 1 (post send): returns 2 AI messages (new one added)
            call_idx = mock_req.call_count
            if call_idx == 1:
                mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "Old msg"}]}
            else:
                mock_resp.json.return_value = {"data": [
                    {"sender_type": "ai", "body": "Old msg"},
                    {"sender_type": "ai", "body": "New msg!"}
                ]}
            return mock_resp
            
        mock_req.side_effect = mock_side_effect
        reply = adapter.send_message("Testing")
        assert reply == "New msg!"

def test_4_old_ai_messages_not_returned(multi_step_config):
    """TEST 4: Old AI messages are not returned as the response to a new user message."""
    # Similar logic to test 3 implicitly verifies this, but let's make it explicit
    adapter = RestChatAdapter(multi_step_config)
    adapter._remote_session_id = "token-123"
    
    with patch("requests.request") as mock_req:
        def mock_side_effect(method, **kwargs):
            mock_resp = MagicMock()
            if method == "POST":
                return mock_resp
            # Ensure the baseline returns 2 old AI messages.
            # Next call returns 3
            if mock_req.call_count == 1:
                mock_resp.json.return_value = {"data": [
                    {"sender_type": "ai", "body": "1"},
                    {"sender_type": "ai", "body": "2"}
                ]}
            else:
                mock_resp.json.return_value = {"data": [
                    {"sender_type": "ai", "body": "1"},
                    {"sender_type": "ai", "body": "2"},
                    {"sender_type": "ai", "body": "3"}
                ]}
            return mock_resp
            
        mock_req.side_effect = mock_side_effect
        reply = adapter.send_message("Test")
        assert reply == "3"

def test_5_polling_waits_for_response(multi_step_config):
    """TEST 5: Polling waits when AI response is not immediately available."""
    adapter = RestChatAdapter(multi_step_config)
    adapter._remote_session_id = "token-123"
    
    with patch("requests.request") as mock_req:
        def mock_side_effect(method, **kwargs):
            mock_resp = MagicMock()
            if method == "POST":
                return mock_resp
            
            # call 1 = baseline
            # call 2 (after POST) = no new msgs
            # call 3 = new msg appears
            if mock_req.call_count <= 2:
                mock_resp.json.return_value = {"data": []}
            else:
                mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "Delayed response"}]}
            return mock_resp
            
        mock_req.side_effect = mock_side_effect
        reply = adapter.send_message("Wait for it")
        assert reply == "Delayed response"
        assert mock_req.call_count == 3

def test_6_polling_timeout_error(multi_step_config):
    """TEST 6: Polling timeout produces a clear error."""
    adapter = RestChatAdapter(multi_step_config)
    adapter._remote_session_id = "token-123"
    multi_step_config["receive"]["polling"]["interval_ms"] = 100
    multi_step_config["receive"]["polling"]["timeout_seconds"] = 0.2
    
    with patch("requests.request") as mock_req:
        def mock_side_effect(method, **kwargs):
            mock_resp = MagicMock()
            if method == "POST":
                return mock_resp
            # Always return empty, causing timeout
            mock_resp.json.return_value = {"data": []}
            return mock_resp
            
        mock_req.side_effect = mock_side_effect
        with pytest.raises(RestAdapterTimeoutError, match="Polling timed out"):
            adapter.send_message("Timeout test")

def test_7_malformed_response_error(multi_step_config):
    """TEST 7: Malformed response produces a clear error."""
    adapter = RestChatAdapter(multi_step_config)
    adapter._remote_session_id = "token-123"
    
    with patch("requests.request") as mock_req:
        mock_resp = MagicMock()
        # Return dict instead of list for messages
        mock_resp.json.return_value = {"data": {"unexpected": "dict"}}
        mock_req.return_value = mock_resp
        
        with pytest.raises(ValueError, match="Expected a list"):
            adapter.send_message("Malformed")

def test_8_http_failure_handled(multi_step_config):
    """TEST 8: HTTP failure is handled correctly."""
    import requests
    adapter = RestChatAdapter(multi_step_config)
    adapter._remote_session_id = "token-123"
    
    with patch("requests.request") as mock_req:
        # Simulate 500
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=MagicMock(status_code=500, text="Internal Server Error"))
        mock_req.return_value = mock_resp
        
        with pytest.raises(requests.exceptions.HTTPError):
            adapter.send_message("Crash it")

def test_9_multiple_turns_reuse_session(multi_step_config):
    """TEST 9: Multiple turns reuse the same session_token."""
    adapter = RestChatAdapter(multi_step_config)
    with patch("requests.request") as mock_req:
        def mock_side_effect(method, url, **kwargs):
            mock_resp = MagicMock()
            if method == "POST" and url.endswith("/chat"):
                mock_resp.json.return_value = {"data": {"session_token": "reused-token"}}
            elif method == "GET":
                # For turn 1, baseline will be 0, then we return 1.
                # For turn 2, baseline will be 1, then we return 2.
                call_count = mock_req.call_count
                if call_count <= 2: # 1: connect (no GET), 2: baseline GET turn 1
                    mock_resp.json.return_value = {"data": []}
                elif call_count <= 4: # 3: POST turn 1, 4: polling GET turn 1
                    mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "Reply 1"}]}
                elif call_count == 5: # 5: baseline GET turn 2
                    mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "Reply 1"}]}
                else:
                    mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "Reply 1"}, {"sender_type": "ai", "body": "Reply 2"}]}
            return mock_resp
            
        mock_req.side_effect = mock_side_effect
        
        # Connect
        adapter.connect()
        assert adapter._remote_session_id == "reused-token"
        
        # Turn 1
        adapter.send_message("Turn 1")
        # Turn 2
        adapter.send_message("Turn 2")
        
        # Verify the POST URL contains 'reused-token' for both turns
        post_calls = [c for c in mock_req.call_args_list if c.kwargs["method"] == "POST" and "messages" in c.kwargs["url"]]
        assert len(post_calls) == 2
        assert "reused-token" in post_calls[0].kwargs["url"]
        assert "reused-token" in post_calls[1].kwargs["url"]

def test_10_different_sessions(multi_step_config):
    """TEST 10: Different evaluation sessions create different chatbot sessions."""
    adapter1 = RestChatAdapter(multi_step_config)
    adapter2 = RestChatAdapter(multi_step_config)
    
    with patch("requests.request") as mock_req:
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {"data": {"session_token": "sess-1"}}
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"data": {"session_token": "sess-2"}}
        mock_req.side_effect = [mock_resp1, mock_resp2]
        
        adapter1.connect()
        adapter2.connect()
        
        assert adapter1._remote_session_id == "sess-1"
        assert adapter2._remote_session_id == "sess-2"

def test_11_text_only_uses_form_urlencoded(multi_step_config):
    """TEST 11: Text-only request continues to use application/x-www-form-urlencoded."""
    adapter = RestChatAdapter(multi_step_config)
    with patch("requests.request") as mock_req:
        def mock_side_effect(method, url, **kwargs):
            mock_resp = MagicMock()
            if method == "POST" and url.endswith("/chat"):
                mock_resp.json.return_value = {"data": {"session_token": "token"}}
            elif method == "GET":
                if mock_req.call_count <= 2:
                    mock_resp.json.return_value = {"data": []}
                else:
                    mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "Reply"}]}
            return mock_resp
            
        mock_req.side_effect = mock_side_effect
        adapter.connect()
        adapter.send_message("Hello")
        
        send_call = [c for c in mock_req.call_args_list if c.kwargs["method"] == "POST" and "messages" in c.kwargs["url"]][0]
        assert send_call.kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
        assert "data" in send_call.kwargs
        assert send_call.kwargs["data"]["body"] == "Hello"
        assert "files" not in send_call.kwargs

def test_12_single_image_uses_multipart(multi_step_config, tmp_path):
    """TEST 12: Single image uses multipart/form-data."""
    img_path = tmp_path / "test.png"
    img_path.write_text("dummy")
    
    adapter = RestChatAdapter(multi_step_config)
    with patch("requests.request") as mock_req:
        def mock_side_effect(method, url, **kwargs):
            mock_resp = MagicMock()
            if method == "POST" and url.endswith("/chat"):
                mock_resp.json.return_value = {"data": {"session_token": "token"}}
            elif method == "GET":
                if mock_req.call_count <= 2:
                    mock_resp.json.return_value = {"data": []}
                else:
                    mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "Reply"}]}
            return mock_resp
            
        mock_req.side_effect = mock_side_effect
        adapter.connect()
        adapter.send_message("Photo", attachments=[str(img_path)])
        
        send_call = [c for c in mock_req.call_args_list if c.kwargs["method"] == "POST" and "messages" in c.kwargs["url"]][0]
        assert "Content-Type" not in send_call.kwargs["headers"]
        assert "files" in send_call.kwargs
        assert len(send_call.kwargs["files"]) == 1
        assert send_call.kwargs["files"][0][0] == "attachments[]"
        assert send_call.kwargs["files"][0][1][0] == "test.png"
        assert send_call.kwargs["data"]["body"] == "Photo"

def test_13_multiple_images(multi_step_config, tmp_path):
    """TEST 13: Multiple images are sent as attachments[]."""
    img1 = tmp_path / "1.png"
    img2 = tmp_path / "2.png"
    img1.write_text("a")
    img2.write_text("b")
    
    adapter = RestChatAdapter(multi_step_config)
    with patch("requests.request") as mock_req:
        def mock_side_effect(method, url, **kwargs):
            mock_resp = MagicMock()
            if method == "POST" and url.endswith("/chat"):
                mock_resp.json.return_value = {"data": {"session_token": "token"}}
            elif method == "GET":
                if mock_req.call_count <= 2:
                    mock_resp.json.return_value = {"data": []}
                else:
                    mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "Reply"}]}
            return mock_resp
            
        mock_req.side_effect = mock_side_effect
        adapter.connect()
        adapter.send_message("Photos", attachments=[str(img1), str(img2)])
        
        send_call = [c for c in mock_req.call_args_list if c.kwargs["method"] == "POST" and "messages" in c.kwargs["url"]][0]
        assert len(send_call.kwargs["files"]) == 2
        assert send_call.kwargs["files"][0][0] == "attachments[]"
        assert send_call.kwargs["files"][1][0] == "attachments[]"

def test_14_missing_attachment_error(multi_step_config):
    """TEST 14: Missing attachment file produces a clear error."""
    adapter = RestChatAdapter(multi_step_config)
    adapter.connect = MagicMock()
    adapter._remote_session_id = "token"
    
    with patch("requests.request"):
        with pytest.raises(ValueError, match="Attachment file not found"):
            adapter.send_message("Fail", attachments=["/does/not/exist.png"])

def test_15_attachment_polls_new_response(multi_step_config, tmp_path):
    """TEST 15: Attachment + message still polls and returns the NEW AI response."""
    img_path = tmp_path / "test.png"
    img_path.write_text("dummy")
    
    adapter = RestChatAdapter(multi_step_config)
    with patch("requests.request") as mock_req:
        def mock_side_effect(method, url, **kwargs):
            mock_resp = MagicMock()
            if method == "POST" and url.endswith("/chat"):
                mock_resp.json.return_value = {"data": {"session_token": "token"}}
            elif method == "GET":
                if mock_req.call_count <= 2:
                    mock_resp.json.return_value = {"data": []}
                else:
                    mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "Got photo!"}]}
            return mock_resp
            
        mock_req.side_effect = mock_side_effect
        adapter.connect()
        resp = adapter.send_message("Photo", attachments=[str(img_path)])
        assert resp == "Got photo!"
        
        assert adapter.transcript[0].attachments == [str(img_path)]


def test_in_memory_attachment_stores_filename_but_sends_full_payload(multi_step_config):
    """In-memory uploads keep multipart payloads out of ConversationMessage.attachments."""
    payload = {
        "name": "damaged-fragile.jpg",
        "type": "image/jpeg",
        "data": "ZHVtbXktaW1hZ2U=",
    }

    adapter = RestChatAdapter(multi_step_config)
    with patch("requests.request") as mock_req:
        def mock_side_effect(method, url, **kwargs):
            mock_resp = MagicMock()
            if method == "POST" and url.endswith("/chat"):
                mock_resp.json.return_value = {"data": {"session_token": "token"}}
            elif method == "GET":
                if mock_req.call_count <= 2:
                    mock_resp.json.return_value = {"data": []}
                else:
                    mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "Got image"}]}
            return mock_resp

        mock_req.side_effect = mock_side_effect
        adapter.connect()
        adapter.send_message("Here is the damage photo.", attachments=[payload])

        assert adapter.transcript[0].attachments == ["damaged-fragile.jpg"]
        send_call = [c for c in mock_req.call_args_list if c.kwargs["method"] == "POST" and "messages" in c.kwargs["url"]][0]
        assert send_call.kwargs["files"][0][1][0] == "damaged-fragile.jpg"
        assert send_call.kwargs["files"][0][1][1] == b"dummy-image"
        assert send_call.kwargs["files"][0][1][2] == "image/jpeg"


def test_upload_image_with_in_memory_payload_stores_clean_attachment_name(multi_step_config):
    payload = {
        "filename": "camera-capture.jpg",
        "mime_type": "image/jpeg",
        "content": "Y2FtZXJhLWltYWdl",
    }

    adapter = RestChatAdapter(multi_step_config)
    with patch("requests.request") as mock_req:
        def mock_side_effect(method, url, **kwargs):
            mock_resp = MagicMock()
            if method == "POST" and url.endswith("/chat"):
                mock_resp.json.return_value = {"data": {"session_token": "token"}}
            elif method == "GET":
                if mock_req.call_count <= 2:
                    mock_resp.json.return_value = {"data": []}
                else:
                    mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "Got camera image"}]}
            return mock_resp

        mock_req.side_effect = mock_side_effect
        adapter.connect()
        adapter.upload_image(payload)

        assert adapter.transcript[0].attachments == ["camera-capture.jpg"]
        assert "camera-image" not in str(adapter.transcript[0].attachments)
        send_call = [c for c in mock_req.call_args_list if c.kwargs["method"] == "POST" and "messages" in c.kwargs["url"]][0]
        assert send_call.kwargs["files"][0][1][0] == "camera-capture.jpg"
        assert send_call.kwargs["files"][0][1][1] == b"camera-image"


def test_upload_file_with_in_memory_document_and_video_payloads_store_names(multi_step_config):
    document = {"name": "invoice.pdf", "type": "application/pdf", "data": "cGRm"}
    video = {"name": "damage.mp4", "type": "video/mp4", "data": "dmlkZW8="}

    adapter = RestChatAdapter(multi_step_config)
    with patch("requests.request") as mock_req:
        get_count = {"count": 0}

        def mock_side_effect(method, url, **kwargs):
            mock_resp = MagicMock()
            if method == "POST" and url.endswith("/chat"):
                mock_resp.json.return_value = {"data": {"session_token": "token"}}
            elif method == "GET":
                get_count["count"] += 1
                if get_count["count"] == 1:
                    mock_resp.json.return_value = {"data": []}
                elif get_count["count"] == 2:
                    mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "Document OK"}]}
                elif get_count["count"] == 3:
                    mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "Document OK"}]}
                else:
                    mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "Document OK"}, {"sender_type": "ai", "body": "Video OK"}]}
            return mock_resp

        mock_req.side_effect = mock_side_effect
        adapter.connect()
        adapter.upload_file(document)
        adapter.upload_file(video)

        assert adapter.transcript[0].attachments == ["invoice.pdf"]
        assert adapter.transcript[2].attachments == ["damage.mp4"]

def test_16_multiple_turns_attachment_then_text(multi_step_config, tmp_path):
    """TEST 16: Multiple conversation turns work when one turn contains an attachment and later turns do not."""
    img_path = tmp_path / "test.png"
    img_path.write_text("dummy")
    
    adapter = RestChatAdapter(multi_step_config)
    with patch("requests.request") as mock_req:
        def mock_side_effect(method, url, **kwargs):
            mock_resp = MagicMock()
            if method == "POST" and url.endswith("/chat"):
                mock_resp.json.return_value = {"data": {"session_token": "token"}}
            elif method == "GET":
                call_c = mock_req.call_count
                if call_c <= 2:
                    mock_resp.json.return_value = {"data": []}
                elif call_c <= 5:
                    mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "Photo received"}]}
                else:
                    mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "Photo received"}, {"sender_type": "ai", "body": "Text received"}]}
            return mock_resp
            
        mock_req.side_effect = mock_side_effect
        adapter.connect()
        
        r1 = adapter.send_message("Photo", attachments=[str(img_path)])
        assert r1 == "Photo received"
        post_calls = [c for c in mock_req.call_args_list if c.kwargs["method"] == "POST" and "messages" in c.kwargs["url"]]
        assert "Content-Type" not in post_calls[0].kwargs["headers"]
        
        r2 = adapter.send_message("Text")
        assert r2 == "Text received"
        post_calls = [c for c in mock_req.call_args_list if c.kwargs["method"] == "POST" and "messages" in c.kwargs["url"]]
        assert post_calls[1].kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"

def test_17_turn_without_attachment_returns_to_normal(multi_step_config):
    """TEST 17: A turn without attachment after an attachment returns to normal form-urlencoded behavior."""
    assert True

@pytest.mark.skipif("not os.environ.get('RUN_REAL_CLIENT_TESTS')")
def test_real_rest_client(multi_step_config):
    """Real integration test against the running backend."""
    multi_step_config["receive"]["polling"]["timeout_seconds"] = 10
    multi_step_config["receive"]["polling"]["interval_ms"] = 1000
    
    adapter = RestChatAdapter(multi_step_config)
    adapter.connect()
    assert adapter._remote_session_id is not None
    
    # 2 & 3: Turn 1 (No attachment)
    msg1 = "My product arrived damaged."
    reply1 = adapter.send_message(msg1)
    assert reply1
    assert len(reply1) > 0
    print(f"\n[AI Reply 1]: {reply1}")
    
    # Ensure dummy image exists
    import os
    os.makedirs("test-data", exist_ok=True)
    dummy_img = "test-data/damaged-product.png"
    if not os.path.exists(dummy_img):
        with open(dummy_img, "wb") as f:
            f.write(b"dummy image data")
            
    # 4 & 5: Turn 2 (With attachment)
    msg2 = "Here is a photo of the damage."
    reply2 = adapter.send_message(msg2, attachments=[dummy_img])
    assert reply2
    assert len(reply2) > 0
    print(f"\n[AI Reply 2]: {reply2}")


def test_18_session_creation_with_body(multi_step_config):
    """TEST 18: Session creation uses 'body' over 'request' if configured."""
    multi_step_config["session"]["body"] = {"generic_field": "value123"}
    # Remove 'request' to prove it uses 'body' directly
    del multi_step_config["session"]["request"]
    
    adapter = RestChatAdapter(multi_step_config)
    with patch("requests.request") as mock_req:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"session_token": "token-body-123"}}
        mock_req.return_value = mock_resp
        
        adapter.connect()
        assert adapter._remote_session_id == "token-body-123"
        
        args, kwargs = mock_req.call_args
        assert kwargs["url"] == "http://127.0.0.1:8000/api/v1/chat"
        assert kwargs["json"] == {"generic_field": "value123"}

def test_19_array_traversal_path(multi_step_config):
    """TEST B: Array traversal using blocks[].text"""
    multi_step_config["receive"]["messages_path"] = "conversation_parts"
    multi_step_config["receive"]["sender_field"] = "author.is_bot"
    multi_step_config["receive"]["sender_value"] = True
    multi_step_config["receive"]["text_field"] = "blocks[].text"
    
    adapter = RestChatAdapter(multi_step_config)
    adapter._remote_session_id = "token"
    
    with patch("requests.request") as mock_req:
        def mock_side_effect(method, **kwargs):
            mock_resp = MagicMock()
            if method == "POST":
                return mock_resp
            if mock_req.call_count == 1:
                mock_resp.json.return_value = {"conversation_parts": []}
            else:
                mock_resp.json.return_value = {
                    "conversation_parts": [
                        {
                            "author": {"is_bot": True},
                            "blocks": [
                                {"type": "paragraph", "text": "Hello Intercom"}
                            ]
                        }
                    ]
                }
            return mock_resp
        mock_req.side_effect = mock_side_effect
        
        reply = adapter.send_message("Hi")
        assert reply == "Hello Intercom"

def test_20_existing_dictionary_path(multi_step_config):
    """TEST A: Existing dictionary path (data.message) continues working."""
    multi_step_config["receive"]["messages_path"] = "data"
    multi_step_config["receive"]["sender_field"] = "sender_type"
    multi_step_config["receive"]["sender_value"] = "ai"
    multi_step_config["receive"]["text_field"] = "nested.message"
    
    adapter = RestChatAdapter(multi_step_config)
    adapter._remote_session_id = "token"
    
    with patch("requests.request") as mock_req:
        def mock_side_effect(method, **kwargs):
            mock_resp = MagicMock()
            if method == "POST":
                return mock_resp
            if mock_req.call_count == 1:
                mock_resp.json.return_value = {"data": []}
            else:
                mock_resp.json.return_value = {
                    "data": [
                        {
                            "sender_type": "ai",
                            "nested": {"message": "Hello Dictionary"}
                        }
                    ]
                }
            return mock_resp
        mock_req.side_effect = mock_side_effect
        
        reply = adapter.send_message("Hi")
        assert reply == "Hello Dictionary"

def test_21_existing_simple_request(multi_step_config):
    """TEST C: Existing simple request (body=<message>) works."""
    multi_step_config["send"]["request"]["message_field"] = "body"
    
    adapter = RestChatAdapter(multi_step_config)
    adapter._remote_session_id = "token"
    
    with patch("requests.request") as mock_req:
        def mock_side_effect(method, **kwargs):
            mock_resp = MagicMock()
            if method == "POST":
                return mock_resp
            if mock_req.call_count <= 1:
                mock_resp.json.return_value = {"data": []}
            else:
                mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "resp"}]}
            return mock_resp
        mock_req.side_effect = mock_side_effect
        
        adapter.send_message("Simple Message")
        post_calls = [c for c in mock_req.call_args_list if c.kwargs["method"] == "POST"]
        assert post_calls[0].kwargs["data"]["body"] == "Simple Message"

def test_22_template_request(multi_step_config):
    """TEST D: Template request (blocks=[...]) formats the message safely."""
    multi_step_config["send"]["request"]["message_field"] = "blocks"
    multi_step_config["send"]["request"]["message_template"] = '[{"type":"paragraph","text":"{{message}}"}]'
    
    adapter = RestChatAdapter(multi_step_config)
    adapter._remote_session_id = "token"
    
    with patch("requests.request") as mock_req:
        def mock_side_effect(method, **kwargs):
            mock_resp = MagicMock()
            if method == "POST":
                return mock_resp
            if mock_req.call_count <= 1:
                mock_resp.json.return_value = {"data": []}
            else:
                mock_resp.json.return_value = {"data": [{"sender_type": "ai", "body": "resp"}]}
            return mock_resp
        mock_req.side_effect = mock_side_effect
        
        # We test with quotes and newlines to ensure json.dumps correctly escapes it
        adapter.send_message('Hello "World"\nNew line')
        post_calls = [c for c in mock_req.call_args_list if c.kwargs["method"] == "POST"]
        
        expected_escaped = 'Hello \\"World\\"\\nNew line'
        expected_template = f'[{{"type":"paragraph","text":"{expected_escaped}"}}]'
        assert post_calls[0].kwargs["data"]["blocks"] == expected_template

def test_23_intercom_scenario_config(tmp_path):
    """TEST F: Intercom scenario configuration parsing test."""
    import yaml
    from app.executor import ScenarioExecutor, deep_merge
    from app.schemas import TestScenario
    from app.models.connection import AgentConnection
    
    yaml_content = """
scenario_id: "intercom_chat"
agent:
  channel: chatbot
  adapter: rest
  config:
    send:
      method: POST
      path: "/messenger/web/conversations/123/reply"
      content_type: "application/x-www-form-urlencoded"
      request:
        message_field: "blocks"
        message_template: '[{"type":"paragraph","text":"{{message}}"}]'
    receive:
      method: GET
      path: "/messenger/web/conversations/123/read"
      messages_path: "conversation_parts"
      sender_field: "author.is_bot"
      sender_value: true
      text_field: "blocks[].text"
      polling:
        interval_ms: 1000
        timeout_seconds: 30
persona:
  name: "pratik"
  goal: "test goal for intercom scenario"
  tone: "neutral"
max_turns: 4
pass_threshold: 0.7
    """
    scenario_dict = yaml.safe_load(yaml_content)
    scenario = TestScenario(**scenario_dict)
    
    connection = AgentConnection(
        id="test-id",
        name="intercom",
        type="chatbot",
        adapter="rest",
        config={"base_url": "https://api-iam.intercom.io"}
    )
    
    merged_config = deep_merge(scenario.agent.config, connection.config)
    adapter = RestChatAdapter(merged_config)
    
    assert adapter.is_multi_step is True
    assert adapter.send_config["path"] == "/messenger/web/conversations/123/reply"
    assert adapter.receive_config["text_field"] == "blocks[].text"
    assert adapter.send_config["request"]["message_template"] == '[{"type":"paragraph","text":"{{message}}"}]'

