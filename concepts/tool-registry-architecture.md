---
title: Tool Registry System Architecture
created: 2026-04-08
updated: 2026-04-15
type: concept
tags: [tool, toolset, tool-registry, architecture, component]
sources: [tools/registry.py, model_tools.py]
---

# Tool Registry — System Architecture

## Overview

The Tool Registry is the **central backbone** of the Hermes Agent's tool system, located at `tools/registry.py` (275 lines/10KB). It implements a design pattern of **declarative tool registration + centralized dispatch**, replacing the previously scattered and parallel data structures maintained in `model_tools.py`.

All tool files (`tools/*.py`) are automatically registered via `registry.register()` upon module import, and `model_tools.py` is solely responsible for querying the registry and triggering the discovery process.

## Architecture Principles

### Import Chain (Circular Import Safe)

```
tools/registry.py  (Zero external dependencies — imported by all tool files)
       ↑
tools/*.py  (Each file calls registry.register() at the module level)
       ↑
model_tools.py  (Imports registry + triggers _discover_tools())
       ↑
run_agent.py, cli.py, batch_runner.py
```

This design **completely avoids circular import** issues: the registry does not import any tool files, tool files only import the registry, and `model_tools` is the only module that imports both the registry and all tools.

### Core Data Structures

```python
class ToolEntry:
    """Metadata for a single tool"""
    __slots__ = (
        "name", "toolset", "schema", "handler", "check_fn",
        "requires_env", "is_async", "description", "emoji",
    )

class ToolRegistry:
    """Singleton registry, collects schema + handler for all tools"""
    def __init__(self):
        self._tools: Dict[str, ToolEntry] = {}         # Tool name → Metadata
        self._toolset_checks: Dict[str, Callable] = {}  # Toolset → Check function
```

**Design Highlight**: Using `__slots__` reduces memory overhead (saving approximately 40% memory per `ToolEntry`), which is significantly effective when registering 100+ tools.

### Automatic Discovery of Built-in Tools (2026-04-14)

Previously, `model_tools.py` maintained a hardcoded list of tool imports; adding a new tool required modifying two files simultaneously. Now, `tools/registry.py` provides `discover_builtin_tools()`, which is called by `model_tools.py` at startup:

```python
def discover_builtin_tools(tools_dir=None) -> List[str]:
    """Scans tools/*.py and imports all self-registering tool modules"""
    tools_path = Path(tools_dir) or Path(__file__).resolve().parent
    module_names = [
        f"tools.{path.stem}"
        for path in sorted(tools_path.glob("*.py"))
        if path.name not in {"__init__.py", "registry.py", "mcp_tool.py"}
        and _module_registers_tools(path)  # AST check
    ]
    # importlib.import_module() for each, triggering module-level registry.register()
```

**AST-level Filtering**: `_module_registers_tools()` uses `ast.parse` to parse modules, importing only if a `registry.register(...)` call is detected at the **module top level**. This ensures:
- Regular tool files (e.g., `tools/terminal_tool.py`) are identified and loaded.
- Helper modules (that do not register tools at the top level) are skipped.
- `registry.register()` calls within helper functions are not misidentified.

**Exclusion List**: `__init__.py`, `registry.py` itself, and `mcp_tool.py` (MCP tools are dynamically loaded on demand and do not follow this path).

**Simplified New Tool Addition Process**: Previously, three places needed modification (tool file + `model_tools.py` import + toolsets definition); now, only two places are required (tool file + toolsets definition), as auto-discovery automatically picks up new files.

## Core Operations

### 1. Register

Each tool file is automatically registered upon import:

```python
# In tools/terminal_tool.py
registry.register(
    name="terminal",
    toolset="terminal",
    schema={"name": "terminal", "description": "...", "parameters": {...}},
    handler=lambda args, **kw: terminal_tool(...),
    check_fn=lambda: True,           # Availability check
    requires_env=[],                 # Environment variable dependencies
    is_async=False,
)
```

- **Name Conflict Detection**: If tools with the same name belong to different toolsets, a warning is issued, and the entry is overwritten.
- **check_fn Caching**: Only the first `check_fn` for each toolset is recorded, preventing redundant checks.

### 2. Availability Check (get_definitions)

Returns a list of tool schemas in OpenAI format, including only tools that pass their `check_fn`:

```python
def get_definitions(self, tool_names: Set[str], quiet: bool = False) -> List[dict]:
    # Cache check_fn results — check each toolset only once
    check_results: Dict[Callable, bool] = {}
    for name in sorted(tool_names):
        entry = self._tools.get(name)
        if entry.check_fn:
            if entry.check_fn not in check_results:
                check_results[entry.check_fn] = bool(entry.check_fn())
            if not check_results[entry.check_fn]:
                continue  # Skip unavailable tool
        result.append({"type": "function", "function": {**entry.schema, "name": entry.name}})
    return result
```

