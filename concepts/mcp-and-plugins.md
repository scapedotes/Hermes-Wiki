---
title: MCP Integration and Plugin System
created: 2026-04-07
updated: 2026-04-07
type: concept
tags: [architecture, mcp, plugins, extensibility]
sources: [hermes-agent source code analysis 2026-04-07]
---

# MCP Integration and Plugin System

## Design Principles

Hermes achieves extensibility through the **Model Context Protocol (MCP)** and a **plugin system**, enabling connection to external tools and custom behaviors.

## MCP Integration

```python
# tools/mcp_tool.py (~L2176)

class MCPServerTask:
    """MCP Server Task"""
    
    def __init__(self, config: dict):
        self.servers = {}
        self.tools = {}
    
    async def connect_server(self, name: str, config: dict):
        """Connect to an MCP server"""
        transport = config.get("transport", "stdio")
        
        if transport == "stdio":
            process = await asyncio.create_subprocess_exec(
                *config["command"],
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
            )
            self.servers[name] = {
                "process": process,
                "transport": transport,
            }
        elif transport == "http":
            self.servers[name] = {
                "url": config["url"],
                "transport": transport,
            }
        
        # Get server tools
        tools = await self._list_tools(name)
        for tool in tools:
            self.tools[f"{name}:{tool['name']}"] = tool
    
    async def call_tool(self, tool_name: str, args: dict) -> dict:
        """Call an MCP tool"""
        server_name, tool_name = tool_name.split(":", 1)
        server = self.servers[server_name]
        
        if server["transport"] == "stdio":
            return await self._call_stdio_tool(server, tool_name, args)
        elif server["transport"] == "http":
            return await self._call_http_tool(server, tool_name, args)
```

### MCP OAuth Support

```python
# tools/mcp_oauth.py

async def authenticate_mcp_server(server_config: dict) -> dict:
    """MCP Server OAuth authentication"""
    auth_type = server_config.get("auth", {}).get("type")
    
    if auth_type == "oauth":
        # Implement OAuth flow
        auth_url = server_config["auth"]["url"]
        client_id = server_config["auth"]["client_id"]
        # ...
        return {"access_token": token, "expires_at": expires}
    
    elif auth_type == "api_key":
        return {"api_key": server_config["auth"]["api_key"]}
    
    return {}
```

## Plugin System

```python
# hermes_cli/plugins.py

class Plugin:
    """Base class for plugins"""
    
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    
    def on_load(self):
        """Called when the plugin is loaded"""
        pass
    
    def on_unload(self):
        """Called when the plugin is unloaded"""
        pass

# Hook System
_HOOKS = {
    "on_session_start": [],
    "pre_llm_call": [],
    "post_llm_call": [],
    "on_tool_call": [],
    "on_session_end": [],
}

def register_hook(hook_name: str, callback: callable):
    """Register a hook callback"""
    if hook_name in _HOOKS:
        _HOOKS[hook_name].append(callback)

def invoke_hook(hook_name: str, **kwargs) -> list:
    """Invoke a hook"""
    results = []
    for callback in _HOOKS.get(hook_name, []):
        try:
            result = callback(**kwargs)
            results.append(result)
        except Exception as e:
            logger.warning(f"Hook {hook_name} failed: {e}")
    return results
```

### Memory Plugin

```python
# plugins/memory/__init__.py

class MemoryPlugin(Plugin):
    """Memory plugin (Honcho integration)"""
    
    name = "honcho-memory"
    
    def on_session_start(self, session_id: str, **kwargs):
        """Warm up cache when a session starts"""
        self._warm_cache(session_id)
    
    def pre_llm_call(self, user_message: str, **kwargs):
        """Inject context before LLM call"""
        context = self._fetch_context(user_message)
        return {"context": context}
    
    def on_session_end(self, messages: list, **kwargs):
        """Persist at session end"""
        self._persist_session(messages)
```

## Plugin CLI

```bash
# Plugin management
hermes plugins list           # List installed plugins
hermes plugins install <name> # Install a plugin
hermes plugins remove <name>  # Remove a plugin
hermes plugins update <name>  # Update a plugin
```

## Configuration

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  filesystem:
      command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/root/work"]
    github:
      command: ["npx", "-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"

plugins:
  enabled:
    - honcho-memory
    - custom-plugin
```

## Comparative Analysis

### Comparison with Other Agent Frameworks

| Feature | Hermes | Cursor | Claude Code |
|---------|--------|--------|-------------|
| MCP Support | ✅ Full | ✅ | ✅ |
| MCP OAuth | ✅ | ❌ | ✅ |
| Plugin System | ✅ Hook system | ❌ | ❌ |
| Custom Tools | ✅ Registry | ❌ | ❌ |
| Plugin CLI | ✅ | N/A | N/A |

## Related Pages

- [[tool-registry-architecture]] — Plugins register tools via registry.register()
- [[hook-system-architecture]] — The plugin hook system complements gateway event hooks
- [[model-tools-dispatch]] — MCP tools are integrated into the orchestration layer via a discovery mechanism

## Related Files

- `tools/mcp_tool.py` — MCP Server Task
- `tools/mcp_oauth.py` — MCP OAuth
- `hermes_cli/plugins.py` — Plugin System
- `plugins/` — Plugin Directory