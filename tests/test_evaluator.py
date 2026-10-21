import pytest
from unittest.mock import patch, MagicMock
from app.evaluator import evaluate_transcript, GeminiJudge
from app.schemas import Persona
from app.models.conversation import ConversationMessage

def test_evaluate_transcript_with_rag_context():
    """
    Ensures that evaluate_transcript executes 9 metrics when rag_context is provided.
    """
    persona = Persona(name="Bob", goal="I want a refund for my order", tone="angry", edge_case="")
    transcript = [
        ConversationMessage(turn_index=0, role="simulated_user", content="I want a refund."),
        ConversationMessage(turn_index=0, role="agent", content="Okay, here is your refund.")
    ]

    with patch("deepeval.metrics.GEval.measure"), \
         patch("deepeval.metrics.ConversationalGEval.measure"), \
         patch("deepeval.metrics.HallucinationMetric.measure"), \
         patch("deepeval.metrics.AnswerRelevancyMetric.measure"), \
         patch("deepeval.metrics.FaithfulnessMetric.measure"), \
         patch("deepeval.metrics.ContextualPrecisionMetric.measure"), \
         patch("deepeval.metrics.ContextualRecallMetric.measure"), \
         patch("deepeval.metrics.ContextualRelevancyMetric.measure"), \
         patch("deepeval.metrics.GEval.score", new_callable=lambda: 1.0), \
         patch("deepeval.metrics.ConversationalGEval.score", new_callable=lambda: 1.0), \
         patch("deepeval.metrics.HallucinationMetric.score", new_callable=lambda: 1.0), \
         patch("deepeval.metrics.AnswerRelevancyMetric.score", new_callable=lambda: 1.0), \
         patch("deepeval.metrics.FaithfulnessMetric.score", new_callable=lambda: 1.0), \
         patch("deepeval.metrics.ContextualPrecisionMetric.score", new_callable=lambda: 1.0), \
         patch("deepeval.metrics.ContextualRecallMetric.score", new_callable=lambda: 1.0), \
         patch("deepeval.metrics.ContextualRelevancyMetric.score", new_callable=lambda: 1.0):
         
        try:
            results = evaluate_transcript(persona, transcript, rag_context=["Some context"])
            assert len(results) == 16
            metric_names = [m.name for m in results]
            assert "Goal Completion" in metric_names
            assert "Persona and Tone Adherence" in metric_names
            assert "Hallucination" in metric_names
            assert "Conversational Quality" in metric_names
            assert "Context Retention" in metric_names
            assert "Multi-turn Consistency" in metric_names
            assert "Intent Understanding" in metric_names
            assert "Answer Relevancy" in metric_names
            assert "Faithfulness" in metric_names
            assert "Context Precision" in metric_names
            assert "Context Recall" in metric_names
            assert "Context Relevancy" in metric_names
            assert all(result.description for result in results)
            assert all(result.threshold is not None for result in results)
            rag_results = [result for result in results if result.category == "rag"]
            assert rag_results
            assert {result.evidence_source for result in rag_results} == {"reference_context"}
        except Exception as e:
            pytest.fail(f"evaluate_transcript raised an unexpected exception: {e}")

def test_evaluate_transcript_without_rag_context():
    """
    Ensures that evaluate_transcript executes conversation metrics when rag_context is absent.
    """
    persona = Persona(name="Bob", goal="I want a refund for my order", tone="angry", edge_case="")
    transcript = [
        ConversationMessage(turn_index=0, role="simulated_user", content="I want a refund."),
        ConversationMessage(turn_index=0, role="agent", content="Okay, here is your refund.")
    ]

    with patch("deepeval.metrics.GEval.measure"), \
         patch("deepeval.metrics.ConversationalGEval.measure"), \
         patch("deepeval.metrics.GEval.score", new_callable=lambda: 1.0), \
         patch("deepeval.metrics.ConversationalGEval.score", new_callable=lambda: 1.0):
         
        try:
            results = evaluate_transcript(persona, transcript, rag_context=None)
            assert len(results) == 10
            metric_names = [m.name for m in results]
            assert "Goal Completion" in metric_names
            assert "Persona and Tone Adherence" in metric_names
            assert "Conversational Quality" in metric_names
            assert "Context Retention" in metric_names
            assert "Multi-turn Consistency" in metric_names
            assert "Intent Understanding" in metric_names
            assert "Completeness" in metric_names
            assert "Response Quality" in metric_names
            assert "Answer Relevancy" in metric_names
            assert "Hallucination" in metric_names
            assert "Faithfulness" not in metric_names
            assert all(result.description for result in results)
        except Exception as e:
            pytest.fail(f"evaluate_transcript raised an unexpected exception: {e}")