**Advantages**:
- **On-demand Filtering**: Only tools with satisfied environmental dependencies are sent to the LLM, preventing the model from calling non-existent tools.
- **Check Caching**: The `check_fn` for the same toolset is executed only once, rather than once for each tool.
- **Quiet Mode**: `quiet=True` suppresses debug logs, suitable for bulk queries.

### 3. Dispatch Execution

```python
def dispatch(self, name: str, args: dict, **kwargs) -> str:
    entry = self._tools.get(name)
    if not entry:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        if entry.is_async:
            from model_tools import _run_async
            return _run_async(entry.handler(args, **kwargs))
        return entry.handler(args, **kwargs)
    except Exception as e:
        return json.dumps({"error": f"Tool execution failed: {type(e).__name__}: {e}"})
```

**Advantages**:
- **Unified Error Format**: All exceptions are caught and returned as `{"error": "..."}` JSON, ensuring the LLM can parse them.
- **Asynchronous Bridging**: Automatically detects the `is_async` flag and bridges through `_run_async`, so callers do not need to worry about it.
- **Safe Failure for Unknown Tools**: Returns a JSON error instead of raising an exception.

### 4. Dynamic Deregistration

```python
def deregister(self, name: str) -> None:
    entry = self._tools.pop(name, None)
    # If no other tools belong to this toolset, clean up its check_fn
    if entry.toolset in self._toolset_checks and not any(
        e.toolset == entry.toolset for e in self._tools.values()
    ):
        self._toolset_checks.pop(entry.toolset, None)
```

**Use Case**: MCP dynamic tool discovery — when the MCP server sends `notifications/tools/list_changed`, it requires "nuking-and-repaving" old tools and re-registering them.

### 5. Query Helper Methods

| Method | Purpose |
|---|---|
| `get_all_tool_names()` | Returns all registered tool names (sorted) |
| `get_schema(name)` | Bypasses `check_fn` to retrieve the raw schema, used for token estimation |
| `get_toolset_for_tool(name)` | Queries the toolset a tool belongs to |
| `get_emoji(name)` | Retrieves the emoji corresponding to the tool |
| `get_tool_to_toolset_map()` | Returns a `{tool_name: toolset_name}` mapping |
| `is_toolset_available(toolset)` | Checks if a toolset meets requirements |
| `check_toolset_requirements()` | Returns the availability status for all toolsets |
| `get_available_toolsets()` | Returns toolset metadata (tool list, environmental dependencies, etc.) |
| `check_tool_availability()` | Returns classification of available/unavailable toolsets |

## Design Advantages

### Comparison with Old Architecture

| Dimension | Old Approach (Scattered in model_tools.py) | New Approach (Tool Registry) |
|---|---|---|
| Data Structure | Multiple dicts maintained in parallel | Single registry |
| Circular Imports | Prone to errors | Zero dependencies, import safe |
| Extensibility | Adding tools required modifying model_tools.py | Only requires calling `register()` in the tool file |
| Dynamic Discovery | Not supported | Supports `deregister` + re-register |
| Testing | Difficult to mock | Singleton is replaceable |
| Availability Check | Scattered logic | Centralized caching |

### Single Responsibility Principle

- **Registry**: Solely responsible for registration, querying, and dispatching.
- **Tool files**: Solely responsible for implementing and registering themselves.
- **Model tools**: Solely responsible for discovery and routing.
- **Run agent**: Solely responsible for executing the loop.

Each module has clear responsibilities, and the dependency direction is unidirectional.

## Configuration and Operations

### Adding New Tools

1. Implement the tool function in `tools/your_tool.py`.
2. Call `registry.register(...)` at the end of the file.
3. Add the toolset in `hermes_cli/toolsets.py`.

> Note: It is **no longer necessary** to manually modify `model_tools.py`'s import list. `discover_builtin_tools()` will scan `tools/*.py` at startup, and as long as there is a top-level `registry.register(...)` call, the module will be automatically imported.

### Viewing Registered Tools

```python
from tools.registry import registry
print(registry.get_all_tool_names())
print(registry.get_tool_to_toolset_map())
```

### Viewing Toolset Availability

```python
print(registry.check_toolset_requirements())
# Output: {'terminal': True, 'web': False, 'browser': True, ...}
```

## Relationship with Other Systems

- [[toolsets-system]] — Registry organizes tools by toolset.
- [[model-tools-dispatch]] — `model_tools.py` discovers tools via the Registry.
- [[mcp-and-plugins]] — MCP uses `deregister`/`register` to achieve dynamic tool discovery.
- [[large-tool-result-handling]] — Dispatch results are processed through a unified error format.
- [[fuzzy-matching-engine]] — The 8-layer fuzzy matching engine used by patch tools.
- [[code-execution-sandbox]] — The `execute_code` sandbox tool.