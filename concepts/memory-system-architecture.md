---
title: Memory System Architecture
created: 2026-04-07
updated: 2026-04-29
type: concept
tags: [memory, architecture, module]
sources: [tools/memory_tool.py, agent/memory_manager.py, agent/memory_provider.py, agent/builtin_memory_provider.py, run_agent.py, agent/prompt_builder.py, plugins/memory/__init__.py]
---

# Memory System Architecture

## Overview

Hermes' memory system adopts a **three-tiered architecture**: Storage Layer (MemoryStore), Orchestration Layer (MemoryManager), and Plugin Layer (MemoryProvider).

```text
┌─────────────────────────────────────────────┐
│              run_agent.py                   │
│  (prefetch → inject → tool interception → sync → flush) │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│           MemoryManager (Orchestration Layer)             │
│  "Built-in + At most one external Provider"               │
│  Tool schema merging / Lifecycle hook broadcasting           │
└────────┬────────────────────┬───────────────┘
         │                    │
┌────────▼────────┐  ┌───────▼────────────────┐
│ BuiltinProvider │  │ External Provider (Optional) │
│ MEMORY.md       │  │ honcho / mem0 / 8 options │
│ USER.md         │  └────────────────────────┘
│ MemoryStore     │
└─────────────────┘
```

## 1. Storage Layer: MemoryStore

File path: `tools/memory_tool.py` (561 lines)

### Dual-File Storage

- **`MEMORY.md`** (default limit 2200 characters) — Agent's personal notes (environmental facts, project conventions, tool characteristics)
- **`USER.md`** (default limit 1375 characters) — User profile (preferences, communication style, expectations)
- Storage path: `{HERMES_HOME}/memories/`
- Entry delimiter: `§` (section sign), supports multi-line entries

### Frozen Snapshot Mode

This is the most crucial design decision:

```text
Session start → load_from_disk() → Reads file → Captures snapshot to _system_prompt_snapshot
                                                     │
                                              Snapshot injected into system prompt
                                              (remains unchanged for the entire session)
                                                     │
Writes during session → Updates disk file + memory_entries ─────── Does not modify system prompt
                                                     │
Next session → Re-loads from_disk() → New snapshot takes effect
```

**Why?** To keep the system prompt stable → Prevents Anthropic prefix cache invalidation. Writes are immediately persisted to disk, but the current session's system prompt does not see its own writes.

### Atomic Writes + File Locking

```python
# Atomic write: temp file + fsync + os.replace()
def _write_file(path, entries):
    fd, tmp_path = tempfile.mkstemp(dir=path.parent)
    os.fsync(f.fileno()) # Assuming 'f' is the file object opened with fd
    os.replace(tmp_path, str(path))  # Atomic operation

# File lock: Separate .lock file + fcntl exclusive lock
def _file_lock(path):
    lock_path = path.with_suffix(path.suffix + ".lock")  # Does not lock the data file itself
    fcntl.flock(fd, fcntl.LOCK_EX) # Assuming 'fd' is the file descriptor for lock_path
```

Readers always see either the complete old file or the complete new file, with no intermediate states.

### Security Scan

All written content undergoes 12 threat pattern detections + invisible Unicode character detection:

```python
_MEMORY_THREAT_PATTERNS = [
    # Prompt Injection
    ("ignore previous instructions", "prompt_injection"),
    ("you are now", "role_hijack"),
    ("do not tell the user", "deception_hide"),
    ("act as if you have no restrictions", "bypass_restrictions"),
    # Exfiltration
    ("curl ... $KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API", "exfil_curl"),
    ("wget ... $KEY|TOKEN|SECRET", "exfil_wget"),
    ("cat .env|credentials|.netrc|.pgpass|.npmrc|.pypirc", "read_secrets"),
    # Backdoor
    ("authorized_keys|~/.ssh", "ssh_backdoor"),
    # ... 12 types in total
]
```

### System Prompt Formatting

```text
════════════════════════════════════════════════════
MEMORY (your personal notes) [65% — 1,430/2,200 chars]
════════════════════════════════════════════════════
Entry 1
§
Entry 2
```

