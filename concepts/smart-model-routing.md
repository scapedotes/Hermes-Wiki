---
title: Smart Model Routing
created: 2026-04-08
updated: 2026-04-29
type: concept
tags: [architecture, module, model-routing, performance, caching, anthropic]
sources: [agent/model_metadata.py, agent/models_dev.py, hermes_cli/model_switch.py, hermes_cli/model_normalize.py]
---

# Smart Model Routing

## Overview

> **Note**: This page covers the collaboration of **multiple modules**, not just `agent/smart_model_routing.py`. `smart_model_routing.py` itself is merely a lightweight heuristic module of approximately 195 lines, responsible for cheap/strong message routing (deciding whether to process the current message with a cheaper or stronger model). The broader model infrastructure discussed on this page—metadata parsing, context length probing, model switching pipeline—is distributed across the four core modules listed below.

Smart Model Routing is the Hermes Agent's **model metadata parsing and automatic context length detection** system, comprising four core modules:

| Module | Source | Responsibility |
|---|---|---|
| **model_metadata.py** | 36KB/941 lines | Context length detection, endpoint probing, token estimation |
| **models_dev.py** | 25KB/781 lines | models.dev 4000+ model database integration |
| **model_switch.py** | 32KB/927 lines | Model switching pipeline (alias resolution → credentials → metadata) |
| **model_normalize.py** | External module | Normalization of model names across providers |

Core Concept: **10-level Context Length Resolution Chain + models.dev 4000+ Model Database + Local Server Auto-Probing.**

## Architectural Principles

### Context Length Resolution Chain (10 Levels)

```python
def get_model_context_length(model, base_url, api_key, config_context_length, provider):
    """
    0. config explicit override → user knows best
    1. Persistent cache (previously probed model@base_url)
    2. Active endpoint metadata (/models endpoint, custom endpoints only)
    3. Local server query (Ollama/LM Studio/vLLM/llama.cpp)
    4. Anthropic /v1/models API (API Key only, no OAuth)
    5. models.dev registry (provider-aware, including Nous suffix matching)
    6. OpenRouter real-time API metadata
    7. Hardcoded defaults (fuzzy matching, longest key first)
    8. Local server last attempt
    9. Default fallback: 128K
    """
```

**Design Philosophy**: From most precise to least permissive, each level is attempted only if the previous one fails.

### Local Server Auto-Probing

```python
def detect_local_server_type(base_url):
    """
    Detection order:
    1. LM Studio → /api/v1/models (most specific)
    2. Ollama → /api/tags (verify response contains "models")
    3. llama.cpp → /v1/props or /props (check default_generation_settings)
    4. vLLM → /version (check "version" field)
    """
```

Each server type has different metadata retrieval methods:

| Server | Endpoint | Context Length Source |
|---|---|---|
| Ollama | /api/show | model_info.context_length or num_ctx parameter |
| LM Studio | /api/v1/models | loaded_instances.config.context_length |
| vLLM | /v1/models/{model} | max_model_len |
| llama.cpp | /v1/props | n_ctx (actual allocated context) |

### Endpoint Metadata Retrieval

```python
def fetch_endpoint_model_metadata(base_url, api_key):
    """
    1. Attempt {base_url}/models and {base_url}/v1/models
    2. Parse context_length, max_completion_tokens, pricing for each model
    3. If llama.cpp → additionally query /v1/props for actual n_ctx
    4. Cache for 5 minutes
    """
```

### Persistent Cache

```python
# Cache key: model@base_url
# The same model name from different providers might have different limitations
def save_context_length(model, base_url, length):
    # Writes to ~/.hermes/context_length_cache.yaml
    # Format: {context_lengths: {"qwen3@http://localhost:11434/v1": 131072}}
```

### Extracting Context Length from Error Messages

```python
def parse_context_limit_from_error(error_msg):
    """
    Extracts actual context limits from API error messages:
    - "maximum context length is 32768 tokens"
    - "context_length_exceeded: 131072"
    - "250000 tokens > 200000 maximum"
    """
```

## Core Components

### 1. models.dev Integration

