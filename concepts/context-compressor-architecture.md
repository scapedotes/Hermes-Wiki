---
title: Context Compressor: Context Compression Architecture
created: 2026-04-08
updated: 2026-04-17
type: concept
tags: [architecture, module, component, agent, context-compression]
sources: [agent/context_engine.py, agent/context_compressor.py, run_agent.py, hermes_state.py, plugins/context_engine/__init__.py]
---

# Context Compressor — Context Compression Architecture

## Overview

The Context Compressor, located at `agent/context_compressor.py`, is an **automatic context window compression** class. When a conversation approaches the model's context limit, it uses an auxiliary LLM (a cheaper/faster model) to generate structured summaries of intermediate turns, while protecting the head and tail context.

### Context Engine Pluginization (2026-04-10)

Previously, context management had only one approach—`ContextCompressor` (summary compression). Changing strategies required modifying the source code. Now, `ContextEngine` ABC has been extracted, making `ContextCompressor` one of its implementations. Third parties can write plugins to replace it without altering Hermes' source code.

**Essence: The decision of "what to do when context is full" has evolved from hardcoding to pluggable.**

```yaml
# config.yaml — One line to switch
context:
  engine: "compressor"   # Default summary compression; set to plugin name to switch (e.g., "lcm")
```

**Examples of Possible Alternative Engines:**

| Engine | Strategy | Applicable Scenario |
|------|------|---------|
| compressor (built-in) | LLM summary compression | General, default |
| lcm (hypothetical) | Stores old conversations in vector DB, semantic retrieval on demand | Very long sessions, precise recall needed |
| sliding-window (hypothetical) | Simple sliding window truncation, no summarization | Low cost, no auxiliary model needed |

**`ContextEngine` ABC requires the implementation of 3 core methods**:
- `name` — Engine identifier (property)
- `should_compress(prompt_tokens)` — Whether compression is needed
- `compress(messages, current_tokens)` — Executes compression, returns new message list

**Optional methods**: `on_session_start/end`, `get_tool_schemas` (engine can expose tools to the agent, e.g., `lcm_grep`), `handle_tool_call`, `update_model`.

**Plugin directory**: `plugins/context_engine/<name>/`, containing `plugin.yaml` + `__init__.py` (implements `register(ctx)` or exposes a `ContextEngine` subclass).

**Only one engine is allowed to be active**, similar to MemoryProvider's "at most one external" constraint.

Core Philosophy: **Long conversations do not require discarding context—old turns are replaced with structured summaries, preserving key information.**

## Architectural Principles

### Compression Algorithm

```text
Algorithm Flow (v3):
  Phase 1: Cheap preprocessing (purely local, no LLM calls, zero token cost)
    ├── Pass 1: MD5 Deduplication — If the same file is read 5 times, only the latest instance is kept
    ├── Pass 2: Smart Collapse — Old tool outputs replaced with informative single-line summaries
    └── Pass 3: tool_call argument truncation — >500 characters truncated to 200
  Phase 2: Boundary determination
    Protect head (system prompt + first turn) + protect tail by token budget
  Phase 3: LLM structured summarization (only processes the middle section after Phase 1 slimming)
  Phase 4: Assembly + cleanup of orphaned tool_call/tool_result pairs
```

#### v2 vs v3 Execution Comparison

**The old version (v2) had only one step**: tokens reach threshold → intermediate dialogue given directly to LLM for summarization → replacement. The problem was that tool outputs could be several KBs (e.g., `npm test` 200 lines, `read_file` reads entire file), feeding all of it to the LLM for summarization was **token-intensive** itself; if the same file was read 5 times, all 5 full contents were present; when compression was inefficient, it would repeatedly trigger, making redundant LLM calls.

**The new version (v3) has three phases**: Phase 1 consists of zero-cost local operations (string hashing, regex replacement, truncation), often cutting 30-50% of tokens. Phase 3's LLM call therefore processes significantly less data. Coupled with an anti-thrashing mechanism (stops after 2 consecutive inefficient compressions), the overall number of LLM calls and the input quantity per call are significantly reduced.

### Evolution History

