---
title: Hermes Multi-Agent Architecture
created: 2026-04-08
updated: 2026-04-18
type: concept
tags: [architecture, module, agent, delegation, concurrency]
sources: [tools/delegate_tool.py, tools/mixture_of_agents_tool.py, run_agent.py]
---

# Hermes Multi-Agent Architecture

## Overview

Hermes' multi-agent capabilities are categorized into **three runtime mechanisms**, all triggered during the agent's conversation process, without involving external scripts or offline tools:

| Mechanism             | Trigger Method                          | Purpose                                   |
| --------------------- | --------------------------------------- | ----------------------------------------- |
| **Delegate Task**     | LLM tool call (model's autonomous decision) | Parallel subtasks, up to 3 paths          |
| **Mixture of Agents** | LLM tool call (model's autonomous decision) | Collaborative multi-model reasoning       |
| **Background Review** | System counter automatic trigger        | Background experience refinement → Create/Improve skill |

## Trigger Mechanisms

The mechanisms are divided into two categories of trigger methods:

### LLM Autonomous Invocation (Delegate Task / MoA)

Exactly like `web_search` and `read_file` — the model sees the tool description in the system prompt and **autonomously decides** whether to invoke it based on the user's question, without any code logic forcing the trigger.

```text
User Question → LLM Reasoning → Decides to invoke delegate_task / mixture_of_agents
                                      │
                                      ▼
                          run_agent._invoke_tool()
                                      │
                ┌─────────────────────┼──────────────────┐
                ▼                                        ▼
        delegate_task                              registry.dispatch()
        (Special branch, requires                  → mixture_of_agents
         injecting parent_agent reference)
```

LLM's description of the tools (decision basis):

| Tool                  | LLM's Description (Decision Basis)                                                                                       |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `delegate_task`     | *"Spawn subagents to work on tasks in isolated contexts. Only the final summary is returned."*                            |
| `mixture_of_agents` | *"Route a hard problem through multiple frontier LLMs collaboratively. Makes 5 API calls — use sparingly."*               |

`delegate_task` has an explicit branch in `_invoke_tool()` (line 6108) because it requires injecting `parent_agent`. `mixture_of_agents` goes through the general registry dispatch.

### System Automatic Trigger (Background Review)

**The LLM does not participate in the decision**. Two independent counters silently increment in the main loop, automatically triggering **after the user receives the response** when the threshold is reached:

```python
# run_agent.py — Two independent counters

# Memory review: +1 for each LLM turn (line 7008)
self._turns_since_memory += 1
if self._turns_since_memory >= self._memory_nudge_interval:  # Default 10
    _should_review_memory = True
    self._turns_since_memory = 0

# Skill review: +1 for each tool call (line 7242)
self._iters_since_skill += 1
if self._iters_since_skill >= self._skill_nudge_interval:    # Default 10
    _should_review_skills = True
    self._iters_since_skill = 0
```

```text
User Question → Agent Reasoning + Tool Call → Response delivered to user
                                                    │
                                              Check counters (line 9158)
                                                    │
                                              Exceeds threshold? ──No──→ Do nothing
                                                    │
                                                   Yes
                                                    │
                                                    ▼
                                          _spawn_background_review()
                                          (Daemon thread, non-blocking)
                                                    │
                                                    ▼
                                              Silent AIAgent fork
                                              max_iterations=8
                                              stdout → /dev/null
                                                    │
                                              Review conversation history
                                              "Are there any trial-and-error experiences or strategy changes?"
                                                    │
                                        ┌─────────┴─────────┐
                                        ▼                   ▼
                                skill_manage()         memory.add()
                                Create/Improve skill   Extract persistent facts
                                        │                   │
                                        └─────────┬─────────┘
                                                  ▼
                                        callback: "💾 Skill updated"
```

**Key distinction**: The user has already received the response; the review is a silent background operation. Similar to Garbage Collection (GC) — it runs periodically and automatically, unnoticed by the user.

## I. Delegate Task — Sub-Agent Delegation

A core multi-agent capability during agent runtime. The parent agent spawns isolated child agents to execute independent tasks.

### Core Constants

```python
# tools/delegate_tool.py
DELEGATE_BLOCKED_TOOLS = frozenset([
    "delegate_task",   # Prohibit recursive delegation
    "clarify",         # Child agents cannot ask users questions
    "memory",          # Cannot write to shared MEMORY.md
    "send_message",    # Cannot produce cross-platform side effects (send_message is a message delivery tool, not part of multi-agent mechanisms)
    "execute_code",    # Child agents should reason step by step
])

MAX_DEPTH = 2                # Parent(0) → Child(1) → Grandchild rejected(2)
MAX_CONCURRENT_CHILDREN = 3  # Maximum 3 concurrent child agents
DEFAULT_MAX_ITERATIONS = 50  # Default iteration limit for each child agent
DEFAULT_TOOLSETS = ["terminal", "file", "web"]
```

### Orchestrator Role + Configurable Depth (v2026.4.18+)

`delegate_task` now includes a `role` parameter, supporting `leaf` (default) and `orchestrator`:

```yaml
# config.yaml
delegation:
  max_concurrent_children: 3   # Max concurrent children (default), can be configured
  max_spawn_depth: 1           # 1=Flat (default), 2-3 unlocks nested delegation
  orchestrator_enabled: true   # Global switch
```

- **leaf**: As before, child agents cannot delegate further.
- **orchestrator**: Child agents retain the `delegation` toolset and can continue to spawn their own workers.

**Default flat posture**: When `max_spawn_depth=1`, the orchestrator role silently downgrades to leaf. Nested delegation is only unlocked when the user explicitly sets `max_spawn_depth` to 2 or 3.

A new `DelegateEvent` enum (with legacy string for backward compatibility) is added for gateway/ACP/CLI progress consumers.

### Cross-Agent File State Coordination (v2026.4.18+)

When multiple concurrent child agents modify files simultaneously, the parent agent can now see a consistent file state:
- Files written by a child agent are visible to other child agents.
- The parent agent can see all file operations of all child agents when receiving the summary.
- Prevents lost concurrent patches.

### Function Signature

```python
def delegate_task(
    goal: Optional[str] = None,          # Single-task mode
    context: Optional[str] = None,       # Background information
    toolsets: Optional[List[str]] = None,# Available toolsets
    tasks: Optional[List[Dict]] = None,  # Batch mode (up to 3 tasks)
    max_iterations: Optional[int] = None,
    acp_command: Optional[str] = None,   # ACP subprocess command
    acp_args: Optional[List[str]] = None,
    parent_agent=None,                   # Automatically injected by the framework
) -> str:  # Returns JSON
```

Two modes:
- **Single-task**: Pass `goal`, execute directly (no thread pool overhead).
- **Batch**: Pass `tasks` array, `ThreadPoolExecutor(max_workers=3)` in parallel.

### Isolation Model

```text
Inherited from Parent Agent           Child Agent Exclusive (Fully Isolated)
─────────────────────────             ─────────────────────────────────────
✓ Model / Provider / API Key          ✗ Conversation history (starts blank)
✓ Working directory (cwd)             ✗ Terminal session (independent)
✓ Credential Pool (same provider)     ✗ Intermediate tool calls (invisible to parent)
✓ Platform / session_db reference     ✗ Reasoning process (invisible to parent)
✓ Max tokens / reasoning config       ✗ Context files (skip_context_files=True)
                                      ✗ Memory (skip_memory=True)
```

### Child Agent Building Process (`_build_child_agent`)

```python
def _build_child_agent(
    task_index: int,              # Index in batch
    goal: str,                    # Delegation goal
    context: Optional[str],       # Context
    toolsets: Optional[List[str]],# Toolsets (intersection with parent's, minus blacklist)
    model: Optional[str],         # Can override parent model
    max_iterations: int,          # Independent iteration limit
    parent_agent,                 # Parent Agent reference
    override_provider=None, override_base_url=None,
    override_api_key=None, override_api_mode=None,
    override_acp_command=None, override_acp_args=None,
):
```

**Toolset calculation rule**: A child agent can never obtain more tools than its parent.

```text
Child Agent Tools = (User Specified ∩ Parent Available) - DELEGATE_BLOCKED_TOOLS
```

### Credential Pool Sharing

```python
def _resolve_child_credential_pool(effective_provider, parent_agent):
    # Same provider → Share parent pool (rotational sync)
    # Different provider → Load that provider's own pool
    # No pool → Inherit parent's fixed credentials
```

### Interruption Propagation

```python
# run_agent.py — Parent Agent's interrupt() method
with self._active_children_lock:
    children_copy = list(self._active_children)
for child in children_copy:
    child.interrupt(message)  # Thread-safe propagation
```

Child agents are registered to `_active_children` during `_build_child_agent` and unregistered in the `finally` block upon completion of execution.

### Result Structure

The parent agent only sees this structured summary, **not the child agent's intermediate tool calls and reasoning**:

```json
{
  "results": [
    {
      "task_index": 0,
      "status": "completed",
      "summary": "Fixed the login bug by...",
      "api_calls": 12,
      "duration_seconds": 45.3,
      "model": "qwen3.6-plus",
      "exit_reason": "completed",
      "tokens": {"input": 8432, "output": 2341},
      "tool_trace": [
        {"tool": "read_file", "args_bytes": 45, "result_bytes": 1234, "status": "ok"},
        {"tool": "patch", "args_bytes": 234, "result_bytes": 56, "status": "ok"}
      ]
    }
  ],
  "total_duration_seconds": 52.1
}
```

### ACP Heterogeneous Orchestration

Delegating to external agents (e.g., Claude Code) via the ACP protocol:

```python
delegate_task(
    goal="Refactor this module",
    acp_command="claude",
    acp_args=["--acp", "--stdio", "--model", "claude-opus-4-6"]
)
```

Hermes acts as the orchestrator, and external agents act as executors.

---

## II. Mixture of Agents — Collaborative Multi-Model Reasoning

Not sub-agents, but **multiple external LLMs collaborating to answer the same question**.

### Architecture

```text
                    User Question
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼            ▼
    Claude Opus    Gemini Pro    GPT-5.4     DeepSeek V3
    (temp=0.6)     (temp=0.6)   (temp=0.6)   (temp=0.6)
          │            │            │            │
          └────────────┼────────────┘
                       ▼
                Claude Opus Aggregator
                  (temp=0.4)
                       │
                  Synthesized Best Answer
```

### Constants

```python
# tools/mixture_of_agents_tool.py
REFERENCE_MODELS = [
    "anthropic/claude-opus-4.6",
    "google/gemini-3-pro-preview",
    "openai/gpt-5.4-pro",
    "deepseek/deepseek-v3.2",
]
AGGREGATOR_MODEL = "anthropic/claude-opus-4.6"

REFERENCE_TEMPERATURE = 0.6     # Diversity
AGGREGATOR_TEMPERATURE = 0.4    # Consistency
MIN_SUCCESSFUL_REFERENCES = 1   # At least 1 successful reference is sufficient for aggregation
```

### Distinctions from Delegate Task

|             | Delegate Task              | Mixture of Agents                      |
| ----------- | -------------------------- | -------------------------------------- |
| **Purpose** | Execute different tasks in parallel | Multi-perspective reasoning for the same question |
| **Isolation** | Complete conversation isolation | Only shares reference responses        |
| **Models**  | Same model or overridable  | 4 references + 1 aggregator (5 API calls) |
| **Output**  | Independent summary for each task | Single synthesized answer              |
| **Scenario**| Research, debugging, multi-workflow | Complex mathematics, algorithms, high-difficulty reasoning |

---

## III. Background Review — Background Experience Refinement

During the conversation, the agent **automatically forks a silent agent** to review the dialogue and create/improve skills.

### Trigger Conditions

```python
# run_agent.py
self._iters_since_skill  # +1 for each tool call
self._skill_nudge_interval = 10  # Triggers a review every 10 times
```

### Fork Mechanism

```python
def _spawn_background_review(self, messages_snapshot, review_memory, review_skills):
    # Daemon thread (non-blocking)
    fork = AIAgent(
        model=self.model,
        provider=self.provider,
        max_iterations=8,         # Lightweight, max 8 steps
        quiet_mode=True,          # stdout → /dev/null
        conversation_history=messages_snapshot,  # Parent conversation snapshot
        skip_context_files=True,
    )
    # Fork shares parent's _memory_store and skill directory
    # Can call skill_manage(action='create/patch')
```

### Three Review Prompts

| Prompt                 | Focus                                  |
| ---------------------- | -------------------------------------- |
| `_MEMORY_REVIEW_PROMPT` | Extract memorable facts → Write to MEMORY.md |
| `_SKILL_REVIEW_PROMPT` | Refine reusable processes → Create/improve skill |
| `_COMBINED_REVIEW_PROMPT` | Perform both memory + skill review simultaneously |

### Distinctions from Delegate Task

|             | Delegate Task             | Background Review                     |
| ----------- | ------------------------- | ------------------------------------- |
| **Trigger** | Agent actively invokes    | Automatically triggered every 10 iterations |
| **Blocking**| Blocks parent agent awaiting results | Daemon thread, completely non-blocking |
| **Isolation** | Complete isolation        | **Shares** memory store and skill directory |
| **Result**  | JSON structured summary   | Callback notification: "💾 Skill 'xxx' updated" |
| **Purpose** | Execute user tasks in parallel | Automatically refines experience, improves skill |

---

## IV. Agent Communication Mechanisms

Hermes' inter-agent communication involves **no message queues, no shared memory, and no IPC** — everything is completed within a single process using native Python mechanisms.

### Delegate Task Communication

Parent and child agents communicate via **ThreadPoolExecutor + Future**, which is essentially inter-thread function calls:

```python
# delegate_tool.py line 619-633
# Parent thread: Submits tasks to the thread pool
with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_CHILDREN) as executor:
    for i, t, child in children:
        future = executor.submit(
            _run_single_child,              # Child agent execution function
            task_index=i, goal=t["goal"],
            child=child, parent_agent=parent_agent,
        )
        futures[future] = i

    # Parent thread: Blocks and waits, receives results from whoever finishes first
    for future in as_completed(futures):
        entry = future.result()             # ← This is "communication"
        results.append(entry)
```

```python
# Inside _run_single_child (line 373)
result = child.run_conversation(user_message=goal)  # Child agent finishes running
summary = result.get("final_response") or ""         # Directly retrieve return value
```

**Even simpler for single tasks**, no thread pool required (line 612):
```python
result = _run_single_child(0, _t["goal"], child, parent_agent)
```

### Mixture of Agents Communication

MoA doesn't even use threads; it's **asynchronous HTTP requests + in-memory aggregation within the same thread**:

```python
# mixture_of_agents_tool.py line 311
# 4 HTTP requests issued concurrently (asyncio coroutines, not multi-threaded)
model_results = await asyncio.gather(*[
    _run_reference_model_safe(model, user_prompt, REFERENCE_TEMPERATURE)
    for model in ref_models
])

# Results collected into a list (pure in-memory variable)
successful_responses = []
for model_name, content, success in model_results:
    if success:
        successful_responses.append(content)

# Construct prompt and send the 5th request
aggregator_system_prompt = _construct_aggregator_prompt(
    AGGREGATOR_SYSTEM_PROMPT, successful_responses
)
```

Intermediate responses from the 4 models are stored in a list on the function stack, garbage collected after aggregation, and not persisted to disk.

### Between Child Agents

**No communication whatsoever.** Multiple child agents run in parallel in their respective threads, unaware of each other's existence, with no coordination mechanisms.

### Result Handling During Interruption

When the user sends a new message during a child agent's execution:

```python
# run_agent.py line 2527-2538
def interrupt(self, message):
    self._interrupt_requested = True
    # Propagate to all running child agents
    with self._active_children_lock:
        children_copy = list(self._active_children)
    for child in children_copy:
        child.interrupt(message)    # Interrupt one by one
```

After interruption:
- The child agent returns `status: "interrupted"`, and any partially produced results are retained in the return value.
- The parent agent's `_persist_session` is triggered, writing messages containing the interrupted results to SQLite.
- **However, interrupted results are not displayed to the user as valid answers** — the parent agent marks `completed: False` and proceeds to the next round of processing new messages.
- The child agent itself has `persist_session=False` and does not write to the DB independently — its partial results exist in the DB as "tool return messages within the parent agent's conversation."

### Communication Model Summary

| Mechanism           | Communication Method                | Concurrency Model         | Intermediate Result Storage       |
| ------------------- | ----------------------------------- | ------------------------- | --------------------------------- |
| Delegate Task       | `Future.result()` (inter-thread return value) | ThreadPoolExecutor multi-threading | Not persisted to disk, function return value |
| Mixture of Agents   | `asyncio.gather` (async coroutine collection) | Single-thread async       | Not persisted to disk, in-memory list |
| Background Review   | Daemon thread fire-and-forget     | Separate daemon thread    | Directly writes to skill/memory files |

**In summary: Everything is completed within a single process, without any inter-process communication.**

---

## V. Iteration Budget System

A resource management layer shared by all multi-agent mechanisms.

### IterationBudget Class

```python
class IterationBudget:
    """Thread-safe iteration counter (run_agent.py:167-209)"""
    
    def __init__(self, max_total: int):
        self.max_total = max_total
        self._used = 0
        self._lock = threading.Lock()
    
    def consume(self) -> bool:
        """Atomic check + decrement. Called once per LLM turn."""
    
    def refund(self) -> None:
        """Refunds one (refunded after execute_code call, encourages more verification)."""
    
    @property
    def remaining(self) -> int: ...
```

### Budget Isolation

```text
Parent Agent:  IterationBudget(90)   ← Default 90
Child Agent A: IterationBudget(50)   ← Independent, does not consume parent's budget
Child Agent B: IterationBudget(50)   ← Independent
Child Agent C: IterationBudget(50)   ← Independent
──────────────────────────────
Theoretical total iterations: 90 + 150 = 240
```

### Budget Pressure Warnings

```python
self._budget_caution_threshold = 0.7   # 70% — "Start wrapping up"
self._budget_warning_threshold = 0.9   # 90% — "Respond immediately"
```

Warnings are injected into the tool result JSON (without breaking message structure or invalidating the prompt cache).

---

## VI. Configuration

```yaml
# config.yaml
delegation:
  provider: openrouter            # Optional: dedicated provider for child agents
  model: google/gemini-3-flash    # Optional: cheaper model for child agents
  max_iterations: 50              # Max iterations per child agent
  reasoning_effort: low           # Optional: controls child agent reasoning depth (low/medium/high/xhigh)
  # Or specify endpoint directly
  base_url: https://api.openai.com/v1
  api_key: sk-xxx
```

### Usage Examples

```python
# Single-task
delegate_task(
    goal="Debug the login failure issue",
    context="User reports 500 error on /api/login",
    toolsets=["terminal", "file"]
)

# 3 parallel tasks
delegate_task(tasks=[
    {"goal": "Fix login bug", "toolsets": ["terminal", "file"]},
    {"goal": "Update API docs", "toolsets": ["terminal", "file"]},
    {"goal": "Run test suite", "toolsets": ["terminal"]},
])

# Multi-model collaborative reasoning
mixture_of_agents(user_prompt="What is the strongest known result proving P ≠ NP?")
```

## Two Levels of Multi-Agent

Hermes actually offers two multi-agent solutions, serving different scenarios:

|                     | In-session Multi-Agent (this page) | Multi-Profile                          |
| ------------------- | ---------------------------------- | -------------------------------------- |
| **Granularity**     | Subtasks within a single session   | Completely independent agent instances |
| **Context**         | Child agents inherit the parent agent's conversation | Completely isolated, mutually invisible |
| **Terminal Backend**| Inherits from parent agent, **cannot switch** | Each Profile is **independently configured** |
| **Memory**          | Shared (same MemoryManager)        | Separate MEMORY.md / USER.md for each |
| **Models**          | Can be different                   | Can be different                       |
| **Collaboration Method** | Automatic dispatch + result feedback | Manual switching, no automatic collaboration |

**In-session multi-agent is "one brain commanding multiple hands"** — suitable for parallel division of labor within a single task.

**Multi-Profile is "multiple independent individuals each minding their own business"** — suitable for isolating different security boundaries, models, and skill sets by function. For example: a `coder` Profile uses the `local` backend for daily development, while an `ops` Profile uses the `docker` backend for risky operations.

### Can Multi-Profiles Communicate?

**There is no native communication channel.** Each Profile is an independent process, independent DB, and independent memory, unaware of each other's existence.

However, they can **interact indirectly via messaging platforms** — two Profiles, each bound to a bot, in the same channel:

```text
Profile A (Bot A) → send_message tool actively sends message to channel
                              ↓
                      Discord / Slack Channel (message relay)
                              ↓
Profile B (Bot B) → ALLOW_BOTS=all → Received, processed as a regular user message
```

Discord and Slack both support `allow_bots` configuration (three modes: none/mentions/all):

```bash
# Discord — Bot B's .env
DISCORD_ALLOW_BOTS=none       # Default: ignores all bot messages
DISCORD_ALLOW_BOTS=mentions   # Only receives bot messages that @mention itself
DISCORD_ALLOW_BOTS=all        # Receives all bot messages

# Slack — Bot B's .env
SLACK_ALLOW_BOTS=none         # Same as above
SLACK_ALLOW_BOTS=mentions
SLACK_ALLOW_BOTS=all
```

Discord also features **multi-bot filtering**: messages that @mention other bots but not themselves are automatically skipped, preventing interference in multi-bot channels.

**Note**: This is not an inter-agent communication feature designed by Hermes, but rather two independent bots incidentally interacting via platform messages. It involves latency, lacks transactional guarantees, and can easily lead to deadlocks (A sends → B replies → A replies again → infinite loop), so caution and control are required during use.

See also → [[configuration-and-profiles]]

## Related Pages

- [[configuration-and-profiles]] — Multi-Profile Architecture (Another Multi-Agent Solution)
- [[tool-registry-architecture]] — Child Agents Obtain Restricted Toolsets via Registry
- [[auxiliary-client-architecture]] — Child Agents Can Configure Independent Auxiliary Models
- [[credential-pool-and-isolation]] — Credential Pool Sharing and Rotation
- [[skills-system-architecture]] — Skills Automatically Created/Improved by Background Review are Stored Here
- [[trajectory-and-data-generation]] — Batch Runner (Nous internal training tool, not part of Agent runtime)

## Related Files

- `tools/delegate_tool.py` — Child Agent Delegation Implementation
- `tools/mixture_of_agents_tool.py` — Multi-Model Collaborative Reasoning
- `tools/send_message_tool.py` — Cross-Platform Message Delivery (Not part of Multi-Agent, categorized under messaging-gateway)
- `run_agent.py` — IterationBudget Class, Background Review, Interruption Propagation
