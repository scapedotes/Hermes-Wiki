---
title: AIAgent Class
created: 2026-04-07
updated: 2026-04-07
type: entity
tags: [component, agent, module]
sources: [Hermes Agent Source Code Analysis 2026-04-07]
---

# AIAgent Class

## Location

`run_agent.py`

## Overview

AIAgent is the core conversation loop class of Hermes Agent, responsible for managing LLM interactions, tool calls, and session state.

## Constructor

```python
class AIAgent:
    def __init__(self,
        model: str = "",  # Default empty string, parsed as "anthropic/claude-opus-4.6" at runtime
        max_iterations: int = 90,
        enabled_toolsets: list = None,
        disabled_toolsets: list = None,
        quiet_mode: bool = False,
        save_trajectories: bool = False,
        platform: str = None,           # "cli", "telegram", etc.
        session_id: str = None,
        skip_context_files: bool = False,
        skip_memory: bool = False,
        # ... more parameters: provider, api_mode, callbacks, routing params
    ):
```

## Core Methods

### `chat(self, message: str, stream_callback: Optional[callable] = None) -> str`

Simple interface, returns the final response string.

### `run_conversation(self, user_message: str, system_message: str = None, conversation_history: List[Dict] = None, task_id: str = None, stream_callback: Optional[callable] = None, persist_user_message: Optional[str] = None) -> Dict[str, Any]`

Full interface, returns a `{final_response, messages}` dictionary.

## Conversation Loop

```python
while api_call_count < self.max_iterations and self.iteration_budget.consume():  # consume() atomically checks and decrements the remaining budget
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tool_schemas
    )
    if response.tool_calls:
        for tool_call in response.tool_calls:
            result = handle_function_call(tool_call.name, tool_call.args, task_id, tool_call.id, session_id, user_task, enabled_tools)
            messages.append(tool_result_message(result))
        api_call_count += 1
    else:
        return response.content
```

## Key Features

- **Fully Synchronous** — Does not use asyncio
- **Tool Looping** — Supports multi-turn tool calls
- **Iteration Budget** — Controls the maximum number of API calls
- **Platform Aware** — Injects different prompts based on the platform
- **Memory Integration** — Automatically loads and injects memory
- **Skill Integration** - Builds skill indexes
- **Context Compression** — Automatically manages context length

## Related Pages

- [[agent-loop-and-prompt-assembly]] — Agent Core Loop and System Prompt Assembly
- [[multi-agent-architecture]] — Sub-Agent Delegation and Iteration Budget System
- [[prompt-builder-architecture]] — System Prompt Building Architecture

## Related Files

- `run_agent.py` — Implementation
- `model_tools.py` — Tool Orchestration
- `agent/prompt_builder.py` — System Prompt Building