```python
# 4000+ models, 109+ providers
# Offline-first: bundled snapshot → disk cache → network fetch → background refresh (60 minutes)

@dataclass
class ModelInfo:
    id: str
    name: str
    family: str
    provider_id: str
    reasoning: bool
    tool_call: bool
    attachment: bool       # Vision support
    context_window: int
    max_output: int
    cost_input: float      # Per million tokens
    cost_output: float
    cost_cache_read: float
    # ... more fields
```

**Three-level Cache**:
1. **In-memory cache**: 1 hour TTL
2. **Disk cache**: `~/.hermes/models_dev_cache.json`
3. **Network fetch**: `https://models.dev/api.json`

### 2. Model Capability Query

```python
def get_model_capabilities(provider, model) -> ModelCapabilities:
    """
    Returns:
    - supports_tools: Whether tool calling is supported
    - supports_vision: Whether vision is supported
    - supports_reasoning: Whether reasoning is supported
    - context_window: Context window
    - max_output_tokens: Maximum output
    - model_family: Model family
    """
```

### 3. Model Switching System

```python
def switch_model(raw_input, current_provider, current_model, ...) -> ModelSwitchResult:
    """
    Two paths:
    
    A. Given --provider:
       1. Parse provider → parse credentials → resolve alias or use as-is
       2. No model → auto-detect from endpoint
    
    B. Provider not given:
       1. Attempt alias with current provider
       2. Alias exists but not with current provider → fallback to other authenticated providers
       3. Aggregator → vendor/model slug conversion
       4. Aggregator directory search
       5. detect_provider_for_model() as fallback
       6. Parse credentials → normalize model name
    """
```

### 4. Alias System

```python
MODEL_ALIASES = {
    "sonnet":  ModelIdentity("anthropic", "claude-sonnet"),
    "opus":    ModelIdentity("anthropic", "claude-opus"),
    "gpt5":    ModelIdentity("openai", "gpt-5"),
    "gemini":  ModelIdentity("google", "gemini"),
    "qwen":    ModelIdentity("qwen", "qwen"),
    # ... 20+ short aliases
}
```

Alias resolution is **dynamic**—finding the latest matching model version by querying the models.dev directory, rather than being hardcoded.

### 5. Provider Prefix Handling

```python
_PROVIDER_PREFIXES = frozenset({
    "openrouter", "nous", "openai-codex", "anthropic", "alibaba",
    "google", "glm", "kimi", "deepseek", "qwen", ...
})

def _strip_provider_prefix(model):
    """
    "local:my-model" → "my-model"
    "qwen3.5:27b" → "qwen3.5:27b"  (retains Ollama tag)
    "deepseek:latest" → "deepseek:latest" (retains Ollama tag)
    """
```

**Key**: Differentiate between provider prefixes and Ollama's `model:tag` format.

### 6. Smart Fuzzy Matching

Context length default values use **longest key precedence** fuzzy matching:

```python
DEFAULT_CONTEXT_LENGTHS = {
    "claude-sonnet-4.6": 1000000,   # Specific version
    "claude": 200000,               # Fallback (must be later)
    "gpt-5": 128000,
    "gemini": 1048576,
    "qwen": 131072,
    # ...
}

# Only checks default_model in model (not reverse)
# Avoids "claude-sonnet-4" erroneously matching "claude-sonnet-4-6"
```

### 7. Context Probing Degradation

```python
CONTEXT_PROBE_TIERS = [128_000, 64_000, 32_000, 16_000, 8_000]

def get_next_probe_tier(current_length):
    """Starts from 128K, progressively degrades upon error"""
```

### 8. Token Estimation

```python
def estimate_tokens_rough(text):
    """Rough estimation of ~4 chars/token"""
    return len(text) // 4

def estimate_request_tokens_rough(messages, system_prompt, tools):
    """
    Full request estimation, including:
    - System prompt
    - Chat messages
    - Tool schemas (50+ tools can reach 20-30K tokens)
    """
```

## Design Advantages

### Comparison with Hardcoded Solutions

| Dimension | Hardcoded | Smart Model Routing |
|---|---|---|
| New model support | Requires code updates | models.dev auto-updates |
| Local servers | Manual configuration | Auto-detects 4 server types |
| Context length | Static dictionary | 10-level resolution chain (0-9) |
| Credential management | Hardcoded | Resolved via runtime_provider |
| Error recovery | None | Extracts limits from error messages |
| Offline support | None | Bundled snapshot + disk cache |

