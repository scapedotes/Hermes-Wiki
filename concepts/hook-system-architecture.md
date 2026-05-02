---
title: Hook System Architecture
created: 2026-04-08
updated: 2026-04-18
type: concept
tags: [architecture, module, extensibility, mcp, plugins]
sources: [gateway/hooks.py, hermes_cli/plugins.py, model_tools.py, run_agent.py]
---

# Hook System Architecture

## Overview

The Hermes Agent features two complementary extension systems:

| System                | Location                    | Responsibility                                | Lines of Code |
| ------------------- | --------------------------- | --------------------------------------------- | ----------- |
| **Gateway Hooks**   | gateway/hooks.py            | Gateway event-driven hooks (startup/session/agent/command) | 170 LoC     |
| **Plugin System**   | hermes_cli/plugins.py       | Plugin lifecycle hooks + tool registration + CLI command extension | 609 LoC     |

Core Philosophy: **Hooks handle event notifications, Plugins handle functional extensions – they are complementary.**

## Architectural Principles

### Gateway Hooks — Event-Driven

Gateway Hooks constitute a **lightweight event system** that triggers handlers at key points in the gateway's lifecycle:

| Event             | Trigger Timing                       |
|-------------------|--------------------------------------|
| `gateway:startup` | Gateway process starts               |
| `session:start`   | New session created (first message)  |
| `session:end`     | Session ends (user executes /new or /reset) |
| `session:reset`   | Session reset completed              |
| `agent:start`     | Agent starts processing messages     |
| `agent:step`      | Each turn in the tool invocation loop |
| `agent:end`       | Agent finishes processing messages   |
| `command:*`       | Any slash command execution (wildcard) |

### Plugin System — Functional Extension

The Plugin System supports plugins registering **tools, hook callbacks, CLI subcommands**, and injecting messages into conversations.

**Three-tiered Plugin Sources**:
1.  **User Plugins** — `~/.hermes/plugins/<name>/`
2.  **Project Plugins** — `./.hermes/plugins/<name>/` (requires `HERMES_ENABLE_PROJECT_PLUGINS`)
3.  **Pip Plugins** — Installed via the `hermes_agent.plugins` entry-point group

## Core Components

### Gateway Hooks

#### HookRegistry

```python
class HookRegistry:
    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}  # event_type → handlers
        self._loaded_hooks: List[dict] = []             # Metadata

    def discover_and_load(self):
        """
        1. Registers built-in hooks (boot-md)
        2. Scans the ~/.hermes/hooks/ directory
        3. Each hook directory requires:
           - HOOK.yaml (name, description, events)
           - handler.py (async def handle(event_type, context))
        4. Dynamically loads the handler.py module
        5. Registers each declared event
        """
```

#### Event Emission

```python
async def emit(self, event_type, context=None):
    """
    Triggers all registered handlers:
    1. Exact match: handlers["agent:start"]
    2. Wildcard match: handlers["command:*"] matches "command:reset"
    3. Supports synchronous and asynchronous handlers
    4. Error handling, does not block the main process
    """
```

#### Built-in Hook: boot-md

```python
# gateway/builtin_hooks/boot_md.py
# Runs ~/.hermes/BOOT.md upon gateway startup
# Allows users to inject custom initialization instructions at gateway startup
```

#### Hook Directory Structure

```
~/.hermes/hooks/
  notify-on-start/
    HOOK.yaml          # name: notify-on-start
                       # events: [agent:start]
    handler.py         # async def handle(event_type, context):
                       #     ...
```

### Plugin System

#### PluginContext — Plugin API Facade

```python
class PluginContext:
    """Provides a facade for plugins, allowing registration of tools, hooks, and CLI commands"""
    
    def register_tool(name, toolset, schema, handler, ...):
        """Registers a tool to the global registry"""
    
    def inject_message(content, role="user"):
        """
        Injects a message into the active conversation:
        - When Agent is idle → Queued as the next input
        - When Agent is running → Interrupts and injects
        """
    
    def register_cli_command(name, help, setup_fn, handler_fn):
        """Registers a CLI subcommand (e.g., hermes honcho ...)"""
    
    def register_hook(hook_name, callback):
        """Registers a lifecycle hook callback"""
```

#### PluginManager

```python
class PluginManager:
    def discover_and_load(self):
        """
        1. Scans user plugins (~/.hermes/plugins/)
        2. Scans project plugins (./.hermes/plugins/, optional)
        3. Scans pip entry-points
        4. Loads each plugin's register(ctx)
        5. Skips plugins disabled in config
        """
```

#### Plugin Structure

