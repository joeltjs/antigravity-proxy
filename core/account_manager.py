import time
import json
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional

QUOTA_API = "https://daily-cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels"

class AccountState:
    """Manages individual Google AI account credentials, token refresh, and quota stats."""
    def __init__(self, cfg_entry: Dict[str, Any], client_id: str, client_secret: str):
        self.email = cfg_entry["email"]
        self.refresh_token = cfg_entry["refresh_token"]
        self.disabled = cfg_entry.get("disabled", False)
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token: Optional[str] = None
        self.expires_at: float = 0.0
        self.request_count: int = 0
        self.error_count: int = 0
        self.last_error: Optional[str] = None
        self.rate_limited_until: float = 0.0
        self.quota: Dict[str, Any] = {}
        self.quota_fetched_at: float = 0.0

    def get_token(self) -> str:
        """Return valid access token, auto-refreshing if expired or expiring soon."""
        if self.access_token and time.time() < (self.expires_at - 60):
            return self.access_token

        body = urllib.parse.urlencode({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token"
        }).encode()

        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                self.access_token = data["access_token"]
                self.expires_at = time.time() + data.get("expires_in", 3600)
                return self.access_token
        except Exception as e:
            self.error_count += 1
            self.last_error = f"Token refresh failed: {e}"
            raise

    def fetch_quota(self) -> bool:
        """Fetch real-time quota fraction and reset times directly from upstream."""
        try:
            token = self.get_token()
            req = urllib.request.Request(
                QUOTA_API,
                data=b"{}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "User-Agent": "antigravity/ide/2.1.1 darwin/arm64"
                }
            )
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

    def status(self) -> Dict[str, Any]:
        return {
            "email": self.email,
            "disabled": self.disabled,
            "has_token": bool(self.access_token),
            "expires_in": max(0, int(self.expires_at - time.time())),
            "requests": self.request_count,
            "errors": self.error_count,
            "last_error": self.last_error,
            "quota": self.quota,
            "quota_age": int(time.time() - self.quota_fetched_at) if self.quota_fetched_at else -1
        }