## Configuration and Operation

### Explicit Override

```yaml
# config.yaml
model:
  context_length: 128000  # Directly overrides all detections
```

### Alias Extension

```yaml
# config.yaml
model_aliases:
  qwen:
    model: "qwen3.5:397b"
    provider: custom
    base_url: "https://ollama.com/v1"
```

## Pricing Estimation

```python
# agent/usage_pricing.py

def estimate_usage_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimates API call cost"""
    pricing = {
        "claude-opus-4.6": {"input": 15.0, "output": 75.0},  # $/MTok
        "claude-sonnet-4": {"input": 3.0, "output": 15.0},
        "gpt-4o": {"input": 2.5, "output": 10.0},
        # ...
    }
    
    prices = pricing.get(model, {"input": 5.0, "output": 15.0})
    input_cost = (prompt_tokens / 1_000_000) * prices["input"]
    output_cost = (completion_tokens / 1_000_000) * prices["output"]
    return input_cost + output_cost
```

## OpenRouter Provider Routing

```python
# Provider preferences
provider_preferences = {}
if self.providers_allowed:
    provider_preferences["order"] = self.providers_allowed
if self.providers_ignored:
    provider_preferences["ignore"] = self.providers_ignored
if self.providers_order:
    provider_preferences["order"] = self.providers_order
if self.provider_sort:
    provider_preferences["sort"] = self.provider_sort

# Sent to OpenRouter
extra_body["provider"] = provider_preferences
```

### Provider Sorting Options

```python
# sort options
"sort": "price"       # Sort by price
"sort": "throughput"  # Sort by throughput
"sort": "latency"     # Sort by latency
```

## Metadata Cache

```python
# OpenRouter model metadata cache (1 hour TTL)
_model_metadata_cache: dict = {}
_metadata_cache_time: float = 0
_METADATA_CACHE_TTL = 3600  # 1 hour

def fetch_model_metadata(model: str = None) -> dict:
    """Fetches model metadata (with cache)"""
    now = time.time()
    if now - _metadata_cache_time < _METADATA_CACHE_TTL:
        return _model_metadata_cache
    
    # Background thread pre-warms cache
    threading.Thread(
        target=lambda: fetch_model_metadata(),
        daemon=True,
    ).start()
```

## Reasoning Model Support

```python
def _supports_reasoning_extra_body(self) -> bool:
    """Determines if reasoning extra_body can be safely sent"""
    
    # Direct Nous Portal
    if "nousresearch" in self._base_url_lower:
        return True
    
    # OpenRouter routing
    if "openrouter" not in self._base_url_lower:
        return False
    
    # Known prefixes for reasoning-enabled models
    reasoning_model_prefixes = (
        "deepseek/",
        "anthropic/",
        "openai/",
        "x-ai/",
        "google/gemini-2",
        "qwen/qwen3",
    )
    return any(self.model.lower().startswith(prefix) for prefix in reasoning_model_prefixes)
```

## Session State Tracking

```python
# Accumulated token usage
self.session_prompt_tokens = 0
self.session_completion_tokens = 0
self.session_total_tokens = 0
self.session_api_calls = 0
self.session_input_tokens = 0
self.session_output_tokens = 0
self.session_cache_read_tokens = 0
self.session_cache_write_tokens = 0
self.session_reasoning_tokens = 0
self.session_estimated_cost_usd = 0.0
self.session_cost_status = "unknown"
self.session_cost_source = "none"

def reset_session_state(self):
    """Resets all session-level token counters"""
    self.session_total_tokens = 0
    self.session_input_tokens = 0
    self.session_output_tokens = 0
    # ... reset all counters
    self._user_turn_count = 0
```

## New Providers (v0.10.0, 2026-04-16)

### AWS Bedrock (Native Converse API)

Dual-path architecture (`agent/bedrock_adapter.py`, 1098 lines):
- **Claude models** → AnthropicBedrock SDK (retains prompt caching, thinking budgets)
- **Non-Claude models** → Converse API via boto3 (Nova, DeepSeek, Llama, Mistral)

