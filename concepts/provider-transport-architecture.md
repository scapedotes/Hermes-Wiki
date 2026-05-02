```
---
title: Provider Transport Architecture
created: 2026-04-18
updated: 2026-04-18
type: concept
tags: [architecture, module, provider, transport, api-dispatch]
sources: [agent/transports/base.py, agent/transports/anthropic.py, agent/transports/chat_completions.py, agent/transports/bedrock.py, agent/transports/codex.py, agent/transports/types.py, agent/transports/__init__.py, run_agent.py]
---

# Provider Transport — Unified Abstraction for API Paths

## Overview

Provider Transport is an architecture-level refactor introduced in **v2026.4.17+** that unifies the API data paths for all providers (Anthropic Messages, OpenAI Chat Completions, OpenAI Responses API, AWS Bedrock) using a single ABC (Abstract Base Class) abstraction. Located in `agent/transports/` (1217 lines), it replaces the previous `if api_mode == "anthropic_messages": ... elif ...` conditional branches scattered throughout `run_agent.py`.

**Core Principle**: **A provider's message conversion, tool conversion, parameter construction, and response normalization should be aggregated within a single class, rather than dispersed across various call sites.**

## Architectural Principles

### Four Abstract Methods + Three Optional Hooks

```python
# agent/transports/base.py
class ProviderTransport(ABC):
    @property
    @abstractmethod
    def api_mode(self) -> str:
        """The api_mode string handled (e.g., 'anthropic_messages')"""

    @abstractmethod
    def convert_messages(self, messages, **kwargs) -> Any:
        """OpenAI format messages → provider native format"""

    @abstractmethod
    def convert_tools(self, tools) -> Any:
        """OpenAI tool definition → provider native format"""

    @abstractmethod
    def build_kwargs(self, model, messages, tools=None, **params) -> Dict:
        """Assemble complete API call kwargs (usually calls the first two methods internally)"""

    @abstractmethod
    def normalize_response(self, response, **kwargs) -> NormalizedResponse:
        """Raw response → shared NormalizedResponse type (the only method returning a transport layer type)"""

    # ── Optional Hooks ───────────────────────────────────────────
    def validate_response(self, response) -> bool: ...       # Structure validation
    def extract_cache_stats(self, response) -> Optional[Dict]: ...  # Cache hit/create extraction
    def map_finish_reason(self, raw_reason) -> str: ...      # Stop reason mapping
```

**Key Design Points**:
- Transport is **solely responsible for the data path**, not for client lifecycle, streaming, authentication, credential refresh, retry mechanisms, or interrupt handling—these responsibilities reside within `AIAgent`.
- `normalize_response` is the only method that returns a transport layer type (`NormalizedResponse`), while other methods return provider-native structures.

### Implemented Transports

| Transport | File | Lines | api_mode | Coverage |
|-----------|------|-------|----------|----------|
| `AnthropicTransport` | `transports/anthropic.py` | 177 | `anthropic_messages` | Claude (Direct Connect, Nous Portal) |
| `ChatCompletionsTransport` | `transports/chat_completions.py` | 387 | `chat_completions`、`openai` etc. | OpenAI, OpenRouter, Gemini, xAI, custom OpenAI compatible |
| `ResponsesApiTransport` | `transports/codex.py` | 217 | `openai_responses` | OpenAI Codex, Responses API |
| `BedrockTransport` | `transports/bedrock.py` | 154 | `bedrock_converse` | AWS Bedrock (Converse API) |
| `NormalizedResponse` | `transports/types.py` | 142 | — | Shared response type |
| Base Class + Registry | `transports/base.py` + `__init__.py` | 89 + 51 | — | ABC + `get_transport()` lazy discovery |

### Registry: Lazy Discovery

```python
# agent/transports/__init__.py
def get_transport(api_mode: str) -> ProviderTransport:
    """Imports the corresponding transport module on demand, triggering module-level register_transport() call"""
    ...

def register_transport(api_mode: str, transport_cls: type) -> None:
    """Called by transport modules on import to register themselves with the registry"""
    ...
