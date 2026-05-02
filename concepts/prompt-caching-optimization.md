---
title: Prompt Caching Optimization Architecture
created: 2026-04-07
updated: 2026-04-08
type: concept
tags: [architecture, module, performance, cost-optimization, anthropic]
sources: [agent/prompt_caching.py, run_agent.py]
---

# Prompt Caching — Anthropic Cache Optimization Architecture

## Overview

Prompt Caching, located at `agent/prompt_caching.py` (2KB/72 lines), implements the **Anthropic `system_and_3` caching strategy**, reducing input token costs by approximately 75% in multi-turn conversations.

Core philosophy: **A maximum of 4 `cache_control` breakpoints — system prompt + last 3 non-system messages.**

## Architectural Principles

### system_and_3 Strategy

Anthropic's prompt cache allows marking `cache_control` breakpoints within messages. Content before a breakpoint is cached, and subsequent requests hitting the cache incur only a minimal `cache_read` fee (approximately 10% of the normal cost).

Anthropic limits to a **maximum of 4 breakpoints**, with Hermes' allocation strategy as follows:

| Breakpoint | Location | Cached Content | Stability |
|---|---|---|---|
| 1 | System Prompt | Identity + Platform Prompt + Skill Index | Highest (unchanged across all turns) |
| 2 | 3rd to last message | Early conversation content | High (unchanged for the first 2 turns) |
| 3 | 2nd to last message | Mid-conversation content | Medium (unchanged for the first 1 turn) |
| 4 | Last message | Most recent conversation content | Low (rolls every turn) |

### Sliding Window Mechanism

```
Turn 1: [System Prompt★] [User1★] [Assistant1] [Assistant2]
                        ↑Breakpoint 2 ↑Breakpoint 3 ↑Breakpoint 4

Turn 2: [System Prompt★] [User1] [Assistant1★] [User2★] [Assistant2★]
                        ↑New Breakpoint 2 ↑New Breakpoint 3 ↑New Breakpoint 4

Turn 3: [System Prompt★] [User1] [Assistant1] [User2] [Assistant2★] [User3★] [Assistant3★]
                                                      ↑New Breakpoint 2 ↑New Breakpoint 3 ↑New Breakpoint 4
```

★ = `cache_control` marker. The breakpoint window slides backward with each new request.

## Core Components

### 1. `cache_control` Marker Injection

```python
def _apply_cache_marker(msg, cache_marker, native_anthropic=False):
    """
    Handles all message format variants:
    
    1. tool role → Marked only in native_anthropic mode
    2. Empty content → Marked directly at the message level
    3. String content → Converted to [{"type": "text", "text": ..., "cache_control": ...}]
    4. List content → cache_control added to the last element
    """
```

**Design Considerations**: The Anthropic API accepts various message formats (strings, lists of objects, tool results); `_apply_cache_marker` handles all formats uniformly.

### 2. Main Function

```python
def apply_anthropic_cache_control(
    api_messages,
    cache_ttl="5m",        # Cache TTL: 5 minutes or 1 hour
    native_anthropic=False # Whether to use native Anthropic format
):
    """
    1. Deep-copy messages (to avoid modifying original data)
    2. Create marker: {"type": "ephemeral"} or {"type": "ephemeral", "ttl": "1h"}
    3. Add breakpoint to the system prompt (if it's the first message)
    4. Find the last 3 non-system messages from the end, and add breakpoints
    5. Return the list of marked messages
    """
```

### 3. Handling Different Roles

| Role | Caching Strategy |
|---|---|
| system | Always marked (most stable cache point) |
| tool | Marked at message level only in `native_anthropic` mode |
| assistant/user | Marked on the last element of the content |

## TTL Configuration

```python
marker = {"type": "ephemeral"}         # Default: 5 minute TTL
marker = {"type": "ephemeral", "ttl": "1h"}  # 1 hour TTL
```

**Use Cases**:
- **5m (Default)**: Suitable for rapid, continuous conversations, leading to a high cache hit rate
- **1h**: Suitable for longer conversation intervals, tolerating a higher cache miss rate

## Cost-Benefit Analysis

Assumptions: System prompt 2000 tokens, average 5000 tokens per conversation:

| Scenario | Cost without Caching | Cost with Cache Hit | Savings |
|---|---|---|---|
| Single turn (System Prompt + 1 message) | ~7000 tokens × price | ~2000 tokens × cache_read + 5000 × normal | ~70% |
| 10 conversation turns | 10 × 7000 = 70K tokens | ~2000 × cache_read + (70K-2000) × normal | ~75% |
| 50 conversation turns | 50 × 7000 = 350K tokens | ~2000 × cache_read + (350K-2000) × normal | ~85% |

## Design Superiority

### Comparison with Non-Caching Solution

| Dimension | Without Caching | Prompt Caching |
|---|---|---|
| System Prompt Cost | Paid every time | Paid only for the first time |
| Early Conversation Cost | Paid every time | Paid only for `cache_read` on hit |
| Latency | No impact | Reduced on cache hit |
| Code Complexity | Low | 72 lines pure function |
| Applicable Scenarios | All models | Anthropic models only |

### Pure Function Design

```python
# No class state, no AIAgent dependencies
# Input message list → Output marked message list
# Deep copy ensures original data is not modified
```

This allows the caching logic to be tested independently without affecting the main conversation flow.

## Integration Points

Prompt caching is invoked in `_build_api_kwargs()` within `run_agent.py`:
1. Build the complete message list
2. If the current provider is Anthropic → Call `apply_anthropic_cache_control()`
3. If `developer_role` needs to be switched → Convert system messages to the developer role
4. Send to API

## Relationship with Other Systems

- [[smart-model-routing]] — Cache cost information is sourced from models.dev
- [[auxiliary-client-architecture]] — Auxiliary models do not use prompt caching
- [[context-compressor-architecture]] — Context compression reduces the number of messages, indirectly affecting cache breakpoint positions