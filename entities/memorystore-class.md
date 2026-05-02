---
title: MemoryStore Class
created: 2026-04-07
updated: 2026-04-07
type: entity
tags: [component, memory, module]
sources: [hermes-agent Source Code Analysis 2026-04-07]
---

# MemoryStore Class

## Location

`tools/memory_tool.py`

## Overview

The `MemoryStore` is the core class of the memory system, responsible for managing read and write operations for `MEMORY.md` and `USER.md`.

## Constructor

```python
class MemoryStore:
    def __init__(self, memory_char_limit=2200, user_char_limit=1375):
        self.memory_entries: List[str] = []
        self.user_entries: List[str] = []
        self.memory_char_limit = memory_char_limit
        self.user_char_limit = user_char_limit
        self._system_prompt_snapshot: Dict[str, str] = {"memory": "", "user": ""}
```

## Core Methods

### `load_from_disk()`

Loads entries from disk and captures a frozen snapshot.

### `add(target, content) -> Dict`

Adds a new entry, checking for duplicates and character limits.

### `replace(target, old_text, new_content) -> Dict`

Replaces an entry using a short, unique substring match.

### `remove(target, old_text) -> Dict`

Removes entries containing the specified text.

### `format_for_system_prompt(target) -> Optional[str]`

Returns the frozen snapshot for system prompt injection.

## Key Design Principles

-   **Frozen Snapshot Mode** — System prompts remain immutable during a session.
-   **Atomic Writes** — Temporary files + `os.replace()` ensure consistency.
-   **File Locking** — `fcntl.flock()` for concurrent safety.
-   **Security Scanning** — Detects injection and leakage patterns.

## Related Pages

-   [[memory-system-architecture]] — Overall Memory System Architecture
-   [[skills-and-memory-interaction]] — Interaction Design Between Skills and Memory
-   [[security-defense-system]] — Memory Content Security Scanning

## Related Files

-   `tools/memory_tool.py` — Implementation
-   `agent/memory_manager.py` — Manager
-   `agent/prompt_builder.py` — System Prompt Integration