from app.fallback_interactions import detect_fallback_interactions


def _types(text):
    return [component["type"] for component in detect_fallback_interactions(text)]


def test_detects_image_upload_requests_from_plain_text():
    components = detect_fallback_interactions("Please upload a photo of the damage.")

    assert components == [
        {
            "type": "image_upload",
            "label": "Upload damage photo",
            "text": "Please upload a photo of the damage.",
            "generated_by": "fallback",
        }
    ]


def test_detects_document_video_otp_date_time_and_location_requests():
    assert _types("Attach the invoice document.") == ["document_upload"]
    assert _types("Please upload a short video.") == ["video_upload"]
    assert _types("Enter the OTP sent to your phone.") == ["otp"]
    assert _types("Choose appointment date.") == ["date"]
    assert _types("Select appointment time.") == ["time"]
    assert _types("Share your location.") == ["location"]


def test_image_receipt_photo_takes_priority_over_document_receipt():
    components = detect_fallback_interactions("Upload receipt photo.")

    assert [component["type"] for component in components] == ["image_upload"]
    assert components[0]["label"] == "Upload receipt photo"


def test_plain_text_without_interaction_returns_empty_list():
    assert detect_fallback_interactions("Thanks, I can help with that.") == []


def test_detector_ignores_markdown_and_punctuation():
    assert _types("**Please**: attach-image!") == ["image_upload"]


def test_keyword_cooccurrence_detects_words_in_any_order():
    assert _types("Browse your device and add the damage image here.") == ["image_upload"]
    assert _types("The invoice is required; please include a PDF.") == ["document_upload"]
    assert _types("A short clip helps us verify this, choose a video.") == ["video_upload"]
    assert _types("For security, type the one time password.") == ["otp"]
    assert _types("What appointment date should we use?") == ["date"]
    assert _types("What appointment time should we use?") == ["time"]
    assert _types("Use the map to send location.") == ["location"]
