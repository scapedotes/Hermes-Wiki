---
title: Handling Large Tool Results and Context Protection
created: 2026-04-07
updated: 2026-04-11
type: concept
tags: [architecture, context-management, performance]
sources: [tools/tool_result_storage.py, tools/budget_config.py, run_agent.py]
---

# Handling Large Tool Results and Context Protection

## Design Principles

Tools may return large results (e.g., `search_files` searching an entire codebase, `terminal` executing commands with lengthy output). If these are directly inserted into the conversation history, they quickly consume the context window. Hermes implements an **intelligent externalization mechanism** that saves large results to disk, retaining only a preview.

## Three-Layer Overflow Protection

Large tool results are progressively protected by a three-layer mechanism (`tools/tool_result_storage.py` + `tools/budget_config.py`):

```text
Layer 1: In-tool Truncation        — Each tool pre-truncates its own output (e.g., search_files)
Layer 2: Single Result Persistence  — Exceeds 100K characters → written to sandbox disk, context retains only 1.5K preview
Layer 3: Turn Aggregation Budget   — Total of all results in a single turn exceeds 200K → largest result overflows to disk
```

### Threshold Configuration (`tools/budget_config.py`)

```python
DEFAULT_RESULT_SIZE_CHARS  = 100_000   # Layer 2: Single result persistence threshold
DEFAULT_TURN_BUDGET_CHARS  = 200_000   # Layer 3: Turn aggregation limit
DEFAULT_PREVIEW_SIZE_CHARS = 1_500     # Inline preview size after persistence

# read_file is pinned to ∞ to prevent "persist -> read -> re-persist" infinite loop
PINNED_THRESHOLDS = {"read_file": float("inf")}
```

Threshold parsing priority: `PINNED_THRESHOLDS > tool_overrides > registry per-tool > default`

### Layer 2: Single Result Persistence (`maybe_persist_tool_result()`)

After a tool returns, if the output exceeds the threshold:
1. The full result is written to `/tmp/hermes-results/{tool_use_id}.txt` in the sandbox via `env.execute()`
2. The context content is replaced with a `<persisted-output>` tag, including a 1,500-character preview + file path
3. The agent can access the full output via `read_file`
4. If sandbox writing fails, it falls back to inline truncation

### Layer 3: Turn Aggregation Budget (`enforce_turn_budget()`)

If multiple medium-sized results in a single turn collectively exceed 200K characters:
- Unpersisted results are sorted by size in descending order
- They are overflowed to disk one by one until the total volume is below the budget

This layer addresses scenarios where "individual results don't exceed the limit, but their aggregate does."

## Context Window Protection

### Pre-flight Compression

```python
# Before entering the main loop, check if the loaded conversation history has exceeded the context threshold
if (
    self.compression_enabled
    and len(messages) > self.context_compressor.protect_first_n
                    + self.context_compressor.protect_last_n + 1
):
    # Includes tool schema tokens — can add 20-30K+ tokens with multiple tools
    _preflight_tokens = estimate_request_tokens_rough(
        messages,
        system_prompt=active_system_prompt or "",
        tools=self.tools or None,
    )
    
    if _preflight_tokens >= self.context_compressor.threshold_tokens:
        # Proactively compress instead of waiting for API errors
        for _pass in range(3):  # Max 3 passes
            _orig_len = len(messages)
            messages, active_system_prompt = self._compress_context(...)
            if len(messages) >= _orig_len:
                break  # Cannot compress further
            if _preflight_tokens < self.context_compressor.threshold_tokens:
                break  # Already below threshold
```

### 413 Error Handling

```python
is_payload_too_large = (
    status_code == 413
    or 'request entity too large' in error_msg
    or 'payload too large' in error_msg
)

if is_payload_too_large:
    compression_attempts += 1
    if compression_attempts > max_compression_attempts:
        return {"error": "Request payload too large: max compression attempts reached."}
    
    # Attempt compression and retry
    messages, active_system_prompt = self._compress_context(...)
    if len(messages) < original_len:
        time.sleep(2)  # Brief pause after compression
        restart_with_compressed_messages = True
        break
```

### Context Length Error Detection

```python
is_context_length_error = any(phrase in error_msg for phrase in [
    'context length', 'context size', 'maximum context',
    'token limit', 'too many tokens', 'reduce the length',
    'exceeds the limit', 'context window',
    'request entity too large',  # OpenRouter/Nous 413 fallback
    'prompt is too long',  # Anthropic
    'prompt exceeds max length',  # Z.AI / GLM
])

# Heuristic: Anthropic sometimes returns a generic 400 error
if not is_context_length_error and status_code == 400:
    ctx_len = getattr(self.context_compressor, 'context_length', 200000)
    is_large_session = approx_tokens > ctx_len * 0.4 or len(api_messages) > 80
    is_generic_error = len(error_msg.strip()) < 30
    if is_large_session and is_generic_error:
        is_context_length_error = True  # Considered as context overflow

# Server disconnection can also be due to excessive context
if not is_context_length_error and not status_code:
    _is_server_disconnect = (
        'server disconnected' in error_msg
        or 'peer closed connection' in error_msg
    )
    if _is_server_disconnect and approx_tokens > ctx_len * 0.6:
        is_context_length_error = True  # Considered as context overflow
```

