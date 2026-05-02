---
title: Configuration Management and Multi-Profile Architecture
created: 2026-04-07
updated: 2026-04-09
type: concept
tags: [architecture, configuration, profile, isolation]
sources: [hermes_cli/profiles.py, hermes_cli/config.py, hermes_cli/main.py, hermes_cli/gateway.py, hermes_constants.py, plugins/memory/honcho/cli.py, agent/prompt_builder.py]
---

# Configuration Management and Multi-Profile Architecture

## Overview

Hermes manages complex multi-dimensional configurations through **layered configuration + Profile isolation**. The Profile is a core design concept – each Profile is a completely independent `HERMES_HOME` directory, with its own configurations, memory, sessions, skills, gateways, and scheduled tasks.

## Configuration Hierarchy

```text
Priority from low to high:
  1. Hardcoded defaults         (hermes_cli/config.py DEFAULT_CONFIG)
  2. User configuration file    (~/.hermes/config.yaml)
  3. Environment variables      (.env file + shell environment variables)
  4. CLI arguments              (--model, --provider, etc. command-line arguments)
  5. Profile override           (HERMES_HOME environment variable pointing to a different directory)
```

## Configuration File Structure

Hermes has two sets of configuration files, each with different responsibilities:

| File         | Stores What            | How It Takes Effect         |
|--------------|------------------------|-----------------------------|
| `.env`       | API Keys, sensitive credentials | Environment variable injection |
| `config.yaml`| Runtime behavior configuration | Read by `load_config()`     |

```yaml
# ~/.hermes/config.yaml Core Configuration Items
model:
  default: "anthropic/claude-opus-4.6"
  provider: "auto"
  base_url: "https://openrouter.ai/api/v1"

terminal:
  backend: "local"
  cwd: "."
  timeout: 180

compression:
  enabled: true
  threshold: 0.50
  summary_model: "google/gemini-3-flash-preview"

memory:
  memory_enabled: true
  user_profile_enabled: true
  memory_char_limit: 2200
  user_char_limit: 1375
  nudge_interval: 10
  flush_min_turns: 6
```

## Multi-Profile Architecture

### Core Principle

All Hermes modules resolve paths via `get_hermes_home()`:

```python
# hermes_constants.py — Globally unique path source
def get_hermes_home() -> Path:
    return Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
```

Switching a Profile = Changing the `HERMES_HOME` environment variable. With over 119 files in the codebase calling `get_hermes_home()`, all paths are automatically redirected when a Profile is switched, without any module needing to be aware of the Profile's existence.

### Directory Structure

```text
~/.hermes/                              ← "default" Profile (for backward compatibility)
  active_profile                        ← Sticky default pointer (stores Profile name)
  config.yaml, .env, SOUL.md            ← default Profile's configuration
  memories/, sessions/, skills/         ← default Profile's data
  state.db                              ← default Profile's database
  profiles/                             ← Named Profile root directory
    coder/                              ← Named Profile (becomes HERMES_HOME when active)
      config.yaml                       ← Independent model/terminal/compression configuration
      .env                              ← Independent API Keys
      SOUL.md                           ← Independent Agent identity definition
      memories/MEMORY.md, USER.md       ← Independent persistent memory
      sessions/                         ← Independent session logs
      skills/                           ← Independent skill set
      state.db                          ← Independent SQLite database
      honcho.json                       ← Independent Honcho configuration
      logs/, cron/, skins/, plans/, workspace/
    ops/                                ← Another Profile
      ...

~/.local/bin/
  coder   → #!/bin/sh\nexec hermes -p coder "$@"
  ops     → #!/bin/sh\nexec hermes -p ops "$@"
```

**The internal structure of each Profile is identical**, containing the following directories: `memories`, `sessions`, `skills`, `skins`, `logs`, `plans`, `workspace`, `cron`.

### Profile Activation Flow

```text
hermes -p coder chat
       │
       ▼
_apply_profile_override()          ← module-level in main.py, executed before any imports
       │
       ├─ Parse sys.argv for -p/--profile arguments
       ├─ Not found → Read ~/.hermes/active_profile (sticky default)
       │
       ▼
os.environ["HERMES_HOME"] = "~/.hermes/profiles/coder"
       │
       ▼
get_hermes_home() → Returns Profile directory
       │
       ▼
All modules automatically operate on the coder Profile
(config, memory, skills, gateway, session are all isolated)
```

Key point: `_apply_profile_override()` executes at the **module level**, prior to all `import` statements—because many modules cache `HERMES_HOME` during import.

### CLI Commands

```bash
# Create
hermes profile create coder              # Blank Profile + seed built-in skills
hermes profile create coder --clone      # Clones config.yaml + .env + SOUL.md + memory
hermes profile create coder --clone-all  # Full copy of all states (excluding runtime files)
hermes profile create coder --no-alias   # Does not generate wrapper shortcut commands

# Use
hermes -p coder chat                     # Start with a specified Profile
coder chat                               # Launch via wrapper shortcut
hermes profile use coder                 # Set as sticky default

# Manage
hermes profile list                      # View all Profile statuses
hermes profile show coder                # Detailed information (model/gateway/skill count)
hermes profile rename coder developer    # Rename
hermes profile alias coder --name dev    # Custom alias
hermes profile export coder              # Export as tar.gz
hermes profile import archive.tar.gz     # Import
hermes profile delete coder              # Delete (requires confirmation)
```

### Profile Naming Rules

