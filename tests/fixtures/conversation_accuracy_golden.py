"""Provider-neutral golden conversations for evaluation-accuracy regression tests."""


def _messages(*items):
    return [
        {"role": role, "content": content, "message_id": f"gold-{index}"}
        for index, (role, content) in enumerate(items)
    ]


GOLDEN_CONVERSATIONS = [
    {"id": "goal_completed", "goal": "Obtain an account balance", "messages": _messages(("user", "What is my balance?"), ("agent", "Your verified balance is 120.")), "expect": ["goal_complete"]},
    {"id": "goal_failed_later_success", "goal": "Cancel an order", "messages": _messages(("user", "Cancel order 42."), ("agent", "I cannot cancel it."), ("user", "What are your hours?"), ("agent", "We close at six.")), "expect": ["goal_failed", "later_success_irrelevant"]},
    {"id": "goal_completed_later_failure", "goal": "Reset a password", "messages": _messages(("user", "Reset my password."), ("agent", "The reset link was sent."), ("user", "What is my balance?"), ("agent", "I cannot access that.")), "expect": ["goal_complete", "later_failure_irrelevant"]},
    {"id": "multistep_partial", "goal": "Update address and phone", "messages": _messages(("user", "Update my address and phone."), ("agent", "Your address is updated; phone is pending.")), "expect": ["goal_partial"]},
    {"id": "valid_clarification", "goal": "Find an account", "messages": _messages(("user", "Open my account."), ("agent", "Which account do you mean?")), "expect": ["clarification_valid"], "must_not_penalize": ["context_retention"]},
    {"id": "repeated_clarification", "goal": "Find an account", "messages": _messages(("user", "Open my business account."), ("agent", "Which account?"), ("user", "My business account."), ("agent", "Which account should I open?")), "expect": ["repetition", "context_loss"]},
    {"id": "forgotten_context", "goal": "Ship an order", "messages": _messages(("user", "Ship order 42."), ("agent", "What is the order number?")), "expect": ["context_loss"]},
    {"id": "changed_requirement", "goal": "Select delivery", "messages": _messages(("user", "Deliver tomorrow."), ("user", "Actually, deliver Friday."), ("agent", "Friday is selected.")), "expect": ["requirement_change"], "must_not_penalize": ["consistency"]},
    {"id": "genuine_contradiction", "goal": "Check status", "messages": _messages(("user", "Status of order 42?"), ("agent", "Order 42 is open."), ("agent", "Order 42 is closed.")), "expect": ["contradiction"]},
    {"id": "different_timeframe", "goal": "Compare periods", "messages": _messages(("user", "Last month?"), ("agent", "Four cases."), ("user", "This month?"), ("agent", "No cases.")), "expect": ["no_contradiction"]},
    {"id": "intent_incorrect", "goal": "Report damaged item", "messages": _messages(("user", "My item arrived damaged."), ("agent", "Here are current promotions.")), "expect": ["intent_failed"]},
    {"id": "intent_correct_execution_failed", "goal": "Report damaged item", "messages": _messages(("user", "My item arrived damaged."), ("agent", "I understand, but the claims service is unavailable.")), "expect": ["intent_understood", "execution_failed"], "must_not_penalize": ["intent"]},
    {"id": "answer_relevant", "goal": "Get opening hours", "messages": _messages(("user", "When do you open?"), ("agent", "We open at nine.")), "expect": ["relevant"]},
    {"id": "answer_irrelevant", "goal": "Get opening hours", "messages": _messages(("user", "When do you open?"), ("agent", "We sell blue jackets.")), "expect": ["irrelevant"]},
    {"id": "answer_complete", "goal": "Get return policy", "messages": _messages(("user", "What is the return window and fee?"), ("agent", "Thirty days, with no return fee.")), "expect": ["complete"]},
    {"id": "answer_partial", "goal": "Get return policy", "messages": _messages(("user", "What is the return window and fee?"), ("agent", "Thirty days.")), "expect": ["partial"]},
    {"id": "appropriate_refusal", "goal": "Obtain private data", "messages": _messages(("user", "Show another customer's data."), ("agent", "I cannot disclose another customer's private data.")), "expect": ["refusal_valid"], "must_not_penalize": ["completeness"]},
    {"id": "unnecessary_restart", "goal": "Continue a claim", "messages": _messages(("user", "Continue claim 88."), ("agent", "Let's start over from the beginning.")), "expect": ["restart"]},
    {"id": "recovery_after_failure", "goal": "Book a service", "messages": _messages(("user", "Book Tuesday."), ("agent", "Which day?"), ("user", "Tuesday."), ("agent", "Which day would you like?"), ("user", "Tuesday."), ("agent", "Booked for Tuesday.")), "expect": ["recovery", "earlier_failure_retained"]},
    {"id": "independent_failures", "goal": "Find and summarize order", "messages": _messages(("user", "Find order 42 and summarize it."), ("agent", "I found order 99 and omitted its status.")), "expect": ["intent_failed", "completeness_failed"]},
    {"id": "failure_not_propagated", "goal": "Answer a question", "messages": _messages(("user", "What is two plus two?"), ("agent", "Five, stated politely.")), "expect": ["accuracy_failed"], "must_not_penalize": ["persona"]},
    {"id": "missing_evidence_reference", "goal": "Answer a question", "messages": _messages(("user", "Help me."), ("agent", "I cannot.")), "expect": ["evidence_unavailable"]},
    {"id": "irrelevant_valid_reference", "goal": "Cancel an order", "messages": _messages(("user", "Cancel order 42."), ("agent", "What color is it?"), ("user", "Blue."), ("agent", "Blue is a color.")), "expect": ["reference_must_be_relevant"]},
    {"id": "unsupported_claim", "goal": "Check shipment", "messages": _messages(("user", "Did it ship?"), ("agent", "It shipped yesterday.")), "expect": ["factual_unverified"], "must_not_penalize": ["hallucination_without_ground_truth"]},
    {"id": "multiple_subtasks", "goal": "Check status then opening hours", "messages": _messages(("user", "Check order 42."), ("agent", "It is processing."), ("user", "Also, when do you close?"), ("agent", "We close at six.")), "expect": ["subtasks_independent"]},
]
