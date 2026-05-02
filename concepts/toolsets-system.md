---
title: Toolsets System
created: 2026-04-07
updated: 2026-04-07
type: concept
tags: [toolset, tool, tool-registry, architecture]
sources: [Hermes Agent Source Code Analysis 2026-04-07]
---

# Toolsets System

## Overview

Toolsets is Hermes Agent's **tool grouping system**, allowing tools to be combined into meaningful collections and enabling different toolsets for various scenarios/platforms.

## Core Design

```python
# toolsets.py
_HERMES_CORE_TOOLS = [
    # Web
    "web_search", "web_extract",
    # Terminal + process management
    "terminal", "process",
    # File manipulation
    "read_file", "write_file", "patch", "search_files",
    # Vision + image generation
    "vision_analyze", "image_generate",
    # Skills
    "skills_list", "skill_view", "skill_manage",
    # Browser automation
    "browser_navigate", "browser_snapshot", "browser_click",
    "browser_type", "browser_scroll", "browser_back",
    "browser_press", "browser_get_images",
    "browser_vision", "browser_console",
    # Text-to-speech
    "text_to_speech",
    # Planning & memory
    "todo", "memory",
    # Session history search
    "session_search",
    # Clarifying questions
    "clarify",
    # Code execution + delegation
    "execute_code", "delegate_task",
    # Cronjob management
    "cronjob",
    # Cross-platform messaging
    "send_message",
    # Home Assistant
    "ha_list_entities", "ha_get_state", "ha_list_services", "ha_call_service",
]
```

## Toolset Definition

```python
TOOLSETS = {
    # Basic Toolset
    "web": {
        "description": "Web research and content extraction tools",
        "tools": ["web_search", "web_extract"],
        "includes": []  # Does not include other toolsets
    },
    
    # Composite Toolset
    "debugging": {
        "description": "Debugging and troubleshooting toolkit",
        "tools": ["terminal", "process"],
        "includes": ["web", "file"]  # Combines other toolsets
    },
    
    # Platform-Specific Toolsets
    "hermes-telegram": {
        "description": "Telegram bot toolset",
        "tools": _HERMES_CORE_TOOLS,  # Uses the core tools list
        "includes": []
    },
    
    "hermes-acp": {
        "description": "Editor integration (VS Code, Zed, JetBrains)",
        "tools": [...],  # Code-specific, no messaging/audio/clarify
        "includes": []
    },
    
    "hermes-api-server": {
        "description": "OpenAI-compatible API server",
        "tools": [...],  # Full toolset, no interactive UI tools
        "includes": []
    },
    
    # Note: "all" is not an entry in TOOLSETS
    # It's handled as a special case in resolve_toolset()
    # if name in {"all", "*"}: ...
}
```

## Recursive Resolution

```python
def resolve_toolset(name: str, visited: Set[str] = None) -> List[str]:
    """Recursively resolves a toolset, handling composite dependencies"""
    
    # Special aliases: all or *
    if name in {"all", "*"}:
        all_tools = set()
        for toolset_name in get_toolset_names():
            resolved = resolve_toolset(toolset_name, visited.copy())
            all_tools.update(resolved)
        return list(all_tools)
    
    # Cycle detection
    if name in visited:
        return []  # Return silently
    
    visited.add(name)
    toolset = TOOLSETS.get(name)
    
    # Collect direct tools
    tools = set(toolset.get("tools", []))
    
    # Recursively resolve included toolsets
    for included_name in toolset.get("includes", []):
        included_tools = resolve_toolset(included_name, visited)
        tools.update(included_tools)
    
    return list(tools)
```

## Platform Toolsets

| Toolset             | Platform             | Characteristics            |
|---------------------|----------------------|----------------------------|
| `hermes-cli`        | Terminal CLI         | Full toolset               |
| `hermes-telegram`   | Telegram             | Full toolset               |
| `hermes-discord`    | Discord              | Full toolset               |
| `hermes-whatsapp`   | WhatsApp             | Full toolset               |
| `hermes-slack`      | Slack                | Full toolset               |
| `hermes-signal`     | Signal               | Full toolset               |
| `hermes-homeassistant`| Home Assistant       | Smart home control         |
| `hermes-email`      | Email (IMAP/SMTP)    | Email interaction          |
| `hermes-sms`        | SMS (Twilio)         | SMS, character limited     |
| `hermes-mattermost` | Mattermost           | Self-hosted team messaging |
| `hermes-matrix`     | Matrix               | Decentralized encrypted messaging |
| `hermes-dingtalk`   | DingTalk             | Enterprise messaging       |
| `hermes-feishu`     | Feishu/Lark          | Enterprise messaging       |
| `hermes-wecom`      | WeCom                | Enterprise messaging       |
| `hermes-webhook`    | Webhook              | Receive external events    |
| `hermes-acp`        | Editor Integration   | Coding specific            |
| `hermes-api-server` | HTTP API             | Accessed via HTTP          |

## Plugin Extension

Toolsets support dynamic plugin registration:

```python
def _get_plugin_toolset_names() -> Set[str]:
    """Returns the names of toolsets registered by plugins"""
    from tools.registry import registry
    return {
        entry.toolset
        for entry in registry._tools.values()
        if entry.toolset not in TOOLSETS
    }
```

## Tool Registry

```python
# tools/registry.py
class ToolRegistry:
    def register(self, name, toolset, schema, handler, ...):
        """Registers a tool to the central registry (requires toolset parameter)"""
    
    def get_schema(self, name):
        """Gets the schema definition for a tool"""
    
    def get_all_tool_names(self):
        """Gets the names of all registered tools"""
```

Each tool file automatically registers upon import:

```python
# tools/terminal_tool.py
from tools.registry import registry

registry.register(
    name="terminal",
    toolset="terminal",
    schema=TERMINAL_SCHEMA,
    handler=terminal_handler,
    ...
)
```

## Tool Enabling/Disabling

Managed via the `hermes tools` command or configuration:

```yaml
# ~/.hermes/config.yaml
tools:
  disabled:
    telegram: ["image_generate"]
    discord: ["text_to_speech"]
```

## File Dependency Chain

```
tools/registry.py  (No dependencies — imported by all tool files)
       ↑
tools/*.py  (Each calls registry.register() upon import)
       ↑
model_tools.py  (Imports tools/registry + triggers tool discovery)
       ↑
run_agent.py, cli.py, batch_runner.py, environments/
```

## Related Pages

- [[tool-registry-architecture]] — Central Tool Registry (Registry organizes tools by toolset)
- [[model-tools-dispatch]] — Tool Orchestration Layer filters tool definitions by toolset
- [[mcp-and-plugins]] — Plugin Dynamic Registration for Toolset Extension

## Related Files

- `toolsets.py` — Toolset Definition and Resolution
- `tools/registry.py` — Central Tool Registry
- `model_tools.py` — Tool Orchestration, `_discover_tools()`, `handle_function_call()`
- `hermes_cli/tools_config.py` — Tool Enabling/Disabling Configuration
---