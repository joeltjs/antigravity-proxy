import hashlib
from typing import Dict, Any, List

def compress_rtk(text: str) -> str:
    """Trim verbose shell and package build logs to conserve context tokens."""
    if not text or not isinstance(text, str) or len(text) < 300:
        return text
    lines = text.splitlines()
    if len(lines) <= 25:
        return text
    head = lines[:10]
    tail = lines[-10:]
    omitted = len(lines) - 20
    return "\n".join(head) + f"\n\n[... RTK: {omitted} lines of noisy output truncated ...]\n\n" + "\n".join(tail)

def inject_optimizer_directives(optimizers: Dict[str, bool], system_instruction: Any) -> Any:
    """Inject zero-slop directives based on active optimizer toggles."""
    directives = []
    if optimizers.get("caveman"):
        directives.append(
            "[OPTIMIZER: CAVEMAN MODE ACTIVE]\n"
            "Be direct and succinct. Omit conversational pleasantries, preambles, and filler."
        )
    if optimizers.get("ponytail"):
        directives.append(
            "[OPTIMIZER: PONYTAIL MODE ACTIVE]\n"
            "Emit surgical diffs/patches when modifying code. Avoid rewriting unchanged lines."
        )

    if not directives:
        return system_instruction

    prompt_addon = "\n\n".join(directives)
    if system_instruction and isinstance(system_instruction, dict):
        parts = system_instruction.setdefault("parts", [{"text": ""}])
        parts[0]["text"] = (parts[0].get("text", "") + "\n\n" + prompt_addon).strip()
        return system_instruction
    return {"parts": [{"text": prompt_addon}]}

def resolve_client_session_id(body: Dict[str, Any], account_email: str) -> str:
    """Derive stable session ID to enable upstream prompt caching across conversation turns."""
    messages = body.get("messages", [])
    if not messages:
        return f"ag-session-{hashlib.md5(account_email.encode()).hexdigest()[:12]}"
    
    # Use the first user message content as deterministic session seed
    first_user_content = ""
    for m in messages:
        if m.get("role") == "user":
            content = m.get("content", "")
            first_user_content = content if isinstance(content, str) else str(content)
            break

    seed = f"{account_email}:{first_user_content[:150]}"
    return f"ag-{hashlib.sha256(seed.encode()).hexdigest()[:16]}"
