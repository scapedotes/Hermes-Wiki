---
title: Model Tools — Tool Orchestration and Scheduling Architecture
created: 2026-04-08
updated: 2026-04-08
type: concept
tags: [architecture, module, component, tool, toolset]
sources: [model_tools.py, tools/registry.py, toolsets.py]
---

# Model Tools — Tool Orchestration and Scheduling Architecture

## Overview

Model Tools, located at `model_tools.py` (22KB/577 lines), is a **lightweight orchestration layer** built on top of the Tool Registry. It is responsible for triggering tool discovery, filtering toolsets, handling asynchronous bridging, and dispatching function calls.

Core Philosophy: **`model_tools.py` no longer maintains its own data structures — all data originates from the Tool Registry.**

## Architectural Principles

### File Dependency Chain

```
tools/registry.py  (zero external dependencies — imported by all tool files)
       ↑
tools/*.py  (each file calls registry.register() at the module level)
       ↑
model_tools.py  (imports registry + triggers _discover_tools())
       ↑
run_agent.py, cli.py, batch_runner.py, environments/
```

### Public API (Backward Compatible)

```python
# These API signatures are preserved from the original 2400-line version for direct use by downstream code
get_tool_definitions(enabled, disabled, quiet) → list
handle_function_call(name, args, task_id, user_task) → str
TOOL_TO_TOOLSET_MAP: dict          # Used by batch_runner.py
TOOLSET_REQUIREMENTS: dict         # Used by cli.py, doctor.py
get_all_tool_names() → list
get_available_toolsets() → dict
check_tool_availability(quiet) → tuple
```

## Core Components

### 1. Asynchronous Bridge (`_run_async`)

This is the most critical infrastructure in `model_tools.py` — the **single source of truth for sync-to-async conversion**:

```python
def _run_async(coro):
    """
    Three execution paths:
    
    1. Existing running event loop (gateway/RL env)
       → Start a separate thread + asyncio.run() to avoid conflicts
    
    2. Worker thread (ThreadPoolExecutor for delegate_task)
       → Use a thread-level persistent loop (_get_worker_loop)
       → Avoid sharing the loop with the main thread, while preventing GC from closing the loop
    
    3. Main thread (CLI regular path)
       → Use a global persistent loop (_get_tool_loop)
       → Cached httpx/AsyncOpenAI clients remain bound to the active loop
    """
```

**Why not `asyncio.run()`**: `asyncio.run()` creates a loop, runs the coroutine, and then **closes** the loop. However, cached httpx/AsyncOpenAI clients remain bound to the closed loop, triggering `RuntimeError: Event loop is closed` during garbage collection.

### 2. Tool Discovery (`_discover_tools`)

```python
def _discover_tools():
    """Imports all tool modules, triggering their registry.register() calls"""
    _modules = [
        "tools.web_tools",
        "tools.terminal_tool",
        "tools.file_tools",
        "tools.browser_tool",
        "tools.code_execution_tool",
        "tools.delegate_tool",
        # ... 20 tool modules
    ]
    for mod_name in _modules:
        try:
            importlib.import_module(mod_name)
        except Exception:
            pass  # Optional tool import failures do not affect other tools

# Note: MCP tool discovery is not in _discover_tools()'s module list,
# but handled separately outside _discover_tools() (approx. lines 173-177):
#   from tools.mcp_tool import discover_mcp_tools
#   discover_mcp_tools()
```

**Three-layer Discovery Mechanism**:
1.  **Static Import**: `_discover_tools()` imports a predefined list of modules.
2.  **MCP Discovery**: Dynamically discovers tools from an external MCP server.
3.  **Plugin Discovery**: Discovers tools from user/project/pip plugins.

### 3. Getting Tool Definitions (`get_tool_definitions`)

```python
def get_tool_definitions(enabled_toolsets, disabled_toolsets, quiet_mode):
    """
    1. Determine tool names to include based on toolset filtering
    2. Request schemas from the registry (only returns tools whose check_fn passes)
    3. Dynamically adjust execute_code schema (only lists available sandbox tools)
    4. Dynamically adjust browser_navigate description (remove references if web tools are unavailable)
    5. Record _last_resolved_tool_names for downstream use
    """
```