| Improvement | v1 | v2 | v3 (2026-04-14+) |
|---|---|---|---|
| Summary Template | Unstructured | Goal/Progress/Decisions/Files/Next Steps | **Numbered Completed Actions + Active State** (action-log style) |
| Summary Update | Regenerated from scratch each time | Iterative update | Iterative update (continues numbering) |
| Tail Protection | Fixed number of messages | Token budget (scaled proportionally) | Same as v2 |
| Tool Output Pruning | None | Generic placeholder `_PRUNED_TOOL_PLACEHOLDER` | **Smart Collapse**: Generates informative single-line summaries per tool type |
| Deduplication | None | None | **MD5 Deduplication**: Only the latest instance of identical tool results is kept |
| `tool_call` Arguments | Retained as-is | Retained as-is | **>500 characters automatically truncated to 200 characters** |
| Summary Budget | Fixed | Scaled proportionally to compressed content | Same as v2, but `max_tokens` reduced from 2× to **1.3×** (anti-inflation) |
| Anti-Thrashing | None | None | **Skip if 2 consecutive compressions save <10%**, avoids thrashing loops |
| Multimodal Messages | Potential crash | Potential crash | Skips list content in dedup/prune paths |
| Compression Note Idempotency | Appended only on first compression | Same as v1 | **Detects existing notes** and does not append duplicates |
| Failure Cooldown | Fixed 10 minutes | Fixed 10 minutes | **No provider 10 minutes, transient error 60 seconds** |
| Tool Call Integrity | Potential loss | `_sanitize_tool_pairs` fixes orphaned pairs | Same as v2 |

## Core Components

### 1. Token Budget Management

```python
class ContextCompressor:
    def __init__(self, model, threshold_percent=0.50):
        self.context_length = get_model_context_length(model)
        self.threshold_tokens = int(self.context_length * 0.50)  # Trigger at 50% usage
        self.tail_token_budget = int(self.threshold_tokens * 0.20)  # Tail budget
        self.max_summary_tokens = min(int(self.context_length * 0.05), 12_000)  # Summary ceiling
```

**Scaling Design**: Both tail budget and summary ceiling are proportional to the model's context window, allowing larger context models to receive richer summaries.

### 2. Tool Output Pruning (Three-Phase Preprocessing)

`_prune_old_tool_results()` now performs three tasks, all without LLM calls:

**Pass 1 — MD5 Deduplication**: Identical tool results (>200 chars, non-multimodal) are deduplicated by MD5 hash, keeping only the latest instance. Old duplicates are replaced with:
```
[Duplicate tool output — same content as a more recent call]
```
Typical scenarios: repeatedly reading the same file, or repeatedly searching for the same pattern.

**Pass 2 — Smart Collapse** (2026-04-14): By looking up the tool name + arguments using `tool_call_id`, it generates an **informative 1-line summary** to replace the generic placeholder. Different tools have different templates:

```text
[terminal] ran `npm test` -> exit 0, 47 lines output
[read_file] read config.py from line 1 (1,200 chars)
[search_files] content search for 'compress' in agent/ -> 12 matches
[patch] replace in config.py (1,500 chars result)
[web_search] query='cache control' (5,200 chars result)
[delegate_task] 'refactor auth module' (8,400 chars result)
[memory] save on long-term
```

Compared to the old `_PRUNED_TOOL_PLACEHOLDER`, the summaries retain **specific commands / file paths / result scale**, allowing the model to understand "what was done before" when reviewing history. Built-in templates cover terminal / read_file / write_file / search_files / patch / browser_* / web_search / web_extract / delegate_task / execute_code / skill_* / vision_analyze / memory / todo / clarify / text_to_speech / cronjob / process, with other tools falling back to a generic template.

**Pass 3 — `tool_call` Argument Truncation**: If an assistant message has `tool_calls.function.arguments` longer than 500 characters, it's truncated to the first 200 characters + `...[truncated]`. This fixes scenarios like `write_file(content=50KB)` where even if the tool result is pruned, the arguments themselves still consume significant context.

**Multimodal Protection**: All three Passes detect `isinstance(content, list)` to skip multimodal messages, avoiding corruption of image/audio content.

### 3. Summary Budget Calculation