### MemoryStore Core API

| Method                       | Behavior                                         |
|------------------------------|--------------------------------------------------|
| `load_from_disk()`           | Reads file → Deduplicates → Captures frozen snapshot |
| `add(target, content)`       | Security scan → Deduplicates → Checks character limit → Appends → Persists |
| `replace(target, old_text, new_content)` | Substring matches old entry → Replaces → Security scan → Persists |
| `remove(target, old_text)`   | Substring matches → Deletes → Persists             |
| `format_for_system_prompt(target)` | Returns **frozen snapshot** (not real-time state) |

---

## 2. Orchestration Layer: MemoryManager

File path: `agent/memory_manager.py` (367 lines)

### Core Constraints

```python
class MemoryManager:
    def __init__(self):
        self._providers: List[MemoryProvider] = []
        self._tool_to_provider: Dict[str, MemoryProvider] = {}  # Tool name → provider routing
        self._has_external: bool = False  # At most one external provider
```

**"Built-in + At most one external" Rule**: `add_provider()` will reject a second non-builtin provider and print a warning.

### Orchestration Methods

| Method                        | Behavior                                           |
|-------------------------------|----------------------------------------------------|
| `build_system_prompt()`       | Collects and concatenates `system_prompt_block()` from all providers |
| `prefetch_all(query)`         | Merges `prefetch()` results from all providers     |
| `queue_prefetch_all(query)`   | Notifies all providers to prefetch context for the next turn in the background |
| `sync_all(user, assistant)`   | Synchronizes completed turn to all providers       |
| `get_all_tool_schemas()`      | Merges all provider tool schemas (deduplicates by name) |
| `handle_tool_call(name, args)`| Routes to the correct provider via `_tool_to_provider` |
| `has_tool(name)`              | Checks if any provider handles the tool            |

### Lifecycle Hooks

All hooks are **broadcast to all providers**, with each provider's failure isolated (try/except, does not propagate):

| Hook                                | Trigger Time              | Purpose                                       |
|-------------------------------------|---------------------------|-----------------------------------------------|
| `on_turn_start(turn_number, message)` | Before each turn starts   | Turn counting, scope management               |
| `on_session_end(messages)`          | Session ends              | Extracts persistent facts, flushes queues     |
| `on_pre_compress(messages)`         | Before context compression| Rescues information about to be compressed    |
| `on_memory_write(action, target, content)`| After built-in memory tool writes | **Only notifies external providers** (skips builtin), mirrors write |
| `on_delegation(task, result)`       | After sub-agent completes | Parent Agent observes delegation results      |

### Memory Context Fence

```python
def build_memory_context_block(raw_context: str) -> str:
    # Wraps with <memory-context> tag to prevent the model from interpreting recalled content as user input
    return f"<memory-context>\n{sanitized}\n</memory-context>"
```

---

## 3. Plugin Layer: MemoryProvider ABC

File path: `agent/memory_provider.py` (232 lines)

### Abstract Interface

```python
class MemoryProvider(ABC):
    # Must be implemented
    @abstractmethod
    def name(self) -> str: ...              # "builtin", "honcho", "mem0"
    @abstractmethod
    def is_available(self) -> bool: ...     # Quick check without network calls
    @abstractmethod
    def initialize(self, session_id, **kwargs): ...  # Session initialization
    @abstractmethod
    def get_tool_schemas(self) -> List[Dict]: ...    # Tools exposed to LLM

    # Optional to override (default no-op)
    def system_prompt_block(self) -> str: ...     # Static text injected into system prompt
    def prefetch(self, query) -> str: ...         # Quick recall before each turn
    def queue_prefetch(self, query): ...          # Background prefetch
    def sync_turn(self, user, assistant): ...     # Persists completed turn
    def handle_tool_call(self, name, args) -> str: ...  # Handles tool call
    def shutdown(self): ...                       # Cleans up resources
    def on_turn_start(self, turn_number, message): ...
    def on_session_end(self, messages): ...
    def on_pre_compress(self, messages) -> str: ...
    def on_memory_write(self, action, target, content): ...
    def on_delegation(self, task, result): ...
    def on_session_switch(self, new_session_id, parent_session_id, reset, **kw): ...  # v2026.4.23+
```