```
~/.hermes/plugins/my-plugin/
  plugin.yaml          # name, version, description
                       # requires_env: [MY_API_KEY]
                       # provides_tools: [my_tool]
                       # provides_hooks: [pre_tool_call]
  __init__.py          # def register(ctx):
                       #     ctx.register_tool(...)
                       #     ctx.register_hook(...)
```

#### Lifecycle Hooks

```python
VALID_HOOKS = {
    "pre_tool_call",      # Before tool invocation
    "post_tool_call",     # After tool invocation
    "pre_llm_call",       # Before LLM invocation
    "post_llm_call",      # After LLM invocation
    "pre_api_request",    # Before API request
    "post_api_request",   # After API request
    "on_session_start",   # On session start
    "on_session_end",     # On session end
}
```

#### Hook Invocation

```python
def invoke_hook(self, hook_name, **kwargs):
    """
    Invokes all registered callbacks:
    1. Each callback uses independent try/except (errors do not propagate)
    2. Collects non-None return values
    3. For pre_llm_call, can return context to be injected into user messages
    
    Important: Context is injected into user messages, not the system prompt
    → Keeps system prompt unchanged → Cache hit
    → Injected content is temporary, not persisted to the session DB
    """
```

#### Hook Invocation Points

`model_tools.py` calls plugin hooks within `handle_function_call()`:

```python
def handle_function_call(function_name, function_args, ...):
    # pre_tool_call hook
    invoke_hook("pre_tool_call", tool_name=..., args=...)
    
    result = registry.dispatch(function_name, function_args, ...)
    
    # post_tool_call hook
    invoke_hook("post_tool_call", tool_name=..., args=..., result=...)
    
    return result
```

#### pre_tool_call Can Block Tool Execution (2026-04-13)

The `pre_tool_call` hook can now **block tool execution**. Plugins can return:

```python
def my_pre_tool_call(tool_name, args):
    if tool_name == "terminal" and "rm -rf" in args.get("command", ""):
        return {"action": "block", "message": "Destructive commands disabled by policy"}
```

The framework collects return values from all plugins in `get_pre_tool_call_block_message()` (`hermes_cli/plugins.py:658`). The **first** `{"action": "block", "message": ...}` takes effect:
- Tool execution is skipped (does not proceed to `registry.dispatch`)
- The `message` is returned to the model as a tool result, allowing the model to adjust its next step accordingly
- All side effects are skipped: counter reset, checkpoints, callbacks, and read-loop tracker are not triggered

**Both execution paths are covered**:
- `handle_function_call()` (`model_tools.py:429`)
- `run_agent.py _invoke_tool` (sequential/concurrent paths)

To prevent double-triggering, `handle_function_call()` supports `skip_pre_tool_call_hook=True`: if `run_agent.py` has already performed an outer check, this flag can be passed when calling `handle_function_call` to skip the secondary check.

**Typical Use Cases**:
- Security policies (block dangerous commands)
- Quota/rate limiting
- Whitelist mode (only allow specific tools)
- Approval workflows (requires manual confirmation)

## Design Advantages

### Gateway Hooks vs Plugin System

| Dimension          | Gateway Hooks              | Plugin System                  |
|--------------------|----------------------------|--------------------------------|
| Scope              | Gateway mode only          | CLI + Gateway                  |
| Registration Method| Directory scan (HOOK.yaml) | Directory/entry-point scan (plugin.yaml) |
| Functionality      | Event notification         | Tool registration + hooks + CLI commands + message injection |
| Complexity         | Lightweight (170 LoC)      | Comprehensive (609 LoC)        |
| Use Cases          | Startup notifications, auditing, monitoring | Tool extension, custom behavior, third-party integrations |

### Error Isolation

```python
# Both systems adopt an "error non-propagation" design
try:
    result = fn(event_type, context)
except Exception as e:
    print(f"[hooks] Error in handler: {e}")  # Logs only, does not block
```

**Design Philosophy**: Errors in the extension system should not affect the core Agent process.

### Cache-Friendly Design for Context Injection

Context returned by Plugin hooks is injected into **user messages**, not the system prompt:

```
System Prompt (Cache Hit ✓)
  ├── Identity Definition (unchanged)
  ├── Platform Prompt (unchanged)
  └── Skill Index (unchanged)

User Message (different each turn)
  ├── User's original input
  └── [Injected context]  ← Content returned by hook
```

This ensures that the system prompt's cache is not invalidated by dynamically injected content.

## Configuration and Operation

### Disabling Plugins

```yaml
# config.yaml
plugins:
  disabled: ["some-plugin", "another-plugin"]
```

### Project Plugins

```bash
export HERMES_ENABLE_PROJECT_PLUGINS=true
```

### Installing Pip Plugins

