---
title: Prompt Builder System Prompt Construction Architecture
created: 2026-04-08
updated: 2026-04-08
type: concept
tags: [architecture, module, component, agent, prompt-builder]
sources: [agent/prompt_builder.py]
---

# Prompt Builder — System Prompt Construction Architecture

## Overview

The Prompt Builder, located at `agent/prompt_builder.py` (44KB/959 lines), is responsible for **assembling the system prompt**—agent identity definition, platform hints, skills index, and context files. All its functions are stateless and are invoked by `AIAgent._build_system_prompt()` to concatenate various modules.

Core Principle: **The system prompt is assembled modularly, with each component being independently testable and replaceable.**

## Architectural Principles

### Prompt Component Hierarchy (Verified Structure)

`_build_system_prompt()` concatenates the `prompt_parts` array in a fixed order, finally returning the complete system prompt via `"\n\n".join(prompt_parts)`. The actual structure, verified through API request captures (approx. 36K chars / 10K tokens), is as follows:

```
System Prompt =
  ① Agent Identity — SOUL.md (~/.hermes/SOUL.md; if present, used; otherwise, DEFAULT_AGENT_IDENTITY)
  ② Tool Usage Enforcement Guidance (filtered by model family)
  ③ Model-Specific Execution Guidance (e.g., OpenAI/Google specific, filtered by model family)
  ④ User/Gateway System Message (if a system_message is passed to run_conversation)
  ⑤ Memory Guidance (hardcoded prompt instructing the model on memory tool usage)
  ⑥ MEMORY Snapshot — ~/.hermes/memories/MEMORY.md (frozen, unchanged throughout the conversation)
  ⑦ USER PROFILE Snapshot — ~/.hermes/memories/USER.md (frozen, unchanged throughout the conversation)
  ⑧ External Memory Provider Block (e.g., mem0/honcho/holographic, if enabled)
  ⑨ Skills Index (build_skills_system_prompt, scans ~/.hermes/skills/)
  ⑩ Project Context Files (.hermes.md → AGENTS.md → CLAUDE.md → .cursorrules, first match wins)
  ⑪ Conversation Metadata (timestamp, Model, Provider, Session ID)
  ⑫ Platform Hints (PLATFORM_HINTS, e.g., Telegram/Discord/CLI)
  ⑬ Conversation Context (Gateway injection: source, Home Channel, delivery options)
```

**Key Points**:
- **SOUL.md is loaded independently** and does not participate in the "project context files" first-match-wins competition.
- **Memory snapshots use a frozen mode**—the system prompt is constructed only once per session and cached (`self._cached_system_prompt`), being rebuilt only after context compression to protect the prefix cache.
- **The entire system prompt is a single message** (`role: "system"`), not a concatenation of multiple messages.

### Context File Injection Protection

```python
_CONTEXT_THREAT_PATTERNS = [
    (r'ignore\s+(previous|all|above|prior)\s+instructions', "prompt_injection"),
    (r'do\s+not\s+tell\s+the\s+user', "deception_hide"),
    (r'system\s+prompt\s+override', "sys_prompt_override"),
    (r'disregard\s+(your|all|any)\s+(instructions|rules|guidelines)', "disregard_rules"),
    (r'bypass_restrictions', ...),
    (r'curl\s+.*\${?\w*(KEY|TOKEN|SECRET)', "exfil_curl"),
    (r'cat\s+[^\\n]*(\\.env|credentials)', "read_secrets"),
]

_CONTEXT_INVISIBLE_CHARS = {
    '\u200b', '\u200c', '\u200d', '\u2060', '\ufeff',  # Zero-width characters
    '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',  # Bidirectional text control characters
}
```

**Dual Protection**:
1.  **Threat Pattern Detection**: 10 common injection patterns (e.g., ignoring instructions, hiding behavior, prompt injection, key exfiltration).
2.  **Invisible Unicode Detection**: 10 zero-width and bidirectional text control characters (5 zero-width + 5 bidirectional control) which might be used for visual deception.

