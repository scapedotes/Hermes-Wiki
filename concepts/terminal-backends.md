---
title: Terminal Backends and Environment Abstraction Layer
created: 2026-04-07
updated: 2026-04-29
type: concept
tags: [architecture, environments, terminal, isolation]
sources: [hermes-agent Source Code Analysis 2026-04-07]
---

# Terminal Backends and Environment Abstraction Layer

## Design Principles

Hermes supports 7 types of terminal backends, offering varying levels of isolation and persistence. A unified `terminal` tool abstraction allows the Agent to switch seamlessly between different backends.

## Backend Types

| Backend | Isolation Level | Persistence | Applicable Scenarios |
|---------|-----------------|-------------|----------------------|
| **Local** | None | ✅ Local Disk | Development, Personal Use |
| **Docker** | Container | ✅ Volume Mount | Testing, CI/CD |
| **SSH** | Remote Host | ✅ Remote Disk | Remote Servers |
| **Modal** | Serverless | ✅ Snapshot | Cloud Execution, On-demand Launch |
| **Daytona** | Sandbox | ✅ Persistent Sandbox | Secure Execution |
| **Singularity** | Container | ✅ Volume Mount | HPC, Research |
| **Vercel Sandbox** | microVM | ✅ Snapshot (by task_id) | Cloud microVM, FileSyncManager credential/skill synchronization (v2026.4.23+) |

### Docker Containers Run as Host User (v2026.4.23+)

`feat(docker): run container as host user` allows processes within the container to start with the host machine's UID/GID, preventing files created by bind mounts from being owned by root and requiring sudo for cleanup.

## Terminal Tool

```python
# tools/terminal_tool.py

def terminal(
    command: str,
    background: bool = False,
    timeout: int = 180,
    workdir: str = None,
    pty: bool = False,
) -> dict:
    """Executes a terminal command."""
    
    # Parse backend type
    backend = os.getenv("TERMINAL_ENV", "local")
    
    # Dispatch to corresponding backend
    if backend == "local":
        return _run_local(command, timeout, workdir)
    elif backend == "docker":
        return _run_docker(command, timeout, workdir)
    elif backend == "ssh":
        return _run_ssh(command, timeout, workdir)
    elif backend == "modal":
        return _run_modal(command, timeout, workdir)
    elif backend == "daytona":
        return _run_daytona(command, timeout, workdir)
    elif backend == "singularity":
        return _run_singularity(command, timeout, workdir)
```

## Unified Execution Model: Spawn-per-call

All 6 backends share the same execution model—**each command independently spawns a `bash -c` process**, maintaining environmental consistency through session snapshots:

```text
During initialization:
  login shell → capture session snapshot (env vars, functions, aliases)

For each command execution:
  spawn bash -c → source snapshot → execute command → capture CWD → exit
```

**BaseEnvironment** (`tools/environments/base.py`) defines a unified interface:

- `init_session()` — Starts a login shell and captures an environment snapshot
- `_wrap_command(cmd)` — Injects snapshot source + CWD tracking markers
- `execute(cmd)` — Unified entry point: wrap → spawn → wait → return `{output, returncode}`
- `_run_bash(wrapped_cmd)` → Abstract method, each backend implements specific process creation

**CWD persistence across calls** is achieved through output markers:
- Local backends: temporary files
- Remote backends (Docker/SSH/Modal): stdout embedded markers

> Note: The old `PersistentShellMixin` (`persistent_shell.py`) was deleted on 2026-04-09, completely replaced by spawn-per-call + session snapshot.

## Environment Context

```python
# environments/tool_context.py

class ToolContext:
    """Tool execution context."""
    
    def __init__(self, environment: BaseEnvironment):
        self.environment = environment
        self.working_directory = "/root"
        self.env_vars = {}
    
    async def run_command(self, command: str, **kwargs) -> dict:
        return await self.environment.run_command(
            command,
            workdir=self.working_directory,
            env=self.env_vars,
            **kwargs
        )
```

## Unified File Synchronization (`file_sync.py`, 2026-04-10)

SSH/Modal/Daytona backends use `tools/environments/file_sync.py` to synchronize files (credentials, skills, cache, etc.) between the local machine and remote environments. Docker/Singularity do not require this due to bind mounts.

-   **Change Detection**: Based on mtime + file size, only changed files are uploaded.
-   **Deletion Detection**: If a local file is deleted, the corresponding remote file is also cleaned up.
-   **Transaction Rollback**: If any upload/deletion step fails, it rolls back to the previous state and retries next time.
-   **Rate Limiting**: Defaults to synchronizing once every 5 seconds (`HERMES_FORCE_FILE_SYNC=1` forces synchronization every time).

## Background Process Monitoring (`watch_patterns`, 2026-04-10)

The `terminal` tool adds a new `watch_patterns` parameter to notify the agent in real-time when background process output matches specified strings:

```python
terminal(command="pytest -v", background=True, watch_patterns=["ERROR", "FAIL", "listening on port"])
```

| Parameter | Value |
|-----------|-------|
| Matching Method | Substring matching (non-regex) |
| Rate Limiting | Max 8 notifications per 10-second window |
| Overload Protection | Automatically disabled after 45 seconds of continuous overload |
| Output Truncation | Max 20 lines, 2000 characters |

Notifications are passed to the CLI/Gateway's main loop via `ProcessRegistry.completion_queue`, triggering an automatic agent response.

## Superiority Analysis

### Compared to Other Agent Frameworks

| Feature | Hermes | Cursor | Claude Code |
|---------|--------|--------|-------------|
| Number of Backends | ✅ 6 types | ❌ 1 | ❌ 1 |
| Serverless Support | ✅ Modal | ❌ | ❌ |
| Sandbox Isolation | ✅ Daytona | ❌ | ❌ |
| HPC Support | ✅ Singularity | ❌ | ❌ |
| Session Snapshot | ✅ | ❌ | ❌ |
| Environment Snapshot | ✅ Modal | ❌ | ❌ |

## Configuration File

```yaml
# ~/.hermes/config.yaml
terminal:
  backend: "local"  # local/docker/ssh/modal/daytona/singularity
  
  docker:
    image: "ubuntu:22.04"
    volumes: ["~/work:/root/work"]
  
  ssh:
    host: "remote-server"
    user: "ubuntu"
    key_path: "~/.ssh/id_rsa"
  
  modal:
    app_name: "hermes-agent"
    image: "python:3.11"
  
  daytona:
    api_key: "${DAYTONA_API_KEY}"
    image: "ubuntu:22.04"
```

## Related Pages

-   [[credential-pool-and-isolation]] — Credential Pool and Environment Isolation (Terminal Backend Environment)
-   [[multi-agent-architecture]] — Sub-agents Executing with Independent Terminal Backends
-   [[tool-registry-architecture]] — Terminal Tools Registered via Registry

## Related Files

-   `tools/terminal_tool.py` — Terminal Tool
-   `tools/environments/` — 6 Backend Implementations
-   `environments/tool_context.py` — Tool Execution Context