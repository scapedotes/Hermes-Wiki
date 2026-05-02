---
title: Skills System Architecture
created: 2026-04-07
updated: 2026-04-29
type: concept
tags: [skill, architecture, module, prompt-builder]
sources: [tools/skills_tool.py, tools/skill_manager_tool.py, tools/skills_hub.py, tools/skills_guard.py, run_agent.py, agent/prompt_builder.py, hermes_cli/plugins.py, agent/skill_utils.py]
---

# Skills System Architecture

## Overview

The Hermes Agent's skill system adopts a **Progressive Disclosure** architecture, inspired by Anthropic's Claude Skills system. The core idea is to load full instructions only when needed, retaining lightweight metadata otherwise to conserve token budget.

## Core Components

### 1. Tool Layer (`tools/skills_tool.py`)

Provides two tools:
- **`skills_list`** — Returns a list of skill metadata (name, description, category), highly token-efficient.
- **`skill_view`** — Loads full skill content (SKILL.md + optional reference files).

### 2. Prompt Construction Layer (`agent/prompt_builder.py`)

During each system prompt construction:
- Scans the `~/.hermes/skills/` directory.
- Parses the YAML frontmatter of each SKILL.md.
- Constructs a skill index manifest injected into the system prompt.
- Caches results using [[prompt-builder-architecture]].

### 3. Skill Directory Structure

```
~/.hermes/skills/
├── my-skill/
│   ├── SKILL.md              # Main instruction file (required)
│   ├── references/           # Support documentation
│   │   ├── api.md
│   │   └── examples.md
│   ├── templates/            # Output templates
│   └── assets/               # Supplementary files (agentskills.io standard)
└── category/                 # Category directory
    └── another-skill/
        └── SKILL.md
```

### 4. SKILL.md Format

```yaml
---
name: skill-name                    # Required, max 64 characters
description: Brief description      # Required, max 1024 characters
version: 1.0.0                      # Optional
license: MIT                        # Optional
platforms: [macos]                  # Optional — restricts OS platforms
prerequisites:                      # Optional — runtime requirements
  env_vars: [API_KEY]               #   Environment variables
  commands: [curl, jq]              #   Command checks
setup:                              # Optional — interactive setup
  help: "Get key at https://..."    #   Help text
  collect_secrets:                  #   Secret collection
    - env_var: API_KEY
      prompt: "Enter your API key"
      secret: true
metadata:                           # Optional
  hermes:
    tags: [fine-tuning, llm]
    related_skills: [peft, lora]
---

# Skill Title

Full instructions and content here...
```

## Skill Discovery Process

```python
# 1. Get all skill directories
get_all_skills_dirs() → [Path, Path, ...]

# 2. Parse frontmatter of each SKILL.md
parse_frontmatter(raw_content) → (dict, body)

# 3. Check platform compatibility
skill_matches_platform(frontmatter) → bool

# 4. Extract conditional activation rules
extract_skill_conditions(frontmatter) → {
    "requires_tools": [...],
    "requires_toolsets": [...],
    "fallback_for_tools": [...],
    "fallback_for_toolsets": [...]
}

# 5. Build skill index and inject into system prompt
_build_skills_index(available_tools, available_toolsets) → str
```

## Conditional Activation Mechanism

Skills can be conditionally displayed based on currently available tools/toolsets:

- **`requires_tools`** — Requires specific tools to be displayed.
- **`requires_toolsets`** — Requires specific toolsets to be displayed.
- **`fallback_for_tools`** — Hidden when primary tools are available (as a fallback).
- **`fallback_for_toolsets`** — Hidden when primary toolsets are available.

## Platform Filtering

The `platforms` frontmatter field restricts skills to be loaded only on specific OS:
- `macos` → `sys.platform == "darwin"`
- `linux` → `sys.platform == "linux"`
- `windows` → `sys.platform == "win32"`

## Plugin Namespaced Skills (2026-04-14)

In addition to the flat directory scan of `~/.hermes/skills/`, plugins can also register **namespaced skills** to avoid naming conflicts with built-in skills.

### Registration Method

```python
# Plugin's __init__.py
def register(ctx):
    ctx.register_skill(
        name="deploy",
        path=Path(__file__).parent / "skills" / "deploy" / "SKILL.md",
        description="Deploy a service to production",
    )
```

`PluginContext.register_skill()` internally stores it as a qualified name in the format `{plugin_name}:{name}`, e.g., a `deploy` skill registered by the `myops` plugin would actually be named `myops:deploy`.