### `on_session_switch` — Session ID Mid-Session Switch Notification (v2026.4.23+)

Previously, providers only received `session_id` once during initialization. However, `session_id` can be **reassigned** in scenarios like `/resume`, `/branch`, `/reset`, `/new`, or context compression—providers were unaware, leading to subsequent writes falling into incorrect session records.

`agent/memory_manager.py:on_session_switch()` now calls `on_session_switch(new_session_id, parent_session_id, reset, **kwargs)` for all providers when the session_id changes, allowing providers to refresh their cached per-session state. Providers do not need to tear down and rebuild; they only need to update their internal handles. Errors will be swallowed (logged as debug, does not block the main flow).

### `initialize()` kwargs

**Always provided**: `hermes_home` (HERMES_HOME path), `platform` ("cli"/"telegram"/"discord"...)

**Potentially provided**: `agent_context` ("primary"/"subagent"/"cron"/"flush"), `agent_identity` (profile name), `agent_workspace` (shared workspace name), `parent_session_id` (parent session for sub-agents), `user_id` (platform user ID)

### 8 Available Plugins

| Plugin        | Path                                           |
|---------------|------------------------------------------------|
| honcho        | `plugins/memory/honcho/` — Honcho AI dialectical user modeling |
| mem0          | `plugins/memory/mem0/`                       |
| hindsight     | `plugins/memory/hindsight/`                  |
| holographic   | `plugins/memory/holographic/`                |
| openviking    | `plugins/memory/openviking/`                 |
| retaindb      | `plugins/memory/retaindb/`                   |
| supermemory   | `plugins/memory/supermemory/`                |
| byterover     | `plugins/memory/byterover/`                  |

Plugin discovery mechanism: Scans the `plugins/memory/` directory, finds subdirectories containing `__init__.py`, and calls `is_available()` for a quick check.

---

## 4. Agent Integration Flow

### Special Interception for Memory Tools

Memory tools are **not in the tool registry**. They are explicitly intercepted in `run_agent.py`:

```python
# run_agent.py:6078-6100 — Special branch, does not go through registry.dispatch()
elif function_name == "memory":
    result = memory_tool(
        action=args.get("action"),
        target=args.get("target", "memory"),
        content=args.get("content"),
        old_text=args.get("old_text"),
        store=self._memory_store,
    )
    # Notify external providers to mirror the write
    if self._memory_manager and args.get("action") in ("add", "replace"):
        self._memory_manager.on_memory_write(action, target, content)
```

**Why not use the registry?** Because memory tools require direct access to the `self._memory_store` instance, and the registry's handler signature does not pass internal agent state.

### Full Lifecycle

```text
Session Start
    │
    ├── MemoryStore.load_from_disk() → Frozen snapshot
    ├── MemoryManager.add_provider(builtin)
    ├── MemoryManager.add_provider(honcho)  ← If configured
    ├── provider.initialize(session_id, hermes_home=..., platform=...)
    └── System Prompt = builtin.system_prompt_block() + external.system_prompt_block()

Each Conversation Turn
    │
    ├── [Before API Call]
    │   ├── prefetch_all(user_message) → Merges all provider recalls
    │   └── Wraps with <memory-context> fence → Injects into current turn's user message
    │       (Temporary injection, does not modify original message, not persisted to session)
    │
    ├── [Tool Call]
    │   ├── "memory" → Special interception → MemoryStore.add/replace/remove
    │   │                        → on_memory_write() Notifies external providers
    │   └── "honcho_*" etc. → MemoryManager.handle_tool_call() → Routes to external provider
    │
    └── [After API Call]
        ├── sync_all(user_message, assistant_response) → Persists to all providers
        └── queue_prefetch_all(user_message) → Background prefetch for next turn context

Before Context Compression
    │
    ├── flush_memories(messages) → Prompts model to write important information to memory
    └── on_pre_compress(messages) → Notifies external providers to rescue information

Session End
    │
    ├── on_session_end(messages) → Full history handed to providers
    └── shutdown_all() → Cleans up resources
```

