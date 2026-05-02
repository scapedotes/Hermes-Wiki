---
title: Interrupt Propagation and Fault Tolerance Mechanisms
created: 2026-04-07
updated: 2026-04-15
type: concept
tags: [architecture, reliability, fault-tolerance, interrupt]
sources: [run_agent.py, gateway/run.py, agent/error_classifier.py, tools/credential_pool.py]
---

# Interrupt Propagation and Fault Tolerance Mechanisms

## Design Principles

Agents may execute long-running tasks (multiple tool calls, sub-agent delegation). Users need to be able to:
1. **Interrupt current operations** — by sending a new message or pressing Ctrl+C
2. **Gracefully handle failures** — API errors, network disconnections, expired credentials
3. **Automatically recover** — retry, fallback, credential rotation

Hermes implements a **multi-layered interrupt and fault tolerance mechanism**.

## Interrupt Mechanism

### Interrupt Flag

```python
class AIAgent:
    def __init__(self):
        self._interrupt_requested = False
        self._interrupt_message = None
    
    @property
    def is_interrupted(self) -> bool:
        """Checks if an interrupt has been requested."""
        return self._interrupt_requested
    
    def clear_interrupt(self):
        """Clears the interrupt state."""
        self._interrupt_requested = False
        self._interrupt_message = None
```

### Interrupt Propagation to Sub-agents

```python
# Parent agent can interrupt all child agents
def _propagate_interrupt(self):
    with self._active_children_lock:
        for child in self._active_children:
            child._interrupt_requested = True
```

### API Call Interruption

```python
def _interruptible_api_call(self, api_kwargs: dict):
    """Runs the API call in a background thread, allowing the main loop to detect interrupts."""
    
    result = {"response": None, "error": None}
    request_client_holder = {"client": None}
    
    def _call():
        try:
            if self.api_mode == "codex_responses":
                request_client_holder["client"] = self._create_request_openai_client(...)
                result["response"] = self._run_codex_stream(...)
            elif self.api_mode == "anthropic_messages":
                result["response"] = self._anthropic_messages_create(api_kwargs)
            else:
                request_client_holder["client"] = self._create_request_openai_client(...)
                result["response"] = request_client_holder["client"].chat.completions.create(**api_kwargs)
        except Exception as e:
            result["error"] = e
        finally:
            # Clean up the request client
            request_client = request_client_holder.get("client")
            if request_client is not None:
                self._close_request_openai_client(request_client, reason="request_complete")
    
    t = threading.Thread(target=_call, daemon=True)
    t.start()
    
    while t.is_alive():
        t.join(timeout=0.3)  # Check for interrupt every 300ms
        if self._interrupt_requested:
            # Force close ongoing HTTP connections
            try:
                if self.api_mode == "anthropic_messages":
                    self._anthropic_client.close()
                    self._anthropic_client = build_anthropic_client(...)
                else:
                    request_client = request_client_holder.get("client")
                    if request_client is not None:
                        self._close_request_openai_client(request_client, reason="interrupt_abort")
            except Exception:
                pass
            raise InterruptedError("Agent interrupted during API call")
    
    if result["error"] is not None:
        raise result["error"]
    return result["response"]
```

### Main Loop Interrupt Check

```python
while api_call_count < self.max_iterations and self.iteration_budget.remaining > 0:
    # Check for interrupt request
    if self._interrupt_requested:
        interrupted = True
        if not self.quiet_mode:
            self._safe_print("⚠️ Interrupted by user")
        break
    
    # ... Normal processing
```

### Streaming API Call Interruption

```python
def _interruptible_streaming_api_call(self, api_kwargs: dict, ...):
    """Streaming variant, supports real-time token delivery."""
    
    for chunk in stream:
        if self._interrupt_requested:
            break  # Stop receiving stream
        
        # ... Process chunk
    
    # Cleanup
    if self._interrupt_requested:
        raise InterruptedError("Agent interrupted during streaming")
```

## Fault Tolerance Mechanism

### Credential Pool Rotation

```python
def _recover_with_credential_pool(self, *, status_code, has_retried_429, ...):
    """Attempts to recover by rotating through the credential pool."""
    
    pool = self._credential_pool
    if pool is None or status_code is None:
        return False, has_retried_429
    
    if status_code == 402:
        # Billing exhausted — rotate immediately
        next_entry = pool.mark_exhausted_and_rotate(status_code=402, ...)
        if next_entry is not None:
            self._swap_credential(next_entry)
            return True, False
    
    if status_code == 429:
        if not has_retried_429:
            return False, True  # First 429, retry with the same credential
        # Second 429, rotate to the next credential
        next_entry = pool.mark_exhausted_and_rotate(status_code=429, ...)
        if next_entry is not None:
            self._swap_credential(next_entry)
            return True, False
    
    if status_code == 401:
        # Attempt to refresh current credential
        refreshed = pool.try_refresh_current()
        if refreshed is not None:
            self._swap_credential(refreshed)
            return True, has_retried_429
        # Refresh failed — rotate to the next credential
        next_entry = pool.mark_exhausted_and_rotate(status_code=401, ...)
        if next_entry is not None:
            self._swap_credential(next_entry)
            return True, False
    
    return False, has_retried_429
```