**Validation Rules** (`hermes_cli/plugins.py:267`):
- `name` cannot contain `:` (namespace is automatically derived from plugin name).
- `name` must match `[a-zA-Z0-9_-]+`.
- `path` must point to an existing SKILL.md.

### Dispatch Logic

`skill_view(name)` in `tools/skills_tool.py:822` detects the `:` separator:
- **Names with `:`** → `parse_qualified_name(name)` → Route to `_serve_plugin_skill(namespace, bare)`.
- **Bare names** → Continue with the original `~/.hermes/skills/` flat tree scan.

Plugin skill loading runs full protection:
1. Plugin is disabled → Returns an error (including `hermes plugins enable` hint).
2. Platform mismatch (`skill_matches_platform`) → Returns UNSUPPORTED.
3. Injection pattern scan (`_INJECTION_PATTERNS`) → Logs but still loads (consistent with local skills).
4. Returns with a **bundle context banner**, listing other skills from the same plugin for agent reference.

### Not Included in System Prompt Index

**Key difference**: Plugin skills **do not appear** in the `<available_skills>` list in the system prompt. They are **explicitly opt-in** — the agent must know the name (via documentation or plugin README) to call `skill_view("myops:deploy")`.

Reasons for this design:
- Avoids plugin clutter in the main prompt (system prompt is already substantial).
- Prevents prefix cache invalidation due to fluctuations in third-party plugin count.
- The agent should not automatically perceive all plugins installed by the user.

### Related APIs

| Symbol | Location | Purpose |
|---|---|---|
| `PluginContext.register_skill()` | `hermes_cli/plugins.py:267` | Plugin registration entry point |
| `PluginManager._plugin_skills` | `hermes_cli/plugins.py` | Registry storage |
| `parse_qualified_name()` | `agent/skill_utils.py:451` | Decomposes `ns:bare` |
| `is_valid_namespace()` | `agent/skill_utils.py` | Namespace validity check |
| `_serve_plugin_skill()` | `tools/skills_tool.py:718` | Load + protection + banner |
| `_INJECTION_PATTERNS` | `tools/skills_tool.py`(module-level) | Injection detection shared with local skills |

## Secret Management

Skills can declare required environment variables, and the system will:
1. Check if `~/.hermes/.env` is already set.
2. If missing and in CLI mode, interactively collect via callback.
3. In Gateway mode, prompt the user for manual configuration.
4. Persist to `.env` file after saving.

## Automatic Skill Review (Background Review)

Hermes not only passively uses Skills but can also **autonomously create and update Skills**. This is Hermes' "self-evolution" mechanism.

### Trigger Conditions

Triggered when three conditions are met simultaneously:

```python
if (self._skill_nudge_interval > 0                          # Feature not disabled
        and self._iters_since_skill >= self._skill_nudge_interval  # Accumulated tool calls meet threshold
        and "skill_manage" in self.valid_tool_names):        # skill_manage tool is available
```

```yaml
# config.yaml
skills:
  creation_nudge_interval: 15   # Triggers a review every 15 accumulated tool calls (0 = disabled)
```

Note: The counter accumulates **tool loop iterations** (not conversation turns) and persists across turns. The counter resets when the agent explicitly calls `skill_manage`.

### Execution Flow

```text
Tool calls accumulate to 15
    ↓
After the turn, a background agent is spawned (separate thread, max_iterations=8)
    ↓
The background agent takes a full conversation snapshot and reviews:
  "Are there any non-trivial experiences involving trial-and-error, course correction, or user expectations for different approaches?"
    ↓
Three possible outcomes:
  ├── Existing skill found → Calls skill_manage to update.
  ├── None, but worth creating → Calls skill_manage to create.
  └── Nothing worth saving → "Nothing to save." Ends.
    ↓
Terminal output: 💾 Skill "docker-network-debug" created
```

### Design Characteristics

- **Non-blocking for user**: Initiates after responding to the user, not occupying conversation latency.
- **Does not modify main conversation**: The background agent runs independently and does not affect the main agent's message history.
- **Shared memory storage**: The background agent shares `_memory_store` with the main agent, making skills immediately available upon writing.
- **Mergeable with Memory Nudge**: When both skill review and memory review are triggered simultaneously, a merged prompt is used for a single processing.

### Differences from Manual Creation

| | Manual Creation (User Instruction) | Automatic Creation (Background Review) |
|---|---|---|
| Trigger Method | User says "help me create a skill" | System counter automatically triggers |
| Content Source | User specified | Background agent extracts from conversation |
| Quality | User controlled | Agent autonomously decides, may create or skip |
| LLM Consumption | Part of the main conversation | Additional consumption (background agent max 8 iterations) |

