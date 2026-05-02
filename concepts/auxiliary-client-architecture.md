---
title: Auxiliary Client — Auxiliary Client Architecture
created: 2026-04-08
updated: 2026-04-08
type: concept
tags: [architecture, module, component, agent, tool]
sources: [agent/auxiliary_client.py]
---

# Auxiliary Client — Auxiliary Client Architecture

## Overview

The Auxiliary Client, located at `agent/auxiliary_client.py` (85KB/2127 lines), is the **auxiliary LLM client router** for Hermes Agent. It provides a unified provider resolution and invocation interface for all non-primary-dialogue LLM tasks (e.g., context compression, session search summarization, visual analysis, web extraction, skill snapshot generation).

Core philosophy: **All auxiliary tasks share the same provider resolution chain, preventing each consumer from repeatedly implementing fallback logic.**

## Architectural Principles

### Design Goals

Auxiliary tasks differ from primary dialogue in several ways:
- **Cost-sensitive**: Does not require the most expensive models; quick and inexpensive options are sufficient.
- **High reliability requirements**: A single provider's payment issues should not render an entire feature unusable.
- **Multimodal requirements**: Some tasks require vision capabilities.
- **Asynchronous support**: Tasks like web extraction require asynchronous operations.

The Auxiliary Client addresses these issues through **multi-layered provider resolution + automatic fallback + client caching**.

### Provider Resolution Chain (Text Tasks)

```
Priority (auto mode):
  1. Main provider (if not an aggregator) → Directly use main model credentials
  2. OpenRouter (OPENROUTER_API_KEY)
  3. Nous Portal (active provider in ~/.hermes/auth.json)
  4. Custom endpoint (config.yaml model.base_url + OPENAI_API_KEY)
  5. Codex OAuth (Responses API, gpt-5.2-codex)
  6. Native Anthropic
  7. Direct API Key providers (z.ai/GLM, Kimi/Moonshot, MiniMax, etc.)
  8. None → Feature unavailable
```

**Key Design**: If the user's main provider is a non-aggregator like Alibaba, DeepSeek, ZAI, etc., the Auxiliary Client will **directly use the main provider's credentials**, without requiring additional OpenRouter key configuration. This significantly lowers the barrier to entry.

### Provider Resolution Chain (Vision Tasks)

```
  1. Main provider (if it's a supported vision backend)
  2. OpenRouter
  3. Nous Portal
  4. Codex OAuth (gpt-5.2-codex supports vision)
  5. Native Anthropic
  6. Custom endpoint (local vision models: Qwen-VL, LLaVA, Pixtral)
  7. None
```

## Core Components

### 1. Adapter Layer (Adapter Pattern)

The Auxiliary Client's most significant architectural highlight is the **Adapter Pattern**—it unifies all disparate API formats to behave as the `client.chat.completions.create()` interface.

#### Codex Responses API Adapter

```python
class _CodexCompletionsAdapter:
    """Drop-in shim: Accepts chat.completions.create() kwargs,
    routes to Codex Responses streaming API"""

class CodexAuxiliaryClient:
    """OpenAI client-compatible wrapper, routing via Codex Responses API"""
```

**Conversion Details**:
- chat.completions `content` format → Responses API `input` format
- `{"type": "text", "text": "..."}` → `{"type": "input_text", "text": "..."}`
- `{"type": "image_url", ...}` → `{"type": "input_image", ...}`
- Streaming response → Collect output items + text deltas → Reconstruct chat.completions format
- Supports tool calls (function_call)
- When `get_final_response()` returns empty, fill from stream events.

#### Anthropic Messages API Adapter

```python
class _AnthropicCompletionsAdapter:
    """OpenAI client-compatible wrapper, based on native Anthropic client"""
```

Bi-directional conversion is achieved through `build_anthropic_kwargs` and `normalize_anthropic_response` in `agent.anthropic_adapter`.

#### Asynchronous Adapter

```python
class _AsyncCodexCompletionsAdapter:
    """Wraps synchronous adapter via asyncio.to_thread()"""

class AsyncCodexAuxiliaryClient:
    """Asynchronous wrapper matching AsyncOpenAI.chat.completions.create()"""
```

### 2. Central Router (`resolve_provider_client`)

```python
def resolve_provider_client(
    provider: str,          # "openrouter", "nous", "openai-codex", "auto"...
    model: str = None,      # Model override
    async_mode: bool = False,
    raw_codex: bool = False,
    explicit_base_url: str = None,
    explicit_api_key: str = None,
) -> Tuple[client, resolved_model]:
```

**Single Entry Point**: All auxiliary consumers should obtain clients via this function or public auxiliary functions; temporary lookup of authentication environment variables is forbidden.

### 3. Auto-detection (`_resolve_auto`)

```python
def _resolve_auto():
    # Step 1: Non-aggregator main provider → Directly use main model
    main_provider = _read_main_provider()
    if main_provider not in {"openrouter", "nous"}:
        client, resolved = resolve_provider_client(main_provider, main_model)
        if client: return client, resolved
    
    # Step 2: Aggregator/Fallback chain
    for label, try_fn in _get_provider_chain():
        client, model = try_fn()
        if client: return client, model
```

**Superiority**: Prioritizes the main provider (reduces additional configuration), then proceeds through the fallback chain (ensures reliability).

### 4. Task-Level Configuration System

```python
def _resolve_task_provider_model(task, provider, model, base_url, api_key):
    """
    Priority:
      1. Explicit parameters (provider/model/base_url/api_key)
      2. Environment variable overrides (AUXILIARY_{TASK}_*, CONTEXT_{TASK}_*)
      3. Configuration file (auxiliary.{task}.* or compression.*)
      4. "auto" (complete auto-detection chain)
    """
```

