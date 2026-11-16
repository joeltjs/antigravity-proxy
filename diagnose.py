#!/usr/bin/env python3
"""ag-proxy diagnostics: one entry point, four subcommands.

    diagnose.py accounts [model]   per-account upstream verdict (TOS / VERIFY / 429 / OK)
    diagnose.py one <idx> [ua]     raw SSE body for one account under a given client UA
    diagnose.py catalog [needle]   union of upstream model catalogs across the active pool
    diagnose.py e2e                end-to-end test of the running proxy (plain, tools, long ctx)

Reads credentials from config.json/.env in memory and never prints their values.
Google traffic is routed through the WARP SOCKS5 proxy, same policy as server.py.
"""
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

import socks

BASE = "/home/ubuntu/ag-proxy"
PROXY = "http://127.0.0.1:20130"
VERSION = os.environ.get("ANTIGRAVITY_CLIENT_VERSION", "2.29.0")
UA = f"antigravity/ide/{VERSION} darwin/arm64"
UA_LEGACY = "antigravity/ide/2.1.1 darwin/arm64"

GOOGLE_DOMAINS = ("daily-cloudcode-pa.googleapis.com", "cloudcode-pa.googleapis.com",
                  "oauth2.googleapis.com")
_orig_create_connection = socket.create_connection


def _warp(address, *a, **kw):
    host, port = address
    if any(str(host).endswith(d) for d in GOOGLE_DOMAINS):
        return socks.create_connection(dest_pair=(host, port), proxy_type=socks.SOCKS5,
                                       proxy_addr="127.0.0.1", proxy_port=40000,
                                       timeout=kw.get("timeout", 60))
    return _orig_create_connection(address, *a, **kw)


socket.create_connection = _warp

CFG = json.load(open(f"{BASE}/config.json"))
_creds = dict(line.split("=", 1) for line in open(f"{BASE}/.env").read().splitlines() if "=" in line)
CLIENT_ID = _creds.get("OAUTH_ACCESS_KEY", "").strip()
CLIENT_SECRET = _creds.get("OAUTH_SECRET_KEY", "").strip()


def token_for(acc):
    data = urllib.parse.urlencode({"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                                   "refresh_token": acc["refresh_token"],
                                   "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token",
                                                       data=data), timeout=25) as r:
        return json.load(r)["access_token"]


def reason_of(body):
    try:
        err = json.loads(body).get("error", {})
    except Exception:
        return body[:70].replace("\n", " ")
    detail = (err.get("details") or [{}])[0]
    return f"{detail.get('reason') or err.get('status') or ''}: {str(err.get('message', ''))[:70]}"


def upstream(token, url, body, ua=UA, timeout=90):
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/json",
        "User-Agent": ua, "X-Client-Version": ua.split("/")[2].split(" ")[0] if "/" in ua else ""})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