## Curator — Background Skill Maintenance (v2026.4.23+)

Introduces an **auxiliary model-driven background maintenance mechanism** (`agent/curator.py`, 869 lines + `hermes_cli/curator.py`, 235 lines + `tools/skill_usage.py`). It periodically reviews **agent-created** skills, tracks usage, and archives idle skills through state machine transitions.

### Invariants (load-bearing)

- **Never touches** bundled or hub-installed skills (`.bundled_manifest` + `.hub/lock.json` dual filter).
- **Never automatically deletes** — only archives; can be restored via `hermes curator restore <skill>`.
- **Pinned skills skip all automatic transitions**: `tools/skill_manager_tool.py:_pinned_guard()` intercepts modifications to pinned skills on the `skill_manage` write path.
- Uses an auxiliary client, **never pollutes the main session's prompt cache**.

### Trigger Logic

Enabled by default, **inactivity-triggered** (no cron daemon): Checks on CLI startup + gateway startup, runs only if two conditions are met:
1. Last run > `interval_hours` (default `24 * 7 = 168`, i.e., 7 days, `agent/curator.py:39`).
2. Agent has been idle for > `min_idle_hours` (default `2`, `agent/curator.py:40`).

In Gateway mode, it also hooks into a cron-ticker thread for periodic checks.

### State Machine

```
active ──unused for N days──> stale ──continues unused──> archived
   ↑                                         │
   └──────── re-used ────────────────────────┘
```

Purely functional (state-machine transitions within `agent/curator.py`), no LLM calls. A Forked AIAgent intervenes only when **integrating overlaps + patching drift** is needed.

### Sidecar Telemetry

`tools/skill_usage.py` maintains a `.usage.json` sidecar file for each skill:
- Atomic writes + provenance filter.
- Records usage count and last used timestamp, serving as input signals for the state machine.

### CLI

```bash
hermes curator status        # Current status, pending skills
hermes curator run           # Run a cycle immediately
hermes curator pause/resume  # Pause/resume
hermes curator pin <skill>   # Pin a skill (skips automatic transitions)
hermes curator unpin <skill>
hermes curator restore <skill>  # Restore from archive
```

The `/curator` slash command exposes the same subcommands.

## /reload-skills and /reload-mcp (v2026.4.23+)

**`/reload-skills`**: Rescans `~/.hermes/skills/` to discover newly installed/uninstalled skills without requiring a process restart. This is a **user-initiated rescan** — it does not reset the prompt cache (skills are called on-demand via `/skill-name`, `skills_list`, `skill_view`, and do not need to be resident in the system prompt). After the rescan, the agent is notified via a next-turn note, with each added/removed skill accompanied by a 60-character description.

> Note: The original PR included a `skills_reload` agent tool, but it was explicitly removed in a subsequent refactor (`dd2d1ba5e`) — the agent can already see newly installed skills on disk via `skill_view` / `skills_list`, so no additional schema surface is needed.

**`/reload-mcp` with confirmation prompt**: MCP reload invalidates the prompt cache. The gateway now pops up a confirmation dialog (including an "don't ask again" opt-out option) to prevent accidental clearing of the expensive cache.

## Refusal to Write Pinned Skills (v2026.4.23+)

`tools/skill_manager_tool.py:134` adds `_pinned_guard(name)` to intercept modifications to pinned skills on the `skill_manage` create/update/archive/delete paths:

```python
if rec.get("pinned"):
    return f"Skill '{name}' is pinned and cannot be modified by skill_manage..."
```

This is an extension of the Curator's invariants — the pinned status is also a no-go zone for the agent, and can only be explicitly unpinned via `hermes curator unpin`.

## Related Pages

- [[prompt-builder-architecture]] — Skill Index Construction and Conditional Activation
- [[skills-and-memory-interaction]] — Interaction Design for Skills and Memory
- [[security-defense-system]] — Skill Security Scanning and Trust Level Policies

## Related Files

- `tools/skills_tool.py` — Skill tool implementation (1378 lines)
- `agent/prompt_builder.py` — Prompt Construction and Skill Indexing
- `agent/skill_utils.py` — Skill Parsing Utility Functions
- `agent/skill_commands.py` — Skill Slash Commands
- `tools/skills_sync.py` — Skill Synchronization Mechanism
- `tools/skills_hub.py` — Skill Hub (Search/Install)
- `tools/skill_manager_tool.py` — Skill Management Tool