**Key Design — Dynamic Schema Adjustment**:

```python
# Problem: execute_code's schema lists all possible sandbox tools.
# But if web_search's API key is not configured, the model sees "web_search available"
# and tries to call a non-existent tool → hallucination.

# Solution: Rebuild the schema based on actually available tools.
if "execute_code" in available_tool_names:
    sandbox_enabled = SANDBOX_ALLOWED_TOOLS & available_tool_names
    dynamic_schema = build_execute_code_schema(sandbox_enabled)
```

The same pattern applies to `browser_navigate`:

```python
# When web_search/web_extract are unavailable, remove the
# "prefer web_search or web_extract" reference from browser_navigate's description.
if not {"web_search", "web_extract"} & available_tool_names:
    desc = desc.replace("For simple information retrieval, prefer web_search...", "")
```

### 4. Argument Type Coercion (`coerce_tool_args`)

```python
def coerce_tool_args(tool_name, args):
    """
    LLMs often return:
    - Numbers as strings: "42" instead of 42
    - Booleans as strings: "true" instead of true
    
    Compare against JSON Schema and safely convert types.
    """
    # Supports: integer, number, boolean, union types [integer, string]
    # Safety: Conversion failure preserves original value
```

### 5. Function Call Dispatch (`handle_function_call`)

```python
def handle_function_call(function_name, function_args, task_id, ...):
    """
    1. Argument type coercion (coerce_tool_args)
    2. Notify read-loop tracker (reset read_file consecutive counter)
    3. Intercept Agent-level tools (todo, memory, session_search, delegate_task)
    4. Trigger pre_tool_call plugin hook
    5. Dispatch to registry.dispatch()
    6. Trigger post_tool_call plugin hook
    """
```

**Agent-level Tool Interception**:

```python
_AGENT_LOOP_TOOLS = {"todo", "memory", "session_search", "delegate_task"}

if function_name in _AGENT_LOOP_TOOLS:
    return json.dumps({"error": f"{function_name} must be handled by the agent loop"})
```

These tools require Agent-level state (TodoStore, MemoryStore, etc.) and are handled directly in `run_agent.py`.

### 6. Backward Compatibility Map

```python
_LEGACY_TOOLSET_MAP = {
    "web_tools": ["web_search", "web_extract"],
    "terminal_tools": ["terminal"],
    "browser_tools": ["browser_navigate", "browser_snapshot", ...],
    "rl_tools": ["rl_list_environments", "rl_select_environment", ...],
    # ...
}
```

Old toolset names (e.g., `"web_tools"`) are automatically mapped to new lists of tool names.

## Design Advantages

### From 2400 Lines to 577 Lines

| Metric            | Before Refactoring | After Refactoring |
| :---------------- | :----------------- | :---------------- |
| Lines of Code     | 2400+              | 577               |
| Data Structures   | Maintained multiple dicts in parallel | Entirely delegated to Registry |
| Availability Check | Scattered throughout model_tools.py | Handled centrally by Registry |
| Async Bridging    | Copied in multiple places | Single _run_async() |
| Test Difficulty   | Difficult to mock  | Registry is swappable/mockable |

### Advantages of Dynamic Schema Adjustment

Traditional static schemas can lead to models referencing unavailable tools. Model Tools ensures, through **dynamic adjustment at runtime**:
- `execute_code` only lists currently available sandbox tools.
- `browser_navigate` only suggests prioritizing web tools when they are actually available.
- All cross-tool references are based on actual availability.

## Relationship with Other Systems

- [[tool-registry-architecture]] — All data originates from the Registry
- [[toolsets-system]] — Toolset parsing and validation via `toolsets.py`
- [[large-tool-result-handling]] — `execute_code` schema dynamically adjusted
- [[mcp-and-plugins]] — MCP and plugin tools integrated via the discovery mechanism
---