def gen_body(model, text="Reply with exactly: PONG", max_tokens=512):
    return json.dumps({"model": model, "userAgent": "antigravity", "request": {
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": {"maxOutputTokens": max_tokens}}}).encode()


def sse_text(raw):
    out = ""
    for chunk in raw.split("data: "):
        chunk = chunk.strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            for cand in json.loads(chunk).get("response", {}).get("candidates", []):
                for p in cand.get("content", {}).get("parts", []):
                    if p.get("text"):
                        out += p["text"]
        except Exception:
            pass
    return out.strip()


def cmd_accounts(model):
    quota_api = "https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels"
    gen_api = "https://daily-cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse"
    print(f"model={model}  current_ua={VERSION}")
    print(f"{'account':30s} {'quota':6s} {'legacy UA':22s} {'current UA':22s} verdict")
    print("-" * 104)
    for acc in CFG["accounts"]:
        email = acc["email"]
        try:
            tok = token_for(acc)
        except Exception as e:
            print(f"{email:30s} {'-':6s} token refresh failed: {type(e).__name__}")
            continue
        qc, _ = upstream(tok, quota_api, b"{}", timeout=25)
        _, old = upstream(tok, gen_api, gen_body(model))
        cc, new = upstream(tok, gen_api, gen_body(model))
        if cc == 200 and "no longer supported" in new:
            verdict = "UA_RETIRED"
        elif cc == 200:
            verdict = "OK"
        elif "TOS_VIOLATION" in new:
            verdict = "TOS"
        elif "VALIDATION_REQUIRED" in new:
            verdict = "VERIFY"
        elif cc == 429:
            verdict = "THROTTLED"
        else:
            verdict = f"HTTP{cc}"
        print(f"{email:30s} {qc:<6d} {(str(cc)+' '+reason_of(new))[:21]:22s} "
              f"{(str(cc)+' '+sse_text(new))[:21]:22s} {verdict}")


def cmd_one(idx, ua):
    acc = CFG["accounts"][idx]
    code, raw = upstream(token_for(acc),
                         "https://daily-cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse",
                         gen_body("gemini-3.8-flash-high"), ua=ua)
    print(f"account={acc['email']} ua={ua} HTTP {code}")
    print(raw[:2500])


def cmd_catalog(needle):
    quota_api = "https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels"
    ids = set()
    for acc in CFG["accounts"]:
        if acc.get("disabled"):
            continue
        try:
            code, raw = upstream(token_for(acc), quota_api, b"{}", timeout=25)
        except Exception as e:
            print(f"{acc['email']:30s} {type(e).__name__}")
            continue
        if code != 200:
            print(f"{acc['email']:30s} HTTP {code}")
            continue
        found = set(json.loads(raw).get("models", {}))
        ids |= found
        print(f"{acc['email']:30s} {len(found)} models")
    chat = sorted(i for i in ids if not i.startswith(("chat_", "tab_")))
    print(f"\nmatching {needle!r}: {[i for i in chat if needle in i] or '(none)'}")
    print(f"chat-usable ({len(chat)}):")
    for i in chat:
        print("  ", i)


def cmd_e2e():
    key = CFG["api_keys"][0]["key"]
    hdr = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}

    def call(body):
        req = urllib.request.Request(PROXY + "/v1/chat/completions",
                                     data=json.dumps(body).encode(), headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.status, r.read().decode(errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")[:400]

    fails = []

    code, raw = call({"model": "gemini-3.8-flash-high", "stream": False, "max_tokens": 400,
                      "messages": [{"role": "user", "content": "Sebutkan angka 3 saja."}]})
    body = json.loads(raw) if code == 200 else {}
    content = (body.get("choices", [{}])[0].get("message", {}) or {}).get("content") or ""
    print(f"1 plain non-stream      HTTP {code} content={content[:60]!r}")
    if code != 200 or "no longer supported" in content:
        fails.append("plain")

    code, raw = call({"model": "gemini-3.8-flash-high", "stream": True, "max_tokens": 800,
                      "messages": [{"role": "user", "content": "List /tmp with the list_dir tool"}],
                      "tools": [{"type": "function", "function": {
                          "name": "list_dir", "description": "list directory",
                          "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                                         "required": ["path"]}}}]})
    tool_chunk = '"tool_calls"' in raw
    print(f"2 stream + tools        HTTP {code} tool_calls={tool_chunk} done={'[DONE]' in raw}")
    if code != 200 or not tool_chunk:
        fails.append("stream_tools")

    # Long context: ring guard must trim, and the window must start on a clean user
    # turn even when the newest 200 messages begin with a tool result.
    filler = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"filler {i}"}
              for i in range(210)]
    tool_block = ([{"role": "assistant", "content": None,
                    "tool_calls": [{"id": "call_1", "type": "function",
                                    "function": {"name": "list_dir", "arguments": "{}"}}]}]
                  + [{"role": "tool", "tool_call_id": "call_1", "content": "a.txt"}
                     for _ in range(5)])
    tail = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"tail {i}"}
            for i in range(195)]
    big = [{"role": "system", "content": "You are terse."}] + filler + tool_block + tail
    big.append({"role": "user", "content": "Sebutkan angka 7 saja."})
    code, raw = call({"model": "gemini-3.8-flash-high", "stream": False, "max_tokens": 400,
                      "messages": big})
    ok = code == 200 and "7" in (json.loads(raw)["choices"][0]["message"].get("content") or "") if code == 200 else False
    print(f"3 long ctx {len(big):>4} msgs   HTTP {code} answered_7={ok}")
    if not ok:
        fails.append("long_context")

    print("\nRESULT:", "PASS" if not fails else f"FAIL {fails}")
    return 0 if not fails else 1


def cmd_matrix():
    """Pin each enabled account in turn and send a REAL request through the proxy."""
    import time
    key = CFG["api_keys"][0]["key"]
    hdr = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    log_path = f"{BASE}/proxy.log"
    enabled = [a for a in CFG["accounts"] if not a.get("disabled")]
    original = CFG.get("active_account") or (enabled[0]["email"] if enabled else "")

    def set_active(email):
        req = urllib.request.Request(PROXY + "/v1/accounts/active",
                                     data=json.dumps({"email": email}).encode(),
                                     headers=hdr, method="PUT")
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status

    def openai_sse_text(raw):
        """Parse the proxy's OpenAI-style SSE chunks (not the upstream Gemini shape)."""
        content, tools, finish = "", "", None
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                continue
            try:
                d = json.loads(payload)
            except Exception:
                continue
            for ch in d.get("choices", []):
                delta = ch.get("delta") or {}
                content += delta.get("content") or ""
                for tc in delta.get("tool_calls") or []:
                    tools += tc.get("function", {}).get("name", "")
                finish = ch.get("finish_reason") or finish
        return content or tools, finish

    def fire(model, stream):
        body = {"model": model, "stream": stream, "max_tokens": 600,
                "messages": [{"role": "user", "content": "Sebutkan angka 3 saja, tanpa penjelasan."}]}
        req = urllib.request.Request(PROXY + "/v1/chat/completions",
                                     data=json.dumps(body).encode(), headers=hdr)
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                raw = r.read().decode(errors="replace")
            dt = time.time() - t0
            if stream:
                txt, finish = openai_sse_text(raw)
                done = "[DONE]" in raw and finish is not None
            else:
                d = json.loads(raw)
                txt = d["choices"][0]["message"].get("content") or ""
                done = True
            return r.status, txt, dt, done
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")[:160], time.time() - t0, False
        except Exception as e:
            return 0, f"{type(e).__name__}: {e}", time.time() - t0, False

    def new_log(start):
        with open(log_path, errors="replace") as fh:
            fh.seek(start)
            return fh.read()

    plans = [("gemini-3.8-flash-high", True), ("gemini-3.8-flash-medium", False)]
    verdict = {a["email"]: [] for a in enabled}
    try:
        for model, stream in plans:
            print(f"\n=== {model} ({'stream' if stream else 'non-stream'}) ===")
            print(f"{'account':30s} {'http':4s} {'serve':22s} {'secs':5s} reply / error")
            print("-" * 100)
            for acc in enabled:
                email = acc["email"]
                set_active(email)
                start = os.path.getsize(log_path) if os.path.exists(log_path) else 0
                code, txt, secs, done = fire(model, stream)
                chunk = new_log(start)
                served = re.findall(r"\[ACC\] (\S+) \(attempt 1\)", chunk)
                served_by = served[0] if served else "?"
                ok = code == 200 and served_by == email and txt.strip() and done
                if ok:
                    mark = "OK"
                elif code != 200:
                    mark = f"HTTP{code}"
                elif served_by != email:
                    mark = "FELL_BACK"
                elif not txt.strip():
                    mark = "EMPTY"
                else:
                    mark = "NO_DONE"
                verdict[email].append(mark)
                note = (txt.strip().replace("\n", " ")[:40] if code == 200 else txt[:40])
                print(f"{email:30s} {code:<4d} {served_by:22s} {secs:5.1f} {note}")
    finally:
        if original:
            set_active(original)
            print(f"\nactive_account restored -> {original}")

    print("\n=== PER-ACCOUNT VERDICT ===")
    healthy = 0
    for email, marks in verdict.items():
        good = all(m == "OK" for m in marks)
        healthy += 1 if good else 0
        print(f"  {email:30s} {'USABLE' if good else 'PROBLEM'}  {marks}")
    print(f"\n{healthy}/{len(enabled)} accounts usable for gemini-3.8-flash (high + medium)")
    return 0 if healthy == len(enabled) else 1


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "e2e"
    args = sys.argv[2:]
    if cmd == "accounts":
        cmd_accounts(args[0] if args else "gemini-3.8-flash-high")
    elif cmd == "one":
        cmd_one(int(args[0]), args[1] if len(args) > 1 else UA)
    elif cmd == "catalog":
        cmd_catalog(args[0] if args else "3.8")
    elif cmd == "e2e":
        sys.exit(cmd_e2e())
    elif cmd == "matrix":
        sys.exit(cmd_matrix())
    else:
        print(__doc__)
        sys.exit(2)
