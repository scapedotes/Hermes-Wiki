---
title: Credential Pool and Environment Isolation System
created: 2026-04-07
updated: 2026-04-11
type: concept
tags: [architecture, credentials, security, isolation]
sources: [agent/credential_pool.py, hermes_cli/auth.py]
---

# Credential Pool and Environment Isolation System

## Design Principles

Enterprise scenarios require multiple API keys for:
1. **Load Balancing** — Distribute requests across multiple keys
2. **Failover** — Automatically switch when a key is rate-limited
3. **Cost Control** — Different keys have different budgets

Hermes implements a **Credential Pool system** that supports automatic rotation of multiple keys.

## Credential Pool Architecture

Core data structures are located in `agent/credential_pool.py` (not `tools/`):

- **`PooledCredential`** — A single credential entry (dataclass), containing `runtime_api_key`, `runtime_base_url`, exhaustion status, and usage count.
- **`CredentialPool`** — The credential pool, managing the selection, rotation, and recovery of multiple credentials.

### 4 Pool Selection Strategies

```yaml
# config.yaml
credential_pool:
  strategy: round_robin  # default
```

| Strategy | Behavior |
|------|------|
| `fill_first` | Always use the first one until exhausted, then switch to the next. |
| `round_robin` | Rotate sequentially, distributing usage evenly. |
| `random` | Randomly select an available one. |
| `least_used` | Select the one with the fewest uses. |

### Key Methods

- `select()` — Selects the next available credential according to the strategy.
- `mark_exhausted(entry)` — Marks as exhausted + automatic rotation (exhaustion TTL is 1 hour, automatically recovers upon expiry).
- `try_refresh(entry)` — OAuth token refresh.
- `has_available()` — Checks if there are any available credentials.

## Credential Rotation Logic

```python
# 402 (Billing Exhausted) — Rotate immediately
if status_code == 402:
    next_entry = pool.mark_exhausted_and_rotate(status_code=402, ...)
    if next_entry:
        self._swap_credential(next_entry)
        return True, False

# 429 (Rate Limit) — Retry first time, rotate second time
if status_code == 429:
    if not has_retried_429:
        return False, True  # Retry with the same credential
    next_entry = pool.mark_exhausted_and_rotate(status_code=429, ...)
    if next_entry:
        self._swap_credential(next_entry)
        return True, False

# 401 (Unauthorized) — Refresh first, rotate if failed
if status_code == 401:
    refreshed = pool.try_refresh_current()
    if refreshed:
        self._swap_credential(refreshed)
        return True, has_retried_429
    # Refresh failed — Rotate
    next_entry = pool.mark_exhausted_and_rotate(status_code=401, ...)
    if next_entry:
        self._swap_credential(next_entry)
        return True, False
```

## Credential Swapping

```python
def _swap_credential(self, entry) -> None:
    """Swaps credentials"""
    runtime_key = getattr(entry, "runtime_api_key", None)
    runtime_base = getattr(entry, "runtime_base_url", None) or self.base_url
    
    if self.api_mode == "anthropic_messages":
        self._anthropic_client.close()
        self._anthropic_api_key = runtime_key
        self._anthropic_base_url = runtime_base
        self._anthropic_client = build_anthropic_client(runtime_key, runtime_base)
        self._is_anthropic_oauth = _is_oauth_token(runtime_key)
        self.api_key = runtime_key
        self.base_url = runtime_base
        return
    
    # OpenAI compatible mode
    self.api_key = runtime_key
    self.base_url = runtime_base.rstrip("/")
    self._client_kwargs["api_key"] = self.api_key
    self._client_kwargs["base_url"] = self.base_url
    self._replace_primary_openai_client(reason="credential_rotation")
```

## Environment Isolation

```python
# HERMES_HOME Isolation
def get_hermes_home() -> Path:
    """Gets the Hermes home directory (supports Profile overrides)"""
    env_override = os.getenv("HERMES_HOME")
    if env_override:
        return Path(env_override)
    return Path.home() / ".hermes"

# Profile Support
# ~/.hermes/ is the default Profile
# HERMES_HOME=/path/to/custom uses a custom Profile
```

### Profile Isolation Scope

| Content | Isolated | Shared |
|------|------|------|
| Configuration (config.yaml) | ✅ | ❌ |
| Secrets (.env) | ✅ | ❌ |
| Skills (~/.hermes/skills/) | ✅ | ❌ |
| Memories (~/.hermes/memories/) | ✅ | ❌ |
| Session Database | ✅ | ❌ |
| Code Repository | ❌ | ✅ |

## Terminal Backend Environment Isolation

```python
# tools/environments/
# Each terminal backend provides an isolated execution environment

local.py      # Local execution (shared file system)
docker.py     # Docker container isolation
ssh.py        # SSH remote execution
modal.py      # Modal serverless isolation
daytona.py    # Daytona sandbox isolation
singularity.py # Singularity container isolation
```

## Superiority Analysis

### Comparison with Other Agent Frameworks

| Feature | Hermes | Cursor | OpenCode |
|------|--------|--------|----------|
| Credential Pool | ✅ Multi-key rotation | ❌ | ❌ |
| Automatic Failover | ✅ 402/429/401 | ❌ | ❌ |
| OAuth Refresh | ✅ Automatic | ❌ | ❌ |
| Profile Isolation | ✅ HERMES_HOME | ❌ | ❌ |
| Terminal Backend Isolation | ✅ 6 backends | ❌ | ✅ Docker |

## Related Pages

- [[interrupt-and-fault-tolerance]] — Interrupt Propagation and Fault Tolerance Mechanism (Credential Rotation Logic)
- [[auxiliary-client-architecture]] — Auxiliary Clients Using Credential Pool for Authentication
- [[configuration-and-profiles]] — Profile Isolation and Credential Management

## Related Files

- `agent/credential_pool.py` — Credential Pool (4 strategies + exhaustion recovery)
- `hermes_cli/auth.py` — Credential Parsing
- `tools/environments/` — Terminal Backend Environments