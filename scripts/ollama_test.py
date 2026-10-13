import time
import requests
import json

SYSTEM_PROMPT = """You are a helpful customer support agent for an e-commerce company.
Your job is to assist users with their orders.
You can handle:
- damaged order (offer a refund or replacement)
- refund request (process refunds for eligible items)
- order status (provide tracking info)
- cancellation (cancel pending orders)
- human escalation (transfer to a human agent if requested or if you cannot help)

Keep your responses concise, helpful, and directly relevant to the user's message.
Do not make up fake order details unless the user provides them.
If you need an order number, ask for it.
"""

user_messages = [
    "Hello, I want a refund for my order.",
    "My order # is A1029.",
    "It arrived completely damaged.",
    "No, just a refund please.",
    "How long will that take?",
    "Okay, thank you for your help."
]

history = [{"role": "system", "content": SYSTEM_PROMPT}]

print("--- OLLAMA CONTEXT GROWTH TEST ---")

for i, user_message in enumerate(user_messages):
    turn = i + 1
    history.append({"role": "user", "content": user_message})
    
    messages_payload = [history[0]] + history[1:][-5:]
    
    # Calculate sizes
    num_messages = len(messages_payload)
    num_chars = sum(len(m["content"]) for m in messages_payload)
    
    t0 = time.perf_counter()
    try:
        response = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "llama3.1:8b",
                "messages": messages_payload,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 80}
            },
            timeout=120,
        )
        response.raise_for_status()
        reply = response.json().get("message", {}).get("content", "").strip()
        elapsed = time.perf_counter() - t0
        
        # Approximate tokens (rule of thumb: 1 token ~= 4 chars)
        approx_tokens = num_chars // 4
        
        print(f"Turn {turn}:")
        print(f"  Request Size: {num_messages} messages, ~{num_chars} chars (~{approx_tokens} tokens)")
        print(f"  Response Time: {elapsed:.3f}s")
        print(f"  Reply: {reply}")
        
    except Exception as e:
        print(f"Turn {turn} failed: {e}")
        reply = "ERROR"
        
    history.append({"role": "assistant", "content": reply})
