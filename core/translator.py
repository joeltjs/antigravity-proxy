import json
import re
from typing import Dict, Any, Tuple, List, Optional
from core.constants import MODEL_MAP, DEFAULT_THOUGHT_SIGNATURE
from core.optimizers import compress_rtk, inject_optimizer_directives

def sanitize_fn_name(name: str) -> str:
    """Ensure tool name complies with Gemini schema."""
    if not name:
        return "_unknown"
    s = re.sub(r"[^a-zA-Z0-9_.:\-]", "_", name)
    if not re.match(r"^[a-zA-Z_]", s):
        s = "fn_" + s
    return s[:64]

def clean_schema_for_gemini(schema: Any) -> Any:
    """Strip unsupported JSON Schema keywords."""
    if not isinstance(schema, dict):
        return schema
    clean = {}
    drop_keys = {"$schema", "additionalProperties", "default", "title", "pattern", "format"}
    for k, v in schema.items():
        if k in drop_keys:
            continue
        if k == "properties" and isinstance(v, dict):
            clean[k] = {pk: clean_schema_for_gemini(pv) for pk, pv in v.items()}
        elif k == "items":
            clean[k] = clean_schema_for_gemini(v)
        else:
            clean[k] = v
    return clean

def openai_to_antigravity(body: Dict[str, Any], optimizers: Dict[str, bool]) -> Tuple[Dict[str, Any], bool, str]:
    """Translate OpenAI chat completion payload to Antigravity format."""
    messages = body.get("messages", [])
    model = body.get("model", "gemini-3-flash")
    stream = body.get("stream", False)
    max_tokens = body.get("max_tokens") or 8192
    temperature = body.get("temperature")
    top_p = body.get("top_p")

    bare_model = model.split("/", 1)[1] if "/" in model and model.split("/", 1)[0] not in MODEL_MAP else model
    ag_model = MODEL_MAP.get(bare_model, bare_model)

    tool_id_to_name = {}
    for msg in messages:
        for tc in msg.get("tool_calls") or []:
            tc_id = tc.get("id")
            fn_name = (tc.get("function") or {}).get("name")
            if tc_id and fn_name:
                tool_id_to_name[tc_id] = sanitize_fn_name(fn_name)

    contents = []
    system_instruction = None

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")
        if role == "system":
            if isinstance(content, str):
                system_instruction = {"parts": [{"text": content}]}
            elif isinstance(content, list):
                texts = [p.get("text", "") for p in content if p.get("type") == "text"]
                system_instruction = {"parts": [{"text": " ".join(texts)}]}
            continue

        ag_role = "model" if role == "assistant" else "user"
        if role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            content_str = content if isinstance(content, str) else json.dumps(content)
            if optimizers.get("rtk"):
                content_str = compress_rtk(content_str)
            resolved_name = tool_id_to_name.get(tool_call_id, "tool")
            contents.append({
                "role": "user",
                "parts": [{
                    "functionResponse": {
                        "id": tool_call_id or None,
                        "name": resolved_name,
                        "response": {"result": content_str}
                    }
                }]
            })
            continue

        parts = []
        tool_calls = msg.get("tool_calls")
        if isinstance(content, str) and content:
            parts.append({"text": content})
        elif isinstance(content, list):
            for p in content:
                if p.get("type") == "text" and p.get("text"):
                    parts.append({"text": p["text"]})
                elif p.get("type") == "image_url":
                    url = p.get("image_url", {}).get("url", "")
                    if url.startswith("data:"):
                        header, b64data = url.split(",", 1)
                        mime = header.split(":")[1].split(";")[0]
                        parts.append({"inlineData": {"mimeType": mime, "data": b64data}})

        if tool_calls:
            for tc in tool_calls:
                fn = tc.get("function", {})
                args = fn.get("arguments", "{}")
                if isinstance(args, str):
                    try: args = json.loads(args)
                    except: args = {}
                if not isinstance(args, dict):
                    args = {"value": args}
                tc_id = tc.get("id", "")
                parts.append({
                    "thoughtSignature": DEFAULT_THOUGHT_SIGNATURE,
                    "functionCall": {
                        "id": tc_id or None,
                        "name": tool_id_to_name.get(tc_id, sanitize_fn_name(fn.get("name", ""))),
                        "args": args
                    }
                })

        if parts:
            contents.append({"role": ag_role, "parts": parts})

    system_instruction = inject_optimizer_directives(optimizers, system_instruction)

    # Merge adjacent same-role entries
    merged = []
    for c in contents:
        if merged and merged[-1]["role"] == c["role"]:
            merged[-1]["parts"].extend(c["parts"])
        else:
            merged.append({"role": c["role"], "parts": list(c["parts"])})

    gen_config: Dict[str, Any] = {"maxOutputTokens": max_tokens}
    if temperature is not None: gen_config["temperature"] = temperature
    if top_p is not None: gen_config["topP"] = top_p

    reasoning_effort = body.get("reasoning_effort")
    if not reasoning_effort:
        if bare_model.endswith("-high"):
            reasoning_effort = "high"
        elif bare_model.endswith("-medium"):
            reasoning_effort = "medium"
        elif bare_model.endswith("-low"):
            reasoning_effort = "low"

    if reasoning_effort:
        if ag_model and "tiered" in str(ag_model):
            gen_config["thinkingConfig"] = {
                "thinkingLevel": reasoning_effort,
                "includeThoughts": True
            }
        else:
            budget_map = {"low": 1024, "medium": 8192, "high": 24576}
            budget = budget_map.get(reasoning_effort, 8192)
            gen_config["thinkingConfig"] = {
                "thinkingBudget": budget,
                "includeThoughts": True
            }
            if max_tokens <= budget:
                gen_config["maxOutputTokens"] = budget + 4096

    tools = []
    for tool in body.get("tools", []):
        fn = tool.get("function", {})
        tools.append({
            "name": sanitize_fn_name(fn.get("name", "")),
            "description": fn.get("description", ""),
            "parameters": clean_schema_for_gemini(fn.get("parameters", {"type": "object", "properties": {}}))
        })

    request_payload: Dict[str, Any] = {
        "contents": merged,
        "generationConfig": gen_config
    }
    if system_instruction:
        request_payload["systemInstruction"] = system_instruction
    if tools:
        request_payload["tools"] = [{"functionDeclarations": tools}]

    return {"model": ag_model, "request": request_payload}, stream, bare_model
