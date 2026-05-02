---
title: Skills and Memory Interaction
created: 2026-04-07
updated: 2026-04-07
type: concept
tags: [skill, memory, architecture, best-practice]
sources: [Hermes Agent Source Code Analysis 2026-04-07]
---

# Skills and Memory Interaction

## Design Philosophy

Skills and Memory are two **distinct types of persistence mechanisms** for the Hermes Agent; they are complementary rather than competitive:

| Dimension         | Memory                                    | Skills                                       |
|-------------------|-------------------------------------------|----------------------------------------------|
| **Stored Content**| Facts, Preferences, Lessons Learned       | Procedural Knowledge, Workflows              |
| **Capacity**      | MEMORY.md: 2200 chars<br>USER.md: 1375 chars | No Hard Limit                                |
| **Format**        | Item List (§ Separated)                   | Markdown Documents + File Structure          |
| **Purpose**       | Quick Retrieval of Stable Facts           | Comprehensive Guides for Complex Tasks       |
| **Loading Method**| Injected into System Prompt               | Progressive Disclosure (Metadata → Full Content) |
| **When to Use**   | User Preferences, Environmental Facts, Tool Characteristics | Complex Workflows with 5+ Tool Calls |

## Decision Tree

```text
After completing a task, ask:

Is this knowledge...
├─ A simple, stable fact? → Save to Memory
│   (e.g., "User prefers Chinese", "Server in /root")
│
└─ A complex, procedural workflow? → Create as a Skill
    (e.g., "Steps to deploy an ML model", "Workflow to debug X problem")
```

## Behavioral Guidance

### Memory Guidance (Injected System Prompt)

```text
You have persistent memory across sessions. Save durable facts using the memory tool:
user preferences, environment details, tool quirks, and stable conventions.
Memory is injected into every turn, so keep it compact and focused on facts
that will still matter later.

Prioritize what reduces future user steering — the most valuable memory is one
that prevents the user from having to correct or remind you again.

Do NOT save task progress, session outcomes, completed-work logs, or temporary
TODO state to memory; use session_search to recall those from past transcripts.
```

### Skills Guidance (Injected System Prompt)

```text
After completing a complex task (5+ tool calls), fixing a tricky error,
or discovering a non-trivial workflow, save the approach as a skill
with skill_manage so you can reuse it next time.

When using a skill and finding it outdated, incomplete, or wrong,
patch it immediately with skill_manage(action='patch') — don't wait to be asked.
Skills that aren't maintained become liabilities.
```

## Skill Self-Improvement Loop

```text
1. Agent performs complex task (5+ tool calls)
   ↓
2. Detects new pattern or workflow
   ↓
3. Creates skill using skill_manage(action='create')
   ↓
4. Next time a similar task is encountered → skills_list discovers the skill
   ↓
5. skill_view loads full instructions
   ↓
6. Discovers issues during execution → skill_manage(action='patch') fixes it
   ↓
7. Skill continuously improves
```

## Role of Session Search

`session_search` is a third persistence mechanism, used for recalling **past conversations**:

```text
When the user references something from a past conversation or you suspect
relevant cross-session context exists, use session_search to recall it before
asking them to repeat themselves.
```

Comparison of the three mechanisms:

| Mechanism         | Content                   | Retrieval Method                                  |
|-------------------|---------------------------|---------------------------------------------------|
| **Memory**        | Stable Facts              | Automatically injected into system prompt each turn |
| **Skills**        | Procedural Knowledge      | On-demand loading (progressive disclosure)        |
| **Session Search**| Past Conversation Records | FTS5 Full-Text Search + LLM Summary               |

## Practical Examples

### Saving to Memory

```python
# User correction
memory(action='add', target='user', content='User prefers to communicate in Chinese')

# Environmental fact
memory(action='add', target='memory', content='Server is Ubuntu 22.04, Python 3.11')

# Tool characteristic
memory(action='add', target='memory', content='patch tool uses fuzzy matching; minor whitespace differences will not break it')
```

### Creating a Skill

```python
# Complex workflow
skill_manage(
    action='create',
    name='deploy-ml-model',
    content='---\nname: deploy-ml-model\n...'
)
```

## Maintenance Priority

```text
Memory > Skills > Session Search
```

- **Memory** is most important — injected every turn, directly influences behavior
- **Skills** are secondary — loaded on demand, but impact complex task quality
- **Session Search** is last — used for recalling context, not core behavior

## Related Pages

- [[skills-system-architecture]] — Skill System Progressive Disclosure Architecture
- [[memory-system-architecture]] — Memory System Frozen Snapshots and Atomic Writes
- [[session-search-and-sessiondb]] — Session Search as a Third Persistence Mechanism

## Related Files

- `agent/prompt_builder.py` — Guidance text definition
- `tools/memory_tool.py` — Memory implementation
- `tools/skills_tool.py` — Skills implementation
- `tools/session_search_tool.py` — Session Search implementation
- `hermes_state.py` — SessionDB (FTS5 search)
