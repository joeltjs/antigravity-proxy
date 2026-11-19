#!/usr/bin/env python3
"""
Antigravity Multi-Account Proxy Server v2
==========================================
OpenAI-compatible proxy that aggregates multiple Google Antigravity accounts.

v2 improvements:
- Quota tracking (fetchAvailableModels API)
- Web dashboard with dark theme, quota bars
- Password-protected UI
- Account management (add/remove/disable)
- Exposed on port 20130 (requires OCI Security List + password)
"""

import json
import os
import secrets
import time
import threading
import socks
import socket
from core.optimizers import resolve_client_session_id

_orig_create_connection = socket.create_connection

def _warp_create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
    host, port = address
    if 'googleapis.com' in host:
        return socks.create_connection(dest_pair=(host, port), proxy_type=socks.SOCKS5, proxy_addr='127.0.0.1', proxy_port=40000, timeout=timeout)
    return _orig_create_connection(address, timeout, source_address)

socket.create_connection = _warp_create_connection

import urllib.request
import urllib.parse
import urllib.error
import socket

# WARP SOCKS5 Proxy for routing Google API requests through Cloudflare
# Only outbound requests to Google APIs go through WARP. All other traffic stays local.
WARP_SOCKS5_HOST = "127.0.0.1"
WARP_SOCKS5_PORT = 40000
WARP_ENABLED = os.environ.get("WARP_ENABLED", "true").lower() == "true"

# Client identity sent to Google CloudCode. Google retires old client builds and
# answers them with a friendly "This version of Antigravity is no longer supported"
# notice over HTTP 200 with no real content — it looks exactly like a dead/flagged
# account but it is a stale User-Agent. Keep the version in ONE place so the next
# retirement is a one-line fix; override with ANTIGRAVITY_CLIENT_VERSION if needed.
ANTIGRAVITY_CLIENT_VERSION = os.environ.get("ANTIGRAVITY_CLIENT_VERSION", "2.29.0")
ANTIGRAVITY_CLIENT_HEADERS = {
    "User-Agent": f"antigravity/ide/{ANTIGRAVITY_CLIENT_VERSION} darwin/arm64",
    "X-Client-Version": ANTIGRAVITY_CLIENT_VERSION,
}

GOOGLE_API_DOMAINS = [
    'daily-cloudcode-pa.googleapis.com',
    'cloudcode-pa.googleapis.com',
    'oauth2.googleapis.com',
    'www.googleapis.com',
    'generativelanguage.googleapis.com'
]

def _is_google_api(host):
    return any(host.endswith(d) for d in GOOGLE_API_DOMAINS)

if WARP_ENABLED:
    try:
        import socks as _socks_mod
        _original_create_connection = socket.create_connection
        
        def _warp_create_connection(address, *args, **kwargs):
            host, port = address
            if _is_google_api(host):
                return _socks_mod.create_connection(
                    dest_pair=(host, port),
                    proxy_type=_socks_mod.SOCKS5,
                    proxy_addr=WARP_SOCKS5_HOST,
                    proxy_port=WARP_SOCKS5_PORT,
                    timeout=kwargs.get('timeout', 300)
                )
            return _original_create_connection(address, *args, **kwargs)
        
        socket.create_connection = _warp_create_connection
        print(f"[WARP] SOCKS5 proxy enabled on {WARP_SOCKS5_HOST}:{WARP_SOCKS5_PORT} (Google API traffic only)")
    except ImportError:
        print("[WARP] PySocks not installed, using direct connection")
        WARP_ENABLED = False
else:
    print("[WARP] Proxy disabled, using direct connection")
import urllib.parse
import urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

CONFIG_PATH = "/home/ubuntu/ag-proxy/config.json"
ENV_PATH = "/home/ubuntu/ag-proxy/.env"

def _load_env_file(path):
    """Load KEY=VALUE lines from .env file (stdlib only, no deps)."""
    if not os.path.exists(path):
        return {}
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip().strip("'\"")
    return env

_ENV_FILE = _load_env_file(ENV_PATH)

with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

PORT = CONFIG.get("port", 20130)
HOST = CONFIG.get("host", "0.0.0.0")

# Optimization plugins configuration
OPTIMIZERS = CONFIG.get("optimizers", {
    "rtk": False,       # Reduced Tool Kit (Shell & command output compressor)
    "caveman": False,   # Zero-slop direct prose compression
    "ponytail": False   # Targeted code diff & minimal edits mode
})
CONFIG["optimizers"] = OPTIMIZERS
# API keys for /v1/* endpoints (multiple keys supported: config.json or environment)
def _load_api_keys():
    keys = []
    # From config.json api_keys list
    if "api_keys" in CONFIG and isinstance(CONFIG["api_keys"], list):
        for k in CONFIG["api_keys"]:
            if isinstance(k, dict) and k.get("key"):
                keys.append(k)
            elif isinstance(k, str) and k.strip():
                keys.append({"id": f"key-{len(keys)+1}", "name": "Default Key", "key": k.strip(), "created": int(time.time())})
    # From legacy single api_key in config.json
    elif CONFIG.get("api_key"):
        keys.append({"id": "key-1", "name": "Default Key", "key": CONFIG["api_key"].strip(), "created": int(time.time())})
    # Fallback to env var
    env_key = os.environ.get("AG_PROXY_API_KEY")
    if env_key and not any(k["key"] == env_key for k in keys):
        keys.append({"id": f"key-{len(keys)+1}", "name": "Env Key", "key": env_key.strip(), "created": int(time.time())})
    # If completely empty, generate a default one
    if not keys:
        default_k = "ag-proxy-" + secrets.token_hex(16)
        keys.append({"id": "key-1", "name": "Default Key", "key": default_k, "created": int(time.time())})
        CONFIG["api_keys"] = keys
        CONFIG.pop("api_key", None)
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(CONFIG, f, indent=2)
        except Exception: pass
    return keys

API_KEYS = _load_api_keys()

def _save_api_keys():
    CONFIG["api_keys"] = API_KEYS
    CONFIG.pop("api_key", None)
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(CONFIG, f, indent=2)
    except Exception as e:
        print(f"  [WARN] Save API keys error: {e}")
DASHBOARD_USER = os.environ.get("AG_DASHBOARD_USER") or _ENV_FILE.get("AG_DASHBOARD_USER") or CONFIG.get("dashboard_user", "admin")
DASHBOARD_PASSWORD = os.environ.get("AG_DASHBOARD_PASSWORD") or _ENV_FILE.get("AG_DASHBOARD_PASSWORD") or CONFIG.get("dashboard_password", "")
# OAuth (Google Cloud Console): env var > .env > config.json (Optional: for web OAuth login like 9router)
OAUTH = dict(CONFIG.get("oauth", {}))
OAUTH["client_id"] = os.environ.get("OAUTH_ACCESS_KEY") or _ENV_FILE.get("OAUTH_ACCESS_KEY") or OAUTH.get("client_id", "")
OAUTH["client_secret"] = os.environ.get("OAUTH_SECRET_KEY") or _ENV_FILE.get("OAUTH_SECRET_KEY") or OAUTH.get("client_secret", "")
ACCOUNTS = CONFIG["accounts"]
STRATEGY = CONFIG.get("strategy", "round-robin")
MAX_RETRIES = CONFIG.get("max_retries", 3)
# Soft client-side RPM ceiling per account. Google's per-minute limit is the real cause of
# HTTP 429 RESOURCE_EXHAUSTED while the daily quota still shows ~100%: a parallel burst from
# the IDE saturates one account's window. Staying just under it and rotating across the pool
# converts those hard 429s into smooth throughput. Tune with AG_SOFT_RPM_LIMIT.
SOFT_RPM_LIMIT = int(os.environ.get("AG_SOFT_RPM_LIMIT") or CONFIG.get("soft_rpm_limit") or 8)
# Stagger between account attempts. Google rejects every request that lands inside the
# same short throttle window, so firing 3 attempts in the same second burns the whole
# retry budget on one blip. A short gap lets that window pass.
ATTEMPT_BACKOFF_BASE = float(os.environ.get("AG_RETRY_BACKOFF_MS", "2500")) / 1000.0
ATTEMPT_BACKOFF_MAX = float(os.environ.get("AG_RETRY_BACKOFF_MAX_MS", "8000")) / 1000.0


def quota_effectively_gone(account):
    """True only when every model on the account is out of quota.

    A 429 with healthy quota is a transient throttle: benching that account for the full
    5 minutes turns a 30-second upstream blip into a multi-minute outage for the pool.
    """
    quota = getattr(account, "quota", None) or {}
    fractions = [v.get("remainingFraction") for v in quota.values()
                 if isinstance(v.get("remainingFraction"), (int, float))]
    return bool(fractions) and max(fractions) <= 0.05
API_ENDPOINT = CONFIG["api_endpoint"]
QUOTA_API = "https://daily-cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels"
OAUTH_SCOPES = CONFIG.get("oauth_scopes",
    "https://www.googleapis.com/auth/cloud-platform "
    "https://www.googleapis.com/auth/userinfo.email "
    "https://www.googleapis.com/auth/userinfo.profile "
    "https://www.googleapis.com/auth/cclog "
    "https://www.googleapis.com/auth/experimentsandconfigs openid")
# Redirect URI for Google OAuth: env var > .env > config > derive from Host header.
# Google requires redirect_uri to match Cloud Console configuration exactly.
OAUTH_REDIRECT_URI = (os.environ.get("OAUTH_REDIRECT_URI")
                      or _ENV_FILE.get("OAUTH_REDIRECT_URI")
                      or CONFIG.get("oauth_redirect_uri", ""))

# Circular buffer for dashboard logs
from collections import deque
import datetime
RECENT_LOGS = deque(maxlen=100)

# Active request tracker for dashboard indicator light
# key: request_id, value: {model, account, started, status}
ACTIVE_REQUESTS = {}
_active_lock = threading.Lock()

def track_start(rid, model, account_email):
    with _active_lock:
        ACTIVE_REQUESTS[rid] = {
            "model": model, "account": account_email,
            "started": time.time(), "status": "connecting"
        }

def track_streaming(rid):
    with _active_lock:
        if rid in ACTIVE_REQUESTS:
            ACTIVE_REQUESTS[rid]["status"] = "streaming"

def track_end(rid):
    with _active_lock:
        ACTIVE_REQUESTS.pop(rid, None)

