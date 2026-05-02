---
title: CLI Architecture and Terminal Interaction Design
created: 2026-04-07
updated: 2026-04-11
type: concept
tags: [architecture, cli, terminal, ux]
sources: [hermes-agent source code analysis 2026-04-07]
---

# CLI Architecture and Terminal Interaction Design

## Design Principles

Hermes CLI offers a complete terminal user experience: autocompletion, multi-line editing, streaming output, and tool call visualization. It is built upon `prompt_toolkit` and `rich`.

## Core Components

```python
# cli.py
class HermesCLI:
    """Main class for Hermes CLI"""
    
    def __init__(self):
        self.agent = None
        self.config = load_cli_config()
        self.session_db = SessionDB(...)
        self.todo_store = TodoStore()
    
    def run(self):
        """Main loop"""
        while True:
            user_input = self._get_input()  # prompt_toolkit input
            if user_input.startswith("/"):
                self._handle_command(user_input)
            else:
                self._handle_message(user_input)
```

## Input System

```python
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

session = PromptSession(
    history=FileHistory("~/.hermes/input_history"),
    auto_suggest=AutoSuggestFromHistory(),
    completer=SlashCommandCompleter(),  # Defined in hermes_cli/commands.py
)

user_input = session.prompt(get_active_prompt_symbol())  # The prompt symbol is configured via the skin engine
```

### Slash Command Autocompletion

```python
class SlashCommandCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith("/"):
            for cmd_name, cmd_def in COMMANDS.items():
                if cmd_name.startswith(text[1:]):
                    yield Completion(cmd_name, start_position=-len(text[1:]))
```

## Display System

### KawaiiSpinner

```python
# agent/display.py
class KawaiiSpinner:
    """Animated loading indicator"""
    
    SPINNERS: dict          # 9 named animation sets ('dots', 'bounce', 'grow', ...)
    KAWAII_WAITING: list     # 10 multi-character emoticons
    KAWAII_THINKING: list    # 15 multi-character emoticons
    THINKING_VERBS: list    # 15 verbs ("pondering", "contemplating", "musing", "cogitating", "ruminating", ...)
    
    def show(self, message: str):
        """Displays the loading animation"""
        # Uses Rich panels and animations
```

### Tool Call Preview

```python
def build_tool_preview(tool_name: str, args: dict) -> str:
    """Builds a tool call preview"""
    preview = f"🔧 {tool_name}("
    for key, value in list(args.items())[:3]:
        preview += f"\n  {key}={preview_value(value)},"
    preview += "\n)"
    return preview

def get_cute_tool_message(tool_name: str) -> str:
    """Gets a friendly tool execution message"""
    emoji = _get_tool_emoji(tool_name)
    return f"{emoji} Calling {tool_name}..."
```

## Skin Engine

```python
# hermes_cli/skin_engine.py
@dataclass
class SkinConfig:
    """Skin configuration data class"""
    ...

# Module-level functions (not methods)
def init_skin_from_config(): ...
def get_active_skin() -> SkinConfig: ...
def list_skins() -> list: ...
def set_active_skin(name: str): ...

# Configuration example
# ~/.hermes/config.yaml
display:
  skin: "default"  # or custom skin name
```

## Advantage Analysis

### Comparison with Other Agent Frameworks

| Feature | Hermes | Claude Code | Codex CLI |
|-------------------------|--------|-------------|-----------|
| Slash Command Autocompletion | ✅ Automatic | ✅ | ❌ |
| Multi-line Editing | ✅ | ✅ | ✅ |
| Input History | ✅ File Persistence | ✅ | ✅ |
| Animated Loading | ✅ KawaiiSpinner | ✅ Simple | ✅ Simple |
| Theming System | ✅ Skin Engine | ❌ | ❌ |
| Tool Call Preview | ✅ Formatted | ✅ | ❌ |

## Related Pages

- [[configuration-and-profiles]] — Configuration Management and Profile System
- [[hook-system-architecture]] — Hook and Plugin Extension System
- [[session-search-and-sessiondb]] — Session Search and SessionDB
- [[voice-mode-architecture]] — Voice Mode (Push-to-talk → STT → TTS)
- [[skin-engine]] — Skin/Theme Customization
- [[context-references]] — @file/@diff/@url Reference System
- [[worktree-isolation]] — Git Worktree Parallel Isolation
- [[code-execution-sandbox]] — Code Execution Sandbox

## Related Files

- `cli.py` — Main CLI class
- `hermes_cli/main.py` — Entry point and subcommands
- `hermes_cli/commands.py` — Slash command definitions
- `hermes_cli/dump.py` — `hermes dump` environment summary (plain text, for debugging/issue reporting)
- `agent/display.py` — Display system
- `hermes_cli/skin_engine.py` — Skin engine