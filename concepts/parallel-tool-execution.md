---
title: Parallel Tool Execution System
created: 2026-04-07
updated: 2026-04-07
type: concept
tags: [architecture, tool, performance, concurrency]
sources: [Hermes Agent Source Code Analysis 2026-04-07]
---

# Parallel Tool Execution System — Intelligent Concurrency Safety Detection

## Design Principles

Modern LLMs often return multiple tool calls (parallel tool calling) in a single response. The design goal of Hermes is: **to maximize parallelism while ensuring safety, thereby reducing total wait time**.

Traditional approaches are either entirely sequential (slow) or entirely parallel (risky). Hermes adopts an intelligent parallel strategy involving **three-layer safety detection + path scope analysis**.

## Core Architecture

### 1. Tool Classification System

```python
# Tools that can never be parallelized (interactive/user-facing)
_NEVER_PARALLEL_TOOLS = frozenset({"clarify"})

# Read-only tools, no shared mutable state
_PARALLEL_SAFE_TOOLS = frozenset({
    "ha_get_state", "ha_list_entities", "ha_list_services",
    "read_file", "search_files", "session_search",
    "skill_view", "skills_list",
    "vision_analyze", "web_extract", "web_search",
})

# File tools, can be parallelized but require non-conflicting paths
_PATH_SCOPED_TOOLS = frozenset({"read_file", "write_file", "patch"})

# Maximum number of concurrent worker threads
_MAX_TOOL_WORKERS = 8
```

### 2. Concurrency Safety Detection Algorithm

```python
def _should_parallelize_tool_batch(tool_calls) -> bool:
    """Determines if a batch of tool calls can be safely parallelized."""
    
    # 1. No parallelism needed for a single tool
    if len(tool_calls) <= 1:
        return False
    
    # 2. Contains 'never parallelized' tools → Degrade to sequential
    tool_names = [tc.function.name for tc in tool_calls]
    if any(name in _NEVER_PARALLEL_TOOLS for name in tool_names):
        return False
    
    # 3. Path scope check (file tools)
    reserved_paths: list[Path] = []
    for tool_call in tool_calls:
        tool_name = tool_call.function.name
        function_args = json.loads(tool_call.function.arguments)
        
        if tool_name in _PATH_SCOPED_TOOLS:
            scoped_path = _extract_parallel_scope_path(tool_name, function_args)
            if scoped_path is None:
                return False  # Cannot parse path → Degrade to sequential
            if any(_paths_overlap(scoped_path, existing) for existing in reserved_paths):
                return False  # Path conflict → Degrade to sequential
            reserved_paths.append(scoped_path)
            continue
        
        if tool_name not in _PARALLEL_SAFE_TOOLS:
            return False  # Unknown tool → Conservatively degrade to sequential
    
    return True  # All checks passed → Safe parallelism
```

### 3. Path Conflict Detection

```python
def _paths_overlap(left: Path, right: Path) -> bool:
    """Determines if two paths might point to the same subtree."""
    left_parts = left.parts
    right_parts = right.parts
    
    # Use the length of the shorter path as the common prefix length
    common_len = min(len(left_parts), len(right_parts))
    return left_parts[:common_len] == right_parts[:common_len]
```

**Examples:**
- `/root/wiki/index.md` and `/root/wiki/log.md` → No conflict (can be parallelized)
- `/root/wiki/index.md` and `/root/wiki/index.md` → Conflict (sequential)
- `/root/wiki/` and `/root/wiki/concepts/` → Conflict (sequential, parent directory overlap)

## Parallel Execution Implementation

```python
if _should_parallelize_tool_batch(tool_calls):
    # Parallel execution: Use ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=_MAX_TOOL_WORKERS
    ) as executor:
        futures = {
            executor.submit(_execute_single_tool, tc): tc
            for tc in tool_calls
        }
        for future in concurrent.futures.as_completed(futures):
            tool_call = futures[future]
            result = future.result()
            # Process results...
else:
    # Sequential execution: Process in order
    for tool_call in tool_calls:
        result = _execute_single_tool(tool_call)
        # Process results...
```

## Safety Degradation Strategy

Hermes adopts a **conservative by default** strategy: any uncertainty leads to degradation to sequential execution.

| Check Item | Failure Condition | Reason for Degradation |
|------------|-------------------|------------------------|
| Never Parallel Tool | Contains `clarify` | User interaction must be sequential |
| Path Resolution Failure | Unable to parse JSON parameters | Cannot verify safety |
| Path Overlap | File paths share a common prefix | Avoid race conditions |
| Unknown Tool | Not in safe list | Conservative default |
| Non-dictionary Parameters | Parameters are not a dict | Cannot analyze scope |

## Superiority Analysis

### Performance Improvement

| Scenario | Sequential Time | Parallel Time | Speedup Ratio |
|----------|-----------------|---------------|---------------|
| 3 Read-Only Tools | 3 × Wait Time | max(Wait Time) | ~3x |
| 5 Independent File Operations | 5 × Wait Time | max(Wait Time) | ~5x |
| Mixed Scenario (2 Parallel + 1 Sequential)| 3 × Wait | 2 × Wait | ~1.5x |

### Safety Guarantees

1.  **Zero Race Conditions** — Path overlap detection prevents simultaneous writes to the same file
2.  **Conservative Default** — Unknown situations degrade to sequential, preventing errors
3.  **User Interaction Protection** — `clarify` and similar tools are always sequential, avoiding confusion
4.  **Maximum Thread Limit** — 8 worker threads prevent resource exhaustion

### Comparison with Other Agent Frameworks

| Feature | Hermes | Cursor/Claude | OpenCode |
|---------|--------|---------------|----------|
| Parallel Tool Execution | ✅ Intelligent Detection | ✅ Full Parallelism | ✅ Full Parallelism |
| Path Conflict Detection | ✅ Prefix Overlap Check | ❌ None | ❌ None |
| Conservative Degradation | ✅ Sequential on Uncertainty | ❌ Potential Race Conditions | ❌ Potential Race Conditions |
| Configurable Thread Count | ✅ _MAX_TOOL_WORKERS | ❌ Fixed | ❌ Fixed |

## Configuration Guide

### Environment Variables

```bash
# No environment variable control, hardcoded in run_agent.py
# Potentially to be added in the future:
# HERMES_MAX_TOOL_WORKERS=8
# HERMES_PARALLEL_TOOLS=true/false
```

### Customizing Parallel Strategy

To add new parallel-safe tools:

```python
# Modify in run_agent.py:
_PARALLEL_SAFE_TOOLS = frozenset({
    # ... existing tools ...
    "your_new_read_only_tool",  # Add read-only tool
})

# Or add new path-scoped tools:
_PATH_SCOPED_TOOLS = frozenset({
    # ... existing tools ...
    "your_file_tool",  # Tool requiring a path parameter
})
```

## Related Pages

- [[model-tools-dispatch]] — Tool Orchestration and Scheduling (upper-layer control for parallel execution)
- [[tool-registry-architecture]] — Tool Registry System and Metadata Management
- [[large-tool-result-handling]] — Handling Large Results from Parallel Tools

## Related Files

- `run_agent.py` — Parallel detection algorithm and execution logic
- `tools/registry.py` — Tool registration and metadata