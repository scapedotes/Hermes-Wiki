```markdown
---
title: Code Execution Sandbox (execute_code)
created: 2026-04-10
updated: 2026-04-10
type: concept
tags: [sandbox, code-execution, tools, architecture]
sources: [tools/code_execution_tool.py]
---

# Code Execution Sandbox

## Overview

The `execute_code` tool allows LLMs to write a Python script and execute it in an isolated subprocess. The script can call back to a limited set of Hermes tools via RPC, compressing multi-step toolchains into a single inference, thereby reducing token consumption and latency.

## Core Value

```text
Traditional approach: 10 tool calls = 10 LLM inferences + 10 context expansions
execute_code: 1 LLM writes script + 1 execution, intermediate results don't enter context
```

## Sandbox Restrictions

### Allowed Tools (Only 7)

```python
SANDBOX_ALLOWED_TOOLS = [
    "web_search",      # Web search
    "web_extract",     # Web page extraction
    "read_file",       # Read file
    "write_file",      # Write file
    "search_files",    # Search files
    "patch",           # Modify file
    "terminal",        # Terminal command
]
```

### Resource Limits

```python
DEFAULT_TIMEOUT = 300         # 5 minute timeout
DEFAULT_MAX_TOOL_CALLS = 50   # Max 50 tool calls
MAX_STDOUT_BYTES = 50_000     # Max stdout 50KB
MAX_STDERR_BYTES = 10_000     # Max stderr 10KB
```

These can be overridden via `code_execution.*` in config.yaml.

## Two Communication Modes

| Mode | Applicable Backend | Communication Method |
|------|--------------------|----------------------|
| **UDS (Unix Domain Socket)** | local | Parent process opens RPC listener, child process calls tools via socket |
| **File-based RPC** | Docker / SSH / Modal / Daytona | Child process writes request file → Parent process polls → Writes response file |

### Process Flow

```text
1. Parent process generates hermes_tools.py stub (containing RPC functions)
2. Parent process starts RPC listener (UDS socket or file polling thread)
3. Child process executes script written by LLM
4. Script calls hermes_tools.web_search(...) etc.
   → Sent back to parent process via RPC → Parent process calls actual tool → Returns result
5. Only final stdout is returned to LLM; intermediate results do not enter context
```

## Relationship with Terminal Backend

The `execute_code` script **executes within the current terminal backend**. If the backend is Docker, the script runs inside Docker and calls back to local tools via file-based RPC.

## Related Pages

- [[terminal-backends]] — Which backend the script executes in
- [[large-tool-result-handling]] — Overflow protection for tool results

## Key Source Code

- `tools/code_execution_tool.py` (1347 lines) — Complete sandbox implementation
```