**Flexibility**: Each task can independently configure its provider, model, base_url, and api_key.

### 5. Client Caching and Event Loop Management

```python
_client_cache: Dict[tuple, tuple] = {}
_client_cache_lock = threading.Lock()
```

**Caching Strategy**:
- Key: `(provider, async_mode, base_url, api_key, loop_id)`
- Asynchronous clients include an **event loop ID** to prevent deadlocks from cross-loop reuse.
- Automatically cleans up expired cache entries when a loop closure is detected.

**Event Loop Safety Measures**:
```python
def neuter_async_httpx_del():
    """Disables aclose() scheduling of AsyncHttpxClientWrapper.__del__
    
    When an AsyncOpenAI client is GC'd, __del__ schedules aclose()
    on prompt_toolkit's event loop, but the underlying TCP transport
    is bound to another loop, leading to RuntimeError("Event loop is closed").
    """
    AsyncHttpxClientWrapper.__del__ = lambda self: None

def cleanup_stale_async_clients():
    """Cleans up stale asynchronous clients after each agent loop"""
    
def shutdown_cached_clients():
    """Cleans up all cached clients before CLI shutdown"""
```

This is critical code for Hermes Agent to resolve compatibility issues between **prompt_toolkit and the async OpenAI SDK**.

### 6. Automatic Fallback for Payment/Quota Exhaustion

```python
def _is_payment_error(exc: Exception) -> bool:
    """Detects HTTP 402 and insufficient balance errors"""
    if status_code == 402: return True
    if "credits" in err or "insufficient funds" in err: return True
    if "can only afford" in err or "billing" in err: return True

def _try_payment_fallback(failed_provider, task):
    """Skips the failed provider, attempts the next available provider in the chain"""
```

**Workflow**:
1. Invoke LLM API.
2. If a `max_tokens` parameter error is encountered → Retries using `max_completion_tokens`.
3. If a payment error (402/insufficient balance) is encountered → Automatically switches to the next available provider.
4. Logs a message to notify the user of the fallback.

### 7. Public API

| Function | Purpose |
|---|---|
| `get_text_auxiliary_client(task)` | Gets a synchronous client for text tasks |
| `get_async_text_auxiliary_client(task)` | Gets an asynchronous client for text tasks |
| `get_vision_auxiliary_client()` | Gets a synchronous client for vision tasks |
| `get_async_vision_auxiliary_client()` | Gets an asynchronous client for vision tasks |
| `call_llm(task, messages, ...)` | Central synchronous LLM invocation entry point |
| `async_call_llm(task, messages, ...)` | Central asynchronous LLM invocation entry point |
| `extract_content_or_reasoning(response)` | Extracts response content, supports reasoning models |
| `get_available_vision_backends()` | Gets a list of currently available vision backends |
| `get_auxiliary_extra_body()` | Gets provider-specific `extra_body` |
| `auxiliary_max_tokens_param(value)` | Returns the correct `max_tokens` parameter name |

## Design Superiority

### Comparison with Decentralized Approach

| Dimension | Decentralized Approach (Each consumer implements independently) | Auxiliary Client (Centralized) |
|---|---|---|
| Authentication Logic | Each file reads env/config independently | Resolved in one place, used everywhere |
| Fallback | Each consumer implements its own | Unified fallback chain |
| Payment Fallback | Typically missing | Automatic detection + switching |
| Client Caching | Duplicate connection creation | Shared cache, reduces overhead |
| Event Loop Safety | Prone to oversight | Unified management |
| New Provider Integration | Requires modifying N files | Only needs adding a `try_*` function |

### Superiority of Adapter Pattern

- **Caller Agnosticism**: `context_compressor`, `web_tools`, `session_search` all just call `client.chat.completions.create()`, without needing to know if the underlying API is Chat Completions, Responses API, or Messages API.
- **Testability**: Each adapter can be tested independently.
- **Extensibility**: New API formats only require adding an adapter class.

## Configuration and Operation

### config.yaml Configuration

```yaml
auxiliary:
  compression:
    provider: auto        # or openrouter, nous, custom
    model: gemini-3-flash
    timeout: 30
  vision:
    provider: auto
    model: claude-sonnet-4-5-20250514
  web_extract:
    provider: openrouter
    model: google/gemini-3-flash-preview
    api_key: sk-xxx
    base_url: https://custom-endpoint.com/v1
```

### Environment Variable Overrides

```bash
# Set provider for a specific task
export AUXILIARY_VISION_PROVIDER=anthropic
export AUXILIARY_COMPRESSION_MODEL=claude-haiku-4-5
export AUXILIARY_WEB_EXTRACT_BASE_URL=https://my-endpoint/v1
export AUXILIARY_WEB_EXTRACT_API_KEY=sk-xxx
```

### Viewing Available Vision Backends

```python
from agent.auxiliary_client import get_available_vision_backends
print(get_available_vision_backends())
# Output: ['openrouter', 'nous', 'anthropic'] (depending on configuration)
```

## Relationship with Other Systems

- [[context-compressor-architecture]] — Uses `get_text_auxiliary_client("compression")`
- [[tool-registry-architecture]] — `web_tools` and `browser_tool` are registered via the registry
- [[credential-pool-and-isolation]] — Uses `load_pool()` to obtain credentials
- [[prompt-builder-architecture]] — The Auxiliary Client is not involved in primary dialogue prompt construction
- [[model-tools-dispatch]] — `model_tools.py` handles side tasks via the Auxiliary Client
