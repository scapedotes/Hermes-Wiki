---
title: Gateway Session Management Architecture
created: 2026-04-08
updated: 2026-04-08
type: concept
tags: [architecture, module, component, gateway, session-store, multi-platform]
sources: [gateway/session.py, gateway/config.py]
---

# Gateway Session — Gateway Session Management Architecture

## Overview

The Gateway Session, located at `gateway/session.py` (44KB/1081 lines), manages the gateway's **session lifecycle**: session context tracking, message persistence, reset policy evaluation, and dynamic system prompt injection.

Core philosophy: **Each combination of platform/user/thread has an independent session, and the session knows its origin and destination.**

## Architectural Principles

### Core Data Model

```text
SessionSource (Message Source)
    ↓
SessionContext (Complete Session Context)
    ↓
SessionEntry (Session Storage Entry)
    ↓
SessionStore (Session Store Manager)
```

### SessionSource — Message Source Description

```python
@dataclass
class SessionSource:
    platform: Platform           # telegram, discord, slack, whatsapp...
    chat_id: str                 # Chat ID
    chat_name: Optional[str]     # Chat Name
    chat_type: str               # "dm", "group", "channel", "thread"
    user_id: Optional[str]       # User ID
    user_name: Optional[str]     # User Name
    thread_id: Optional[str]     # Thread/Topic ID
    chat_topic: Optional[str]    # Channel Topic
    user_id_alt: Optional[str]   # Alternate ID like Signal UUID
    chat_id_alt: Optional[str]   # Signal Group Internal ID
```

**Multi-Platform Adaptation**: Different platforms use different ID formats (Telegram uses numeric IDs, Signal uses UUID + internal group IDs), which SessionSource uniformly abstracts.

### SessionKey Construction Rules

```python
def build_session_key(source, group_sessions_per_user=True, thread_sessions_per_user=False):
    """
    DM Session:
    → agent:main:{platform}:dm:{chat_id}
    → agent:main:{platform}:dm:{chat_id}:{thread_id}  (with thread)
    
    Group Session:
    → agent:main:{platform}:group:{chat_id}:{user_id}  (per-user isolation)
    → agent:main:{platform}:group:{chat_id}            (shared session)
    
    Thread Session:
    → agent:main:{platform}:thread:{chat_id}:{thread_id}  (shared by default)
    → agent:main:{platform}:thread:{chat_id}:{thread_id}:{user_id}  (per-user)
    """
```

**Design Considerations**:
- DM sessions: Isolated by chat to ensure private conversations are independent.
- Group sessions: Isolated per user by default (each user has their own conversation).
- Thread sessions: Shared by default (all participants see the same conversation), but per-user isolation can be enabled via `thread_sessions_per_user`.

### PII Redaction

```python
_PHONE_RE = re.compile(r"^\+?\d[\d\-\s]{6,}$")

def _hash_id(value: str) -> str:
    """Deterministic 12-character hexadecimal hash"""
    return hashlib.sha256(value.encode()).hexdigest()[:12]

def _hash_sender_id(value: str) -> str:
    return f"user_{_hash_id(value)}"

def _hash_chat_id(value: str) -> str:
    """Retains platform prefix: telegram:12345 → telegram:<hash>"""
    colon = value.find(":")
    if colon > 0:
        return f"{value[:colon]}:{_hash_id(value[colon+1:])}"
    return _hash_id(value)
```

**Discord Exception**: Discord uses the `<@user_id>` mention system. The LLM requires the actual ID to mention users, hence Discord is not included in `_PII_SAFE_PLATFORMS`.

### SessionContext — Dynamic System Prompt Injection

```python
def build_session_context_prompt(context, redact_pii=False):
    """
    Generates context information injected into the system prompt:
    
    ## Current Session Context
    **Source:** Telegram (DM with lnisang La)
    **User:** lnisang La
    **Connected Platforms:** local, telegram: Connected ✓
    
    **Delivery options for scheduled tasks:**
    - "origin" → Back to this chat (lnisang La)
    - "local" → Save to local files only
    - "telegram" → Home channel (...)
    """
```

**Platform-Specific Behavior Hints**:

```python
if platform == SLACK:
    "You do NOT have access to Slack-specific APIs..."
elif platform == DISCORD:
    "You do NOT have access to Discord-specific APIs..."
```

Prevents the Agent from committing to actions it cannot complete.

### SessionStore — Session Storage Manager

```python
class SessionStore:
    def __init__(self, sessions_dir, config):
        # Prioritize SQLite (SessionDB)
        # Fallback to JSONL files
        self._db = SessionDB()  # if available
```

**Dual Storage Strategy**:
1.  **SQLite** (preferred): Via `hermes_state.SessionDB`, supports FTS5 full-text search.
2.  **JSONL** (fallback): Simple JSON file storage.

### Session Reset Policy