def test_full_conversation_failures_reduce_scores_even_after_recovery():
    persona = Persona(
        name="Rahul Sharma",
        goal="Book a dental appointment.",
        tone="Polite",
    )
    transcript = [
        {"role": "simulated_user", "content": "I need to book a dental consultation for October 8, 2026 at 4:00 PM.", "turn_index": 0, "id": "msg_0"},
        {"role": "agent", "content": "Which date and time would you prefer?", "turn_index": 1, "id": "msg_1"},
        {"role": "simulated_user", "content": "October 8, 2026 at 4:00 PM.", "turn_index": 2, "id": "msg_2"},
        {"role": "agent", "content": "Let's start over. What date and time would you prefer?", "turn_index": 3, "id": "msg_3"},
        {"role": "simulated_user", "content": "October 8, 2026 at 4:00 PM.", "turn_index": 4, "id": "msg_4"},
        {"role": "agent", "content": "Your appointment is confirmed.", "turn_index": 5, "id": "msg_5"},
    ]

    with patch("deepeval.metrics.GEval.score", new_callable=lambda: 1.0), \
         patch("deepeval.metrics.ConversationalGEval.score", new_callable=lambda: 1.0), \
         patch("deepeval.metrics.GEval.success", new_callable=lambda: True), \
         patch("deepeval.metrics.ConversationalGEval.success", new_callable=lambda: True), \
         patch("deepeval.metrics.GEval.measure", lambda self, test_case: None), \
         patch("deepeval.metrics.ConversationalGEval.measure", lambda self, test_case: None):
        results = evaluate_transcript(persona, transcript, rag_context=None)

    by_name = {result.name: result for result in results}
    assert by_name["Conversational Quality"].score <= 0.65
    assert by_name["Context Retention"].score <= 0.55
    assert by_name["Multi-turn Consistency"].score <= 0.55
    for name in ("Conversational Quality", "Context Retention", "Multi-turn Consistency"):
        assert by_name[name].passed is False
        assert "Full-conversation penalty" in by_name[name].reason

    for name in (
        "Goal Completion",
        "Persona and Tone Adherence",
        "Intent Understanding",
        "Answer Relevancy",
        "Hallucination",
        "Completeness",
        "Response Quality",
    ):
        assert by_name[name].score == 1.0
        assert "Full-conversation penalty" not in by_name[name].reason


def test_evaluate_transcript_with_turn_scoped_rag_evidence():
    persona = Persona(name="Bob", goal="I want a refund for my order", tone="angry", edge_case="")
    transcript = [
        ConversationMessage(turn_index=0, role="simulated_user", content="What is the refund policy?"),
        ConversationMessage(turn_index=1, role="agent", content="Refunds are allowed within 30 days."),
    ]
    rag_evidence_by_turn = [
        {
            "input": "What is the refund policy?",
            "actual_output": "Refunds are allowed within 30 days.",
            "contexts": ["Customers can return products within 30 days."],
        }
    ]

    with patch("deepeval.metrics.GEval.measure"), \
         patch("deepeval.metrics.ConversationalGEval.measure"), \
         patch("deepeval.metrics.HallucinationMetric.measure"), \
         patch("deepeval.metrics.AnswerRelevancyMetric.measure"), \
         patch("deepeval.metrics.FaithfulnessMetric.measure"), \
         patch("deepeval.metrics.ContextualPrecisionMetric.measure"), \
         patch("deepeval.metrics.ContextualRecallMetric.measure"), \
         patch("deepeval.metrics.ContextualRelevancyMetric.measure"), \
         patch("deepeval.metrics.GEval.score", new_callable=lambda: 1.0), \
         patch("deepeval.metrics.ConversationalGEval.score", new_callable=lambda: 1.0), \
         patch("deepeval.metrics.HallucinationMetric.score", new_callable=lambda: 0.0), \
         patch("deepeval.metrics.AnswerRelevancyMetric.score", new_callable=lambda: 1.0), \
         patch("deepeval.metrics.FaithfulnessMetric.score", new_callable=lambda: 1.0), \
         patch("deepeval.metrics.ContextualPrecisionMetric.score", new_callable=lambda: 1.0), \
         patch("deepeval.metrics.ContextualRecallMetric.score", new_callable=lambda: 1.0), \
         patch("deepeval.metrics.ContextualRelevancyMetric.score", new_callable=lambda: 1.0):
        results = evaluate_transcript(
            persona,
            transcript,
            rag_context=None,
            rag_evidence_by_turn=rag_evidence_by_turn,
        )

    metric_names = [m.name for m in results]
    assert len(results) == 16
    assert "Goal Completion" in metric_names
    assert "Conversational Quality" in metric_names
    assert "Hallucination" in metric_names
    assert "Answer Relevancy" in metric_names
    assert "Faithfulness" in metric_names
    assert "Context Precision" in metric_names
    assert "Context Recall" in metric_names
    assert "Context Relevancy" in metric_names
    rag_results = [result for result in results if result.category == "rag"]
    assert rag_results
    assert {result.evidence_source for result in rag_results} == {"agent_retrieval"}


