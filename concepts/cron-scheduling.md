---
title: Cron Scheduling and Automated Workflows
created: 2026-04-07
updated: 2026-04-07
type: concept
tags: [architecture, cron, automation, scheduling]
sources: [hermes-agent Source Code Analysis 2026-04-07]
---

# Cron Scheduling and Automated Workflows

## Design Principles

Hermes features a built-in Cron scheduler, supporting **natural language-based scheduled tasks**. It can automatically execute repetitive work and push results to any platform.

## Cron Tools

```python
# tools/cronjob_tools.py

def cronjob(
    action: str,           # create/list/update/pause/resume/remove
    prompt: str = None,    # Task prompt
    schedule: str = None,  # Schedule expression
    name: str = None,      # Task name
    deliver: str = None,   # Delivery target
    job_id: str = None,    # Job ID
) -> dict:
    """Manages scheduled jobs"""
    
    if action == "create":
        return _create_job(prompt, schedule, name, deliver)
    elif action == "list":
        return _list_jobs()
    elif action == "update":
        return _update_job(job_id, prompt, schedule, name, deliver)
    elif action == "pause":
        return _pause_job(job_id)
    elif action == "resume":
        return _resume_job(job_id)
    elif action == "remove":
        return _remove_job(job_id)
```

## Scheduler

The scheduler uses a **module-level function** architecture (non-class based), driven by the Gateway calling `tick()` every 60 seconds:

```python
# cron/scheduler.py — Module-level function architecture

def tick():
    """Called by the Gateway every 60 seconds to check and execute due tasks"""
    now = datetime.now()
    jobs = _load_jobs()  # Loaded from jobs.json
    for job in jobs.values():
        if _should_run(job, now):
            run_job(job)

def run_job(job: dict):
    """Executes a single job"""
    # Create a new Agent instance
    agent = AIAgent(
        model=job.get("model"),
        platform="cron",
        enabled_toolsets=job.get("toolsets", ["terminal", "web", "file"]),
    )
    
    # Execute the task
    result = agent.run_conversation(job["prompt"])
    
    # Deliver the result
    if job.get("deliver"):
        _deliver_result(job["deliver"], result)

async def _deliver_result(target: str, result: dict):
    """Delivers the result to the target platform"""
    ...
```

## Job Data Structure

Jobs are stored as **plain dictionaries** in `jobs.json` (non-class based):

```python
# cron/jobs.py — Jobs are plain dicts, stored in jobs.json

# Example job dictionary structure
job = {
    "id": "daily-report",
    "prompt": "Generate today's work summary report",
    "schedule": "0 18 * * *",       # cron expression
    "name": "daily-report",
    "deliver": "telegram",
    "model": "gpt-4",
    "toolsets": ["terminal", "web", "file"],
    "is_paused": False,
    "created_at": "2026-04-07T10:00:00",
    "last_run": None,
    "next_run": "2026-04-07T18:00:00",
}

# Supported schedule expression formats:
# - cron: "0 9 * * *" (daily at 9 AM)
# - Relative: "30m", "every 2h", "daily"
# - ISO: "2026-04-08T09:00:00"
```

## Delivery Targets

```python
# Known delivery platforms
_KNOWN_DELIVERY_PLATFORMS = {
    "telegram", "discord", "slack", "whatsapp", "signal",
    "matrix", "mattermost", "homeassistant",
    "dingtalk", "feishu", "wecom",
    "sms", "email", "webhook",
}

async def _deliver_result(target: str, result: dict):
    """Delivers the result to the target"""
    if target == "origin":
        # Return to the original chat (via Gateway)
        await self.gateway.send_message(result["final_response"])
    elif target == "local":
        # Save to local file
        output_dir = get_hermes_home() / "cron" / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{self.job_id}.txt"
        output_file.write_text(result["final_response"])
    elif target in DELIVER_TARGETS:
        # Send via platform
        await self.platform_send(target, result["final_response"])
```

## Usage Examples

```python
# Create daily report job
cronjob(
    action="create",
    name="daily-report",
    prompt="Generate today's work summary report, including completed tasks, to-do items, and tomorrow's plan",
    schedule="0 18 * * *",  # Daily at 18:00
    deliver="telegram",
)

# Create hourly check job
cronjob(
    action="create",
    name="hourly-check",
    prompt="Check server status, send alert if anomalies are found",
    schedule="every 1h",
    deliver="origin",
)

# Create one-time job
cronjob(
    action="create",
    name="backup-database",
    prompt="Back up database and upload to cloud storage",
    schedule="2026-04-08T02:00:00",  # ISO time
    deliver="local",
)
```

## Gateway Integration

```bash
# Start Gateway (including scheduler)
hermes gateway start

# Gateway calls scheduler.tick() every 60 seconds
# The scheduler has no independent event loop; it's driven by the Gateway
```

## Superiority Analysis

### Comparison with Other Agent Frameworks

| Feature                   | Hermes                     | Claude Code | Cursor |
|---------------------------|----------------------------|-------------|--------|
| Built-in scheduler        | ✅                         | ❌          | ❌     |
| Natural language scheduling | ✅                         | ❌          | ❌     |
| Multi-platform delivery   | ✅ 14 platforms            | ❌          | ❌     |
| Cron expressions          | ✅                         | ❌          | ❌     |
| Relative time             | ✅ "30m", "every 2h"       | ❌          | ❌     |
| Job management            | ✅ CLI/Gateway             | ❌          | ❌     |

## Configuration

```yaml
# ~/.hermes/config.yaml
cron:
  enabled: true
  timezone: "Asia/Shanghai"
  output_dir: "~/.hermes/cron/output"
```

## Related Pages

- [[messaging-gateway-architecture]] — Gateway-driven scheduler tick() loop
- [[hook-system-architecture]] — Collaboration between Gateway event hooks and Cron jobs
- [[gateway-session-management]] — Session origin for Cron delivery routing

## Related Files

- `tools/cronjob_tools.py` — Cron Tools
- `cron/scheduler.py` — Scheduler
- `cron/jobs.py` — Job Definition
- `gateway/run.py` — Gateway Integration