```

Only when `get_transport("anthropic_messages")` is called for the first time is `transports/anthropic.py` imported—**deferring until actual use**, which prevents startup slowdowns caused by eagerly importing a bundle of SDKs.

## Integration Points in run_agent.py

`AnthropicTransport`, `ChatCompletionsTransport`, `BedrockTransport`, `ResponsesApiTransport` have replaced **20+ direct calls to provider adapter functions** in `run_agent.py`:

| Scenario | New Method |
|----------|------------|
| Main kwargs construction (dispatched by api_mode) | `transport.build_kwargs(...)` |
| Memory flush (build_kwargs + normalize) | `_tflush.build_kwargs` / `_tfn.normalize_response` |
| Iteration limit summary + retry | `_tsum.build_kwargs` / `_tsum.normalize_response` |
| Response structure validation | `transport.validate_response` |
| Finish reason mapping (Anthropic stop_reason → OpenAI) | `transport.map_finish_reason` |
| Normalization of truncated responses | `transport.normalize_response` |
| Cache hit/create statistics extraction | `transport.extract_cache_stats` |
| Main normalize loop | `transport.normalize_response` |

All adapter imports within the call paths of transport methods are now fully encapsulated within the transport classes, and `run_agent.py` itself no longer directly imports functions like `anthropic_adapter`.

**Zero direct adapter imports remaining** (referring to the call paths of transport methods).

Auxiliary clients (`agent/auxiliary_client.py`) have also been migrated to the transport layer (for compression, memory flush, and session summarization paths).

## Design Advantages

### Compared to the Old Architecture

| Aspect | Old Approach | Transport ABC |
|--------|--------------|---------------|
| Branching code | `if api_mode == ...` conditionals scattered in `run_agent.py` | Single point `get_transport(api_mode)` |
| Adding new provider | Modify multiple places (conversion, normalize, cache stats...) | Add a new transport subclass |
| Testing | Difficult to test message/tool conversion independently | Each method can be unit-tested independently |
| Circular dependencies | Prone to them | Zero—transport only imports `base` / `types` |
| Startup overhead | Potentially eager import all SDKs | Lazy import, loaded on demand |

### Single Responsibility Principle

- **Transport**: Message/tool format conversion + response normalization
- **AIAgent**: Client lifecycle, streaming, authentication, retry, interrupt handling
- **Adapter** (old code): Retained, delegated to internally by transport, to be gradually deprecated

### Migration Status

| Provider | Transport Coverage | Status |
|----------|--------------------|--------|
| Anthropic | AnthropicTransport (delegates to `anthropic_adapter.py`) | Full path complete |
| Chat Completions (OpenAI compatible) | ChatCompletionsTransport | Full path complete |
| OpenAI Responses API (Codex) | ResponsesApiTransport | Full path complete |
| AWS Bedrock | BedrockTransport | Full path complete |
| Auxiliary Client (Compression/Memory) | Migrated to Transport | Complete |

## Relationship with Other Systems

- [[auxiliary-client-architecture]] — `auxiliary_client` has been migrated to Transport
- [[smart-model-routing]] — Transport dispatches based on `api_mode`, cooperating with model routing
- [[interrupt-and-fault-tolerance]] — Interrupt and retry mechanisms remain in the AIAgent layer, not within transport's responsibility
- [[prompt-caching-optimization]] — Cache statistics are exposed via the `extract_cache_stats` hook

## Related Files

- `agent/transports/base.py` (89 lines) — `ProviderTransport` ABC
- `agent/transports/types.py` (142 lines) — `NormalizedResponse` shared type
- `agent/transports/__init__.py` (51 lines) — Registry + lazy discovery
- `agent/transports/anthropic.py` (177 lines) — Anthropic Messages
- `agent/transports/chat_completions.py` (387 lines) — Chat Completions
- `agent/transports/codex.py` (217 lines) — OpenAI Responses API
- `agent/transports/bedrock.py` (154 lines) — AWS Bedrock Converse
- `run_agent.py` — 10+ integration points
- `agent/auxiliary_client.py` — Auxiliary paths migrated
```