```python
def _compute_summary_budget(turns_to_summarize):
    content_tokens = estimate_messages_tokens_rough(turns_to_summarize)
    budget = int(content_tokens * 0.20)  # Compress to 20%
    return max(2000, min(budget, self.max_summary_tokens))
```

**Design**: The summary budget is proportional to the content to be compressed, but controlled by upper and lower limits.

### 4. Serialization for Summary Text

```python
def _serialize_for_summary(turns):
    """
    Serializes conversation turns into tagged text:
    [TOOL RESULT xxx]: content (truncated to 3000 chars: first 2000 + ... + last 800)
    [ASSISTANT]: content + [Tool calls: tool_name(args), ...]
    [USER]: content (truncated to 3000 chars)
    """
```

**Key**: Includes tool call names and arguments, enabling the summarizer to retain specific file paths, commands, and outputs.

### 5. Structured Summary Generation

#### First Compression (v3 action-log template, 2026-04-14)

```text
## Goal
[What the user is trying to accomplish]

## Constraints & Preferences
[User preferences, coding style, constraints, important decisions]

## Completed Actions
[Numbered list of actions, each formatted as: N. ACTION target — outcome [tool: name]
Example:
1. READ config.py:45 — found `==` should be `!=` [tool: read_file]
2. PATCH config.py:45 — changed `==` to `!=` [tool: patch]
3. TEST `pytest tests/` — 3/50 failed: test_parse, test_validate, test_edge [tool: terminal]
Be CONCRETE: file paths, commands, line numbers, and results MUST be retained]

## Active State
[Current working state:
- Working directory and branch
- Modified/created files and brief descriptions
- Test status (X/Y passing)
- Running processes or servers
- Key environment information]

## In Progress
[Work that was ongoing when compression was triggered]

## Blocked
[Unresolved blockers/errors, including full error messages]

## Key Decisions
[Important technical decisions and their WHY]

## Resolved Questions
[Questions the user asked that were ALREADY answered — include the answer, to prevent subsequent agents from re-answering]

## Pending User Asks
[Questions the user asked that have NOT yet been answered]

## Relevant Files
[Files read/modified/created]

## Critical Context
[Specific values, error messages, configuration details, etc. that MUST NOT be lost]
```

#### v2 Summary Template (Old Version, for comparison)

```text
## Goal
[What the user is trying to accomplish]

## Constraints & Preferences
[User preferences, coding style, constraints, important decisions]

## Progress
### Done
[Completed work — include specific file paths, commands run, results obtained]
### In Progress
[Work currently underway]
### Blocked
[Any blockers or issues encountered]

## Key Decisions
[Important technical decisions and why they were made]

## Resolved Questions
[Questions the user asked that were ALREADY answered — include the answer]

## Pending User Asks
[Questions or requests from the user that have NOT yet been answered]

## Relevant Files
[Files read, modified, or created — with brief note on each]

## Remaining Work
[What remains to be done — framed as context, not instructions]

## Critical Context
[Any specific values, error messages, configuration details]

## Tools & Patterns
[Which tools were used, how they were used effectively, and any tool-specific discoveries]
```

#### v2 → v3 Prompt Differences Item by Item

| Section | v2 | v3 | Reason for Change |
|------|----|----|----------|
| Completed Actions | `## Progress > ### Done` free text | `## Completed Actions` mandatory numbering + fixed format `N. ACTION target — outcome [tool: name]` | Free text often produced vague descriptions ("modified some files"). Numbered format forces LLM to provide specific paths, commands, line numbers. |
| Format Examples | None | Provided 3 examples (READ/PATCH/TEST) | Few-shot prompting guides LLM to adhere to the format. |
| Current State | No dedicated section, information scattered in Progress | Added `## Active State` (working directory, branch, modified files, test status, running processes) | The most crucial information for continuing an agent's work is "where am I now, what's the state?". The old version had no clear place for this. |
| Tool Patterns | `## Tools & Patterns` as a separate section | **Removed**. Tool information integrated into `[tool: name]` in Completed Actions. | Tools are inherently tied to actions; a separate section was redundant and wasted tokens. |
| Specificity Requirement | "Be specific — include file paths, command outputs, error messages, and concrete values" | "Be CONCRETE — include file paths, command outputs, error messages, **line numbers**, and specific values. **Avoid vague descriptions like 'made some changes' — say exactly what changed.**" | Explicitly prohibits vague descriptions, added line numbers requirement. |
| Iterative Update | "ADD new progress. Move from 'In Progress' to 'Done'" | "ADD new completed actions to numbered list **(continue numbering)**. Update 'Active State' to reflect current state. **Remove information only if it is clearly obsolete.**" | "Continue numbering" prevents information loss due to numbering reset on each compression. "Only if clearly obsolete" prevents excessive deletion. |
| Summary Budget | `max_tokens = budget × 2` | `max_tokens = budget × 1.3` | 2× was too lenient, leading to summary inflation. 1.3× is more concise. |