```python
def _is_session_expired(self, entry):
    """
    Checks if the session has expired:
    1. Check for active background processes (if present, session does not expire)
    2. Retrieve the reset policy for the platform/chat type
    3. Check for idle timeout or daily reset
    """
```

**Background Expiration Monitoring**:

```python
# When a session expires:
entry.was_auto_reset = True
entry.auto_reset_reason = "idle"  # or "daily"
entry.reset_had_activity = bool(entry.total_tokens > 0)
```

When the next message arrives, the gateway injects a notification:

```
"⚠️ Previous session expired (idle for 24h). Starting fresh conversation."
```

### Token Tracking

```python
@dataclass
class SessionEntry:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    cost_status: str = "unknown"
    last_prompt_tokens: int = 0  # For compression pre-check
    memory_flushed: bool = False  # Memory flush flag (persistent)
```

### Atomic Save

```python
def _save(self):
    """Atomically writes sessions.json using tempfile + os.replace"""
    fd, tmp_path = tempfile.mkstemp(dir=sessions_dir, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, sessions_file)  # Atomic replace
```

**Why Atomic Write**: Prevents incomplete `sessions.json` writes in case of a gateway crash.

## Design Advantages

### Session Isolation Flexibility

| Scenario | Default Behavior | Configurable |
|---|---|---|
| DM | Isolated by chat | Not configurable |
| Group | Isolated per user | `group_sessions_per_user=False` → Shared |
| Thread | Shared | `thread_sessions_per_user=True` → Per-user isolated |

### Comparison with Simple Session Management

| Dimension | Simple Approach | Gateway Session |
|---|---|---|
| Multi-platform | Manual handling required | SessionSource uniform abstraction |
| Session Isolation | Fixed policy | Configurable (per-user / shared) |
| PII Protection | None | Automatic hash redaction |
| Context Injection | None | Dynamic system prompts |
| Reset Policy | None | Idle/daily automatic reset |
| Cost Tracking | None | Token usage + cost estimation |
| Persistence | In-memory | SQLite + JSON dual storage |

## Configuration and Operations

### Session Reset Policy

```yaml
# config.yaml
gateway:
  reset_policy:
    dm: idle:24h        # DM resets after 24h idle
    group: daily        # Group resets daily
    thread: idle:12h    # Thread resets after 12h idle
```

### Session Isolation

```yaml
gateway:
  group_sessions_per_user: true    # Independent session for each user in groups
  thread_sessions_per_user: false  # Shared session in threads (default)
```

### Viewing Active Sessions

```python
# Via gateway internal API
store._entries  # Dict[session_key, SessionEntry]
```

## Handling New Messages While Agent is Running (gateway/run.py line 1920+)

Logic for handling new messages from a user when an agent for the same session is already executing:

```text
New message received for the same session
    │
    ├── /stop         → Hard interrupt: interrupt + force clear _running_agents lock, immediately unlock session
    ├── /reset /new   → Interrupt + clear pending queue (prevents old text replay #2170) → Execute reset
    ├── /queue <text> → Queue: No interruption, will be used as next round's input after current round completes
    ├── /status       → No interruption, directly return current status
    ├── /model        → Reject: "Agent is running — wait or /stop first"
    ├── /approve /deny→ Bypass interruption, directly route to approval handler (agent is blocked on approval event)
    ├── Photo         → Queue without interruption, multiple photos automatically merged into the same pending event
    └── Normal Text   → interrupt(event.text) + append text to _pending_messages
```

### Full Process for Normal Text Interruption

```python
# gateway/run.py line 2033-2038
running_agent.interrupt(event.text)      # Set interruption signal
if _quick_key in self._pending_messages:
    self._pending_messages[_quick_key] += "\n" + event.text  # Append
else:
    self._pending_messages[_quick_key] = event.text          # Create new
```

The agent detects the interruption signal at the next checkpoint → stops the current round → pending text is processed as input for the new round.

### Complete Isolation Across Sessions

The key for `_running_agents` is `_quick_key` (composed of platform + user_id + chat_id), ensuring different sessions have independent keys:

| Scenario | Interrupt? | Reason |
|---|:---:|---|
| Send normal text in the same chat window | ✅ | `interrupt()` interrupts current agent |
| Send `/queue` in the same chat window | ❌ | Queued, waits for current task to complete |
| Send photo in the same chat window | ❌ | Automatically queued and merged |
| Different chat window / different user | ❌ | Different `_quick_key`, independent threads run in parallel |

Agents for different sessions execute in parallel in a thread pool via `run_in_executor`.

## Relationship with Other Systems

- [[messaging-gateway-architecture]] — Session is a core gateway component
- [[multi-agent-architecture]] — Interruptions propagate to child agents (`_active_children`)
- [[session-search-and-sessiondb]] — SQLite SessionDB provides FTS5 search
- [[cron-scheduling]] — Session origin used for cron delivery routing
- [[memory-system-architecture]] — Expired sessions trigger memory flush
