import os
import re
import time
import json
import uuid
import socks
import socket
import secrets
from typing import Dict, Any, List, Optional

# Constants & Model Mapping
MODEL_MAP = {
    # Gemini 3.8 Series: upstream Google engine is 'gemini-3.8-flash-tiered'
    # Reasoning level is injected via generationConfig.thinkingConfig.thinkingLevel
    "gemini-3.8-flash-high": "gemini-3.8-flash-tiered",
    "gemini-3.8-flash-medium": "gemini-3.8-flash-tiered",

    # Claude Series: thinking enabled natively
    "claude-sonnet-4-6-thinking": "claude-sonnet-4-6",
    "claude-opus-4-6-thinking": "claude-opus-4-6-thinking",
}

FULL_MODEL_CATALOG = [
    {"id": "gemini-3.8-flash-high", "display": "Gemini 3.8 Flash (High)", "kind": "chat"},
    {"id": "gemini-3.8-flash-medium", "display": "Gemini 3.8 Flash (Medium)", "kind": "chat"},
    {"id": "gemini-3.8-flash-tiered", "display": "Gemini 3.8 Flash (Tiered)", "kind": "chat"},
    {"id": "claude-sonnet-4-6", "display": "Claude Sonnet 4.6 (Thinking)", "kind": "chat"},
    {"id": "claude-opus-4-6-thinking", "display": "Claude Opus 4.6 (Thinking)", "kind": "chat"},
    {"id": "gemini-2.5-flash", "display": "Gemini 2.5 Flash", "kind": "chat"},
]

DEFAULT_THOUGHT_SIGNATURE = (
    "EoMBCoABARFNMg+bY3p0aZ2F2c3RldmVuc29uQGdtYWlsLmNvbSo/ChFhbnRpZ3Jhdml0eS9pZGUvMi4xLjESG2Rhcndpbi9hcm02NCI"
    "Z0xCJdRo1gjexOFeODZMpQF6Yxnoic7IrdgsFA3iePTbFnPp3IAM1fAThWhXJUn3QInUOTd5o1qmTmn6REbL15g/JQNl+dqUoPkhle"
    "eb2V3kjqp1okmO3wMZbPknR3S1LZNmlS72/iBQUm+n2b/RCn4PjmM2"
)

# SOCKS5 WARP Interceptor Setup
def setup_warp_routing(proxy_host="127.0.0.1", proxy_port=40000):
    orig_create_conn = socket.create_connection

    def _warp_create_connection(address, timeout=None, source_address=None):
        host, port = address
        kwargs = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        if isinstance(host, str) and (host.endswith(".googleapis.com") or host == "googleapis.com"):
            return socks.create_connection(
                dest_pair=(host, port),
                proxy_type=socks.SOCKS5,
                proxy_addr=proxy_host,
                proxy_port=proxy_port,
                **kwargs
            )
        return orig_create_conn(address, timeout=timeout or 60, source_address=source_address)

    socket.create_connection = _warp_create_connection
    print(f"[WARP] SOCKS5 routing active on {proxy_host}:{proxy_port} (Google API only)")