### Fallback Model Chain

```python
# Configuration example
fallback_chain:
  - model: "anthropic/claude-opus-4.6"
    provider: "anthropic"
  - model: "openai/gpt-4o"
    provider: "openrouter"
  - model: "google/gemini-2.5-pro"
    provider: "openrouter"

def _try_activate_fallback(self):
    """Activates the next fallback model."""
    if self._fallback_index >= len(self._fallback_chain):
        return False  # No more fallback
    
    fallback = self._fallback_chain[self._fallback_index]
    self._fallback_index += 1
    
    # Switch model/credential
    self.model = fallback["model"]
    self.provider = fallback["provider"]
    # ... Rebuild client
    
    return True
```

### Structured Error Classification (error_classifier.py)

A centralized error classifier, introduced on 2026-04-09, replaces the scattered string matching in `run_agent.py`. All API errors are categorized into 13 `FailoverReason` types, each corresponding to a different recovery strategy:

| Error Type | Recovery Strategy |
|---|---|
| `auth` | Refresh/rotate credentials |
| `billing` | Switch Provider immediately |
| `rate_limit` | Backoff and wait, then rotate |
| `context_overflow` | Compress context |
| `payload_too_large` | Compress payload |
| `timeout` | Rebuild client + retry |
| `model_not_found` | Fallback to other models |
| `server_error` / `overloaded` | Retry / Backoff |
| `thinking_signature` | Invalid Anthropic thinking block signature |
| `long_context_tier` | Downgrade to 200K standard tier |

The classification result is a structured `ClassifiedError`, containing recovery hints:

```python
@dataclass
class ClassifiedError:
    reason: FailoverReason
    retryable: bool = True
    should_compress: bool = False
    should_rotate_credential: bool = False
    should_fallback: bool = False
```

The retry loop directly reads these field decisions, eliminating redundant error message parsing.

### Connection Health Check

```python
def _cleanup_dead_connections(self) -> bool:
    """Detects and cleans up dead TCP connections resulting from provider failures."""
    
    # Check for dead connections in the shared connection pool
    cleaned = 0
    for conn in self._connection_pool:
        if not conn.is_healthy():
            conn.close()
            cleaned += 1
    
    return cleaned > 0

# Check before each conversation turn
if self.api_mode != "anthropic_messages":
    try:
        if self._cleanup_dead_connections():
            self._emit_status(
                "🔌 Detected stale connections from a previous provider "
                "issue — cleaned up automatically."
            )
    except Exception:
        pass
```

### Automatic Credential Refresh

```python
def _try_refresh_nous_client_credentials(self, *, force: bool = True) -> bool:
    """Refreshes Nous Portal credentials."""
    try:
        creds = resolve_nous_runtime_credentials(
            min_key_ttl_seconds=max(60, int(os.getenv("HERMES_NOUS_MIN_KEY_TTL_SECONDS", "1800"))),
            timeout_seconds=float(os.getenv("HERMES_NOUS_TIMEOUT_SECONDS", "15")),
            force_mint=force,
        )
    except Exception:
        return False
    
    api_key = creds.get("api_key")
    base_url = creds.get("base_url")
    if not isinstance(api_key, str) or not api_key.strip():
        return False
    
    self.api_key = api_key.strip()
    self.base_url = base_url.strip().rstrip("/")
    self._client_kwargs["api_key"] = self.api_key
    self._client_kwargs["base_url"] = self.base_url
    
    return self._replace_primary_openai_client(reason="nous_credential_refresh")

def _try_refresh_anthropic_client_credentials(self) -> bool:
    """Refreshes Anthropic credentials (OAuth token rotation)."""
    if self.api_mode != "anthropic_messages" or self.provider != "anthropic":
        return False
    
    try:
        new_token = resolve_anthropic_token()
    except Exception:
        return False
    
    if not isinstance(new_token, str) or not new_token.strip():
        return False
    if new_token == self._anthropic_api_key:
        return False  # No change
    
    self._anthropic_client.close()
    self._anthropic_client = build_anthropic_client(new_token, self._anthropic_base_url)
    self._anthropic_api_key = new_token
    
    # Update OAuth flag — token type may have changed
    self._is_anthropic_oauth = _is_oauth_token(new_token)
    return True
```

## Activity Tracking

```python
# Used for Gateway timeout handler and "still working" notifications
self._last_activity_ts: float = time.time()
self._last_activity_desc: str = "initializing"
self._current_tool: str | None = None
self._api_call_count: int = 0

def _touch_activity(self, description: str):
    """Updates the activity timestamp."""
    self._last_activity_ts = time.time()
    self._last_activity_desc = description

def get_status(self) -> dict:
    """Gets the current status (for timeout detection)."""
    elapsed = time.time() - self._last_activity_ts
    return {
        "last_activity_ts": self._last_activity_ts,
        "last_activity_desc": self._last_activity_desc,
        "seconds_since_activity": round(elapsed, 1),
        "current_tool": self._current_tool,
        "api_call_count": self._api_call_count,
        "budget_used": self.iteration_budget.used,
        "budget_max": self.iteration_budget.max_total,
    }
```