def log_event(level, msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    RECENT_LOGS.append({"ts": ts, "level": level, "msg": msg})
    print(f"[{ts}] [{level}] {msg}")


# ─── Usage Monitor: token stats per completed request ────────────────────────
# Append-only JSONL log + in-memory daily rollups. /v1/usage always answers
# from memory; the file is scanned once at most (lazy first access).
USAGE_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage.jsonl")
USAGE_MAX_BYTES = 5 * 1024 * 1024   # rotate to usage.jsonl.1 above this
USAGE_KEEP_DAYS = 60                # longest window served

_usage_lock = threading.Lock()
_usage_days = {}                    # "YYYY-MM-DD" -> {requests, input, output, cached}
_usage_recent = deque(maxlen=50)    # raw records, oldest first
_usage_h24 = deque()                # (ts, in, out, cached) for the rolling 24h window
_usage_loaded = False


def _usage_day(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _usage_prune_locked(now):
    # Drop 24h entries and day buckets older than the longest window.
    cutoff = now - 86400
    while _usage_h24 and _usage_h24[0][0] < cutoff:
        _usage_h24.popleft()
    oldest = _usage_day(now - (USAGE_KEEP_DAYS - 1) * 86400)
    for k in [k for k in _usage_days if k < oldest]:
        del _usage_days[k]


def _usage_load_locked():
    # One-time rebuild of rollups from the JSONL file (bounded by the 5MB cap).
    global _usage_loaded
    _usage_loaded = True  # set first so a broken file is never re-read per request
    if not os.path.exists(USAGE_LOG):
        return
    now = time.time()
    try:
        with open(USAGE_LOG, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                ts = rec.get("ts", 0)
                d = _usage_days.setdefault(_usage_day(ts),
                    {"requests": 0, "input": 0, "output": 0, "cached": 0})
                d["requests"] += 1
                d["input"] += rec.get("in", 0)
                d["output"] += rec.get("out", 0)
                d["cached"] += rec.get("cached", 0)
                if now - ts <= 86400:
                    _usage_h24.append((ts, rec.get("in", 0), rec.get("out", 0), rec.get("cached", 0)))
                _usage_recent.append(rec)
        _usage_prune_locked(now)
    except Exception as e:
        print(f"  [WARN] Usage load: {e}")


def record_usage(model, input_tokens, output_tokens, cached_tokens, status, elapsed_ms):
    # Additive by design — must never break a response, so guard everything.
    try:
        now = time.time()
        rec = {"ts": round(now, 3), "model": model,
               "in": int(input_tokens or 0), "out": int(output_tokens or 0),
               "cached": int(cached_tokens or 0), "status": status,
               "ms": int(elapsed_ms or 0)}
        with _usage_lock:
            if not _usage_loaded:
                _usage_load_locked()
            d = _usage_days.setdefault(_usage_day(now),
                {"requests": 0, "input": 0, "output": 0, "cached": 0})
            d["requests"] += 1
            d["input"] += rec["in"]
            d["output"] += rec["out"]
            d["cached"] += rec["cached"]
            _usage_recent.append(rec)
            _usage_h24.append((now, rec["in"], rec["out"], rec["cached"]))
            _usage_prune_locked(now)
            with open(USAGE_LOG, "a") as f:
                f.write(json.dumps(rec) + "\n")
            if os.path.getsize(USAGE_LOG) > USAGE_MAX_BYTES:
                os.replace(USAGE_LOG, USAGE_LOG + ".1")
    except Exception as e:
        print(f"  [WARN] Usage record: {e}")


def usage_snapshot():
    # Served entirely from memory: 5 window sums + last 15 requests.
    now = time.time()
    with _usage_lock:
        if not _usage_loaded:
            _usage_load_locked()
        _usage_prune_locked(now)

        def blank():
            return {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0}

        windows = {"today": blank(), "h24": blank(), "d7": blank(), "d30": blank(), "d60": blank()}
        today = datetime.datetime.strptime(_usage_day(now), "%Y-%m-%d")
        for day, d in _usage_days.items():
            try:
                age = (today - datetime.datetime.strptime(day, "%Y-%m-%d")).days
            except Exception:
                continue
            if age < 0 or age >= USAGE_KEEP_DAYS:
                continue
            for name, span in (("today", 1), ("d7", 7), ("d30", 30), ("d60", 60)):
                if age < span:
                    w = windows[name]
                    w["requests"] += d["requests"]
                    w["input_tokens"] += d["input"]
                    w["output_tokens"] += d["output"]
                    w["cached_tokens"] += d["cached"]
        for ts, i, o, c in _usage_h24:
            w = windows["h24"]
            w["requests"] += 1
            w["input_tokens"] += i
            w["output_tokens"] += o
            w["cached_tokens"] += c
        # Filter out zero-token OK noise from recent requests if real requests exist
        raw_recent = list(_usage_recent)
        filtered_recent = [r for r in raw_recent if r.get("in", 0) > 0 or r.get("out", 0) > 0 or r.get("status") != "ok"]
        display_recent = filtered_recent[-15:] if filtered_recent else raw_recent[-15:]
        recent = [{"model": r.get("model", ""), "in": r.get("in", 0), "out": r.get("out", 0),
                   "cached": r.get("cached", 0), "status": r.get("status", ""),
                   "ts": r.get("ts", 0), "ms": r.get("ms", 0)}
                  for r in display_recent]
        recent.reverse()  # newest first
    return {"windows": windows, "recent": recent}


# ─── Security: brute-force protection & request limits ───────────────────────
_auth_failures = {}   # ip -> [fail_count, window_start, locked_until]
_auth_lock = threading.Lock()
AUTH_MAX_FAILURES = 5
AUTH_WINDOW = 900     # 15 min window
AUTH_LOCKOUT = 900    # 15 min lockout
MAX_BODY_BYTES = 25 * 1024 * 1024  # 25 MB request body cap

def _auth_allowed(ip):
    with _auth_lock:
        rec = _auth_failures.get(ip)
        if rec and rec[2] > time.time():
            return False
    return True

def _auth_fail(ip):
    with _auth_lock:
        now = time.time()
        rec = _auth_failures.get(ip)
        if not rec or now - rec[1] > AUTH_WINDOW:
            rec = [0, now, 0]
        rec[0] += 1
        if rec[0] >= AUTH_MAX_FAILURES:
            rec[2] = now + AUTH_LOCKOUT
            rec[0] = 0
            log_event("WARN", f"IP {ip} locked out {AUTH_LOCKOUT//60} min after {AUTH_MAX_FAILURES} auth failures")
        _auth_failures[ip] = rec

def _auth_success(ip):
    with _auth_lock:
        _auth_failures.pop(ip, None)


# Per-session random tokens with expiry. The old design derived ONE static
# HMAC from the dashboard password — forgeable offline, shared by every
# browser, never expired, impossible to revoke (Strix finding vuln-0001).
_SESSION_TOKENS = {}  # token -> expiry ts
SESSION_TTL = 24 * 3600


def _issue_session_token():
    tok = secrets.token_urlsafe(32)
    now = time.time()
    with _auth_lock:
        for k in [k for k, exp in _SESSION_TOKENS.items() if exp < now]:
            del _SESSION_TOKENS[k]
        _SESSION_TOKENS[tok] = now + SESSION_TTL
    return tok


def _session_token_valid(tok):
    with _auth_lock:
        exp = _SESSION_TOKENS.get(tok)
        if exp is None:
            return False
        if exp < time.time():
            del _SESSION_TOKENS[tok]
            return False
    return True


# ─── Account State ────────────────────────────────────────────────────────────

class AccountState:
    def __init__(self, cfg):
        self.email = cfg["email"]
        self.refresh_token = cfg["refresh_token"]
        self.disabled = cfg.get("disabled", False)
        self.access_token = None
        self.expires_at = 0
        self.lock = threading.Lock()
        self.request_count = 0
        self.error_count = 0
        self.last_error = None
        self.rate_limited_until = 0
        self.quota = {}  # model -> {remainingFraction, resetTime}
        self.quota_fetched_at = 0
        # Rolling window of recent request timestamps (epoch seconds) used by the soft RPM
        # guard to spread IDE bursts across the pool before Google's per-minute limit trips.
        self.recent_requests = []

    def rpm_used(self, window_sec=60.0):
        """Count requests served in the trailing window."""
        cutoff = time.time() - window_sec
        self.recent_requests = [t for t in self.recent_requests if t >= cutoff]
        return len(self.recent_requests)

    def note_request(self):
        """Record that this account just served a request."""
        self.recent_requests.append(time.time())
        if len(self.recent_requests) > 500:
            self.recent_requests = self.recent_requests[-250:]

    def get_token(self):
        with self.lock:
            now = time.time()
            if not self.access_token or now >= self.expires_at - 300:
                self._refresh()
            return self.access_token

    def _refresh(self):
        data = urllib.parse.urlencode({
            "client_id": OAUTH["client_id"],
            "client_secret": OAUTH["client_secret"],
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token"
        }).encode()
        req = urllib.request.Request(OAUTH["token_url"], data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                self.access_token = result["access_token"]
                self.expires_at = time.time() + result.get("expires_in", 3599)
                self.error_count = 0
                self.last_error = None
                print(f"  [TOKEN] Refreshed {self.email} ({result.get('expires_in',3599)}s)")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode()
            self.last_error = f"HTTP {e.code}: {err_body[:200]}"
            self.error_count += 1
            if "invalid_grant" in err_body:
                self.disabled = True
            raise
        except Exception as e:
            self.last_error = str(e)
            self.error_count += 1
            raise

    def fetch_quota(self):
        """Fetch quota info from Antigravity API."""
        try:
            token = self.get_token()
            req = urllib.request.Request(QUOTA_API,
                data=b'{}',
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    **ANTIGRAVITY_CLIENT_HEADERS,
                })
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                models = data.get("models", {})
                self.quota = {}
                for model_id, info in models.items():
                    qi = info.get("quotaInfo", {})
                    if qi:
                        self.quota[model_id] = {
                            "remainingFraction": qi.get("remainingFraction", 0),
                            "resetTime": qi.get("resetTime", ""),
                            "displayName": info.get("displayName", model_id),
                            "maxOutputTokens": info.get("maxOutputTokens", 0)
                        }
                self.quota_fetched_at = time.time()
                return True
        except Exception as e:
            print(f"  [QUOTA] Failed for {self.email}: {e}")
            return False

    def status(self):
        return {
            "email": self.email,
            "disabled": self.disabled,
            "has_token": bool(self.access_token),
            "expires_in": max(0, int(self.expires_at - time.time())),
            "requests": self.request_count,
            "errors": self.error_count,
            "last_error": self.last_error,
            "quota": self.quota,
            "quota_age": int(time.time() - self.quota_fetched_at) if self.quota_fetched_at else -1,
            "last_test": getattr(self, "last_test", None),
        }


LOAD_CODE_ASSIST_URLS = (
    "https://daily-cloudcode-pa.googleapis.com/v1internal:loadCodeAssist",
    "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist",
)


def probe_plan(acc, token):
    """Best-effort subscription tier from Google's loadCodeAssist.

    Returns {"id","name"} when the call works. The value is whatever Google reports
    (e.g. "free-tier" / "standard" / "ultra"); it is NOT an independent verification,
    so the dashboard always shows where the label came from.
    """
    last_err = None
    for url in LOAD_CODE_ASSIST_URLS:
        try:
            req = urllib.request.Request(
                url, data=b'{"metadata":{"pluginType":"GEMINI"}}',
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json",
                         **ANTIGRAVITY_CLIENT_HEADERS})
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode())
            tier = data.get("currentTier") or {}
            if isinstance(tier, dict) and (tier.get("id") or tier.get("name")):
                # allowedTiers + top-level keys are captured so the dashboard can show
                # WHAT Google actually said (tier ids only, no credentials).
                return {
                    "id": tier.get("id"),
                    "name": tier.get("name"),
                    "tier": {k: tier.get(k) for k in ("id", "name", "description") if tier.get(k)},
                    "allowed_tiers": [t.get("id") for t in (data.get("allowedTiers") or [])
                                      if isinstance(t, dict) and t.get("id")],
                    "paid_tier": ({k: v for k, v in (data.get("paidTier") or {}).items()
                                   if k in ("id", "name", "description")}
                                  if isinstance(data.get("paidTier"), dict) else data.get("paidTier")),
                    "upgrade_uri": data.get("upgradeSubscriptionUri"),
                    "keys": sorted(data.keys()),
                }
            last_err = "no currentTier in reply"
        except Exception as e:
            last_err = str(e)[:140]
    return {"id": None, "name": None, "error": last_err}


def probe_account(acc, model):
    """One real end-to-end check for ONE account: token -> plan -> generate -> quota.

    Deliberately sends an actual upstream request (16 output tokens) instead of only
    reading cached quota, because a saved token proves nothing about whether the
    account can still answer right now.
    """
    res = {"email": acc.email, "ok": False, "http": None, "latency_ms": None,
           "error": None, "plan": None, "plan_id": None, "plan_source": None,
           "quota_left": None, "reset": None, "checked_at": int(time.time())}
    t0 = time.time()
    try:
        token = acc.get_token()
    except Exception as e:
        res["error"] = f"token refresh failed: {e}"
        res["latency_ms"] = int((time.time() - t0) * 1000)
        acc.last_test = res
        return res

    plan = probe_plan(acc, token)
    if plan.get("id") or plan.get("name"):
        res["plan"] = plan.get("name") or plan.get("id")
        res["plan_id"] = plan.get("id")
        res["plan_source"] = "loadCodeAssist"
        res["plan_detail"] = plan.get("tier")
        res["allowed_tiers"] = plan.get("allowed_tiers")
        res["paid_tier"] = plan.get("paid_tier")
        res["upgrade_uri"] = plan.get("upgrade_uri")
        res["plan_keys"] = plan.get("keys")
        # Google reports CloudCode's own tier ("free-tier" for every Antigravity install);
        # the real Google AI Pro/Ultra subscription shows up in paidTier. Say which one the
        # label came from instead of pretending the two are the same thing.
        paid = plan.get("paid_tier") if isinstance(plan.get("paid_tier"), dict) else {}
        if paid.get("id") or paid.get("name"):
            res["plan"] = "Pro"          # paidTier ada -> langganan berbayar aktif
            res["plan_detail_label"] = paid.get("name") or paid.get("id")
        else:
            res["plan"] = "Free"         # tidak ada paidTier -> tier gratis
            res["plan_detail_label"] = plan.get("id") or "free-tier"
    elif plan.get("error"):
        res["plan_error"] = plan["error"]

    try:
        body = {"model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 16}
        ag_body, _ = openai_to_antigravity(body)
        ag_body["request"]["sessionId"] = resolve_client_session_id(body, acc.email)
        req = urllib.request.Request(
            API_ENDPOINT, data=json.dumps(ag_body).encode(),
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json",
                     **ANTIGRAVITY_CLIENT_HEADERS})
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", "replace")
        res["latency_ms"] = int((time.time() - t0) * 1000)
        res["http"] = 200
        res["ok"] = '"candidates"' in raw
        if not res["ok"]:
            res["error"] = "upstream replied without candidates"
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", "replace")
        res["http"] = e.code
        res["latency_ms"] = int((time.time() - t0) * 1000)
        res["error"] = f"HTTP {e.code}: {' '.join(err_body.split())[:220]}"
        if e.code == 401:
            acc.access_token = None
            acc.expires_at = 0
    except Exception as e:
        res["latency_ms"] = int((time.time() - t0) * 1000)
        res["error"] = str(e)[:220]

    acc.fetch_quota()
    if not res["plan"] and acc.quota:
        has_claude = any(k.startswith("claude-") for k in acc.quota)
        res["plan"] = "Pro/Ultra (inferred)" if has_claude else "Free (inferred)"
        res["plan_source"] = "model-catalog"
    upstream_id = MODEL_MAP.get(model, model)
    q = acc.quota.get(upstream_id) or acc.quota.get(model) or {}
    if q:
        res["quota_left"] = round(float(q.get("remainingFraction") or 0) * 100, 1)
        res["reset"] = q.get("resetTime")
    acc.last_test = res
    return res


ACCOUNT_STATES = [AccountState(a) for a in ACCOUNTS]
_round_robin_idx = 0
_sticky_account_email = None
_rr_lock = threading.Lock()


def get_next_account():
    global _round_robin_idx, _sticky_account_email
    now = time.time()
    with _rr_lock:
        available = [a for a in ACCOUNT_STATES if not a.disabled]
        if not available:
            return None
        if STRATEGY == "restrict":
            # Restrict mode: never hop accounts. Always the pinned account (or the first
            # enabled one), even while it is cooling down — the client must back off.
            if not _sticky_account_email:
                pref = CONFIG.get("active_account")
                pinned = next((a for a in available if a.email == pref), None)
                _sticky_account_email = (pinned or available[0]).email
            return next((a for a in available if a.email == _sticky_account_email), available[0])
        if STRATEGY == "sticky":
            # Use active sticky account; if rate limited or error, advance sticky pointer
            if '_sticky_account_email' not in globals() or not _sticky_account_email:
                # Check if user set active_account preference in config
                pref = CONFIG.get("active_account")
                if pref and any(a.email == pref and not a.disabled for a in available):
                    _sticky_account_email = pref
                else:
                    _sticky_account_email = available[0].email

            current_sticky = next((a for a in available if a.email == _sticky_account_email), None)
            if current_sticky and now >= current_sticky.rate_limited_until:
                # Soft RPM guard: sticky keeps prompt-cache warm, but a parallel burst from
                # the IDE would hammer ONE account into Google's per-minute limit while the
                # rest of the pool idles (observed: 45x HTTP 429 in a single minute with 84%
                # of the daily quota still intact). If the anchor is already saturated in the
                # trailing window, rotate to the next healthy account instead of 429-ing.
                if current_sticky.rpm_used() < SOFT_RPM_LIMIT:
                    current_sticky.note_request()
                    return current_sticky
                for acc in available:
                    if acc is current_sticky:
                        continue
                    if now >= acc.rate_limited_until and acc.rpm_used() < SOFT_RPM_LIMIT:
                        _sticky_account_email = acc.email
                        acc.note_request()
                        return acc
                # Whole pool is saturated: keep the anchor (client will throttle) but do
                # not pretend another account is free.
                current_sticky.note_request()
                return current_sticky

            # Fallback & migrate sticky anchor to next healthy account
            for acc in available:
                if now >= acc.rate_limited_until:
                    _sticky_account_email = acc.email
                    return acc
            return available[0]
        for _ in range(len(available)):
            idx = _round_robin_idx % len(ACCOUNT_STATES)
            _round_robin_idx += 1
            acc = ACCOUNT_STATES[idx]
            if not acc.disabled and now >= acc.rate_limited_until:
                return acc
        # All rate-limited — still return something rather than failing
        return available[0]


def get_fallback_account(exclude_email):
    """Pick an account different from the excluded one (for sticky failover)."""
    now = time.time()
    with _rr_lock:
        global _round_robin_idx
        candidates = [a for a in ACCOUNT_STATES
                      if not a.disabled and a.email != exclude_email and now >= a.rate_limited_until]
        if not candidates:
            candidates = [a for a in ACCOUNT_STATES if not a.disabled and a.email != exclude_email]
        if not candidates:
            return None
        idx = _round_robin_idx % len(candidates)
        _round_robin_idx += 1
        return candidates[idx]


def add_account_to_pool(email, refresh_token):
    global ACCOUNT_STATES
    with _rr_lock:
        for i, acc in enumerate(ACCOUNT_STATES):
            if acc.email == email:
                ACCOUNT_STATES[i] = AccountState({"email": email, "refresh_token": refresh_token})
                break
        else:
            ACCOUNT_STATES.append(AccountState({"email": email, "refresh_token": refresh_token}))
        _save_accounts()
    for acc in ACCOUNT_STATES:
        if acc.email == email:
            try: acc.get_token()
            except Exception: pass
            break


def remove_account_from_pool(email):
    global ACCOUNT_STATES
    with _rr_lock:
        before = len(ACCOUNT_STATES)
        ACCOUNT_STATES = [a for a in ACCOUNT_STATES if a.email != email]
        if len(ACCOUNT_STATES) == before:
            return False
        _save_accounts()
    return True


def _save_accounts():
    config_accounts = []
    for acc in ACCOUNT_STATES:
        config_accounts.append({
            "email": acc.email, "refresh_token": acc.refresh_token, "disabled": acc.disabled
        })
    try:
        CONFIG["accounts"] = config_accounts
        with open(CONFIG_PATH, "w") as f:
            json.dump(CONFIG, f, indent=2)
    except Exception as e:
        print(f"  [WARN] Save config: {e}")


# ─── Model Mapping ────────────────────────────────────────────────────────────

MODEL_MAP = {
    # Gemini 3.8 Series: upstream Google engine is 'gemini-3.8-flash-tiered'
    # Reasoning level (high/medium) is injected via generationConfig.thinkingConfig.thinkingLevel
    "gemini-3.8-flash-high": "gemini-3.8-flash-tiered",
    "gemini-3.8-flash-medium": "gemini-3.8-flash-tiered",

    # Gemini 4 "Hydrogen" — upstream accepts the id as-is (no mapping needed), listed here so
    # it shows up in /v1/models and therefore in client model pickers (Kilo Code, 9router).
    "gemini-4-hydrogen-sonar": "gemini-4-hydrogen-sonar",

    # Claude Series: thinking enabled natively
    "claude-sonnet-4-6-thinking": "claude-sonnet-4-6",
    "claude-opus-4-6-thinking": "claude-opus-4-6-thinking",
}

# Full upstream catalog (for dashboard "show all models" button).
# Source: Antigravity API; includes image & completion models not exposed to Hermes.
FULL_MODEL_CATALOG = [
    {"id": "gemini-3.8-flash-high", "display": "Gemini 3.8 Flash (High)", "kind": "chat"},
    {"id": "gemini-3.8-flash-medium", "display": "Gemini 3.8 Flash (Medium)", "kind": "chat"},
    {"id": "gemini-3.8-flash-tiered", "display": "Gemini 3.8 Flash (Tiered)", "kind": "chat"},
    {"id": "gemini-4-hydrogen-sonar", "display": "Gemini 4 Hydrogen (Sonar)", "kind": "chat"},
    {"id": "claude-sonnet-4-6", "display": "Claude Sonnet 4.6 (Thinking)", "kind": "chat"},
    {"id": "claude-opus-4-6-thinking", "display": "Claude Opus 4.6 (Thinking)", "kind": "chat"},
    {"id": "gemini-2.5-flash", "display": "Gemini 2.5 Flash", "kind": "chat"},
]

# ─── OpenAI → Antigravity Translation ────────────────────────────────────────

def _sanitize_fn_name(name):
    """Gemini/Antigravity function name rules (mirrors 9router):
    only [a-zA-Z0-9_.:-], first char letter/underscore, max 64 chars."""
    if not name:
        return "_unknown"
    import re
    s = re.sub(r"[^a-zA-Z0-9_.:\-]", "_", name)
    if not re.match(r"^[a-zA-Z_]", s):
        s = "_" + s
    return s[:64]


def _trim_schema_descriptions(schema, cap):
    """Recursively shorten `description` strings inside a JSON Schema.

    Tool/parameter descriptions are documentation for the model, not behaviour — the
    function name, types and required list carry the contract. Agent clients ship dozens of
    verbose schemas, which cost thousands of prompt tokens on every single request and push
    the per-account per-minute budget over the edge (Google answers 429 RESOURCE_EXHAUSTED
    even while the daily quota reads ~100%). Capping them keeps tool use working.
    """
    if not isinstance(schema, dict):
        return schema
    out = {}
    for k, v in schema.items():
        if k == "description" and isinstance(v, str) and len(v) > cap:
            cut = v[:cap]
            if " " in cut:
                cut = cut.rsplit(" ", 1)[0]
            out[k] = cut + "…"
        elif isinstance(v, dict):
            out[k] = _trim_schema_descriptions(v, cap)
        elif isinstance(v, list):
            out[k] = [_trim_schema_descriptions(i, cap) for i in v]
        else:
            out[k] = v
    return out


def _clean_schema_for_gemini(schema):
    """Recursively clean JSON Schema for Gemini/Antigravity API:
    Only allow fields supported by Google CloudCode Schema proto:
    type, format, description, nullable, enum, properties, required, items.
    Converts and strips all draft-04/07/2020 validation keys."""
    if not isinstance(schema, dict):
        return schema

    ALLOWED_KEYS = {
        "type", "format", "description", "nullable", "enum",
        "properties", "required", "items"
    }

    cleaned = {}
    for k, v in schema.items():
        if k not in ALLOWED_KEYS:
            continue
        if k == "type":
            if isinstance(v, list):
                non_null = [t for t in v if t != "null"]
                cleaned["type"] = non_null[0] if non_null else "string"
                if "null" in v:
                    cleaned["nullable"] = True
            else:
                cleaned["type"] = v
        elif k == "properties" and isinstance(v, dict):
            cleaned[k] = {pk: _clean_schema_for_gemini(pv) for pk, pv in v.items()}
        elif k == "items" and isinstance(v, dict):
            cleaned[k] = _clean_schema_for_gemini(v)
        elif isinstance(v, dict):
            cleaned[k] = _clean_schema_for_gemini(v)
        elif isinstance(v, list):
            cleaned[k] = [_clean_schema_for_gemini(item) if isinstance(item, dict) else item for item in v]
        else:
            cleaned[k] = v
    return cleaned


# Antigravity requires a thought_signature on functionCall parts for tool use.
# 9router uses this static default signature and it works (verified in its
# openai-to-gemini.js translator: DEFAULT_THINKING_AG_SIGNATURE).
DEFAULT_THOUGHT_SIGNATURE = (
    "EuwGCukGAXLI2nxwZIq54WWSoL/YN0P3TsDZ7zRnLi8g0S4aVr2HUGxvaHKySuY6HAVzcE0GPGjXrytLIldxthSvfxgUlJh6Qa9Z"
    "+Oj5QZBlYdg6HaJ6yuY5R7waE6rdwBsRf7Ft2j3DJ9rMi9qhWFqApewYtPhls3VHtuvND3l8Rm09+lbAXQs6KKWEWrxNLKTBkfpMg"
    "XhRERc/TQRMZu1twAablm6/Zk1tsYRvfWKLsNbeKF+CCojJdXJKvnR/8Ouuoa+Y2Ti20hcW7aZIIjZDFYPU//k6Ybmhg69J/imbFa"
    "i2ckhfLaisqdDkdoIiBJScTOUvYqP6AE9d4MsydSC+UlhIMk4hoP76R8vUSCZRMkjOaDXstf/QoVZKbt94wyRZgAJ1G0BqI8L5ow8"
    "6kLpA4wJEtxsRGymOE4bKUvApveBakYDNM9APkf+LbtbzWSseGjoZcSlycF9iN8Q2XNYKRrHbv3Lr5Y8JjdH/5y/6SHkNehTEZugae"
    "GnSPSyCTWto1kQgHpxdWmhkLfJGNUGLmue7Mesj4TSms4J33mRpYVhNB/J333FCqIP0hr/E7BkkjEn7yZ4X7SQlh+xKPurapsnHRwi"
    "KmtsilmEFrnTE9iQr+pMr6M29qqFNv1tr5yumbaJw8JW9sB15tNsRv+dW6BjNanbsKz7HCgKUBc8tGy+7YuhXzAfViyRefcjK7eZW0"
    "Fbyt7AbybJTKz78W8NH7ye6LAwzOebXpeZ4D43fNIt8bKh26qgduSQv/7o+pAflkuqHZ99YWgHQ8h8OkZFi3eOiSYjsjhdZ/czWOdo"
    "PI/OnqIldzMPF5YlrKBLFX8VhRKVmqgsmWf5PHGulHhMkVlS+XG2UIseGy69ARa93D78Gsa+1n1kJr7EEB7Rh+27vUMxVYLdz1yMSv"
    "E5nalTAlg/ZeG8+XQ0cHuAI3KbQpHW2Q++RdXfm5JzD5WdJZUU+Zn8t8UUn85BH4RxZLeE0qJikgSsKoYVBc6YhiMjhPgkR95ReimY4"
    "Z0xCJdRo1gjexOFeODZMpQF6Yxnoic7IrdgsFA3iePTbFnPp3IAM1fAThWhXJUn3QInUOTd5o1qmTmn6REbL15g/JQNl+dqUoPkhle"
    "eb2V3kjqp1okmO3wMZbPknR3S1LZNmlS72/iBQUm+n2b/RCn4PjmM2"
)


def _compress_rtk(text):
    """RTK: Trim noisy terminal and build output to preserve input tokens."""
    if not text or not isinstance(text, str) or len(text) < 300:
        return text
    lines = text.splitlines()
    if len(lines) <= 25:
        return text
    # Keep header context and recent execution tail, compress verbose middle
    head = lines[:10]
    tail = lines[-10:]
    omitted = len(lines) - 20
    return "\n".join(head) + f"\n\n[... RTK: {omitted} lines of noisy build/shell output truncated ...]\n\n" + "\n".join(tail)


def _flatten_old_history(messages, keep_recent, transcript_budget):
    """Collapse the older half of a long conversation into ONE transcript message.

    Why this exists: the previous ring guard solved Google's message-count limit by DELETING
    the middle of the conversation, which destroyed continuity and made the model hallucinate
    ("halu"). Deleting was never necessary — Google's abuse detector reacts to MESSAGE COUNT
    (a ~850-message burst earned a 403 TOS_VIOLATION) while the context window itself is large.
    Flattening keeps every word of the old turns but presents them as a transcript, so the
    count drops to a handful while the meaning survives.

    The transcript is capped by character budget; when it overflows, the OLDEST lines are
    shortened first so the most recent context stays verbatim.
    """
    system_msgs = [m for m in messages if m.get("role") == "system"]
    convo = [m for m in messages if m.get("role") != "system"]
    if len(convo) <= keep_recent:
        return messages

    old, recent = convo[:-keep_recent], convo[-keep_recent:]
    # Drop ONLY orphaned tool results at the window boundary: a functionResponse whose
    # functionCall landed in the transcript cannot be sent to Gemini (400).
    # DO NOT strip until a "user" turn. An agent session (Kilo Code) has no user turn in its
    # tail — it is assistant/tool pairs only — so the old loop
    #     while recent and recent[0] != "user": recent = recent[1:]
    # deleted the ENTIRE window (observed: 475 msgs -> 3), leaving the model with a summary
    # and no idea what it just did. That is what caused the endless "thinking through how to
    # approach this" loop.
    while recent and recent[0].get("role") == "tool":
        recent = recent[1:]
    # Hard floor: never hand the model an empty tail. If the boundary strip emptied the
    # window, fall back to the newest few turns unconditionally.
    if len(recent) < 4:
        recent = convo[-min(len(convo), 8):]

    lines = []
    for m in old:
        role = m.get("role", "user")
        content = m.get("content")
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content
                               if isinstance(p, dict) and p.get("text"))
        if not isinstance(content, str):
            content = ""
        if m.get("tool_calls"):
            names = ", ".join((tc.get("function") or {}).get("name", "?") for tc in m["tool_calls"])
            content += f"\n[panggil tool: {names}]"
        content = " ".join(content.split())
        if not content:
            continue
        label = {"user": "PENGGUNA", "assistant": "ASISTEN"}.get(role, role.upper())
        lines.append(f"[{label}] {content}")

    if not lines:
        return messages

    header = ("=== RIWAYAT PERCAKAPAN SEBELUMNYA (transkrip ringkas) ===\n"
              "Semua langkah di bawah SUDAH SELESAI dijalankan. JANGAN mengulanginya, "
              "jangan merencanakan ulang dari awal. Lanjutkan tepat dari langkah terakhir.")
    footer = ("=== AKHIR RIWAYAT ===\n"
              "Semua langkah di atas SUDAH dijalankan. Lanjutkan tugas sampai selesai: "
              "langsung panggil tool yang diperlukan, JANGAN minta izin ke pengguna, "
              "JANGAN mengulang langkah yang sudah ada di transkrip.")

    # Budget trim: shorten the oldest lines first, keep the newest ones intact.
    body_len = sum(len(x) + 2 for x in lines)
    if body_len > transcript_budget:
        per_line = max(160, transcript_budget // max(1, len(lines)))
        trimmed = []
        for line in lines:
            if len(line) > per_line:
                trimmed.append(line[:per_line].rsplit(" ", 1)[0] + " [...]")
            else:
                trimmed.append(line)
        lines = trimmed

    transcript = header + "\n\n".join(lines) + "\n" + footer
    # No synthetic assistant bridge: a fake model turn between the transcript and the live
    # tail pushes the model into answering conversationally ("mau saya lanjutkan?") instead
    # of calling the next tool. Keep the message list as transcript(user) + real tail.
    out = system_msgs + [
        {"role": "user", "content": transcript, "_proxy_transcript": True},
    ] + recent
    print(f"[CTX] flatten: {len(messages)} -> {len(out)} msgs "
          f"({len(old)} pesan lama jadi 1 transkrip {len(transcript)} chars, isi dipertahankan)")
    return out


def openai_to_antigravity(body, request_headers=None):
    messages = body.get("messages", [])
    # Flatten BEFORE any destructive guard so long sessions lose message COUNT, not content.
    # Context guards stay, but they must not fire during ordinary agent work. The old
    # thresholds (flatten at 300, ring guard at 700) sanitised healthy Kilo Code sessions;
    # these defaults only step in when the message count approaches the range that Google's
    # abuse filter flagged (~850 messages = 403 TOS_VIOLATION).
    flatten_above = int(os.environ.get("AG_FLATTEN_ABOVE", "600"))
    flatten_keep = int(os.environ.get("AG_FLATTEN_KEEP_RECENT", "300"))
    flatten_budget = int(os.environ.get("AG_FLATTEN_BUDGET_CHARS", "150000"))
    if len(messages) > flatten_above:
        messages = _flatten_old_history(messages, flatten_keep, flatten_budget)
    # Context safety ring: Google's CloudCode abuse detector suspends whole accounts
    # when a single sticky account receives very large conversation bursts (msgs 1000+).
    # Keep system prompt + first user turn + the newest window, and align the window to
    # a clean user turn so no functionCall/functionResponse pair is left dangling.
    max_msgs = int(os.environ.get("AG_MAX_MESSAGES", "800"))
    keep_recent = int(os.environ.get("AG_KEEP_RECENT_MESSAGES", "500"))
    if len(messages) > max_msgs:
        original_len = len(messages)
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]
        head = non_system[:1] if non_system and non_system[0].get("role") == "user" else []
        tail = non_system[-keep_recent:]
        # Same trap as the flatten guard: stripping until a "user" turn empties the window in
        # agent sessions (assistant/tool tail only). Drop orphan tool results only, keep a floor.
        while tail and tail[0].get("role") == "tool":
            tail = tail[1:]
        if len(tail) < 8:
            tail = non_system[-min(len(non_system), 16):]
        messages = system_msgs + head + tail
        print(f"[CTX] ring guard: {original_len} -> {len(messages)} msgs "
              f"(dropped {original_len - len(messages)} from the middle)")

    # Volume guard: message count is a poor proxy for token volume. The newest 200 messages
    # of an agent session can still be hundreds of thousands of characters, which burns the
    # per-minute token budget in a single shot and comes back as 429 on every account while
    # the daily quota still reads ~100%. Keep the newest messages that fit the budget.
    max_chars = int(os.environ.get("AG_MAX_PROMPT_CHARS", "420000"))
    # Cap a single message before accumulating: one giant tool result (a whole file dump) used
    # to force the window down to two messages, throwing away the entire conversation. Keep the
    # message but trim its payload head+tail, the way _compress_rtk does for shell output.
    max_msg_chars = int(os.environ.get("AG_MAX_MESSAGE_CHARS", "40000"))

    # Vision support: dropping every image made the proxy blind for screenshot sessions.
    # Keep the newest screenshots (re-encoded small enough to fit the guards) and replace
    # only the older ones with a placeholder.
    img_keep = int(os.environ.get("AG_IMG_KEEP", "2"))
    img_max_px = int(os.environ.get("AG_IMG_MAX_PX", "1024"))
    img_quality = int(os.environ.get("AG_IMG_QUALITY", "70"))
    img_max_chars = int(os.environ.get("AG_IMG_MAX_CHARS", "200000"))

    def _reencode_image_url(url):
        """Downscale a base64 data: URL so the picture still reaches Gemini.

        A phone screenshot is 150-400 KB of PNG; base64 makes that 200-550k chars, so every
        image message tripped the per-message cap and every picture was thrown away. Re-encoding
        to a 1024px JPEG keeps it readable at a fraction of the payload. Returns None when it
        is still too big to send.
        """
        try:
            import base64 as _b64, io as _io
            if not isinstance(url, str) or not url.startswith("data:"):
                return None
            _, payload = url.split(",", 1)
            raw = _b64.b64decode(payload)
            if len(payload) <= img_max_chars and len(raw) <= 1_200_000:
                return url  # already cheap enough, keep the original bytes untouched
            from PIL import Image
            img = Image.open(_io.BytesIO(raw))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            # Shrink progressively: one pass is not enough for heavy screenshots, and giving up
            # silently is how vision used to disappear completely.
            best = None
            for px in (img_max_px, int(img_max_px * 0.75), int(img_max_px * 0.55)):
                for q in (img_quality, max(35, img_quality - 15), max(25, img_quality - 30)):
                    cand = img.copy()
                    cand.thumbnail((px, px))
                    buf = _io.BytesIO()
                    cand.save(buf, format="JPEG", quality=q, optimize=True)
                    out = _b64.b64encode(buf.getvalue()).decode()
                    if len(out) <= img_max_chars:
                        print(f"[CTX] image re-encoded: {len(payload)} -> {len(out)} b64 chars "
                              f"({cand.size[0]}x{cand.size[1]} jpeg q{q})")
                        return "data:image/jpeg;base64," + out
                    best = len(out)
            print(f"[CTX] image too heavy even after re-encode ({best} > {img_max_chars} chars)")
            return None
        except Exception as e:
            print(f"[CTX] image re-encode failed ({e}); image dropped")
            return None

    def _part_image_url(part):
        if part.get("type") == "image_url":
            return (part.get("image_url") or {}).get("url", "")
        return part.get("data") or (part.get("image_url") or {}).get("url", "")

    def _is_image_part(part):
        return isinstance(part, dict) and part.get("type") in ("image_url", "input_image", "image")

    # Flag the newest image-bearing messages BEFORE the guards run, so their picture survives.
    kept_images = 0
    for idx in range(len(messages) - 1, -1, -1):
        if kept_images >= img_keep:
            break
        msg = messages[idx]
        content = msg.get("content")
        if not isinstance(content, list) or not any(_is_image_part(p) for p in content):
            continue
        new_parts = []
        kept_here = False
        for part in content:
            if _is_image_part(part):
                fixed = _reencode_image_url(_part_image_url(part))
                if fixed:
                    kept_here = True
                    # Normalise to image_url: the translator only emits inlineData for that type.
                    new_parts.append({"type": "image_url", "image_url": {"url": fixed}})
                else:
                    new_parts.append({"type": "text",
                                      "text": "[gambar dihapus proxy: terlalu besar untuk dikirim]"})
            else:
                new_parts.append(part)
        if kept_here:
            messages[idx] = {**msg, "content": new_parts, "_proxy_vision": True}
            kept_images += 1

    def _shrink_text(value, cap):
        if not isinstance(value, str) or len(value) <= cap:
            return value
        head = int(cap * 0.6)
        tail = max(0, cap - head)
        return (value[:head]
                + f"\n\n[... dipangkas proxy: {len(value) - cap} karakter dari pesan ini ...]\n\n"
                + (value[-tail:] if tail else ""))

    def _shrink_parts(parts, cap, keep_vision=False):
        """Trim a multimodal content list: keep text (shrunk), drop heavy media payloads.

        An image part carries megabytes of base64 and cannot be shrunk usefully, so it becomes
        a short placeholder. Dropping them is what keeps a screenshot-heavy session sendable.
        The newest screenshots are flagged `_proxy_vision` and pass through untouched.
        """
        out = []
        budget = cap
        for part in parts:
            if not isinstance(part, dict):
                out.append(part)
                continue
            kind = part.get("type")
            if kind in ("text", "input_text") or "text" in part:
                text = _shrink_text(part.get("text"), max(200, budget))
                budget = max(200, budget - len(text or ""))
                out.append({**part, "text": text})
            elif kind in ("image_url", "input_image", "image"):
                if keep_vision and part.get("image_url"):
                    out.append(part)
                    continue
                out.append({"type": "text",
                            "text": "[gambar dilampirkan — dihapus proxy agar muat kuota]"})
            else:
                blob = json.dumps(part, default=str)
                out.append(part if len(blob) <= 2000 else
                           {"type": "text", "text": "[lampiran besar dihapus proxy]"})
        return out

    def _shrink_message(msg, keep_vision=False):
        """Trim oversized text, multimodal parts and tool-call arguments on a copy."""
        shrunk = dict(msg)
        content = shrunk.get("content")
        if isinstance(content, list):
            shrunk["content"] = _shrink_parts(content, max_msg_chars, keep_vision)
        else:
            shrunk["content"] = _shrink_text(content, max_msg_chars)
        if isinstance(shrunk.get("tool_calls"), list):
            calls = []
            for call in shrunk["tool_calls"]:
                call = dict(call)
                fn = dict(call.get("function") or {})
                fn["arguments"] = _shrink_text(fn.get("arguments"), max_msg_chars)
                call["function"] = fn
                calls.append(call)
            shrunk["tool_calls"] = calls
        return shrunk

    def _msg_chars(msgs):
        # Measure the WHOLE message, not just `content`: an agent session carries most of its
        # weight in tool_calls arguments and tool results, which are invisible when only the
        # text field is counted. Those requests slip past a content-only guard and then blow
        # the upstream per-minute token budget (429 on every account, quota still ~100%).
        total = 0
        for m in msgs:
            try:
                total += len(json.dumps(m, ensure_ascii=False, default=str))
            except Exception:
                total += len(str(m))
        return total

    if max_msg_chars > 0:
        # The flattened transcript is deliberately large: it is the compressed memory of the
        # whole session. Shrinking it would delete the very context the flatten step saved.
        oversized = [m for m in messages
                     if not m.get("_proxy_transcript") and _msg_chars([m]) > max_msg_chars]
        if oversized:
            messages = [_shrink_message(m, keep_vision=bool(m.get("_proxy_vision")))
                        if _msg_chars([m]) > max_msg_chars else m for m in messages]
            print(f"[CTX] message guard: {len(oversized)} pesan besar dipangkas ke <= {max_msg_chars} chars")

    if max_chars > 0 and _msg_chars(messages) > max_chars:
        original_chars = _msg_chars(messages)
        volume_system = [m for m in messages if m.get("role") == "system"]
        volume_rest = [m for m in messages if m.get("role") != "system"]
        volume_head = volume_rest[:1] if volume_rest and volume_rest[0].get("role") == "user" else []
        kept_reversed = []
        # The flattened transcript is prioritised: it carries the compressed memory of the
        # whole session, so it is counted first and never evicted by the newest-messages loop.
        volume_transcript = [m for m in volume_rest if m.get("_proxy_transcript")]
        volume_rest = [m for m in volume_rest if not m.get("_proxy_transcript")]
        used = _msg_chars(volume_system + volume_head + volume_transcript)
        for msg in reversed(volume_rest[len(volume_head):]):
            size = _msg_chars([msg])
            if used + size > max_chars and kept_reversed:
                break
            kept_reversed.append(msg)
            used += size
        kept = list(reversed(kept_reversed))
        # Gemini requires the conversation to start with a user turn. Stripping leading
        # tool/assistant messages is correct, but doing it unconditionally with
        # `kept = kept[1:]` can empty the whole history (observed: 114 msgs -> 2 msgs),
        # which silently destroys all context and makes the model answer as if blind.
        # Keep the real messages and only prepend a synthetic user turn when needed.
        if kept and kept[0].get("role") != "user":
            messages = volume_system + volume_head + volume_transcript + [
                {"role": "user", "parts": [{"text": "[lanjutan percakapan sebelumnya]"}]}
            ] + kept
        else:
            messages = volume_system + volume_head + volume_transcript + kept
        print(f"[CTX] volume guard: {original_chars} -> {_msg_chars(messages)} chars "
              f"({len(messages)} msgs, budget {max_chars})")
    model = body.get("model", "gemini-3-flash")
    stream = body.get("stream", False)
    max_tokens = body.get("max_tokens") or 8192
    temperature = body.get("temperature")
    top_p = body.get("top_p")
    # Strip provider prefix (e.g. "ag2/gemini-3-flash" → "gemini-3-flash")
    bare_model = model.split("/", 1)[1] if "/" in model and model.split("/", 1)[0] not in MODEL_MAP else model
    # Per-model max output limits (Antigravity rejects values above these)
    MODEL_MAX_TOKENS = {"claude-sonnet-4-6-thinking": 64000, "claude-opus-4-6-thinking": 64000}
    if bare_model in MODEL_MAX_TOKENS and max_tokens > MODEL_MAX_TOKENS[bare_model]:
        max_tokens = MODEL_MAX_TOKENS[bare_model]
    ag_model = MODEL_MAP.get(bare_model, bare_model)

    # Build tool_call_id -> sanitized function name map (Gemini requires
    # functionResponse.name to match the original functionCall name)
    tool_id_to_name = {}
    for msg in messages:
        for tc in msg.get("tool_calls") or []:
            tc_id = tc.get("id")
            fn_name = (tc.get("function") or {}).get("name")
            if tc_id and fn_name:
                tool_id_to_name[tc_id] = _sanitize_fn_name(fn_name)

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
            if OPTIMIZERS.get("rtk"):
                content_str = _compress_rtk(content_str)
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
                elif p.get("type") == "input_audio":
                    # OpenAI audio part -> Gemini inlineData. Only runs when
                    # the request actually carries audio; plain chat is untouched.
                    audio = p.get("input_audio") or {}
                    data = audio.get("data")
                    if data:
                        fmt = (audio.get("format") or "wav").lower()
                        mime = {"wav": "audio/wav", "mp3": "audio/mp3", "m4a": "audio/mp4",
                                "flac": "audio/flac", "ogg": "audio/ogg", "aac": "audio/aac"}.get(fmt, f"audio/{fmt}")
                        parts.append({"inlineData": {"mimeType": mime, "data": data}})
                elif p.get("type") == "audio_url":
                    # Alternate style: base64 data URL
                    url = (p.get("audio_url") or {}).get("url", "")
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
                parts.append({"thoughtSignature": DEFAULT_THOUGHT_SIGNATURE,
                    "functionCall": {
                    "id": tc_id or None,
                    "name": tool_id_to_name.get(tc_id, _sanitize_fn_name(fn.get("name", ""))),
                    "args": args}})
        if parts:
            contents.append({"role": ag_role, "parts": parts})
    # Per-request optimizer overrides (via body parameters or HTTP headers)
    # Allows learning sessions / detail analyses to force Caveman OFF even if globally ON
    opts = dict(OPTIMIZERS)
    if isinstance(body.get("optimizers"), dict):
        opts.update(body["optimizers"])
    if request_headers:
        if request_headers.get("X-Optimizer-Caveman") == "false" or request_headers.get("x-optimizer-caveman") == "false":
            opts["caveman"] = False
        elif request_headers.get("X-Optimizer-Caveman") == "true" or request_headers.get("x-optimizer-caveman") == "true":
            opts["caveman"] = True

    # Gemini requires strict user/model alternation — merge adjacent same-role entries
    # Optimizer directive injections (Caveman & Ponytail)
    injected_instructions = []
    if opts.get("caveman"):
        injected_instructions.append(
            "[OPTIMIZER: CAVEMAN MODE ACTIVE]\n"
            "Be extremely direct and succinct. Omit polite pleasantries, filler phrases, and repetitive conversational fluff. "
            "Get straight to the answer or technical solution."
        )
    if opts.get("ponytail"):
        injected_instructions.append(
            "[OPTIMIZER: PONYTAIL MODE ACTIVE]\n"
            "When modifying code, write minimal targeted diffs or surgical snippets instead of rewriting entire files. "
            "Never reproduce unchanged lines or redundant boilerplate."
        )

    if injected_instructions:
        opt_prompt = "\n\n".join(injected_instructions)
        if system_instruction:
            system_instruction["parts"][0]["text"] += "\n\n" + opt_prompt
        else:
            system_instruction = {"parts": [{"text": opt_prompt}]}

    merged = []
    for c in contents:
        if merged and merged[-1]["role"] == c["role"]:
            merged[-1]["parts"].extend(c["parts"])
        else:
            merged.append({"role": c["role"], "parts": list(c["parts"])})

    # Guard 1: Ensure initial turn is 'user'
    # If history begins with a model turn (e.g. after client compacts/slices history),
    # Google rejects requests where a model turn containing functionCall is the first turn with:
    # "Please ensure that function call turn comes immediately after a user turn or after a function response turn."
    if merged and merged[0]["role"] != "user":
        merged.insert(0, {"role": "user", "parts": [{"text": "..."}]})

    # Guard 2: Google Antigravity rejects requests ending with role: "model"
    while merged and merged[-1]["role"] == "model":
        merged.pop()
    if not merged:
        merged.append({"role": "user", "parts": [{"text": "Continue"}]})

    contents = merged
    gen_config = {"maxOutputTokens": max_tokens}
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
        # AG_THINKING_GUARD=0 (default since 19 Nov 2026) restores the pre-16-Nov behaviour:
        # no thinkingBudget cap, the model decides how long to think. That cap only ever
        # became live on 16 Nov (commit 67160fe moved it out of the unused
        # core/translator.py into server.py, so before that it never took effect).
        # Set AG_THINKING_GUARD=1 to cap thinking again.
        thinking_guard = os.environ.get("AG_THINKING_GUARD", "0") != "0"
        budget_map = {"low": 1024, "medium": 8192, "high": 24576}
        budget = budget_map.get(reasoning_effort, 8192)
        if ag_model and "tiered" in str(ag_model):
            gen_config["thinkingConfig"] = {
                "thinkingLevel": reasoning_effort,
                "includeThoughts": True
            }
        elif thinking_guard:
            gen_config["thinkingConfig"] = {
                "thinkingBudget": budget,
                "includeThoughts": True
            }
        else:
            # Uncapped: no thinkingBudget sent, thoughts still returned to the client.
            gen_config["thinkingConfig"] = {"includeThoughts": True}
        # Thinking still consumes maxOutputTokens, so the ceiling has to leave room for
        # BOTH. Guarded mode reserves the capped budget; uncapped mode reserves 32k of
        # thinking room, and the client's own max_tokens stays available for the answer.
        _want = max(max_tokens + budget, budget + 4096) if thinking_guard else (max_tokens + 32768)
        _capped = min(_want, 64000)
        if _capped > gen_config["maxOutputTokens"]:
            gen_config["maxOutputTokens"] = _capped
    tools = []
    # Tool schemas are a fixed token tax on EVERY request. An agent client like Hermes ships
    # 34 functions (~71 KB, ~18k tokens) before a single word of conversation, which competes
    # with history for the per-account per-minute budget. Trimming the prose out of
    # descriptions keeps function calling intact (name + params still fully present) while
    # removing the bulk. Disable with AG_TOOL_DESC_CHARS=0.
    tool_desc_cap = int(os.environ.get("AG_TOOL_DESC_CHARS", "600"))
    for tool in body.get("tools", []):
        if tool.get("type") == "function":
            fn = tool.get("function", {})
            raw_params = fn.get("parameters", {"type": "object", "properties": {}})
            cleaned_params = _clean_schema_for_gemini(raw_params)
            if tool_desc_cap > 0:
                cleaned_params = _trim_schema_descriptions(cleaned_params, tool_desc_cap)
            desc = fn.get("description", "") or ""
            if tool_desc_cap > 0 and len(desc) > tool_desc_cap:
                desc = desc[:tool_desc_cap].rsplit(" ", 1)[0] + "…"
            tools.append({"functionDeclarations": [{
                "name": _sanitize_fn_name(fn.get("name", "")),
                "description": desc,
                "parameters": cleaned_params}]})
    # The Antigravity backend answers 429 RESOURCE_EXHAUSTED when a large prompt arrives in
    # the dedicated `systemInstruction` field, even though the daily quota still reads ~100%
    # and the identical text passes when sent as an ordinary conversation turn. Verified by
    # isolating each field: systemInstruction+thinking => 429, systemInstruction+sessionId =>
    # 429, thinking+sessionId => 200. Folding the system prompt into a leading user/model pair
    # keeps the same semantics and gets a 200. Set AG_SYS_AS_TURN=0 to restore the old shape.
    sys_as_turn = os.environ.get("AG_SYS_AS_TURN", "1") != "0"
    ag_request = {"model": ag_model, "userAgent": "antigravity",
        "request": {"contents": contents, "generationConfig": gen_config}}
    if system_instruction:
        if sys_as_turn and system_instruction.get("parts"):
            sys_text = "".join(p.get("text", "") for p in system_instruction["parts"])
            if sys_text.strip():
                contents.insert(0, {"role": "user", "parts": [{"text": sys_text}]})
                contents.insert(1, {"role": "model", "parts": [{"text": "Understood."}]})
        else:
            ag_request["request"]["systemInstruction"] = system_instruction
    if tools: ag_request["request"]["tools"] = tools
    return ag_request, stream


