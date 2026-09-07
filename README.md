# Antigravity Multi-Account Proxy v2.3.0

![Version](https://img.shields.io/badge/version-2.3.0-0284c7)
![License](https://img.shields.io/badge/license-MIT-green)

OpenAI-compatible reverse proxy that aggregates multiple Google Antigravity accounts into a single load-balanced endpoint with automatic rate-limit failover, quota tracking, session authentication, multi-API key support, and built-in token optimization plugins.

---

## What's New in v2.3.0

- **Built-in Token Optimization Plugins:**
  - **RTK (Reduced Tool Kit):** Shell & terminal output trimmer that cuts out verbose build traces, package installation logs, and noisy traceback middles (Save ~30% - 50% input tokens).
  - **Caveman Mode:** Zero-slop prose compressor that eliminates AI pleasantries, conversational fluff, and generic greetings in favor of direct technical answers (Save ~40% - 60% output tokens).
  - **Ponytail Mode:** Surgical code diff mode that prevents models from rewriting entire 400+ line files for minor 2-line edits (Save ~50% - 70% code context).
- **Interactive Optimizer Controls:** Toggle plugins on the fly directly from the Web Dashboard or config file, complete with side-by-side token saving comparisons.
- **Accurate Real-Time Quota Tracking:** Fixed quota endpoint synchronization with `daily-cloudcode-pa` to accurately reflect account usage fractions in real time.
- **Streaming Reasoning Content:** Native support for streaming thinking chunks (`includeThoughts: true`) in OpenAI-compatible format.

---

## Supported Models

| Model Name (OpenAI Format) | Upstream Antigravity Target | Thinking Configuration |
|---|---|---|
| `gemini-3.8-flash-high` | `gemini-3.8-flash-tiered` | `thinkingLevel: high` |
| `gemini-3.8-flash-medium` | `gemini-3.8-flash-tiered` | `thinkingLevel: medium` |
| `gemini-3.7-flash-high` | `gemini-3.7-flash-tiered` | `thinkingLevel: high` |
| `gemini-3.6-flash-high` | `gemini-3.6-flash-high` | `thinkingBudget: 24576` |
| `gemini-3.1-pro-high` | `gemini-pro-agent` | `thinkingBudget: 24576` |
| `claude-sonnet-4-6-thinking` | `claude-sonnet-4-6` | Thinking enabled |
| `claude-opus-4-6-thinking` | `claude-opus-4-6-thinking` | Thinking enabled |

---

## Optimization Plugins

Control plugins dynamically via dashboard or `config.json`:
```json
{
  "optimizers": {
    "rtk": true,
    "caveman": false,
    "ponytail": true
  }
}
```

### 1. RTK (Reduced Tool Kit)
- **Problem:** Terminal outputs from `npm install`, `cargo build`, or test suites often dump thousands of lines into the conversation context.
- **Solution:** RTK retains the initial command context and the recent exit tail while compressing the noisy middle, reducing 1,000+ tokens to under 20 tokens.

### 2. Caveman Mode
- **Problem:** LLMs often add unnecessary conversational padding ("I would be delighted to assist you with your request...").
- **Solution:** Enforces direct, high-density technical answers, drastically saving completion token spend and accelerating stream generation.

### 3. Ponytail Mode
- **Problem:** Coding assistants frequently rewrite an entire 500-line file when only modifying a single variable or function call.
- **Solution:** Enforces targeted diffs and surgical patches, preserving context space for larger multi-file coding sessions.

---

## Account Setup & Import Methods

There are 3 standard ways to add accounts:

### Method 1: Import from 9router (Automatic or Manual)
- Automatic Scan:
  Click "Import 9router" in the web dashboard navigation bar. The server automatically scans default SQLite database locations (`~/.9router/db/data.sqlite` or `/app/data/db/data.sqlite`).
- Manual Input:
  If custom database paths are used, copy your SQLite path from 9router Settings > Local Mode and paste it into the prompt. The path is saved automatically.

### Method 2: OAuth 2.0 Web Authorization
Authenticate accounts directly via your browser by clicking "Add Account via OAuth" in the web UI.

### Method 3: Manual Refresh Token Entry
Add refresh tokens directly via the "Add Account" modal in the dashboard or append them to the `accounts` array in `config.json`.

---

## License

MIT License (c) 2026 Julian Efendi
