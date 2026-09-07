# CHANGELOG

All notable changes to `antigravity-proxy-v2` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.3.0] - 2026-09-07

### Added
- **Prompt Cache Optimization:** Improved optimizer and increased cache hit rate using conversation seed hashing.
- **Modular Core Architecture:** Refactored codebase into clean, maintainable sub-modules under `core/` and HTML views under `templates/`.
- **Token Optimization Suite:**
  - **RTK (Reduced Tool Kit):** Automated truncation and compression for noisy shell, terminal, and build tool responses, saving ~30% - 50% input context.
  - **Caveman Mode:** Zero-slop prose compression engine that forces direct, polite-free technical answers, saving ~40% - 60% completion tokens.
  - **Ponytail Mode:** Surgical code patch mode preventing full-file rewrites for minor modifications, saving ~50% - 70% code context.
- **Interactive Optimizer UI:** Live toggle switches on dashboard for RTK, Caveman, and Ponytail with real-time state persistence.
- **Comparison & Examples Modal:** Side-by-side modal dialog showcasing token differences with and without optimizers.
- **Dynamic Catalog Integration:** Added Gemini 3.8 Flash series to `FULL_MODEL_CATALOG`.

### Fixed
- **Real-Time Quota Accuracy:** Synchronized `QUOTA_API` endpoint with `daily-cloudcode-pa` so account usage fractions properly decay in real time instead of remaining locked at 100%.
- **Streaming Reasoning Delivery:** Emitted thought chunks during streaming completions via `includeThoughts: true`.

---

## [2.2.0] - 2026-09-02

### Added
- **Native Gemini 3.8 Flash Support:** Integrated `gemini-3.8-flash-tiered` with dynamic `thinkingLevel` translation (`high` / `medium`).
- **1-Click & Fallback 9router Importer:** Instant SQLite database scanner with automated fallback prompt.
- **WARP SOCKS5 Routing:** Routing outbound Google API traffic via local SOCKS5 proxy to resolve datacenter IP geo-restrictions.

---

## [2.1.0] - 2026-08-25

### Added
- Multi-API key management (`/v1/api-keys`).
- Session-based web login with dark glassmorphism design.
