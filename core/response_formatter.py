import time
import json
from typing import Dict, Any, List, Optional

def antigravity_to_openai(ag_response: Dict[str, Any], model_name: str, request_id: str) -> Dict[str, Any]:
    """Convert Antigravity JSON response to OpenAI chat completion format."""
    candidates = ag_response.get("response", {}).get("candidates", [])
    usage = ag_response.get("response", {}).get("usageMetadata", {})
    content = ""
    reasoning_content = ""
    tool_calls = []

    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        for part in parts:
            if (part.get("thought") or part.get("thoughtSignature")) and part.get("text"):
                reasoning_content += part["text"]
            elif part.get("text"):
                content += part["text"]
            elif part.get("functionCall"):
                fc = part["functionCall"]
                tool_calls.append({
                    "id": fc.get("id", f"call_{fc.get('name','')}"),
                    "type": "function",
                    "function": {
                        "name": fc.get("name", ""),
                        "arguments": json.dumps(fc.get("args", {}))
                    }
                })

    message: Dict[str, Any] = {"role": "assistant"}
    if content: message["content"] = content
    if reasoning_content: message["reasoning_content"] = reasoning_content
    if tool_calls: message["tool_calls"] = tool_calls
    if not content and not tool_calls: message["content"] = ""

    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
            "reasoning_tokens": usage.get("thoughtsTokenCount", 0),
            "prompt_tokens_details": {
                "cached_tokens": usage.get("cachedContentTokenCount", 0)
            }
        }
    }

def antigravity_chunk_to_openai(chunk_data: Dict[str, Any], model_name: str, request_id: str, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert Antigravity SSE stream chunk to OpenAI streaming delta."""
    response = chunk_data.get("response", {})
    candidates = response.get("candidates", [])
    usage = response.get("usageMetadata", {})
    if usage:
        state["usage"] = usage
    if not candidates:
        return None

    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts", [])
    finish_reason = candidate.get("finishReason")
    openai_finish = None
    if finish_reason == "STOP": openai_finish = "stop"
    elif finish_reason == "MAX_TOKENS": openai_finish = "length"

    delta: Dict[str, Any] = {}
    content = ""
    reasoning = ""
    tool_calls = []

    for part in parts:
        if (part.get("thought") or part.get("thoughtSignature")) and part.get("text"):
            reasoning += part["text"]
        elif part.get("text"):
            content += part["text"]
        elif part.get("functionCall"):
            fc = part["functionCall"]
            tool_calls.append({
                "index": 0,
                "id": fc.get("id", f"call_{fc.get('name','')}"),
                "type": "function",
                "function": {
                    "name": fc.get("name", ""),
                    "arguments": json.dumps(fc.get("args", {}))
                }
            })

    if not state.get("sent_role"):
        delta["role"] = "assistant"
        state["sent_role"] = True
    if content: delta["content"] = content
    if reasoning: delta["reasoning_content"] = reasoning
    if tool_calls: delta["tool_calls"] = tool_calls

    if not delta and not openai_finish:
        return None

    return {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{"index": 0, "delta": delta, "finish_reason": openai_finish}]
    }
