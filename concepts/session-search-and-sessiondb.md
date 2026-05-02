---
title: Session Search and SessionDB
created: 2026-04-07
updated: 2026-04-18
type: concept
tags: [session-search, session-store, memory, architecture]
sources: [Hermes Agent Source Code Analysis 2026-04-07]
---

# Session Search and SessionDB

## Overview

`session_search` provides **cross-session conversation recall capabilities**, utilizing SQLite FTS5 full-text search and LLM summary generation.

## SessionDB

```python
# hermes_state.py
class SessionDB:
    """SQLite Session Storage, supporting FTS5 search"""
    
    def __init__(self, db_path: str):
        # Create session table and FTS5 virtual table
        ...
    
    def save_session(self, session_id, messages, ...):
        """Saves a session to the database"""
    
    def search_sessions(self, query, ...):
        """FTS5 full-text search"""
```

## FTS5 Search

Achieves efficient full-text search using SQLite's FTS5 extension:

```sql
-- FTS5 Virtual Table (indexes the messages table)
CREATE VIRTUAL TABLE messages_fts USING fts5(
    content,
    content=messages,
    content_rowid=id
);

-- Search query
SELECT * FROM messages_fts WHERE messages_fts MATCH 'elevenlabs OR baseten OR funding';
```

Search syntax supports:
- **Keyword OR** — `elevenlabs OR baseten`
- **Phrase Matching** — `"docker networking"`
- **Boolean Logic** — `python NOT java`
- **Prefix Matching** — `deploy*`

## Session Search Tool

```python
def session_search(query: str, role_filter: str = None, limit: int = 3):
    """
    Searches past conversation sessions
    
    Two modes:
    1. No query — Browses recent sessions (title, preview, timestamp)
    2. With query — Keyword search + LLM summary generation
    """
```

### Mode 1: Browse Recent Sessions

```text
Call without parameters → Returns a list of recent sessions:
- Session Title
- Content Preview
- Timestamp
Zero LLM cost, instant return
```

### Mode 2: Keyword Search

```text
Call with query → FTS5 search → LLM summary generation:
- Searches matching messages
- LLM summarizes session content
- Returns a structured summary
```

## Search Suggestions

```text
Use OR to connect keywords for best results when searching:
  elevenlabs OR baseten OR funding

FTS5 defaults to AND, which might miss sessions that mention only some of the keywords.
If a broad OR query yields no results, try searching for individual keywords in parallel.
```

## Distinction from Memory

| Aspect      | Memory                   | Session Search       |
|-------------|--------------------------|----------------------|
| **Content** | Stable facts, preferences| Complete conversation history |
| **Capacity**| Limited (~3500 characters) | Unlimited (SQLite)   |
| **Retrieval** | Automatically injected each turn | Search on demand     |
| **Format**  | List of entries          | Structured conversation |
| **Purpose** | Guiding core behavior    | Recalling context    |

## Use Cases

```text
When the user says:
- "We've done this before" → session_search
- "Do you remember when..." → session_search
- "Last time we..." → session_search
- "What did we do about X?" → session_search

When you suspect:
- Relevant context exists in past sessions → session_search
- Don't make the user repeat themselves → session_search
```

## Data Flow

```text
Session ends
  ↓
SessionDB.save_session()
  ↓
Writes to SQLite + FTS5 index
  ↓
User initiates search
  ↓
FTS5 full-text search
  ↓
LLM generates summary
  ↓
Returns structured results
```

## Session Deletion and Pruning

`delete_session()` and `prune_sessions()` employ an **orphan strategy** instead of cascading deletion:

- When a parent session is deleted, the `parent_session_id` of its child sessions is set to `NULL` (orphaned) instead of being deleted along with the parent.
- Child sessions resulting from compression or splitting remain searchable even after their parent session is cleaned up.
- `prune_sessions(older_than_days=90)` only cleans up **ended sessions**; active sessions are unaffected.

Design intention: To protect historical data integrity and prevent accidental deletion of valuable conversation records by cleanup operations.

### Automatic Pruning + VACUUM at Startup (v2026.4.18+)

`state.db` previously grew indefinitely. A heavy user (gateway + cron) reported 384MB / 982 sessions / 68K messages leading to performance degradation. After manually running `hermes sessions prune --older-than 7` + `VACUUM`, the size dropped to 43MB. Version 2026.4.18+ automatically performs this at startup:

```python
# hermes_state.py
class SessionDB:
    def vacuum(self): ...

    def maybe_auto_prune_and_vacuum(
        self,
        retention_days: int = 90,        # Cleans up ended sessions older than 90 days
        min_interval_hours: int = 24,    # Default once per day
        vacuum: bool = True,
    ) -> Dict[str, Any]:
        """Idempotent: state_meta table records last_auto_prune, shared lock across processes for the same HERMES_HOME
        Returns {'skipped', 'pruned', 'vacuumed', 'error'?}"""
```

- Adds a `state_meta` key/value table to store the timestamp of the last run (key: `last_auto_prune`).
- Shared by all Hermes processes under the same `HERMES_HOME`; no-op within `min_interval_hours`.
- **Smart VACUUM**: VACUUM is only truly executed if `pruned > 0` (`hermes_state.py:1567`); empty cleanups do not waste I/O.
- Never throws an exception—failures are logged as warnings and do not affect startup.

## Update `/usage` to Display Account Limits (v2026.4.18+)

The `/usage` command appends **account-level quota information** (remaining credit, period, rate limits returned by the provider) below the existing token table:

- CLI (`cli.py`): Fetches within a `concurrent.futures.ThreadPoolExecutor(max_workers=1)` + 10s timeout; slow providers will not block the prompt.
- Gateway (`gateway/run.py`): Fetches via `asyncio.to_thread`; when no agent is resident, parses the provider from `billing_provider` / `billing_base_url` persistent fields.
- New module `agent/account_usage.py` (326 lines) provides two entry points: `fetch_account_usage(provider, base_url, api_key)` and `render_account_usage_lines(snapshot, markdown)`.

## Related Pages

- [[gateway-session-management]] — Gateway Session Management (SessionStore uses SessionDB)
- [[cli-architecture]] — Session Management and Search Commands in CLI
- [[skills-and-memory-interaction]] — Session Search as a Third Persistence Mechanism

## Related Files

- `hermes_state.py` — SessionDB Implementation
- `tools/session_search_tool.py` — Session Search Tool
- `agent/trajectory.py` — Trajectory Saving Utility