def antigravity_to_openai(ag_response, model_name, request_id):
    candidates = ag_response.get("response", {}).get("candidates", [])
    usage = ag_response.get("response", {}).get("usageMetadata", {})
    content = ""
    reasoning_content = ""
    tool_calls = []
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        for part in parts:
            if part.get("thought") is True and part.get("text"):
                reasoning_content += part["text"]
            elif part.get("text"):
                content += part["text"]
            elif part.get("functionCall"):
                fc = part["functionCall"]
                tool_calls.append({"id": fc.get("id", f"call_{fc.get('name','')}"),
                    "type": "function", "function": {
                        "name": fc.get("name", ""),
                        "arguments": json.dumps(fc.get("args", {}))}})
    message = {"role": "assistant"}
    if content: message["content"] = content
    if reasoning_content: message["reasoning_content"] = reasoning_content
    if tool_calls: message["tool_calls"] = tool_calls
    if not content and not tool_calls: message["content"] = ""
    # OpenAI contract: a turn that ends in function calls reports finish_reason "tool_calls".
    # Agent clients (Kilo Code, Cline, Roo) key off this to dispatch the tool; sending "stop"
    # makes them think the turn produced no action, so they re-send the same prompt forever —
    # the visible symptom is an endless "I'm thinking through how to approach this".
    if tool_calls:
        openai_finish = "tool_calls"
    elif not content:
        # Empty turn is never a legitimate "stop": either the budget ran out while the model
        # was thinking, or the candidate was truncated. Report "length" so the client retries
        # with more room instead of re-sending the identical prompt (silent loop).
        openai_finish = "length"
    else:
        openai_finish = "stop"
    return {"id": request_id, "object": "chat.completion", "created": int(time.time()),
        "model": model_name,
        "choices": [{"index": 0, "message": message, "finish_reason": openai_finish}],
        "usage": {"prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
            "reasoning_tokens": usage.get("thoughtsTokenCount", 0),
            "prompt_tokens_details": {
                "cached_tokens": usage.get("cachedContentTokenCount", 0)
            }}}


