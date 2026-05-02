---
title: Trajectory Saving and Training Data Generation
created: 2026-04-07
updated: 2026-04-14
type: concept
tags: [architecture, data-generation, training, trajectory, batch-runner]
sources: [agent/trajectory.py, batch_runner.py, toolset_distributions.py, environments/, run_agent.py]
---

# Trajectory Saving and Training Data Generation

## What Problem Does This System Solve?

The Hermes repository includes a built-in **training data production infrastructure** (off by default, requires explicit activation). The core idea is for the Agent to truly execute tasks, saving the dialogue process (including tool calls and reasoning) in a standard format, for Nous Research to train the next generation of tool-calling models. This functionality is not involved in daily use.

```
Batch Task Dataset (JSONL)
    ↓ batch_runner.py (multi-process parallel execution)
AIAgent genuinely executes each task
    ↓ save_trajectories=True
Dialogue Trajectory Format Conversion (ShareGPT format)
    ↓ trajectory.py
JSONL Training Data
    ↓ environments/ + Atropos
RL Reinforcement Learning Training
```

## When Is It Used?

| Scenario                   | Description                                                                                             |
|----------------------------|---------------------------------------------------------------------------------------------------------|
| **Internal to Nous Research** | Batch generation of tool-calling training data to iterate on Hermes series models.                     |
| **Model Fine-tuning**      | Use `batch_runner` to generate high-quality SFT data when training your own tool-calling models.      |
| **Single Debugging Session** | `--save_trajectories` saves a single dialogue trajectory for analyzing Agent behavior.                 |
| **RL Training**            | Integrates with the Atropos framework via `environments/` for reinforcement learning.                  |
| **Daily Use**              | Disabled by default (`save_trajectories=False`), does not affect normal conversations.                 |

## Trajectory Saving (`trajectory.py`)

When `save_trajectories=True`, trajectories are automatically saved after each conversation.

**Trigger Location**: The `_save_trajectory()` method in `run_agent.py` (line 2358), called at the end of `run_conversation()`.

**Output Format**: ShareGPT format JSONL, each record contains:

```json
{
  "conversations": [
    {"from": "system", "value": "You are a function calling AI model..."},
    {"from": "human", "value": "User query"},
    {"from": "gpt", "value": "<think>\nReasoning process\n</think>\n<tool_call>\n{...}\n</tool_call>"},
    {"from": "tool", "value": "<tool_response>\n{...}\n</tool_response>"},
    {"from": "gpt", "value": "<think>\n...\n</think>\nFinal answer"}
  ],
  "timestamp": "2026-04-14T...",
  "model": "qwen3.6-plus",
  "completed": true
}
```

**Output Files**:
- Successful dialogues → `trajectory_samples.jsonl`
- Failed dialogues → `failed_trajectories.jsonl`

### Format Conversion Details

`_convert_to_trajectory_format()` (`run_agent.py:2193`) is responsible for converting the internal OpenAI format to the training format:

| Conversion Rule                      | Description                                                                  |
|--------------------------------------|------------------------------------------------------------------------------|
| `role: assistant` → `from: gpt`      | Role mapping                                                                 |
| `role: user` → `from: human`         | Role mapping                                                                 |
| `role: tool` → `from: tool`          | Tool results are wrapped in `<tool_response>` XML.                           |
| `reasoning` field → `<think>` tag    | Native thought chain is preserved.                                           |
| `<REASONING_SCRATCHPAD>` → `<think>` | Non-native reasoning is also unified to this format.                         |
| No reasoning content → empty `<think></think>` | Ensures consistent format for each GPT turn, facilitating training.          |
| `tool_calls` → `<tool_call>` XML     | Tool calls are wrapped in XML.                                               |

## Batch Runner (`batch_runner.py`)

The core component for large-scale data generation, 1287 lines.

**Usage**:

```bash
# Basic usage: Batch execution from a dataset
python batch_runner.py --dataset_file=data.jsonl --batch_size=10 --run_name=my_run

# Resume an interrupted run
python batch_runner.py --dataset_file=data.jsonl --batch_size=10 --run_name=my_run --resume

# Specify toolset distribution
python batch_runner.py --dataset_file=data.jsonl --batch_size=10 --run_name=my_run --distribution=image_gen
```

**Key Features**:

| Feature                  | Implementation                                                                     |
|--------------------------|------------------------------------------------------------------------------------|
| Parallel Execution       | `multiprocessing.Pool` (not thread pool), true multi-process.                      |
| Resume from Checkpoint   | Checkpoint mechanism allows `--resume` to restart after interruption.              |
| Toolset Sampling         | Randomly selects toolsets based on probability distributions via `toolset_distributions.py`. |
| Automatic Trajectory Saving | Each sub-task sets `save_trajectories=True` and `skip_context_files=True`. |
| Tool Statistics          | Summarizes tool usage statistics across all batches.                               |
| HuggingFace Compatibility | Standardized JSONL schema output, directly uploadable to HF datasets.              |

### Toolset Distributions (`toolset_distributions.py`)

Controls which tool combinations are enabled during data generation and their probabilities:

```python
DISTRIBUTIONS = {
    "default": {...},        # All tools 100%
    "image_gen": {...},      # Focuses on image generation tools
    "web_research": {...},   # Focuses on web search tools
    ...
}
```

This allows for targeted generation of training data for specific tool combinations.

### Data Generation Configuration Examples

The `datagen-config-examples/` directory provides ready-to-use configurations:

```
trajectory_compression.yaml    # Trajectory compression configuration
web_research.yaml              # Web research task configuration
run_browser_tasks.sh           # Batch script for browser tasks
example_browser_tasks.jsonl    # Example browser task dataset
```

## RL Training Environment (`environments/`)

Reinforcement learning environments integrated with the Tinker-Atropos framework:

| Environment                | Purpose                                |
|----------------------------|----------------------------------------|
| `hermes_base_env.py`       | Base Agent environment                 |
| `agentic_opd_env.py`       | Agentic interaction environment        |
| `web_research_env.py`      | Web research task environment          |
| `terminal_test_env/`       | Terminal command testing environment   |
| `hermes_swe_env/`          | Software engineering task environment  |
| `tool_call_parsers/`       | Tool call parsers                      |
| `agent_loop.py`            | Agent loop and environment bridging    |

## Do Regular Users Need to Care?

**Generally, no**. This entire system is off by default, and regular chat is completely unaffected.

If you want to use it:

```bash
# Save trajectory for a single conversation (for debugging)
python run_agent.py --save_trajectories --query="Your question"

# Batch generate training data (for model training)
python batch_runner.py --dataset_file=your_tasks.jsonl --batch_size=10 --run_name=run1
```

## Related Pages

- [[agent-loop-and-prompt-assembly]] — `save_trajectories` parameter and `_convert_to_trajectory_format()` method
- [[multi-agent-architecture]] — Batch Runner as a large-scale batch processing engine
- [[context-compressor-architecture]] — For more compact compressed trajectory data

## Related Files

- `agent/trajectory.py` — Trajectory file writing and format conversion utility functions
- `run_agent.py:2193-2371` — `_convert_to_trajectory_format()` + `_save_trajectory()`
- `batch_runner.py` — Batch Runner (1287 lines)
- `toolset_distributions.py` — Toolset probability distribution definitions
- `environments/` — RL training environments
- `datagen-config-examples/` — Data generation configuration examples