When a threat is detected: the content is replaced with `[BLOCKED: filename contained potential prompt injection]`.

## Core Components

### 1. Context File Discovery

**Two independent loading paths**:

```python
# Path A: SOUL.md — Agent Identity, fixed path, always loaded
load_soul_md()  → ~/.hermes/SOUL.md  (HERMES_HOME)

# Path B: Project Context Files — Mutually exclusive, first match wins
project_context = (
    _load_hermes_md(cwd_path)    # .hermes.md / HERMES.md (traverses upwards to git root)
    or _load_agents_md(cwd_path) # AGENTS.md (cwd only)
    or _load_claude_md(cwd_path) # CLAUDE.md (cwd only)
    or _load_cursorrules(cwd_path) # .cursorrules / .cursor/rules/*.mdc (cwd only)
)
```

| File | Location | Search Scope | Role |
|------|------|---------|------|
| **SOUL.md** | `~/.hermes/SOUL.md` | HERMES_HOME (globally unique) | Agent Identity/Persona, loaded independently |
| **.hermes.md** | cwd upwards to git root | Recursive search | Project-level configuration, Priority 1 |
| **AGENTS.md** | cwd only | Non-recursive | Codebase development guidelines, Priority 2 |
| **CLAUDE.md** | cwd only | Non-recursive | Anthropic format compatibility, Priority 3 |
| **.cursorrules** | cwd only (including `.cursor/rules/*.mdc`) | Non-recursive | Cursor format compatibility, Priority 4 |

**Common Misconceptions**:
- SOUL.md **does not participate** in the project context's priority competition—it is a separate identity slot.
- Project context files are loaded **mutually exclusively** (first match wins), not "all loaded."
- If the current working directory contains both `.hermes.md` and `CLAUDE.md`, only `.hermes.md` will be loaded.

**Skip Mechanism**:
- `AIAgent(skip_context_files=True)` — Commonly used by sub-agents to avoid inheriting parent agent's project context.
- Launching Hermes in a different directory (e.g., `TERMINAL_CWD=~`) — Naturally skips project files.
- Skipping SOUL.md: `build_context_files_prompt(skip_soul=True)` avoids duplicate injection if SOUL.md has already been loaded as an identity slot.

**Content Protection**:
- Each file content has a limit of 20,000 characters; exceeding this automatically truncates the content (indicated by `[...truncated...]`).
- YAML frontmatter is automatically stripped (structured configuration is handled separately).
- Scans for threat patterns (see next section).

### 2. Skills Indexing and Caching

```python
_SKILLS_PROMPT_CACHE_MAX = 8
_SKILLS_PROMPT_CACHE: OrderedDict[tuple, str] = OrderedDict()

def build_skills_system_prompt(
    available_tools: set,
    available_toolsets: set,
    disabled_skills: set,
) -> str:
    """
    1. Scans the skills directory
    2. Parses the frontmatter of each SKILL.md
    3. Checks platform compatibility + conditional activation rules
    4. Constructs the skill manifest prompt
    5. Caches the result (based on mtime/size manifest)
    """
```

### 3. Skill Snapshot Persistence

```python
def _load_skills_snapshot(skills_dir: Path) -> Optional[dict]:
    """Loads snapshot from disk, reuses if manifest matches"""

def _write_skills_snapshot(skills_dir, manifest, skill_entries, category_descriptions):
    """Atomically writes snapshot (atomic_json_write)"""
```

**Cold Start Optimization**: If skill files are unchanged, the snapshot is loaded directly from disk, eliminating the need to re-parse all SKILL.md files.

### 4. Skill Conditional Activation

```python
def _skill_should_show(conditions, available_tools, available_toolsets):
    """
    fallback_for_toolsets: Hides when primary toolset is available (fallback skill)
    fallback_for_tools: Hides when primary tool is available
    requires_toolsets: Hides when required toolset is not present
    requires_tools: Hides when required tool is not present
    """
```