**Core Design Idea**: v2's template gave the LLM too much freedom, leading to inconsistent output quality; v3, through mandatory numbering, specific examples, and explicit prohibitions, transformed "how to write a summary" from an open-ended task into a fill-in-the-blank one, making compression output more predictable and information-dense.

#### Preamble (Role Setting) — Consistent across both versions

```text
You are a summarization agent creating a context checkpoint.
Your output will be injected as reference material for a DIFFERENT
assistant that continues the conversation.
Do NOT respond to any questions or requests in the conversation —
only output the structured summary.
Do NOT include any preamble, greeting, or prefix.
```

Inspired by OpenCode's "do not respond to any questions" + Codex's "another language model" framework. Unchanged in both versions.

#### Iterative Update

When an old summary already exists, the prompt becomes:

```text
PREVIOUS SUMMARY: [Old Summary]
NEW TURNS TO INCORPORATE: [New Turns]

Update the summary, retaining all useful old information.
ADD new completed actions to the numbered list (continue numbering).
Move "In Progress" to "Completed Actions" (when completed).
Move answered questions to "Resolved Questions".
Update "Active State" to reflect the current state.
Remove information only if it is clearly obsolete.
```

### 6. Adaptive Failure Cooldown Mechanism

```python
_SUMMARY_FAILURE_COOLDOWN_SECONDS = 600   # 10 minutes, for no provider
_TRANSIENT_COOLDOWN_SECONDS      = 60    # 1 minute, for transient errors

def _generate_summary(self, turns):
    if time.monotonic() < self._summary_failure_cooldown_until:
        return None  # Skip during cooldown

    try:
        response = call_llm(task="compression", ...)
        self._summary_failure_cooldown_until = 0.0  # Reset on success
    except RuntimeError:
        # No provider configured — won't recover by itself for 10 minutes
        self._summary_failure_cooldown_until = time.monotonic() + 600
    except Exception:
        # Transient error (timeout/rate limit/network) — short cooldown for quick retry
        self._summary_failure_cooldown_until = time.monotonic() + 60
```

**Design Considerations** (2026-04-14 Improvement): Distinguishes between two types of failures. `RuntimeError` indicates a configuration issue, triggering a 10-minute long cooldown. Other exceptions are assumed to be transient, triggering a 60-second short cooldown, allowing compression to recover faster from temporary glitches.

### 6b. Anti-Thrashing Protection (2026-04-14)

```python
def should_compress(self, prompt_tokens=None) -> bool:
    if tokens < self.threshold_tokens:
        return False
    # Skip if last 2 compressions saved <10% each
    if self._ineffective_compression_count >= 2:
        logger.warning(
            "Compression skipped — last %d compressions saved <10%% each. "
            "Consider /new to start a fresh session, or /compress <topic> ..."
        )
        return False
    return True
```

After each compression, the actual percentage saved is calculated based on `saved_estimate / display_tokens`:
- `>= 10%` → Reset `_ineffective_compression_count = 0`
- `< 10%`  → `_ineffective_compression_count += 1`

**Problem Solved**: In some scenarios (when the tail + head + summary itself are already large), compression might only squeeze out 1-2 messages, triggering every turn but yielding almost no benefit, creating a compression thrashing loop. If two consecutive compressions are ineffective, it gives up and prompts the user to `/new` or `/compress <topic>` for manual intervention.

### 7. Tool Call Pair Integrity Guarantee