def antigravity_chunk_to_openai(chunk_data, model_name, request_id, state):
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
    delta = {}
    content = ""
    reasoning = ""
    tool_calls = []
    for part in parts:
        # A part is ONLY internal reasoning when the explicit `thought` flag is true.
        # `thoughtSignature` is just an opaque checksum Google attaches to REAL answer
        # parts — treating it as a thought marker silently routes the actual response
        # into reasoning_content and leaves `content` empty.
        if part.get("thought") is True:
            reasoning += part.get("text") or ""
        elif part.get("text"):
            content += part["text"]
        elif part.get("functionCall"):
            fc = part["functionCall"]
            tool_calls.append({"index": len(state.get("tool_calls", [])),
                "id": fc.get("id", f"call_{fc.get('name','')}"), "type": "function",
                "function": {"name": fc.get("name", ""),
                    "arguments": json.dumps(fc.get("args", {}))}})
    if reasoning: delta["reasoning_content"] = reasoning
    if content: delta["content"] = content
    if reasoning or content:
        # Track whether the turn produced anything the client can use. A reasoning-only turn
        # (thinking models such as gemini-4-hydrogen-sonar exhaust max_tokens while thinking)
        # arrives as an empty "stop" and agent clients just re-send the prompt — a silent loop.
        state["content_chars"] = state.get("content_chars", 0) + len(content)
        state["reasoning_chars"] = state.get("reasoning_chars", 0) + len(reasoning)
    if tool_calls:
        delta["tool_calls"] = tool_calls
        state.setdefault("tool_calls", []).extend(tool_calls)
    openai_finish = None
    if finish_reason:
        finish_map = {"STOP": "stop", "MAX_TOKENS": "length", "SAFETY": "content_filter", "RECITATION": "content_filter"}
        openai_finish = finish_map.get(finish_reason, "stop")
        # Same contract as the non-stream path: tool calls must end the turn as "tool_calls",
        # otherwise agent clients keep re-sending the same prompt (the loop).
        if state.get("tool_calls") and openai_finish == "stop":
            openai_finish = "tool_calls"
    if not delta and not openai_finish: return None
    chunk = {"id": request_id, "object": "chat.completion.chunk", "created": int(time.time()),
        "model": model_name,
        "choices": [{"index": 0, "delta": delta, "finish_reason": openai_finish}]}
    if usage:
        chunk["usage"] = {"prompt_tokens": usage.get("promptCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
            "reasoning_tokens": usage.get("thoughtsTokenCount", 0)}
    return chunk


# ─── Request Handler ──────────────────────────────────────────────────────────

class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress default logging

    def _client_ip(self):
        # Trust X-Forwarded-For only if behind a known proxy; otherwise peer IP
        return self.client_address[0] if self.client_address else "unknown"

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")

    def _send_json(self, code, data, account_email=None, set_cookie=None, extra_headers=None):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        if account_email:
            self.send_header("X-Account-Used", account_email)
        for header_name, header_value in (extra_headers or {}).items():
            self.send_header(header_name, str(header_value))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self, max_bytes=None):
        """Read request body with size cap (DoS protection)."""
        try:
            cl = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            return None, "Invalid Content-Length"
        limit = max_bytes or MAX_BODY_BYTES
        if cl < 0 or cl > limit:
            return None, f"Request body too large (max {limit // (1024*1024)}MB)"
        if cl == 0:
            return b"", None
        return self.rfile.read(cl), None

    def _bearer_ok(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
            now = time.time()
            for k in API_KEYS:
                if secrets.compare_digest(token, k["key"]):
                    exp = k.get("expires_at")
                    if exp is not None and exp > 0 and now > exp:
                        log_event("WARN", f"Rejected expired API key: {k.get('name', k['id'])}")
                        return False
                    return True
        return False

    def _cookie_session_ok(self):
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("ag_session="):
                if _session_token_valid(part[11:]):
                    return True
        return False

    def _basic_auth_ok(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Basic "):
            return False
        import base64
        try:
            decoded = base64.b64decode(auth[6:]).decode()
        except Exception:
            return False
        expected = f"{DASHBOARD_USER}:{DASHBOARD_PASSWORD}"
        return secrets.compare_digest(decoded, expected)

    def _check_auth(self):
        """API auth: Bearer API key, or dashboard session cookie (browser)."""
        ip = self._client_ip()
        if not _auth_allowed(ip):
            self._send_json(429, {"error": {"message": "Too many failed attempts. Try again later."}})
            return False
        if self._cookie_session_ok() or self._bearer_ok():
            return True
        # Missing or expired session cookie on API call should return 401, NOT count as a password brute-force failure
        self._send_json(401, {"error": {"message": "Invalid or missing credentials"}})
        return False

    def _check_dashboard_auth(self):
        """Dashboard auth: session cookie or Basic Auth (sets cookie on success)."""
        if not DASHBOARD_PASSWORD:
            return True
        ip = self._client_ip()
        if not _auth_allowed(ip):
            self.send_response(429)
            self.send_header("Content-Type", "text/plain")
            self._security_headers()
            self.end_headers()
            self.wfile.write(b"Too many failed attempts. Try again later.")
            return False
        if self._cookie_session_ok():
            return True
        if self._basic_auth_ok():
            _auth_success(ip)
            return True
        
        # Serve modern dark login UI instead of browser popup
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._security_headers()
        self.end_headers()
        login_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "login.html")
        if os.path.exists(login_path):
            with open(login_path, "rb") as lf:
                self.wfile.write(lf.read())
        else:
            self.wfile.write(b"<h1>Please login</h1>")
        return False

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ok": True})
            return

        # Dashboard routes (password protected)
        if self.path == "/" or self.path == "/index.html" or self.path.startswith("/auth/"):
            if not self._check_dashboard_auth():
                return

        if self.path == "/" or self.path == "/index.html":
            self._serve_dashboard()
            return

        if self.path == "/login" or self.path == "/login.html":
            login_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "login.html")
            if os.path.exists(login_path):
                with open(login_path, "rb") as lf:
                    content = lf.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self._security_headers()
                self.end_headers()
                self.wfile.write(content)
                return

        if self.path == "/auth/login":
            self._oauth_login()
            return

        if self.path.startswith("/auth/callback"):
            self._oauth_callback()
            return

        if self.path == "/v1/models":
            if not self._check_auth(): return
            models = [{"id": n, "object": "model", "created": 1700000000, "owned_by": "antigravity"} for n in MODEL_MAP]
            self._send_json(200, {"object": "list", "data": models})
            return

        if self.path == "/v1/accounts":
            if not self._check_auth(): return
            active_acc = _sticky_account_email if STRATEGY == "sticky" else (ACCOUNT_STATES[_round_robin_idx % len(ACCOUNT_STATES)].email if ACCOUNT_STATES else None)
            self._send_json(200, {
                "accounts": [a.status() for a in ACCOUNT_STATES],
                "strategy": STRATEGY,
                "active_account": active_acc or CONFIG.get("active_account"),
                "optimizers": OPTIMIZERS
            })
            return

        if self.path == "/v1/quota":
            if not self._check_auth(): return
            # Force refresh quota for all accounts
            for acc in ACCOUNT_STATES:
                if not acc.disabled:
                    acc.fetch_quota()
            self._send_json(200, {"accounts": [a.status() for a in ACCOUNT_STATES]})
            return

        if self.path == "/v1/logs":
            if not self._check_auth(): return
            self._send_json(200, {"logs": list(RECENT_LOGS)})
            return

        if self.path == "/v1/all-models":
            if not self._check_auth(): return
            self._send_json(200, {"models": FULL_MODEL_CATALOG})
            return

        if self.path == "/v1/api-keys":
            if not self._check_auth(): return
            self._send_json(200, {"api_keys": API_KEYS})
            return

        if self.path == "/v1/api-key":
            if not self._check_auth(): return
            primary_key = API_KEYS[0]["key"] if API_KEYS else ""
            self._send_json(200, {"api_key": primary_key, "api_keys": API_KEYS})
            return

        if self.path == "/v1/active":
            if not self._check_auth(): return
            with _active_lock:
                active = [
                    {"model": r["model"], "account": r["account"],
                     "status": r["status"], "elapsed": round(time.time() - r["started"], 1)}
                    for r in ACTIVE_REQUESTS.values()
                ]
            self._send_json(200, {"active": active})
            return

        if self.path == "/v1/usage":
            if not self._check_auth(): return
            self._send_json(200, usage_snapshot())
            return

        self._send_json(404, {"error": {"message": "Not found"}})

    def do_PUT(self):
        """PUT /v1/strategy or /v1/accounts/active — switch strategy or set starting account."""
        global STRATEGY, _sticky_account_email, _round_robin_idx
        if not self._check_auth(): return
        if self.path == "/v1/optimizers/toggle" or self.path == "/api/optimizers/toggle":
            # Handled via PUT
            pass

        if self.path == "/v1/accounts/active":
            body_raw, err = self._read_body(4096)
            if err or body_raw is None:
                self._send_json(413, {"error": {"message": err or "Empty body"}})
                return
            try:
                req = json.loads(body_raw)
                target_email = req.get("email", "").strip()
            except Exception:
                self._send_json(400, {"error": {"message": "Invalid JSON"}})
                return

            acc_idx = -1
            for i, a in enumerate(ACCOUNT_STATES):
                if a.email == target_email:
                    acc_idx = i
                    break
            if acc_idx == -1:
                self._send_json(404, {"error": {"message": f"Account '{target_email}' not found"}})
                return

            with _rr_lock:
                _sticky_account_email = target_email
                _round_robin_idx = acc_idx

            CONFIG["active_account"] = target_email
            try:
                with open(CONFIG_PATH, "w") as f:
                    json.dump(CONFIG, f, indent=2)
            except Exception as e:
                print(f"  [WARN] Save active account: {e}")

            print(f"  [ROUTING] Active starting account manually set to: {target_email} (index {acc_idx})")
            self._send_json(200, {"ok": True, "active_account": target_email, "strategy": STRATEGY, "index": acc_idx})
            return

        if self.path == "/v1/strategy":
            body_raw, err = self._read_body(4096)
            if err:
                self._send_json(413, {"error": {"message": err}})
                return
            try:
                req = json.loads(body_raw)
                strategy = req.get("strategy", "").strip()
            except Exception:
                self._send_json(400, {"error": {"message": "Invalid JSON"}})
                return
            if strategy not in ("round-robin", "sticky", "restrict"):
                self._send_json(400, {"error": {"message": "strategy must be 'round-robin', 'sticky' or 'restrict'"}})
                return
            STRATEGY = strategy
            CONFIG["strategy"] = strategy
            try:
                with open(CONFIG_PATH, "w") as f:
                    json.dump(CONFIG, f, indent=2)
            except Exception as e:
                print(f"  [WARN] Save strategy: {e}")
            print(f"[CONFIG] Strategy changed to: {strategy}")
            self._send_json(200, {"ok": True, "strategy": strategy})
            return
        self._send_json(404, {"error": {"message": "Not found"}})

    def _serve_dashboard(self):
        dashboard_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "dashboard.html")
        try:
            with open(dashboard_path, "rb") as f:
                html = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self._security_headers()
            # Content-Security-Policy: allow self, cdn.jsdelivr.net for SweetAlert2, and cloudflare insights
            self.send_header("Content-Security-Policy",
                "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data:; connect-src 'self'")
            # Fresh per-session token (httpOnly — JS can't read it)
            self.send_header("Set-Cookie", f"ag_session={_issue_session_token()}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400")
            self.end_headers()
            self.wfile.write(html)
        except Exception:
            # Never expose internal details to the client
            self._send_json(500, {"error": {"message": "Internal server error"}})

    # ── OAuth ──

    _oauth_states = {}

    def _redirect_uri(self):
        """Redirect URI: dari .env/env, atau loopback Host (ssh -L flow)."""
        if OAUTH_REDIRECT_URI:
            return OAUTH_REDIRECT_URI
        # Fallback only ever serves the ssh -L localhost flow. Trusting an
        # arbitrary Host header here let an attacker point redirect_uri at
        # their own domain and steal the OAuth code (Strix vuln-0001).
        host_hdr = self.headers.get("Host") or ""
        host = host_hdr.split(":")[0]
        if host not in ("localhost", "127.0.0.1", "[::1]", "::1"):
            return None
        return f"http://{host_hdr}/auth/callback"

    def _oauth_login(self):
        redirect_uri = self._redirect_uri()
        if not redirect_uri:
            self._send_json(400, {"error": {"message":
                "Set OAUTH_REDIRECT_URI in .env before using OAuth login"}})
            return
        state = secrets.token_urlsafe(24)
        self._oauth_states[state] = time.time()
        for k in list(self._oauth_states):
            if time.time() - self._oauth_states[k] > 600:
                del self._oauth_states[k]
        params = urllib.parse.urlencode({
            "client_id": OAUTH["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": OAUTH_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state
        })
        self.send_response(302)
        self.send_header("Location", f"https://accounts.google.com/o/oauth2/v2/auth?{params}")
        self.end_headers()

    def _oauth_callback(self):
        import html as _html
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        state = qs.get("state", [None])[0]
        code = qs.get("code", [None])[0]
        error = qs.get("error", [None])[0]
        if error:
            # Never reflect raw upstream input without sanitizing
            self._send_json(400, {"error": {"message": "OAuth error"}})
            return
        if not code or not state or state not in self._oauth_states:
            self._send_json(400, {"error": {"message": "Invalid or expired OAuth state"}})
            return
        del self._oauth_states[state]
        redirect_uri = self._redirect_uri()
        if not redirect_uri:
            self._send_json(400, {"error": {"message":
                "Set OAUTH_REDIRECT_URI in .env before using OAuth login"}})
            return
        data = urllib.parse.urlencode({
            "client_id": OAUTH["client_id"], "client_secret": OAUTH["client_secret"],
            "code": code, "grant_type": "authorization_code",
            "redirect_uri": redirect_uri
        }).encode()
        req = urllib.request.Request(OAUTH["token_url"], data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
        except urllib.error.HTTPError:
            self._send_json(500, {"error": {"message": "Token exchange failed"}})
            return
        refresh_token = result.get("refresh_token")
        if not refresh_token:
            self._send_json(400, {"error": {"message": "No refresh_token (re-consent needed)"}})
            return
        email = "unknown"
        try:
            ureq = urllib.request.Request("https://www.googleapis.com/oauth2/v1/userinfo?alt=json",
                headers={"Authorization": f"Bearer {result.get('access_token', '')}"})
            with urllib.request.urlopen(ureq, timeout=15) as uresp:
                email = json.loads(uresp.read().decode()).get("email", "unknown")
        except Exception:
            pass
        add_account_to_pool(email, refresh_token)
        # Escape all dynamic values — email comes from external source (XSS prevention)
        safe_email = _html.escape(str(email), quote=True)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._security_headers()
        self.end_headers()
        self.wfile.write(f"""<!DOCTYPE html><html><body style="font-family:sans-serif;padding:40px;text-align:center;background:#0f1117;color:#e4e4e7">
<h2 style="color:#4ade80">Account successfully added!</h2><p style="color:#a1a1aa">Email: {safe_email}</p>
<p style="color:#a1a1aa">Total accounts: {len(ACCOUNT_STATES)}</p>
<p><a href="/" style="color:#3b82f6">&larr; Back to Dashboard</a></p></body></html>""".encode())
        print(f"[AUTH] Added {email}. Total: {len(ACCOUNT_STATES)}")

    def do_POST(self):
        global API_KEYS

        if self.path == "/auth/login-web":
            body_raw, err = self._read_body(64 * 1024)
            ip = self._client_ip()
            if not _auth_allowed(ip):
                self._send_json(429, {"error": {"message": "Too many failed attempts. Please wait."}})
                return
            if err or not body_raw:
                self._send_json(400, {"error": {"message": "Missing credentials"}})
                return
            try:
                data = json.loads(body_raw)
                u = data.get("username", "").strip()
                p = data.get("password", "")
                if secrets.compare_digest(u, DASHBOARD_USER) and secrets.compare_digest(p, DASHBOARD_PASSWORD):
                    _auth_success(ip)
                    tok = _issue_session_token()
                    cookie_val = f"ag_session={tok}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400"
                    self.send_response(200)
                    self.send_header("Set-Cookie", cookie_val)
                    self.send_header("Content-Type", "application/json")
                    self._security_headers()
                    self.end_headers()
                    self.wfile.write(b'{"ok": true}')
                    log_event("INFO", f"Dashboard login success from {ip}")
                else:
                    _auth_fail(ip)
                    log_event("WARN", f"Dashboard login failed from {ip}")
                    self._send_json(401, {"error": {"message": "Invalid username or password"}})
            except Exception as e:
                self._send_json(400, {"error": {"message": str(e)}})
            return

        if not self._check_auth(): return

        if self.path == "/v1/optimizers/toggle" or self.path == "/api/optimizers/toggle":
            body_raw, err = self._read_body(4096)
            if err or not body_raw:
                self._send_json(400, {"error": {"message": err or "Empty body"}})
                return
            try:
                req = json.loads(body_raw.decode("utf-8"))
                opt_name = req.get("optimizer", "").strip().lower()
            except Exception:
                self._send_json(400, {"error": {"message": "Invalid JSON"}})
                return
            if opt_name not in OPTIMIZERS:
                self._send_json(400, {"error": {"message": f"Unknown optimizer: {opt_name}"}})
                return
            OPTIMIZERS[opt_name] = not OPTIMIZERS[opt_name]
            CONFIG["optimizers"] = OPTIMIZERS
            try:
                with open(CONFIG_PATH, "w") as f:
                    json.dump(CONFIG, f, indent=2)
            except Exception as e:
                print(f"  [WARN] Save optimizers config: {e}")
            print(f"[CONFIG] Optimizer {opt_name} toggled to: {OPTIMIZERS[opt_name]}")
            self._send_json(200, {"ok": True, "optimizers": OPTIMIZERS})
            return

        if self.path == "/api/import-9router":
            body_raw, _ = self._read_body(64 * 1024)
            custom_path = None
            if body_raw:
                try:
                    req_data = json.loads(body_raw)
                    custom_path = req_data.get("path", "").strip() or None
                except Exception: pass

            import sqlite3
            candidate_paths = []
            if custom_path:
                candidate_paths.append(os.path.expanduser(custom_path))
            
            # Check configured path in config.json
            saved_router_path = CONFIG.get("router_db_path")
            if saved_router_path:
                candidate_paths.append(os.path.expanduser(saved_router_path))

            # Default search paths
            candidate_paths.extend([
                os.path.expanduser("~/.9router/db/data.sqlite"),
                "/app/data/db/data.sqlite",
                "/home/ubuntu/.9router/db/data.sqlite"
            ])

            found_db = None
            for p in candidate_paths:
                if os.path.exists(p) and os.path.isfile(p):
                    found_db = p
                    break

            if not found_db:
                self._send_json(404, {
                    "error": {
                        "message": "9router database not found in default locations. Please provide custom SQLite path.",
                        "searched_paths": candidate_paths
                    }
                })
                return

            imported_count = 0
            updated_count = 0
            try:
                conn = sqlite3.connect(f"file:{found_db}?mode=ro", uri=True)
                cursor = conn.cursor()
                rows = cursor.execute("SELECT email, data FROM providerConnections WHERE provider = 'antigravity'").fetchall()
                
                existing_emails = {a.email: a for a in ACCOUNT_STATES}
                for email, data_str in rows:
                    if not email: continue
                    try:
                        conn_data = json.loads(data_str) if isinstance(data_str, str) else {}
                        rt = conn_data.get("refreshToken")
                        if not rt: continue

                        if email in existing_emails:
                            existing_emails[email].refresh_token = rt
                            updated_count += 1
                        else:
                            acc_obj = AccountState({"email": email, "refresh_token": rt, "disabled": False})
                            ACCOUNT_STATES.append(acc_obj)
                            imported_count += 1
                    except Exception: pass
                conn.close()

                # Save to config.json and remember path
                CONFIG["router_db_path"] = found_db
                _save_accounts()
                log_event("INFO", f"Imported {imported_count} new accounts ({updated_count} updated) from 9router at {found_db}")
                self._send_json(200, {
                    "success": True,
                    "imported": imported_count,
                    "updated": updated_count,
                    "db_path": found_db,
                    "total_accounts": len(ACCOUNT_STATES)
                })
            except Exception as e:
                self._send_json(500, {"error": {"message": f"Failed to read 9router database: {str(e)}"}})
            return
        if self.path == "/v1/api-keys/create" or self.path == "/v1/api-key/generate":
            body_raw, _ = self._read_body(64 * 1024)
            name = "API Key"
            expires_at = None
            if body_raw:
                try:
                    req_data = json.loads(body_raw)
                    name = req_data.get("name", "API Key").strip() or "API Key"
                    exp_val = req_data.get("expires_at")
                    if exp_val is not None:
                        try:
                            exp_int = int(exp_val)
                            if exp_int > 0:
                                expires_at = exp_int
                        except (ValueError, TypeError):
                            pass
                except Exception: pass
            new_key = "ag-proxy-" + secrets.token_hex(16)
            new_entry = {
                "id": f"key-{int(time.time()*1000)}",
                "name": name,
                "key": new_key,
                "created": int(time.time()),
                "expires_at": expires_at
            }
            API_KEYS.append(new_entry)
            _save_api_keys()
            log_event("INFO", f"Created new API key: {name} (expires: {expires_at})")
            self._send_json(200, {"success": True, "api_key": new_key, "entry": new_entry, "api_keys": API_KEYS})
            return

        if self.path == "/v1/api-keys/delete":
            body_raw, err = self._read_body(64 * 1024)
            if err or not body_raw:
                self._send_json(400, {"error": {"message": err or "Missing request body"}})
                return
            try:
                req_data = json.loads(body_raw)
                target_key = req_data.get("key", "").strip()
                target_id = req_data.get("id", "").strip()
                
                initial_len = len(API_KEYS)
                API_KEYS = [k for k in API_KEYS if (k["key"] != target_key and k["id"] != target_id)]
                if len(API_KEYS) < initial_len:
                    _save_api_keys()
                    log_event("INFO", f"Deleted API key: {target_id or target_key[:12]}")
                    self._send_json(200, {"success": True, "api_keys": API_KEYS})
                else:
                    self._send_json(404, {"error": {"message": "Key not found"}})
            except Exception as e:
                self._send_json(400, {"error": {"message": f"Invalid request: {e}"}})
            return

        if self.path == "/v1/accounts/add":
            body_raw, err = self._read_body(64 * 1024)
            if err:
                self._send_json(413, {"error": {"message": err}})
                return
            try:
                req = json.loads(body_raw)
                email = req.get("email", "").strip()
                refresh_token = req.get("refresh_token", "").strip()
                if not email or not refresh_token:
                    self._send_json(400, {"error": {"message": "email and refresh_token are required"}})
                    return
                # Basic email format validation
                if "@" not in email or len(email) > 320:
                    self._send_json(400, {"error": {"message": "Invalid email format"}})
                    return
                # Reject control chars / HTML in email (defense in depth)
                if any(ord(c) < 32 for c in email) or "<" in email or ">" in email:
                    self._send_json(400, {"error": {"message": "Email contains forbidden characters"}})
                    return
            except Exception:
                self._send_json(400, {"error": {"message": "Invalid JSON"}})
                return
            add_account_to_pool(email, refresh_token)
            self._send_json(200, {"ok": True, "email": email, "total": len(ACCOUNT_STATES)})
            return

        if self.path == "/v1/accounts/remove":
            body_raw, err = self._read_body(64 * 1024)
            if err:
                self._send_json(413, {"error": {"message": err}})
                return
            try:
                req = json.loads(body_raw)
                email = req.get("email", "")
            except Exception:
                self._send_json(400, {"error": {"message": "Invalid JSON"}})
                return
            if remove_account_from_pool(email):
                self._send_json(200, {"ok": True, "removed": email})
            else:
                self._send_json(404, {"error": {"message": "Not found"}})
            return

        if self.path == "/v1/accounts/toggle":
            body_raw, err = self._read_body(64 * 1024)
            if err:
                self._send_json(413, {"error": {"message": err}})
                return
            try:
                req = json.loads(body_raw)
                email = req.get("email", "")
            except Exception:
                self._send_json(400, {"error": {"message": "Invalid JSON"}})
                return
            target_acc = None
            for acc in ACCOUNT_STATES:
                if acc.email == email:
                    acc.disabled = not acc.disabled
                    target_acc = acc
                    break
            if target_acc:
                for c_acc in CONFIG.get("accounts", []):
                    if c_acc.get("email") == email:
                        c_acc["disabled"] = target_acc.disabled
                        _save_accounts()
                        break
                self._send_json(200, {"ok": True, "email": email, "disabled": target_acc.disabled})
            else:
                self._send_json(404, {"error": {"message": "Not found"}})
            return

        if self.path == "/v1/accounts/test":
            body_raw, err = self._read_body(4096)
            model = "gemini-3.8-flash-medium"
            if body_raw:
                try:
                    model = (json.loads(body_raw) or {}).get("model") or model
                except Exception:
                    pass
            targets = [a for a in ACCOUNT_STATES if not a.disabled]
            if not targets:
                self._send_json(200, {"model": model, "results": [],
                                      "note": "no enabled accounts"})
                return
            out: list = [None] * len(targets)

            def _run(i, acc):
                try:
                    out[i] = probe_account(acc, model)
                except Exception as e:
                    out[i] = {"email": acc.email, "ok": False,
                              "error": f"probe crashed: {e}"[:200],
                              "checked_at": int(time.time())}

            workers = [threading.Thread(target=_run, args=(i, a), daemon=True)
                       for i, a in enumerate(targets)]
            for w in workers:
                w.start()
            for w in workers:
                w.join(timeout=90)
            results = [r if r else {"email": targets[i].email, "ok": False,
                                    "error": "timeout >90s",
                                    "checked_at": int(time.time())}
                       for i, r in enumerate(out)]
            ok_count = sum(1 for r in results if r.get("ok"))
            log_event("INFO", f"Account test: {ok_count}/{len(results)} OK (model={model})")
            self._send_json(200, {"model": model, "ok_count": ok_count,
                                  "total": len(results), "results": results})
            return

        if self.path != "/v1/chat/completions":
            self._send_json(404, {"error": {"message": "Not found"}})
            return

        body_raw, err = self._read_body()
        if err:
            self._send_json(413, {"error": {"message": err}})
            return
        try:
            body = json.loads(body_raw)
        except json.JSONDecodeError:
            self._send_json(400, {"error": {"message": "Invalid JSON"}})
            return

        model = body.get("model", "gemini-3-flash")
        stream = body.get("stream", False)
        request_id = f"chatcmpl-{int(time.time()*1000)}"
        usage_start = time.time()  # for usage stats; never affects the request
        print(f"\n[REQ] id={request_id} model={model} stream={stream} msgs={len(body.get('messages',[]))} keys={sorted(body.keys())}")
        # Payload size matters: Google returns 429 RESOURCE_EXHAUSTED (not 400) for requests
        # whose prompt blows past the per-account token budget, so record the dimensions that
        # actually drive it — otherwise a big-tools client failure looks like an empty quota.
        try:
            _tools = body.get("tools") or []
            _msgs = body.get("messages") or []
            _body_kb = len(json.dumps(body)) / 1024
            _tools_kb = len(json.dumps(_tools)) / 1024
            _msg_kb = len(json.dumps(_msgs)) / 1024
            print(f"[SIZE] body={_body_kb:.1f}KB tools={len(_tools)} ({_tools_kb:.1f}KB) "
                  f"messages={_msg_kb:.1f}KB max_tokens={body.get('max_tokens')}")
        except Exception:
            pass
        # NOTE: debug dump ke /tmp/last_req.json DIHAPUS — request body bisa
        # berisi data sensitif (prompt, tool calls). Enable via env DEBUG_DUMP=1.
        if os.environ.get("DEBUG_DUMP") == "1":
            try:
                with open("/tmp/last_req.json", "w") as _f:
                    json.dump(body, _f, indent=1)
            except Exception:
                pass
        ag_body, ag_stream = openai_to_antigravity(body, request_headers=self.headers)

        restrict_mode = STRATEGY == "restrict"
        fallback_models = [m.strip() for m in os.environ.get(
            "AG_MODEL_FALLBACK", "gemini-3-flash").split(",") if m.strip()]
        model_chain = [model] + [m for m in fallback_models if m != model]
        last_status, last_body, account = None, "", None
        for chain_model in model_chain:
            if chain_model != model:
                # Same request, next model: the account pool is shared, but the per-minute
                # budget is per model, so a throttled "high" tier does not block "medium".
                retry_body = dict(body)
                retry_body["model"] = chain_model
                ag_body, ag_stream = openai_to_antigravity(retry_body, request_headers=self.headers)
                log_event("INFO", f"Model fallback: {model} -> {chain_model}")
            handled, last_status, last_body, account = self._attempt_pool(
                ag_body, chain_model, request_id, usage_start, restrict_mode, stream, body)
            if handled:
                return
            # Only throttling/capacity failures are worth another model; a 403 or a malformed
            # request would fail identically on every model.
            if last_status not in (429, 500, 502, 503, 504):
                break

        last_err = (account.last_error if account else None) or str(last_body or "No accounts")
        track_end(request_id)
        record_usage(model, 0, 0, 0, "error", (time.time() - usage_start) * 1000)
        if restrict_mode and last_status:
            # Surface the real upstream verdict (429/503/403) so the client can back off,
            # instead of the generic 502 "all attempts failed" wrapper.
            try:
                payload = json.loads(last_body)
            except Exception:
                payload = {"error": {"message": str(last_body or last_err)[:500],
                                     "code": last_status}}
            status = last_status if last_status in (400, 401, 403, 429, 500, 502, 503, 504) else 502
            headers = {"X-Account-Used": getattr(account, "email", "") or ""}
            if status in (429, 503):
                headers["Retry-After"] = "20"
            self._send_json(status, payload, extra_headers=headers)
            return
        self._send_json(502, {"error": {"message": (
            f"All {MAX_RETRIES} attempts failed on {model} and its fallbacks. Last: {last_err}")}})

    def _attempt_pool(self, ag_body, chain_model, request_id, usage_start, restrict_mode, stream, body):
        """Try the account pool for ONE model. Returns (handled, status, body, account)."""
        global _sticky_account_email
        excluded_email = None
        retry_after = 0.0
        # Restrict mode: single attempt, no account hop. The client gets the upstream verdict
        # and backs off itself instead of the pool silently switching identity mid-session.
        restrict_mode = STRATEGY == "restrict"
        attempt_budget = 1 if restrict_mode else MAX_RETRIES
        last_status = None
        last_body = ""
        account = None
        for attempt in range(attempt_budget):
            if attempt:
                delay = retry_after or (ATTEMPT_BACKOFF_BASE * attempt)
                delay = max(0.2, min(delay, ATTEMPT_BACKOFF_MAX))
                log_event("INFO", f"Retry {attempt + 1}/{MAX_RETRIES} in {delay:.1f}s")
                time.sleep(delay)
            if STRATEGY == "sticky" and excluded_email:
                account = get_fallback_account(excluded_email)
            else:
                account = get_next_account()
            if not account:
                self._send_json(503, {"error": {"message": "No active accounts"}})
                return True, None, "", None

            # Inject deterministic session ID into Antigravity request for prompt cache hit
            stable_session_id = resolve_client_session_id(body, account.email)
            ag_body["request"]["sessionId"] = stable_session_id
            try:
                token = account.get_token()
                account.request_count += 1
            except:
                continue
            print(f"  [ACC] {account.email} (attempt {attempt+1})")
            track_start(request_id, chain_model, account.email)
            ag_body_json = json.dumps(ag_body).encode()
            req = urllib.request.Request(API_ENDPOINT, data=ag_body_json,
                headers={"Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    **ANTIGRAVITY_CLIENT_HEADERS})
            try:
                resp = urllib.request.urlopen(req, timeout=300)
                # Auto-clear error state on successful connection
                account.error_count = 0
                account.last_error = None
            except urllib.error.HTTPError as e:
                err_body = e.read().decode()
                retry_after = 0.0
                try:
                    raw_retry_after = e.headers.get("Retry-After") if e.headers else None
                    if raw_retry_after:
                        retry_after = max(1.0, min(float(raw_retry_after), 15.0))
                except (TypeError, ValueError):
                    retry_after = 0.0
                account.error_count += 1
                account.last_error = f"HTTP {e.code}: {err_body[:500]}"
                last_status, last_body = e.code, err_body
                print(f"  [ERR] {account.email}: {account.last_error}")
                log_event("ERR", f"{account.email}: {account.last_error}")
                if e.code == 401:
                    account.access_token = None
                    account.expires_at = 0
                elif e.code == 429:
                    # Real exhaustion -> long cooldown; transient throttle with quota intact
                    # -> short cooldown so one blip cannot bench the whole pool.
                    cooldown = 300 if quota_effectively_gone(account) else 60
                    account.rate_limited_until = int(time.time()) + cooldown
                    log_event("WARN", f"Account {account.email} RATE LIMITED (429) - cooldown {cooldown // 60} min, switching account")
                elif e.code in (500, 502, 503, 504):
                    # Transient upstream capacity (e.g. MODEL_CAPACITY_EXHAUSTED): a 10-minute
                    # bench over a capacity crunch that lasts seconds empties the pool fast.
                    account.rate_limited_until = int(time.time()) + 60
                    log_event("WARN", f"Account {account.email} UPSTREAM {e.code} - cooldown 1 min, switching account")
                else:
                    # HTTP 403 or other persistent error: cooldown 10 minutes so sticky advances!
                    account.rate_limited_until = int(time.time()) + 600
                    log_event("WARN", f"Account {account.email} ERROR ({e.code}) - cooldown 10 min, switching account")
                
                # Update global sticky anchor to the fallback account immediately
                if STRATEGY == "sticky":
                    global _sticky_account_email
                    fallback = get_fallback_account(account.email)
                    if fallback:
                        _sticky_account_email = fallback.email
                excluded_email = account.email
                continue
            except Exception as e:
                account.error_count += 1
                account.last_error = str(e)
                continue

            if stream:
                self._handle_stream(resp, chain_model, request_id, account, usage_start)
            else:
                self._handle_nonstream(resp, chain_model, request_id, account, usage_start)
            return True, last_status, last_body, account
        return False, last_status, last_body, account


    def _handle_nonstream(self, resp, model, request_id, account, started=0.0):
        raw = resp.read().decode()
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                # Merge all chunks into one consolidated response
                data = self._merge_chunks(data)
            if "error" in data:
                track_end(request_id)
                record_usage(model, 0, 0, 0, "error", (time.time() - started) * 1000)
                self._send_json(502, {"error": {"message": f"Antigravity: {data['error'].get('message','?')}"}})
                return
            openai_resp = antigravity_to_openai(data, model, request_id)
            try:
                um = data.get("response", {}).get("usageMetadata", {})
                record_usage(model, um.get("promptTokenCount", 0), um.get("candidatesTokenCount", 0),
                             um.get("cachedContentTokenCount", 0), "ok", (time.time() - started) * 1000)
            except Exception:
                pass  # usage is additive; never fail the response
            log_event("INFO", f"✅ {model} via {account.email} → {openai_resp['usage']['total_tokens']} tokens")
            self._send_json(200, openai_resp, account_email=account.email)
            track_end(request_id)
            print(f"  [OK] {account.email} → {openai_resp['usage']['total_tokens']} tokens")
        except Exception as e:
            track_end(request_id)
            record_usage(model, 0, 0, 0, "error", (time.time() - started) * 1000)
            log_event("ERR", f"{model} via {account.email} FAILED ({type(e).__name__}): {e}")
            print(f"  [ERR] {account.email}: {type(e).__name__}: {e}")
            self._send_json(500, {"error": {"message": f"Parse error: {e}"}})

    def _merge_chunks(self, chunks):
        """Merge a list of Antigravity response chunks into a single response."""
        if not chunks:
            return {}
        if len(chunks) == 1:
            return chunks[0]
        merged_parts = []
        usage = {}
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            if "error" in chunk:
                return chunk
            resp = chunk.get("response", {})
            for cand in resp.get("candidates", []):
                merged_parts.extend(cand.get("content", {}).get("parts", []))
            if resp.get("usageMetadata"):
                usage = resp["usageMetadata"]
        return {"response": {"candidates": [{"content": {"parts": merged_parts}, "finishReason": "STOP"}], "usageMetadata": usage}}

    def _handle_stream(self, resp, model, request_id, account, started=0.0):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.close_connection = True
        if account:
            self.send_header("X-Account-Used", account.email)
        self.end_headers()
        track_streaming(request_id)
        state = {}
        buffer = ""
        try:
            for line in resp:
                buffer += line.decode()
                while buffer:
                    try:
                        data = json.loads(buffer)
                        if isinstance(data, list):
                            for chunk_data in data:
                                openai_chunk = antigravity_chunk_to_openai(chunk_data, model, request_id, state)
                                if openai_chunk:
                                    self.wfile.write(f"data: {json.dumps(openai_chunk)}\n\n".encode())
                                    self.wfile.flush()
                            buffer = ""
                            break
                        else:
                            break
                    except json.JSONDecodeError:
                        break
            if state.get("tool_calls"):
                final_finish = "tool_calls"
            elif not state.get("content_chars"):
                # Nothing usable reached the client (thinking ate the budget / truncation).
                # "length" lets the agent retry with more room; "stop" makes it loop silently.
                final_finish = "length"
            else:
                final_finish = "stop"
            final = {"id": request_id, "object": "chat.completion.chunk", "created": int(time.time()),
                "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": final_finish}]}
            um = state.get("usage", {})
            if um:
                final["usage"] = {
                    "prompt_tokens": um.get("promptTokenCount", 0),
                    "completion_tokens": um.get("candidatesTokenCount", 0),
                    "total_tokens": um.get("totalTokenCount", 0),
                    "reasoning_tokens": um.get("thoughtsTokenCount", 0),
                    "prompt_tokens_details": {
                        "cached_tokens": um.get("cachedContentTokenCount", 0)
                    }
                }
            self.wfile.write(f"data: {json.dumps(final)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            # Usage arrives in the final chunk (usageMetadata, no candidates)
            try:
                record_usage(model, um.get("promptTokenCount", 0), um.get("candidatesTokenCount", 0),
                             um.get("cachedContentTokenCount", 0), "ok", (time.time() - started) * 1000)
            except Exception:
                pass  # usage is additive; never fail the response
            log_event("INFO", f"STREAM {model} via {account.email} done finish={final_finish} "
                           f"out={um.get('candidatesTokenCount',0)} think={um.get('thoughtsTokenCount',0)}")
            print(f"  [OK] {account.email} -> stream done")
        except Exception as e:
            record_usage(model, 0, 0, 0, "error", (time.time() - started) * 1000)
            # Sebelumnya jalur ini SENYAP: client dapat error di Kilo tapi proxy.log kosong.
            # Sekarang setiap kegagalan mid-stream (client putus / upstream reset) tercatat.
            kind = type(e).__name__
            if isinstance(e, (BrokenPipeError, ConnectionResetError)) or "Broken pipe" in str(e):
                log_event("WARN", f"STREAM {model} via {account.email} CLIENT ABORT ({kind}): {e}")
                print(f"  [ABORT] {account.email} -> client closed the stream early")
            else:
                log_event("ERR", f"STREAM {model} via {account.email} FAILED ({kind}): {e}")
                print(f"  [ERR-STREAM] {account.email}: {kind}: {e}")
            err_chunk = {"id": request_id, "object": "chat.completion.chunk", "created": int(time.time()),
                "model": model, "choices": [{"index": 0, "delta": {"content": f"\n[Proxy Error: {e}]"}, "finish_reason": "stop"}]}
            try:
                self.wfile.write(f"data: {json.dumps(err_chunk)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except Exception:
                pass
        finally:
            track_end(request_id)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Antigravity Multi-Account Proxy v2")
    print("=" * 60)
    print(f"  Port: {PORT} | Strategy: {STRATEGY}")
    print(f"  Accounts: {len(ACCOUNTS)} | Models: {len(MODEL_MAP)}")
    for a in ACCOUNTS:
        print(f"    - {a['email']}")
    print(f"  Dashboard: {'password protected' if DASHBOARD_PASSWORD else 'OPEN (no password!)'}")
    print("=" * 60)
    print("\n[INIT] Pre-refreshing tokens...")
    for acc in ACCOUNT_STATES:
        if acc.disabled:
            print(f"  [DISABLED] {acc.email}: disabled (token still refreshed)")
        try:
            acc.get_token()
            acc.fetch_quota()
            print(f"  [READY] {acc.email}: token + quota OK")
        except:
            print(f"  [FAIL] {acc.email}: failed")
    # Background quota refresh every 5 min
    def _quota_loop():
        while True:
            time.sleep(300)
            for acc in ACCOUNT_STATES:
                if not acc.disabled:
                    acc.fetch_quota()
    threading.Thread(target=_quota_loop, daemon=True).start()
    class _BurstServer(ThreadingHTTPServer):
        # Default backlog is 5, so an IDE burst (40+ parallel tool calls) overflows the
        # accept queue and the client sees ConnectionResetError instead of a response.
        request_queue_size = 256
        daemon_threads = True

    server = _BurstServer((HOST, PORT), ProxyHandler)
    server.daemon_threads = True
    print(f"\n[SERVER] Listening on {HOST}:{PORT}")
    print(f"[SERVER] Dashboard: http://localhost:{PORT}/")
    print(f"[SERVER] API: http://localhost:{PORT}/v1/chat/completions")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down...")
        server.server_close()


if __name__ == "__main__":
    main()