def test_reference_context_is_not_used_as_expected_output(monkeypatch):
    from app import evaluator

    captured = []

    class FakeLLMTestCase:
        def __init__(self, **kwargs):
            captured.append(kwargs)
            self.input = kwargs.get("input", "")
            self.actual_output = kwargs.get("actual_output", "")

    class FakeConversationalTestCase:
        def __init__(self, turns):
            self.turns = turns

    class FakeMetric:
        name = "Goal Completion"
        score = 1.0
        reason = "ok"
        success = True

        def measure(self, test_case):
            return None

    monkeypatch.setattr(evaluator, "LLMTestCase", FakeLLMTestCase)
    monkeypatch.setattr(evaluator, "ConversationalTestCase", FakeConversationalTestCase)
    monkeypatch.setattr(evaluator, "_build_metrics", lambda persona, rag_context: [FakeMetric()])

    persona = Persona(name="Bob", goal="I want a refund for my order", tone="angry", edge_case="")
    transcript = [
        ConversationMessage(turn_index=0, role="simulated_user", content="I want a refund."),
        ConversationMessage(turn_index=1, role="agent", content="Refunds are allowed."),
    ]

    evaluate_transcript(persona, transcript, rag_context=["Reference policy text"])

    assert captured[0]["context"] == ["Reference policy text"]
    assert captured[0]["retrieval_context"] == ["Reference policy text"]
    assert captured[0]["expected_output"] is None

def test_hallucination_normalization():
    """
    Ensures that the Hallucination metric score is correctly normalized (1.0 - raw_score).
    """
    from app.evaluator import evaluate_transcript, get_judge
    from deepeval.metrics import HallucinationMetric
    
    persona = Persona(name="Bob", goal="I want a refund for my order", tone="angry", edge_case="")
    transcript = [
        ConversationMessage(turn_index=0, role="simulated_user", content="I want a refund."),
        ConversationMessage(turn_index=0, role="agent", content="Okay, here is your refund.")
    ]

    # Mock all metric measurements to return a fixed raw score
    with patch("deepeval.metrics.GEval.measure") as mock_geval, \
         patch("deepeval.metrics.ConversationalGEval.measure") as mock_conv_geval, \
         patch("deepeval.metrics.HallucinationMetric.measure") as mock_hallucination, \
         patch("deepeval.metrics.AnswerRelevancyMetric.measure") as mock_answer_relevancy, \
         patch("deepeval.metrics.FaithfulnessMetric.measure") as mock_faithfulness, \
         patch("deepeval.metrics.ContextualPrecisionMetric.measure"), \
         patch("deepeval.metrics.ContextualRecallMetric.measure"), \
         patch("deepeval.metrics.ContextualRelevancyMetric.measure"), \
         patch("deepeval.metrics.GEval.score", new_callable=lambda: 0.8), \
         patch("deepeval.metrics.ConversationalGEval.score", new_callable=lambda: 0.8), \
         patch("deepeval.metrics.HallucinationMetric.score", new_callable=lambda: 0.8), \
         patch("deepeval.metrics.AnswerRelevancyMetric.score", new_callable=lambda: 0.8), \
         patch("deepeval.metrics.FaithfulnessMetric.score", new_callable=lambda: 0.8), \
         patch("deepeval.metrics.ContextualPrecisionMetric.score", new_callable=lambda: 0.8), \
         patch("deepeval.metrics.ContextualRecallMetric.score", new_callable=lambda: 0.8), \
         patch("deepeval.metrics.ContextualRelevancyMetric.score", new_callable=lambda: 0.8):
         
         results = evaluate_transcript(persona, transcript, rag_context=["Dummy context"])
         
         hallucination_result = next((r for r in results if r.name == "Hallucination" and r.category == "rag"), None)
         goal_result = next((r for r in results if r.name == "Goal Completion"), None)
         
         assert hallucination_result is not None
         # 1.0 - 0.8 = 0.2 (due to floating point math, check via round)
         assert round(hallucination_result.score, 3) == 0.2
         assert round(goal_result.score, 3) == 0.8