```python
def _sanitize_tool_pairs(messages):
    """
    Fixes orphaned tool_call / tool_result pairs after compression:
    
    Failure Mode 1: The assistant's tool_call referenced by a tool result's call_id is removed
    → API error "No tool call found for function call output..."
    → Solution: Delete the orphaned result
    
    Failure Mode 2: The assistant has tool_calls but their corresponding results are discarded
    → API error "every tool_call must be followed by a tool result..."
    → Solution: Insert a stub result "[Result from earlier conversation]"
    """
```

**Importance**: Failure to fix this would lead to the API rejecting the entire message list, causing compression to fail.

### 8. Boundary Alignment

```python
def _align_boundary_forward(messages, idx):
    """If the boundary falls on a tool result, push it forward to a non-tool message"""

def _align_boundary_backward(messages, idx):
    """If the boundary falls in the middle of a tool call/result group, pull it back to fully include the group"""
```

**Preventing Data Loss**: Avoid splitting assistant + tool_results groups; otherwise, `_sanitize_tool_pairs` would remove orphaned tail results, leading to silent data loss.

**v0.10.0 Fix**: Added `_ensure_last_user_message_in_tail()` method, called at the end of `_find_tail_cut_by_tokens`, to ensure that the **last user message always remains in the tail**. Previously, in some scenarios, compression would push the user's active task instruction into the summary area, causing the agent to lose its current task context, stall, or repeat already completed work (#10896).

### 9. Tail Token Budget Protection

```python
def _find_tail_cut_by_tokens(messages, head_end, token_budget):
    # Hard minimum: at least protect 3 tail messages
    min_tail = min(3, n - head_end - 1)
    
    # Soft ceiling: allow 1.5x budget overage, to avoid cutting in middle of very large message
    soft_ceiling = int(token_budget * 1.5)
    
    # Accumulate backwards from the end, until soft_ceiling is exceeded AND min_tail is met
    # If budget is insufficient to cover min_tail → Fallback to n - min_tail (force protect 3 messages)
    # If budget covers all → Force cut after head, ensuring compression still executes
```

Key change (2026-04-09): Switched from fixed number of messages to **token budget + hard minimum `min_tail=3`**, which is more reasonable for both long and short messages.

### 10. Summary Role Selection

```python
# When inserting summary message, choose appropriate role to avoid consecutive same roles
if last_head_role in ("assistant", "tool"):
    summary_role = "user"
else:
    summary_role = "assistant"

# If the chosen role conflicts with the tail, attempt to flip
# If both roles cause conflict → Merge into the first tail message
```

## Context Management Overview

### Infinite Turn Conversations

Hermes **does not limit the number of conversation turns**. There is no `max_history` or fixed turn truncation. The entire conversation history is retained in memory, with the compressor continuously compressing it:

```text
Conversation starts → Messages accumulate → 50% context window reached → Automatic compression
                                                                        │
                                                                  Pruning + Summarization + Reassembly
                                                                        │
                                                             Continue accumulation → 50% reached again → Compress again → ...
```

Theoretically, conversations can be infinite. Each compression generates an iteratively updated summary, not a complete re-summarization from scratch.

### Session Splitting

During compression, the **session is split** to preserve complete original messages for future retrieval via `session_search`.

```text
Before compression:
  session "abc" (DB already has msg 0-49 complete original messages)
  In-memory msg 2-40 are about to be compressed into a summary

After compression:
  session "abc" (ended, reason="compression")
    → DB retains complete msg 0-49 ← session_search can find original content

  session "abc-2" (newly created, parent_session_id="abc")
    → Summary + tail messages + subsequent new messages
    → _last_flushed_db_idx reset to 0

Multiple compressions form a chain:
  abc → abc-2 → abc-3 → ...
  Each segment is complete, maintaining lineage through parent_session_id
```

**Why not in-place replacement?** If compressed messages were overwritten back into the same session, the DB would have original messages in the first half and summaries in the second, leading to inconsistent data for `session_search`. Splitting ensures each session segment contains consistent, complete content.

### Message Persistence Mechanism

Messages are **not written to the DB in real-time per message**, but rather flushed in batches at exit points:

```python
def _flush_messages_to_session_db(self, messages, conversation_history):
    # Incremental write: starting from the last watermark, only write new messages
    flush_from = max(start_idx, self._last_flushed_db_idx)
    for msg in messages[flush_from:]:
        db.append_message(session_id, role, content, ...)
    self._last_flushed_db_idx = len(messages)  # Update watermark
```

**Trigger Timings** (20 call points in code, covering all exit paths):

| Scenario | Guarantee |
|------|------|
| Conversation completes normally | ✅ Written |
| API error max retry exhausted | ✅ Written before abandoning |
| User interruption (Ctrl+C) | ✅ Written before interruption |
| Interrupted during rate limit wait | ✅ Written |
| 413/context overflow compression failure | ✅ Written |
| Tool execution exception | ✅ Written |
| All fallback providers fail | ✅ Written |

**Watermark Anti-Duplication**: `_last_flushed_db_idx` records the last written position. Even if multiple exit paths repeatedly call `_persist_session()`, the same message will not be written twice (fixed issue #860).

```text
First flush:  messages[0:15] → DB,  watermark = 15
Second flush: messages[15:23] → DB, watermark = 23
Third flush:  messages[23:23] → Skipped (no new messages)
```

## Design Superiority

### Comparison to Discarding Old Messages

| Aspect | Discarding Old Messages | Context Compressor |
|---|---|---|
| Information Retention | Completely lost | Structured summary retains key information |
| Continuity | Agent forgets completed work | Knows progress and decisions |
| File Tracking | Lost | Lists relevant files |
| Iterative Updates | Not applicable | Summary can be iteratively updated |
| User Experience | Agent repeats work | Agent continues from summary |

### Cost-Effectiveness

Compression uses an **auxiliary LLM** (cheaper model, e.g., Gemini 3 Flash), not the main dialogue model. Typical scenario:
- Auxiliary model cost: $0.01-0.05/compression
- Avoided cost of repetitive work: Far exceeds compression cost
- Context saving: 30-70%

## Configuration and Operation

### Configuration Parameters

```yaml
# config.yaml
compression:
  summary_provider: auto      # Or openrouter, nous, custom
  summary_model: ""           # Empty = auto-select
  threshold_percent: 0.50     # Trigger at 50% context usage
```

### Environment Variables

```bash
# Set specific model for compression tasks
export AUXILIARY_COMPRESSION_MODEL=claude-haiku-4-5
export CONTEXT_COMPRESSION_PROVIDER=openrouter
```

### Runtime Status

```python
compressor.get_status()
# Returns: {
#   "last_prompt_tokens": 45000,
#   "threshold_tokens": 65536,
#   "context_length": 131072,
#   "usage_percent": 34,
#   "compression_count": 2
# }
```

## Comparison with OpenClaw (Claude Code) Compression Mechanism

OpenClaw's compression implementation, located at `src/agents/compaction.ts`, adopts a **chunk-based summarization** strategy, contrasting sharply with Hermes' **three-phase preprocessing + single-pass summarization**.

### Overall Architectural Differences

| Aspect | Hermes v3 | OpenClaw |
|------|-----------|----------|
| Overall Strategy | Local preprocessing → Boundary partitioning → Single LLM summary | Chunking + Multiple LLM summaries (two paths, see below) |
| LLM Call Count | **1 call** (only on the slimmed intermediate section) | **Multiple calls** (N times in rolling, or N+1 times in parallel) |
| Preprocessing | MD5 deduplication + Smart Collapse + Argument truncation (zero token cost) | `stripToolResultDetails()` removes tool details (lightweight) |
| Chunking | No chunking, three sections: head-middle-tail | Two chunking strategies (see below) |

OpenClaw actually has two compression paths (`src/agents/compaction.ts`):

- **`summarizeChunks` (Rolling)**: Chunks by token limit, processes serially—chunk1's summary is passed as `previousSummary` to chunk2, progressively rolling. N LLM calls.
- **`summarizeInStages` (Parallel + Merge)**: `splitMessagesByTokenShare()` splits into N chunks (default `DEFAULT_PARTS=2`), each summarized independently, then merged using `MERGE_SUMMARIES_INSTRUCTIONS`. N+1 LLM calls.

### Summary Template Comparison

**Hermes v3 (11 Sections):**

```
Goal / Constraints & Preferences / Completed Actions (numbered+formatted) /
Active State / In Progress / Blocked / Key Decisions /
Resolved Questions / Pending User Asks / Relevant Files /
Remaining Work / Critical Context
```

**OpenClaw (5 Sections):**

```
Decisions / Open TODOs / Constraints/Rules /
Pending user asks / Exact identifiers
```

Hermes' template is more detailed (Active State, Relevant Files, numbered Completed Actions), while OpenClaw's is more concise but includes an `Exact identifiers` section explicitly requiring retention of literal values like IDs/URLs/hashes/ports.

### Item-by-Item Comparison

| Aspect | Hermes v3 | OpenClaw |
|------|-----------|----------|
| Action Record | `Completed Actions` numbered list `N. ACTION target — outcome [tool: name]` | No dedicated section, integrated into Decisions |
| Runtime State | `Active State` (branch, test status, running processes) | None |
| Exact Value Retention | `Critical Context` section | `Exact identifiers` section (IDs/URLs/hashes/ports) |
| Unanswered Question Tracking | `Pending User Asks` + `Resolved Questions` (distinguishes answered/unanswered) | `Pending user asks` (only tracks unanswered) |
| File Tracking | `Relevant Files` as a dedicated section | None, relies on Exact identifiers for paths |
| Quality Validation | None (trusts LLM output) | `auditSummaryQuality()` checks 5 sections; retries if failed, falls back to a skeleton |
| Iterative Update | "continue numbering" to append to old summary numbers | `previousSummary` passed to next chunk |
| Summary Limit | 20% of compressed content, max 12K tokens | Hard limit of 16,000 characters |
| Anti-Thrashing | Skip if 2 consecutive compressions save <10% | 6 types of skip reasons (`already_compacted_recently` etc.) |
| Failure Handling | RuntimeError 600s / Transient 60s cooldown | 15-minute safety timeout + 3 retries + structured fallback |
| Tool Pair Repair | `_sanitize_tool_pairs()` supplements orphaned pairs | `repairToolUseResultPairing()` deletes orphaned pairs |
| Tail Protection | Dynamic token budget + hard minimum 3 messages | `DEFAULT_RECENT_TURNS_PRESERVE=3` (max 12) |
| Multilingual | No special handling | "Write summary in the primary language" |

### Respective Strengths

**Hermes Advantages:**
- Local preprocessing (MD5 deduplication + Smart Collapse) cuts 30-50% tokens before the LLM, a layer OpenClaw lacks.
- Single LLM call, regardless of conversation length (only 1 call).
- More detailed template (11 sections vs 5 sections), providing richer context for continuing agents.

**OpenClaw Advantages:**
- Closed-loop quality validation (audit → retry → skeleton fallback), which Hermes does not have.
- Chunking strategy inherently adapts to very long conversations (single LLM input window is limited, chunking avoids overflow).
- `Exact identifiers` section explicitly retains key literal values.
- More granular classification of skip reasons (6 reasons) aids debugging.

## Interaction with Prompt Caching

Anthropic's prompt caching is most effective with system prompt prefixes. The compression strategy coordinates with caching:

1.  **Keep system prompt unchanged** — Maximizes cache hits
2.  **Only compress dialogue history** — The message part is variable
3.  **Use the same system prompt structure** — Stable cache key

## Trigger in Agent Loop

```python
while api_call_count < max_iterations and iteration_budget.remaining > 0:
    # Check token budget
    if token_usage > threshold:
        compressed = compressor.compress(messages, current_tokens=token_usage)
        messages = [system_prompt] + [compressed] + recent_messages
```

## Relationship with Other Systems

- [[auxiliary-client-architecture]] — Compression calls via `call_llm(task="compression")`
- [[smart-model-routing]] — Uses `get_model_context_length()` to obtain context window
- [[prompt-builder-architecture]] — Compressed messages passed to prompt builder to reconstruct the prompt
- [[prompt-caching-optimization]] — Compression strategy coordinates with prompt caching
- [[large-tool-result-handling]] — Tool output pruning shares common principles with large result handling
- [[session-search-and-sessiondb]] — Original messages retained in DB for retrieval after session splitting
- [[memory-system-architecture]] — `flush_memories` and `on_pre_compress` notifications before compression