Features:
- IAM credential chain + Bedrock API Key two authentication modes
- `ListFoundationModels` + `ListInferenceProfiles` dynamic model discovery
- Streaming + delta callbacks + guardrails
- `/usage` pricing support for 7 Bedrock models
- `hermes doctor` + `hermes auth` integration

### Google Gemini CLI OAuth

Accesses Gemini via the Cloud Code Assist backend (`cloudcode-pa.googleapis.com`), using the same backend as Google's official `gemini-cli`.

Two new modules (under `agent/`):
- `google_oauth.py` (1048 lines): PKCE Authorization Code flow, inter-process file locks (fcntl POSIX / msvcrt Windows), automatic refresh token renewal, concurrent refresh deduplication
- `gemini_cloudcode_adapter.py`: provider registration, model discovery, streaming

Supports both free tier (personal account daily quota) and paid tier (Standard/Enterprise via GCP project).

### Ollama Cloud

Registered as a built-in provider (on par with gemini, xai, etc.):
- `OLLAMA_API_KEY` environment variable authentication
- Provider aliases: `ollama` → custom (local), `ollama_cloud` → ollama-cloud
- models.dev integration for accurate context length
- Dynamic model discovery + disk cache (1 hour TTL)
- Retains Ollama `model:tag` format (no normalization)

### MiniMax OAuth (v2026.4.23+)

Added `minimax-oauth` as a first-class provider, using PKCE device-code flow (ported from `openclaw/extensions/minimax/oauth.ts`). `hermes_cli/auth.py` additions:

- 8 `MINIMAX_OAUTH_*` constants (client ID, scope, grant type, global/CN base URLs, inference URLs, refresh skew)
- `auth_type="oauth_minimax"` provider type, alongside device-code/external OAuth
- Aliases: `minimax-portal` / `minimax-global` / `minimax_oauth`
- Standard OAuth2 refresh_token grant automatic renewal, `invalid_grant` / `refresh_token_reused` triggers relogin
- Integrates with MiniMax-M2.7 models (`agent/minimax_oauth_provider.py`)

### Step Plan (v2026.4.18+)

StepFun's first API-key provider (Step Plan), supporting international and China region settings. Dynamically discovers models from `/step_plan/v1/models`, with a hardcoded fallback directory for offline use.

### Vercel AI Gateway (v2026.4.18+)

Added `ai-gateway` provider (alias `vercel-ai-gateway`), providing unified access to multiple models via Vercel AI Gateway:
- Custom model list (`VERCEL_AI_GATEWAY_MODELS` in `hermes_cli/models.py`, OSS first, Kimi K2.5 recommended by default)
- Live pricing translation (Vercel input/output → prompt/completion format)
- Automatically prioritizes free Moonshot models in the picker
- Increased sorting priority in provider picker
- Uses Vercel's deep-link to create API key

### OpenRouter Tool Support Filtering (v2026.4.18+)

Hermes-agent is a tool-calling-first agent; only models that support `tools` can drive the agent loop. `fetch_openrouter_models()` now filters out models whose `supported_parameters` explicitly do not include `tools` (e.g., image-only, completion-only models).

Lenient mode: If `supported_parameters` is missing, it's allowed by default (Nous Portal, private mirrors, old snapshots might not populate it). Only models explicitly declared *not* to support `tools` are hidden.

### Tool Gateway (Nous Subscription-based Tool Gateway)

Routes API calls for tools like web search, TTS, browser, image generation to a unified gateway hosted by Nous, eliminating the need for users to provide their own API keys for each service:

```yaml
# config.yaml — Opt-in by tool category
web:
  use_gateway: true
tts:
  use_gateway: true
image_gen:
  use_gateway: true
browser:
  use_gateway: true
```

- `managed_nous_tools_enabled()` checks Nous login status + subscription tier
- `prefers_gateway(section)` shared helper function, used uniformly by 4 tool runtimes
- `hermes model` interaction flow: After Nous login, available tool list is displayed; users can choose to enable all / only unconfigured / skip
- Free tier users see an upgrade prompt

## Relationship with Other Systems

- [[context-compressor-architecture]] — Uses `get_model_context_length()` to determine context limits
- [[prompt-caching-optimization]] — Cached cost information comes from models.dev
- [[auxiliary-client-architecture]] — Auxiliary models resolve context length via models.dev