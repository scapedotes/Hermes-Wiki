---
title: Git Worktree Isolation
created: 2026-04-10
updated: 2026-04-10
type: concept
tags: [git, worktree, isolation, parallel]
sources: [cli.py, hermes_cli/main.py, cli-config.yaml.example]
---

# Git Worktree Isolation

## Overview

Hermes supports **multiple agents operating on the same repository in parallel without conflicts** through Git worktrees. Each agent session operates within an independent worktree branch, ensuring file modifications do not affect one another.

## Usage

```bash
hermes -w              # Creates an isolated worktree on startup
hermes --worktree      # Same as above
```

Alternatively, enable globally in `config.yaml`:
```yaml
worktree: true         # Automatically creates a worktree every time Hermes is started within a Git repository.
```

## How it Works

```text
hermes -w
    ↓
_setup_worktree()
    ↓
1. Checks if the current directory is within a Git repository (errors if not).
2. Creates a new worktree under .worktrees/ (using git worktree add).
3. Creates a branch named hermes/hermes-{8-digit-random-ID}, based on HEAD.
4. Automatically adds .worktrees/ to .gitignore.
5. Copies files listed in .worktreeinclude (which are gitignored but required by the agent).
6. Changes the Current Working Directory (CWD) to the worktree directory.
    ↓
Agent operates in the isolated environment.
    ↓
Session ends → _cleanup_worktree()
    ↓
Deletes the worktree directory and branch (using git worktree remove + git branch -D).
```

## .worktreeinclude File

Certain files are ignored by `.gitignore` but are required by the agent (e.g., `.env`, `node_modules`). Create a `.worktreeinclude` file in the project root:

```text
# One path per line, supports files and directories
.env
node_modules
```

- Files: Copied using `shutil.copy2`.
- Directories: Symlinks are created (to save disk space).
- Path Traversal Attack Protection: Both source and target paths must be within their respective root directories.

## Applicable Scenarios

- Multiple agents simultaneously modifying different parts of the same repository.
- Protecting the main branch from experimental changes.
- Used in conjunction with multiple Profiles (different Profile + different worktree = fully isolated parallel development).

## Related Pages

- [[configuration-and-profiles]] — Multi-Profile Architecture
- [[multi-agent-architecture]] — Multi-Agent Collaboration

## Key Source Files

- `cli.py` — `_setup_worktree()` / `_cleanup_worktree()`
- `hermes_cli/main.py` — Parsing of `-w`/`--worktree` parameters.