```text
Regex: ^[a-z0-9][a-z0-9_-]{0,63}$
  ✅ coder, ops-team, dev2, my_profile
  ❌ Coder (uppercase), -ops (prefix hyphen), hermes (reserved name), chat (subcommand conflict)
```

Reserved names: `hermes`, `default`, `test`, `tmp`, `root`, `sudo` + all Hermes subcommand names.

### Cloning Behavior

| Mode          | Content Copied                                  |
|---------------|-------------------------------------------------|
| `--clone`     | config.yaml, .env, SOUL.md, MEMORY.md, USER.md  |
| `--clone-all` | Full copytree (excluding runtime files like gateway.pid) |
| No parameters | Only creates directory structure + seeds built-in skills |

Memory files (MEMORY.md / USER.md) are copied with `--clone`. Source code comment: "Memory files are part of the agent's curated identity — just as important as SOUL.md for continuity."

### Export/Import Security

**Exclude sensitive files during export:**
- `.env` (API Keys)
- `auth.json` (OAuth tokens)
- `state.db` (may contain sensitive conversations)
- Various caches (image_cache, audio_cache, checkpoints)

**Security checks during import:**
- Reject path traversal attacks (`../`)
- Reject absolute paths (`/etc/passwd`)
- Reject Windows drive letters (`C:\`)
- Reject symbolic links
- Only allows regular files and directories

## Profile and Subsystem Interoperability

### Gateway Isolation

Each Profile can run its own independent Gateway (Telegram/Slack, etc.):

```text
default Profile  → hermes-gateway          (service name)
coder Profile    → hermes-gateway-coder    (service name with suffix)
```

- PID files operate within their respective `HERMES_HOME`s, avoiding conflicts.
- systemd/launchd service names automatically include the Profile suffix.
- If two Profiles use the same Bot Token, the second Gateway will be blocked and error out.

### Honcho Memory Isolation

Each Profile has an independent host block in Honcho:

```text
default → hermes          (host key)
coder   → hermes.coder    (host key with suffix)
```

AI Peer is isolated by Profile (independent user modeling), but the workspace is shared (all Profiles see the same user observation data).

Honcho configuration is automatically cloned when creating a new Profile; `hermes update` automatically syncs Honcho host blocks for all Profiles.

### SOUL.md Identity

Each Profile has its own `SOUL.md`, defining the Agent's identity and behavioral norms. `prompt_builder.py` loads it via `get_hermes_home() / "SOUL.md"`, automatically pointing to the corresponding file after a Profile switch.

### Skill Synchronization

`hermes update` automatically syncs built-in skills to **all** Profiles:

```text
hermes update
  → Updates current Profile skills
  → Scans all other Profiles
  → Executes seed_profile_skills() for each Profile
  → User-defined skills will not be overwritten
```

Skill seeding is executed via **subprocess** (not in-process) because `sync_skills()` caches `HERMES_HOME` at the module level.

### Banner and Prompt

- Startup Banner displays the current Profile name (when not `default`).
- CLI input prompt includes a Profile prefix: `coder >` instead of `>`.
- Gateway supports the `/profile` command to view the current Profile.

## Typical Use Cases

```bash
# Scenario: Isolation by function
hermes profile create coder --clone       # Daily development
hermes profile create ops --clone         # Operations tasks
hermes profile create research --clone    # Research and exploration

# Configure different security boundaries separately
hermes -p coder config set terminal.backend local
hermes -p ops config set terminal.backend docker
hermes -p research config set terminal.backend ssh

# Configure different models separately
hermes -p coder config set model.default "anthropic/claude-opus-4.6"
hermes -p research config set model.default "google/gemini-2.5-pro"

# Run their respective Gateways separately
hermes -p coder telegram &
hermes -p ops telegram &
```

## Relationship with Multi-Agent

Multi-Profile can be considered Hermes' **second multi-Agent solution**. In-session multi-agent (delegate_task) is suitable for "parallel division of labor within a single task", while Multi-Profile is suitable for "long-term isolation of different functional roles". Both are complementary:

- A delegate_task sub-agent **inherits the parent agent's terminal backend**, making it unable to switch isolation levels per task.
- Multi-Profile can **independently configure backends for each role** (coder uses local, ops uses docker).
- The trade-off is that there is no automatic collaboration between Multi-Profiles, requiring manual switching by the user.

See also → [[multi-agent-architecture]]

## Related Pages

- [[multi-agent-architecture]] — In-session Multi-Agent (delegate_task / MoA / Background Review)
- [[terminal-backends]] — Terminal Backend Selection (Profile can configure different backends for each role)
- [[memory-system-architecture]] — Memory System (each Profile has independent MEMORY.md / USER.md)
- [[skills-system-architecture]] — Skill System (each Profile has an independent skill set)
- [[credential-pool-and-isolation]] — Credential Isolation
- [[hook-system-architecture]] — Hook System (Gateway Hooks are isolated by Profile)

## Key Source Files

| File                       | Responsibility                                  |
|----------------------------|-------------------------------------------------|
| `hermes_constants.py`      | `get_hermes_home()` — Global path source        |
| `hermes_cli/profiles.py`   | Profile CRUD, export/import, alias management   |
| `hermes_cli/main.py`       | `_apply_profile_override()` — Profile activation at startup |
| `hermes_cli/config.py`     | `load_config()` — Reads Profile-scoped `config.yaml` |
| `hermes_cli/gateway.py`    | Gateway service name suffix, PID isolation      |
| `plugins/memory/honcho/cli.py` | Honcho host block isolation by Profile          |
| `agent/prompt_builder.py`  | SOUL.md loaded by Profile                       |