def test_groq_succeeds_gemini_not_called():
    from app.evaluator import GroqJudge
    judge = GroqJudge()
    with patch.object(judge.client.chat.completions, 'create') as mock_groq, \
         patch.object(judge.fallback, 'generate') as mock_gemini:
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"success": true}'
        mock_groq.return_value = mock_response

        response = judge.generate("Test prompt")

        assert response == '{"success": true}'
        mock_groq.assert_called_once()
        mock_gemini.assert_not_called()

def test_groq_api_exception_calls_gemini():
    from app.evaluator import GroqJudge
    judge = GroqJudge()
    with patch.object(judge.client.chat.completions, 'create', side_effect=Exception("Generic API Error")) as mock_groq, \
         patch.object(judge.fallback, 'generate', return_value='{"fallback": true}') as mock_gemini:
        
        response = judge.generate("Test prompt")

        assert response == '{"fallback": true}'
        mock_groq.assert_called_once()
        mock_gemini.assert_called_once_with("Test prompt\nRespond in JSON format.")

def test_both_groq_and_gemini_fail():
    from app.evaluator import GroqJudge
    judge = GroqJudge()
    with patch.object(judge.client.chat.completions, 'create', side_effect=Exception("Groq Error")) as mock_groq, \
         patch.object(judge.fallback, 'generate', side_effect=Exception("Gemini Error")) as mock_gemini:
        
        with pytest.raises(Exception, match="Gemini Error"):
            judge.generate("Test prompt")
            
        mock_groq.assert_called_once()
        mock_gemini.assert_called_once_with("Test prompt\nRespond in JSON format.")

def test_metric_exception_handling():
    """
    Ensures that if a metric raises an exception during measure(),
    it creates a failed MetricResult and subsequent metrics still execute.
    """
    persona = Persona(name="Bob", goal="I want a refund for my order", tone="angry", edge_case="")
    transcript = [
        ConversationMessage(turn_index=0, role="simulated_user", content="I want a refund."),
        ConversationMessage(turn_index=0, role="agent", content="Okay, here is your refund.")
    ]

    with patch("deepeval.metrics.GEval.measure") as mock_geval, \
         patch("deepeval.metrics.ConversationalGEval.measure") as mock_conv_geval, \
         patch("deepeval.metrics.GEval.score", new_callable=lambda: 1.0), \
         patch("deepeval.metrics.ConversationalGEval.score", new_callable=lambda: 1.0):
         
         # Force Conversational Quality to fail
         mock_conv_geval.side_effect = Exception("Simulated Metric Failure")
         
         results = evaluate_transcript(persona, transcript, rag_context=None)
         
         assert len(results) == 10
         
         goal_completion = next((r for r in results if r.name == "Goal Completion"), None)
         persona_adherence = next((r for r in results if r.name == "Persona and Tone Adherence"), None)
         conv_quality = next((r for r in results if r.name == "Conversational Quality"), None)
         
         # Verify previous/subsequent metrics executed correctly
         assert goal_completion is not None
         assert goal_completion.score == 1.0
         assert persona_adherence is not None
         assert persona_adherence.score == 1.0
         
         # Verify the failed metric produced a MetricResult with score 0.0
         assert conv_quality is not None
         assert conv_quality.score == 0.0
         assert conv_quality.passed is False
         assert conv_quality.description
         assert conv_quality.threshold is not None
         assert "Simulated Metric Failure" in conv_quality.reason