### 429 Long Context Tier Error

```python
# Anthropic returns 429 "Extra usage is required for long context requests"
# When Claude Max subscription does not include 1M context tier
_is_long_context_tier_error = (
    status_code == 429
    and "extra usage" in error_msg
    and "long context" in error_msg
    and "sonnet" in self.model.lower()
)

if _is_long_context_tier_error:
    _reduced_ctx = 200000  # Downgrade to standard 200K tier
    compressor.context_length = _reduced_ctx
    compressor.threshold_tokens = int(_reduced_ctx * compressor.threshold_percent)
    # Not persisted — this is a subscription tier limit, not a model capability
    compressor._context_probe_persistable = False
```

## Agent Safe Writing

```python
class _SafeWriter:
    """Transparent stdio wrapper that catches broken pipe OSError/ValueError"""
    
    def write(self, data):
        try:
            return self._inner.write(data)
        except (OSError, ValueError):
            return len(data) if isinstance(data, str) else 0
    
    def flush(self):
        try:
            self._inner.flush()
        except (OSError, ValueError):
            pass

def _install_safe_stdio() -> None:
    """Wraps stdout/stderr to ensure best-effort console output doesn't crash the Agent"""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and not isinstance(stream, _SafeWriter):
            setattr(sys, stream_name, _SafeWriter(stream))
```

**Why is this needed?**
- In `systemd` services/Docker containers, `stdout/stderr` pipes might be unavailable
- After a sub-agent thread exits, the shared `stdout` handle might be closed
- Prevents `OSError: [Errno 5] Input/output error` from crashing the Agent

## Surrogate Character Cleaning

```python
_SURROGATE_RE = re.compile(r'[\ud800-\udfff]')

def _sanitize_surrogates(text: str) -> str:
    """Replaces lone surrogate code points with U+FFFD (Replacement Character)"""
    if _SURROGATE_RE.search(text):
        return _SURROGATE_RE.sub('\ufffd', text)
    return text

# Surrogates are invalid in UTF-8 and will crash json.dumps() in the OpenAI SDK
def _sanitize_messages_surrogates(messages: list) -> bool:
    """Cleans surrogate characters from all string content in the message list"""
    found = False
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str) and _SURROGATE_RE.search(content):
            msg["content"] = _SURROGATE_RE.sub('\ufffd', content)
            found = True
    return found
```

**Why is this needed?**
- Pasting rich text from clipboards (Google Docs, Word) can inject lone surrogates
- Can cause JSON serialization to crash

## Budget Warning Cleaning

```python
_BUDGET_WARNING_RE = re.compile(
    r"\[BUDGET(?:\s+WARNING)?:\s+Iteration\s+\d+/\d+\..*?\]",
    re.DOTALL,
)

def _strip_budget_warnings_from_history(messages: list) -> None:
    """Removes budget pressure warnings from tool result messages"""
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue
        content = msg.get("content")
        if not isinstance(content, str) or "_budget_warning" not in content and "[BUDGET" not in content:
            continue
        
        # Attempt JSON parsing (common case)
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict) and "_budget_warning" in parsed:
                del parsed["_budget_warning"]
                msg["content"] = json.dumps(parsed, ensure_ascii=False)
                continue
        except (json.JSONDecodeError, TypeError):
            pass
        
        # Fallback: Remove pattern from plain text tool results
        cleaned = _BUDGET_WARNING_RE.sub("", content).strip()
        if cleaned != content:
            msg["content"] = cleaned
```

**Why is this needed?**
- Budget warnings are **turn-scoped** signals and should not leak into replay history
- GPT models might interpret them as still-active instructions, preventing tool calls in all subsequent turns

## Superiority Analysis

### Context Savings

| Scenario             | Unprotected | Protected           | Savings   |
|----------------------|-------------|---------------------|-----------|
| Large Search Output  | 100K chars  | 1.5K + file reference | ~98.5%    |
| Long Terminal Output | 50K chars   | 1.5K + file reference | ~97%      |
| Pre-flight Compression | Waits for API errors | Proactive compression | Avoids failures |

### Comparison with Other Agent Frameworks

| Feature                 | Hermes        | Cursor      | OpenCode    |
|-------------------------|---------------|-------------|-------------|
| Large Result Externalization | ✅ Automatic  | ✅ Automatic | ❌ Truncation |
| Configurable Thresholds | ✅ BudgetConfig | ❌ Fixed    | N/A         |
| Pre-flight Compression  | ✅            | ✅          | ❌          |
| Surrogate Cleaning      | ✅            | ❌          | ❌          |
| Budget Warning Cleaning | ✅            | N/A         | N/A         |
| Safe stdio              | ✅            | N/A         | N/A         |

## Related Pages

- [[context-compressor-architecture]] — Context Compression and Pre-flight Compression Mechanism
- [[parallel-tool-execution]] — Scenarios involving large results from parallel tool execution
- [[model-tools-dispatch]] — Tool results processed with a unified format

## Related Files

- `tools/tool_result_storage.py` — Three-Layer Overflow Protection (Layer 2 + Layer 3)
- `tools/budget_config.py` — Threshold Configuration and Priority Resolution
- `run_agent.py` — Surrogate Cleaning, Budget Warning Cleaning
- `agent/context_compressor.py` — Context Compression