```bash
# Plugin packages are declared in pyproject.toml:
# [project.entry-points."hermes_agent.plugins"]
# my-plugin = "my_plugin:register"

pip install hermes-agent-my-plugin
```

## PluginContext New API (v0.10.0, 2026-04-16)

### `register_command()` — Plugin Slash Commands

Previously, the dispatching code in `cli.py` and `gateway/run.py` already called `get_plugin_command_handler()`, but the registration side was not yet implemented. v0.10.0 completes this pipeline:

```python
def register(ctx):
    ctx.register_command(
        name="deploy",
        description="Deploy the current project",
        handler=my_deploy_handler,
    )
```

- Name normalization + conflict detection with built-in commands
- Registered commands automatically appear in Telegram bot menus and CLI autocompletion
- `/plugins` displays the number of commands registered by each plugin

### `dispatch_tool()` — Plugin Tool Dispatch

Plugin slash command handlers can dispatch tool invocations via the registry, automatically injecting the parent agent's context:

```python
async def my_handler(ctx, args):
    result = ctx.dispatch_tool("delegate_task", {
        "task": "refactor auth module",
        "instructions": "..."
    })
```

- CLI mode: Lazily parses the parent agent from `_cli_ref`
- Gateway mode: No `_cli_ref`, graceful tool degradation
- Use cases: Plugin commands like `/deliver` and `/fanout` derive child agents via `delegate_task`

### Shell Hooks (v2026.4.18+)

Implemented in `agent/shell_hooks.py` (831 LoC) + `hermes_cli/hooks.py` (385 LoC). Hook callbacks are no longer limited to Python – users can declare shell scripts as hooks in `config.yaml`:

```yaml
hooks:
  pre_tool_call:
    - command: /path/to/my-hook.sh
  subagent_stop:
    - command: /path/to/audit.sh
```

Scripts receive JSON events (tool_name/args, etc.) from stdin and return JSON decisions (can block tool invocation, inject context) to stdout.

**Key Design Points**:
- Registers closures on `PluginManager._hooks`, zero changes to `invoke_hook()` call points
- `subprocess.run(shell=False)` + `shlex.split` – no shell injection
- On first use, prompts user for consent for `(event, command)` pair, stored in allowlist JSON
- Bypassed via `--accept-hooks` / `HERMES_ACCEPT_HOOKS=1` / `hooks_auto_accept`
- `hermes hooks list/test/revoke/doctor` CLI subcommands
- Claude Code compatible response format (reusable with Claude Code ecosystem hook scripts)
- Added `subagent_stop` event (triggered when `delegate_task` child agent exits)

### Plugin Slash Commands Cross-Platform Native Integration (v2026.4.18+)

Plugin slash commands registered with `register_command()` now appear natively on each gateway platform:

- Discord native slash command picker
- Telegram BotCommand menu
- Slack `/hermes` subcommand mapping

No need to write separate plugin APIs for each platform. `register_command()` now includes an optional `args_hint` parameter, allowing plugins to declare argument structures, which Discord automatically uses to generate argument pickers.

#### Decisional Command Hooks

The `command:<name>` gateway hook has been upgraded to be **decisional**, collecting return values via `HookRegistry.emit_collect()`:

```python
def my_command_hook(event_type, context):
    if context["command"] == "deploy" and not user_has_permission(context["user"]):
        return {"decision": "deny", "message": "Permission denied"}
```

Decision types: `deny` / `handled` / `rewrite` / `allow`, intercepting before core processing. Backward compatible – fire-and-forget telemetry hooks still go through `emit()`.

### Dashboard Plugin System

Plugins can add custom tabs to the Web Dashboard:

```
~/.hermes/plugins/<name>/dashboard/
  manifest.json     # name, label, icon, tab config, entry point
  dist/index.js     # Pre-built JS bundle (IIFE, uses SDK global variables)
  plugin_api.py     # Optional FastAPI route, mounted at /api/plugins/<name>/
```

- `GET /api/dashboard/plugins` — Returns a list of discovered plugin manifests
- `GET /api/dashboard/plugins/rescan` — Forces a rescan
- `GET /dashboard-plugins/<name>/<path>` — Serves static resources (with path traversal protection)
- Supports optional automatic mounting of backend API routes

Also, a new **Dashboard Theme System** has been added, supporting real-time switching.

## Relationship with Other Systems

- [[tool-registry-architecture]] — Plugins register tools via registry.register()
- [[mcp-and-plugins]] — MCP is another tool discovery mechanism, complementary to the plugin system
- [[messaging-gateway-architecture]] — Gateway Hooks are triggered during the gateway's lifecycle
- [[model-tools-dispatch]] — pre/post_tool_call hooks are called within handle_function_call