### Background Memory Review

The system automatically triggers a background review every 10 turns (`_memory_nudge_interval`):

```python
# run_agent.py — Turn counter
self._turns_since_memory += 1
if self._turns_since_memory >= 10:
    _should_review_memory = True  # Triggers _spawn_background_review() after the main loop ends
```

The Review Agent examines conversation history with `_MEMORY_REVIEW_PROMPT` and automatically calls memory tools to extract persistent facts.

---

## 5. Memory Tools as Seen by LLM

```python
# tools/memory_tool.py:489-538 — Tool schema
{
    "name": "memory",
    "description": "Save durable facts about the user or environment...",
    "parameters": {
        "action": "add | replace | remove",
        "target": "memory | user",
        "content": "Content to add/replace",
        "old_text": "Old text to match (required for replace/remove)"
    }
}
```

Guidance in system prompt (`prompt_builder.py:144-156`):

```text
MEMORY_GUIDANCE:
- Save user preferences, environment details, tool characteristics, stable conventions
- Prioritize saving information that "reduces future user corrections"
- Do NOT save: task progress, session outcomes, completed work logs, temporary TODOs
- Discovered a new method? Save with the skill tool, not memory
```

---

## 6. Configuration

```yaml
# config.yaml
memory:
  memory_enabled: true           # Enable MEMORY.md (default false)
  user_profile_enabled: true     # Enable USER.md (default false)
  memory_char_limit: 2200        # MEMORY.md character limit
  user_char_limit: 1375          # USER.md character limit
  nudge_interval: 10             # How many turns before triggering a background memory review
  flush_min_turns: 6             # Minimum number of turns before flushing is allowed prior to compression
  provider: honcho               # External provider name (optional)
```

---

## 7. Design Principles

### Failure Isolation

Each provider method call in MemoryManager is wrapped in a try/except block. A provider crash does not affect other providers and does not block Agent execution.

### Built-in Memory Write Mirroring

When the LLM calls `memory(action="add", target="user", content="User prefers dark mode")`:
1. MemoryStore writes to `USER.md` (local file)
2. `on_memory_write("add", "user", "User prefers dark mode")` notifies external providers
3. External providers (e.g., Honcho) can synchronize this fact to their own backend.

**Only `add` and `replace` trigger mirroring; `remove` does not.**

### Prefetch Cache

`prefetch_all()` is called once before each API call, and the results are cached in `_ext_prefetch_cache`. Multiple tool calls within the same turn will not trigger duplicate prefetches (avoiding 10x latency for 10 tool calls).

---

## 8. FAQ

### Q1: Under frozen snapshot mode, how does the current session see newly written memories?

**Through tool return values as a fallback.** After each `memory(action="add/replace/remove")` call, the return value includes **all real-time entries**:

```json
{
  "success": true,
  "entries": ["Entry 1", "Entry 2", "Newly added Entry 3"],
  "usage": "65% — 1,430/2,200 chars",
  "entry_count": 3
}
```

The model can already see the latest content in the conversation context; the system prompt does not need to be updated.

```text
Turn 1:  System prompt contains frozen snapshot [Entry 1, Entry 2]
Turn 3:  LLM calls memory(add, "Entry 3")
         → Return value contains [Entry 1, Entry 2, Entry 3]  ← Model sees this
Turn 5:  LLM calls memory(replace, old="Entry 1", new="Updated Entry 1")
         → Return value contains [Updated Entry 1, Entry 2, Entry 3]

System prompt always displays [Entry 1, Entry 2]  ← Frozen, protects prefix cache
Conversation context has full real-time state        ← Functionality unaffected
```

### Q2: What happens if the character limit is exceeded?