## Automatic Resumption After Gateway Restart (2026-04-14)

If the Gateway process is restarted (SIGTERM, crash, `drain_timeout`) **after** the agent calls a tool but **before** it generates a final reply, the session transcript will end with a `role: "tool"` message. Previously, users had to manually `/retry` (replaying the conversation from scratch, losing all progress) or say "continue". Now, when the next user message arrives, the Gateway detects that the history ends with a tool result and automatically injects a system note:

```
[System note: Your previous turn was interrupted before you could process the
last tool result(s). The conversation history contains tool outputs you haven't
responded to yet. Please finish processing those results and summarize what was
accomplished, then address the user's new message below.]

<Original User Message>
```

### Implementation (`gateway/run.py:8679-8692`)

```python
# Auto-continue: if the loaded history ends with a tool result,
# the previous agent turn was interrupted mid-work
if agent_history and agent_history[-1].get("role") == "tool":
    message = SYSTEM_NOTE + "\n\n" + message
```

The injection point is within the `_run_agent()`'s `run_sync` closure, **immediately before** `agent.run_conversation()`. The Agent sees the complete history (including unprocessed tool results) plus this system note, and then continues execution — so it first summarizes previous work before addressing the user's new message.

### Key Design Points

| Design Decision | Explanation |
|---|---|
| **No schema change** | No new session flags or persistent fields are added; it purely detects the role of the last message |
| **Applies to all restart scenarios** | Covers clean shutdown / crash / SIGTERM / drain timeout |
| **Preserves user message** | The original user message remains after the system note and is not lost |
| **Suspended sessions not triggered** | If a session is in a suspended state (abnormal shutdown), history is discarded, and the user starts from a blank slate, preventing erroneous auto-continuation of outdated content |
| **Shutdown notification copy changed** | The notification sent during shutdown changes from "Use /retry after restart to continue" to "Send any message after restart to resume where it left off" — this is now accurate |

### Comparison with Old Behavior

```text
Old Flow (Manual /retry):
  User: "deploy v2.3"
  agent: [calls terminal "kubectl apply"] → [tool result: "deployment started"]
  [Gateway Crash/Restart]
  User: "did it work?"
  → User must manually type /retry to replay conversation → agent runs kubectl apply from scratch (potentially double deploying!)

New Flow (Auto-continue):
  User: "deploy v2.3"
  agent: [calls terminal "kubectl apply"] → [tool result: "deployment started"]
  [Gateway Crash/Restart]
  User: "did it work?"
  → Gateway detects trailing tool result → injects system note → agent sees tool result + new user message
  → agent: "Deployment started (kubectl apply successful). Regarding your question..."
```

**Key Safety Aspect**: The old flow's `/retry` would replay side effects (running kubectl apply again); the new flow merely allows the agent to interpret **already occurred** tool results without re-executing them.

## Superiority Analysis

### Comparison with Other Agent Frameworks

| Feature | Hermes | Cursor | OpenCode |
|---|---|---|---|
| User Interrupt | ✅ Ctrl+C/New Message | ✅ | ✅ |
| Sub-agent Interrupt Propagation | ✅ | N/A | N/A |
| Credential Pool Rotation | ✅ Automatic multi-key rotation | ❌ | ❌ |
| Fallback Model Chain | ✅ Automatic switching | ❌ | ❌ |
| Connection Health Check | ✅ Automatic cleanup | ❌ | ❌ |
| Automatic Credential Refresh | ✅ OAuth/token | ❌ | ❌ |
| Activity Tracking | ✅ Timeout detection | ❌ | ❌ |

## Configuration Guide

### Environment Variables

```bash
# Nous Credential Refresh
HERMES_NOUS_MIN_KEY_TTL_SECONDS=1800  # Minimum Key TTL
HERMES_NOUS_TIMEOUT_SECONDS=15        # Refresh Timeout

# Streaming Read Timeout
HERMES_STREAM_READ_TIMEOUT=60.0       # Streaming read timeout (seconds)
HERMES_API_TIMEOUT=1800.0             # API total timeout (seconds)
```

## Related Pages

- [[credential-pool-and-isolation]] — Credential Pool and Rotation Mechanism
- [[multi-agent-architecture]] — Sub-agent Interrupt Propagation and Budget Isolation
- [[agent-loop-and-prompt-assembly]] — AIAgent Interrupt Flag and Main Loop

### Related Files

- `agent/error_classifier.py` — Structured API Error Classification (13 FailoverReason types)
- `run_agent.py` — Interrupt Mechanism, Retry Loop
- `tools/credential_pool.py` — Credential Pool
- `tools/interrupt.py` — Interrupt Tool