### 5. Platform Hints

```python
PLATFORM_HINTS = {
    "telegram": "You are on Telegram. No markdown. MEDIA:/path for files...",
    "discord": "You are in Discord. MEDIA:/path for attachments...",
    "cli": "You are a CLI AI. Use simple text renderable in terminal.",
    "cron": "You are running as a cron job. No user present. Execute fully...",
    "whatsapp": "You are on WhatsApp. No markdown...",
    "slack": "You are in Slack...",
    "signal": "You are on Signal...",
    "email": "You are communicating via email. Plain text...",
    "sms": "You are communicating via SMS. ~1600 chars limit...",
}
```

### 6. Model-Specific Execution Guidance

#### OpenAI/GPT Codex Series

```python
OPENAI_MODEL_EXECUTION_GUIDANCE = """
<tool_persistence>
- Use tools whenever they improve correctness
- Do not stop early
- If a tool returns empty, retry with different strategy
- Keep calling tools until task is complete AND verified
</tool_persistence>

<prerequisite_checks>
- Check prerequisite discovery before action
- Don't skip steps just because final action seems obvious
</prerequisite_checks>

<verification>
- Correctness: does output satisfy every requirement?
- Grounding: are claims backed by tool outputs?
- Formatting: does output match requested schema?
- Safety: confirm scope before side-effect operations
</verification>

<missing_context>
- Do NOT guess or hallucinate
- Use lookup tools for missing information
- Label assumptions explicitly
</missing_context>
"""
```

#### Gemini/Gemma Series

```python
GOOGLE_MODEL_OPERATIONAL_GUIDANCE = """
- Absolute paths: always use absolute file paths
- Verify first: check file contents before changes
- Dependency checks: check package.json before importing
- Conciseness: keep text brief, focus on actions
- Parallel tool calls: batch independent operations
- Non-interactive: use -y, --yes flags
- Keep going: execute fully, don't stop with a plan
"""
```

### 7. Developer Role Switching

```python
DEVELOPER_ROLE_MODELS = ("gpt-5", "codex")
# New OpenAI models give higher weight to instructions within the 'developer' role.
# This role is automatically switched at the API boundary, while internally the representation remains consistent as "system".
```

## Design Advantages

### Modularity Benefits

| Dimension | Monolithic Prompt | Modular Prompt Builder |
|---|---|---|
| Testing | Difficult to unit test | Each component is independently testable |
| Customization | Requires full replacement | Dynamically assembled by platform/model/skill |
| Security | Injection difficult to detect | Context files scanned independently |
| Maintenance | Changes in one place affect everything | Each component evolves independently |
| Caching | Cannot cache | Skills index can be cached |

### Superior Security Protection

Traditional context file injection lacks protection. The Prompt Builder ensures that injected content does not alter agent behavior through **multi-layered detection**:
1.  Threat pattern regular expression matching
2.  Invisible Unicode character detection
3.  When a threat is detected, it's replaced with a BLOCKED marker rather than discarded (informing the agent there was an issue).

## Configuration and Operations

### Customizing Agent Identity

Create `~/hermes-agent/SOUL.md` to define a personalized identity.

### Project-level Configuration

Create a `.hermes.md` in the project root; its content will be injected into the system prompt.

### Disabling Specific Skills

```yaml
# config.yaml
skills:
  disabled: ["some-skill", "another-skill"]
```

## Relationship to Other Systems

- [[tool-registry-architecture]] — Skill conditional activation depends on available toolsets
- [[context-compressor-architecture]] — Compressed message list is passed to the prompt builder to reconstruct the prompt
- [[memory-system-architecture]] — Memory guidance is part of the prompt
- [[agent-loop-and-prompt-assembly]] — The prompt builder is called by the agent loop