**Hard rejection + returns current entries for the model to manage space itself.** No automatic eviction, no LRU, no overflow.

```json
{
  "success": false,
  "error": "Memory at 2,100/2,200 chars. Adding this entry (200 chars) would exceed the limit. Replace or remove existing entries first.",
  "current_entries": ["Entry 1", "Entry 2", "Entry 3"],
  "usage": "2,100/2,200"
}
```

**Design intent**: Memory is not a database; it's a **carefully curated small card box**. Limited space forces the model to curate — replacing outdated entries, removing unimportant ones, adding new discoveries.

### Q3: What about more historical information?

Memory only stores **persistent facts** (2200 + 1375 characters). Larger volumes of historical information are retrieved via the **session_search tool**.

Their division of labor is clear, with explicit guidance in the system prompt for the model:

```text
MEMORY_GUIDANCE:
  "Do NOT save task progress, session outcomes, completed-work logs...
   use session_search to recall those from past transcripts."
```

---

## 9. Relationship with Session Search

Session Search is not part of Memory, but it is a **complementary mechanism** to the Memory system.

|                   | Memory Tool                    | Session Search Tool                      |
|-------------------|--------------------------------|------------------------------------------|
| **What it stores**| Persistent facts (preferences, environment, conventions) | All raw historical dialogue              |
| **Capacity**      | 2200 + 1375 characters (limited) | Unlimited (SQLite, all sessions)         |
| **Retrieval Method** | No retrieval (directly injected into system prompt) | FTS5 keyword search + LLM summarization  |
| **Writer**        | LLM actively calls memory tool | Automatic (each turn automatically persisted to SQLite) |
| **Read Cost**     | Zero (frozen snapshot in system prompt) | FTS5 query + Gemini Flash summarization (one LLM call per session) |

### Session Search Workflow

```text
session_search(query="nginx configuration")
        │
  ┌─────▼──────┐
  │ FTS5 Search   │  BM25 ranking, retrieves top 50 matching messages
  └─────┬──────┘
        │
  Groups by session → Deduplicates → Excludes current session → Takes top 3
        │
  ┌─────▼──────────────────┐
  │ LLM Summarization (Parallel)         │  Each session truncates ±50K characters around match location
  │ Gemini Flash, temp=0.1  │  Generates structured summaries focused on search terms
  └─────┬──────────────────┘
        │
  Returns per-session summaries (not raw dialogue text)
```

**Note**: Session Search is FTS5 keyword matching, not semantic vector search. Searching "nginx configuration" will not match sessions that only mention "reverse proxy". Search syntax supports `OR`, `NOT`, `"exact phrase"`, `prefix*`.

Two modes:
- **Empty query** → Lists recent sessions (zero LLM cost, only returns title/preview/timestamp)
- **Query provided** → FTS5 search + parallel LLM summarization (max 3-5 sessions)

## Related Pages

- [[memory-system-architecture]] — MemoryStore Core Class Detailed API (this page)
- [[security-defense-system]] — Memory Content Security Scan
- [[skills-and-memory-interaction]] — Skills and Memory Interaction Decision Tree
- [[context-compressor-architecture]] — `flush_memories` and `on_pre_compress` Before Compression
- [[prompt-caching-optimization]] — How Frozen Snapshots Protect Prefix Cache
- [[session-search-and-sessiondb]] — Session Search Tool (FTS5 + LLM Summarization)

## Related Files

- `tools/memory_tool.py` — MemoryStore class + memory tool schema (561 lines)
- `agent/memory_manager.py` — MemoryManager orchestration layer (367 lines)
- `agent/memory_provider.py` — MemoryProvider ABC interface (232 lines)
- `agent/builtin_memory_provider.py` — Built-in Provider (114 lines)
- `plugins/memory/` — 8 external Provider plugins
- `run_agent.py` — Agent integration (tool interception, prefetch, sync, flush)
- `agent/prompt_builder.py` — MEMORY_GUIDANCE system prompt
- `tools/session_search_tool.py` — Session Search tool (FTS5 + LLM summarization, 505 lines)