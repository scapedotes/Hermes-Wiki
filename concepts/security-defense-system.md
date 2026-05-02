---
title: Security Defense System — Multi-Layer Injection Detection
created: 2026-04-07
updated: 2026-04-11
type: concept
tags: [architecture, security, injection-defense, skills-guard]
sources: [Hermes Agent Source Code Analysis 2026-04-07]
---

# Security Defense System — Multi-Layer Injection Detection

## Design Principles

Hermes Agent has the ability to execute code, read/write files, and access networks, therefore it must defend against:
1.  **Prompt Injection** — Malicious content attempting to override Agent instructions
2.  **Data Exfiltration** — Stealing API keys, credentials
3.  **Destructive Operations** — Deleting files, damaging the system
4.  **Persistence Backdoors** — Modifying startup scripts, cron jobs
5.  **Supply Chain Attacks** — Malicious skills, unpinned dependencies

Hermes implements a **5-layer defense system**, ranging from content scanning to trust policies.

## Layer 1: Skills Guard Security Scan

### Threat Pattern Library (100+ Regex Patterns)

```python
THREAT_PATTERNS = [
    # ── Data Exfiltration ──
    (r'curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD)',
     "env_exfil_curl", "critical", "exfiltration",
     "curl command interpolating secret environment variables"),
    (r'os\.getenv\s*\(\s*[^\)]*(?:KEY|TOKEN|SECRET|PASSWORD)',
     "python_getenv_secret", "critical", "exfiltration",
     "Reading secrets via os.getenv()"),
    (r'\$HOME/\.ssh|\~/\.ssh',
     "ssh_dir_access", "high", "exfiltration",
     "Referencing user SSH directory"),
    (r'\$HOME/\.hermes/\.env|\~/\.hermes/\.env',
     "hermes_env_access", "critical", "exfiltration",
     "Directly referencing Hermes secret file"),
    
    # ── Prompt Injection ──
    (r'ignore\s+(?:\w+\s+)*(previous|all|above|prior)\s+instructions',
     "prompt_injection_ignore", "critical", "injection",
     "Prompt Injection: Ignore previous instructions"),
    (r'do\s+not\s+(?:\w+\s+)*tell\s+(?:\w+\s+)*the\s+user',
     "deception_hide", "critical", "injection",
     "Instructing Agent to hide info from user"),
    (r'act\s+as\s+(if|though)\s+(?:\w+\s+)*you\s+(?:\w+\s+)*(have\s+no|don\'t\s+have)\s+(?:\w+\s+)*(restrictions|limits|rules)',
     "bypass_restrictions", "critical", "injection",
     "Instructing Agent to act without restrictions"),
    
    # ── Destructive Operations ──
    (r'rm\s+-rf\s+/',
     "destructive_root_rm", "critical", "destructive",
     "Recursive deletion from root"),
    (r'shutil\.rmtree\s*\(\s*[\"\']/',
     "python_rmtree", "high", "destructive",
     "Python rmtree absolute path"),
    (r'>\s*/etc/',
     "system_overwrite", "critical", "destructive",
     "Overwriting system configuration files"),
    
    # ── Persistence Backdoors ──
    (r'\bcrontab\b',
     "persistence_cron", "medium", "persistence",
     "Modifying cron jobs"),
    (r'authorized_keys',
     "ssh_backdoor", "critical", "persistence",
     "Modifying SSH authorized keys"),
    (r'systemd.*\.service|systemctl\s+(enable|start)',
     "systemd_service", "medium", "persistence",
     "Referencing or enabling systemd service"),
    (r'\.(bashrc|zshrc|profile)',
     "shell_rc_mod", "medium", "persistence",
     "Referencing shell startup files"),
    
    # ── Network Backdoors ──
    (r'\bnc\s+-[lp]|ncat\s+-[lp]|\bsocat\b',
     "reverse_shell", "critical", "network",
     "Potential reverse shell listener"),
    (r'\bngrok\b|\blocaltunnel\b|\bserveo\b',
     "tunnel_service", "high", "network",
     "Using tunneling service for external access"),
    
    # ── Obfuscated Execution ──
    (r'base64\s+(-d|--decode)\s*\|',
     "base64_decode_pipe", "high", "obfuscation",
     "base64 decode and pipe execution"),
    (r'\beval\s*\(\s*[\"\']',
     "eval_string", "high", "obfuscation",
     "eval() string argument"),
    (r'echo\s+[^\n]*\|\s*(bash|sh|python)',
     "echo_pipe_exec", "critical", "obfuscation",
     "echo pipe to interpreter execution"),
    
    # ── Supply Chain Attacks ──
    (r'curl\s+[^\n]*\|\s*(ba)?sh',
     "curl_pipe_shell", "critical", "supply_chain",
     "curl pipe to shell (download and execute)"),
    (r'pip\s+install\s+(?!-r\s)(?!.*==)',
     "unpinned_pip_install", "medium", "supply_chain",
     "pip install without version pinning"),
    
    # ── Hardcoded Secrets ──
    (r'(?:api[_-]?key|token|secret|password)\s*[=:]\s*[\"\'][A-Za-z0-9+/=_-]{20,}',
     "hardcoded_secret", "critical", "credential_exposure",
     "Potential hardcoded API key"),
    (r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----',
     "embedded_private_key", "critical", "credential_exposure",
     "Embedded private key"),
]
```

### Invisible Unicode Detection

```python
INVISIBLE_CHARS = {
    '\u200b',  # Zero Width Space
    '\u200c',  # Zero Width Non-Joiner
    '\u200d',  # Zero Width Joiner
    '\u2060',  # Word Joiner
    '\ufeff',  # Zero Width No-Break Space (BOM)
    '\u202a',  # Left-to-Right Embedding
    '\u202b',  # Right-to-Left Embedding
    '\u202e',  # Right-to-Left Override
    # ... 17 characters in total
}

# Detect invisible characters in skill files
for i, line in enumerate(lines, start=1):
    for char in INVISIBLE_CHARS:
        if char in line:
            findings.append(Finding(
                pattern_id="invisible_unicode",
                severity="high",
                category="injection",
                match=f"U+{ord(char):04X}",
                description="Invisible Unicode character (potential text hiding/injection)",
            ))
```

### Structure Checks

```python
MAX_FILE_COUNT = 50       # Skill should not have 50+ files
MAX_TOTAL_SIZE_KB = 1024  # Total size > 1MB suspicious
MAX_SINGLE_FILE_KB = 256  # Single file > 256KB suspicious

SUSPICIOUS_BINARY_EXTENSIONS = {
    '.exe', '.dll', '.so', '.dylib', '.bin',
    '.msi', '.dmg', '.app', '.deb', '.rpm',
    '.dat', '.com',
}
```

## Layer 2: Trust Level Policies

```python
TRUSTED_REPOS = {"openai/skills", "anthropics/skills"}

INSTALL_POLICY = {
    #               safe      caution    dangerous
    "builtin":     ("allow",  "allow",   "allow"),
    "trusted":     ("allow",  "allow",   "block"),
    "community":   ("allow",  "block",   "block"),
    "agent-created":("allow", "allow",   "ask"),
}

VERDICT_INDEX = {"safe": 0, "caution": 1, "dangerous": 2}
```

### Verdict Logic

```python
def _determine_verdict(findings):
    if not findings:
        return "safe"
    
    has_critical = any(f.severity == "critical" for f in findings)
    has_high = any(f.severity == "high" for f in findings)
    
    if has_critical:
        return "dangerous"
    if has_high:
        return "caution"
    return "safe"  # only medium/low
```

### Installation Decision

| Source | safe | caution | dangerous |
|---|---|---|---|
| builtin | allow | allow | allow |
| trusted (OpenAI/Anthropic) | allow | allow | block |
| community | allow | **block** | block |
| agent-created | allow | allow | **ask** |

## Layer 3: Memory Content Scanning

```python
_MEMORY_THREAT_PATTERNS = [
    # Prompt Injection
    (r'ignore\s+(previous|all|above|prior)\s+instructions', "prompt_injection"),
    (r'you\s+are\s+now\s+', "role_hijack"),
    (r'do\s+not\s+tell\s+the\s+user', "deception_hide"),
    (r'system\s+prompt\s+override', "sys_prompt_override"),
    (r'act\s+as\s+(if|though)\s+.*no\s+(restrictions|limits)', "bypass_restrictions"),
    # Secret Exfiltration
    (r'curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET)', "exfil_curl"),
    (r'cat\s+[^\n]*(\.env|credentials|\.netrc)', "read_secrets"),
    (r'base64\s+(-d|--decode)\s*\|', "base64_decode_pipe"),
    # Persistence Backdoors
    (r'authorized_keys', "ssh_backdoor"),
    (r'\$HOME/\.ssh|\~/\.ssh', "ssh_access"),
    (r'crontab', "persistence_cron"),
    (r'\.(bashrc|zshrc|profile)', "shell_rc_mod"),
]

def _scan_memory_content(content: str) -> Optional[str]:
    """Scans memory content, returns error string if threat found"""
    # Detect invisible Unicode
    for char in _INVISIBLE_CHARS:
        if char in content:
            return f"Blocked: Invisible Unicode character U+{ord(char):04X}"
    
    # Detect threat patterns
    for pattern, pid in _MEMORY_THREAT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return f"Blocked: Matches threat pattern '{pid}'"
    
    return None  # Safe
```

## Layer 4: Context File Injection Scanning

```python
_CONTEXT_THREAT_PATTERNS = [
    (r'ignore\s+(previous|all|above|prior)\s+instructions', "prompt_injection"),
    (r'you\s+are\s+now\s+', "role_hijack"),
    (r'do\s+not\s+tell\s+the\s+user', "deception_hide"),
    (r'system\s+prompt\s+override', "sys_prompt_override"),
    (r'act\s+as\s+(if|though)\s+.*no\s+(restrictions|limits)', "bypass_restrictions"),
    (r'curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET)', "exfil_curl"),
    (r'cat\s+[^\n]*(\.env|credentials)', "read_secrets"),
    (r'<!--[^>]*(?:ignore|override|system|secret|hidden)[^>]*-->', "html_comment_injection"),
    (r'<\s*div\s+style\s*=\s*["\'].*display\s*:\s*none', "hidden_div"),
    (r'base64\s+(-d|--decode)\s*\|', "base64_decode_pipe"),
]

def _scan_context_content(content: str, filename: str) -> str:
    """Scans context files (SOUL.md, AGENTS.md, etc.)"""
    findings = []
    
    # Detect invisible Unicode
    for char in _CONTEXT_INVISIBLE_CHARS:
        if char in content:
            findings.append(f"invisible unicode U+{ord(char):04X}")
    
    # Detect threat patterns
    for pattern, pid in _CONTEXT_THREAT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            findings.append(pid)
    
    if findings:
        logger.warning("Context file %s blocked: %s", filename, ", ".join(findings))
        return f"[BLOCKED: {filename} contained potential prompt injection ({', '.join(findings)}). Content not loaded.]"
    
    return content  # Safe, return original content
```

## Layer 5: Terminal Command Heuristic Detection

```python
_DESTRUCTIVE_PATTERNS = re.compile(
    r"""(?:^|\s|&&|\|\||;|`)(?:
        rm\s|rmdir\s|
        mv\s|
        sed\s+-i|
        truncate\s|
        dd\s|
        shred\s|
        git\s+(?:reset|clean|checkout)\s
    )""",
    re.VERBOSE,
)

_REDIRECT_OVERWRITE = re.compile(r'[^>]>[^>]|^>[^>]')

def _is_destructive_command(cmd: str) -> bool:
    """Heuristic: Does this terminal command look like it modifies/deletes files?"""
    if not cmd:
        return False
    if _DESTRUCTIVE_PATTERNS.search(cmd):
        return True
    if _REDIRECT_OVERWRITE.search(cmd):
        return True
    return False
```

## Security Scan Execution Timing

| Timing | Scanned Content | Scanner |
|---|---|---|
| Skill Creation | Entire skill directory | Skills Guard |
| Skill Editing/Patching | Entire skill directory | Skills Guard |
| Memory Write | Entry content | Memory Scanner |
| Context File Loading | SOUL.md, AGENTS.md, etc. | Context Scanner |
| Skill Installation (Hub) | Entire skill directory | Skills Guard |

## Rollback Mechanism

```python
# Scan after skill creation/editing
scan_error = _security_scan_skill(skill_dir)
if scan_error:
    # Automatically roll back to pre-modification state
    _atomic_write_text(target, original_content)
    return {"success": False, "error": scan_error}
```

## Comparison with Other Agent Frameworks

| Feature | Hermes | Cursor | Claude Desktop |
|---|---|---|---|
| Skill Security Scan | ✅ 100+ patterns | N/A | N/A |
| Trust Level Policy | ✅ 4 levels | N/A | N/A |
| Memory Content Scan | ✅ | N/A | N/A |
| Context File Scan | ✅ | N/A | N/A |
| Unicode Injection Detection | ✅ 17 characters | ❌ | ❌ |
| Automatic Rollback | ✅ | N/A | N/A |
| Destructive Command Detection | ✅ Heuristic | ❌ | ❌ |

## Dangerous Command Approval System (tools/approval.py — 877 lines)

When a terminal command executed by the agent matches a dangerous pattern, the system intercepts it and requires user confirmation.

### Three Approval Modes

```yaml
# config.yaml
approvals:
  mode: smart   # manual | smart | off
```

| Mode | Behavior |
|---|---|
| `manual` | All commands matching dangerous patterns require manual confirmation |
| `smart` | First, use an auxiliary LLM to assess risk. Low-risk commands are auto-approved, high-risk ones prompt the user. |
| `off` (yolo) | Skip all approvals (dangerous, only for trusted environments) |

### Approval Options (CLI Interaction)

After seeing a dangerous command, the user can choose:
-   **once** — Allow this time
-   **session** — Allow similar commands for this session
-   **always** — Allow permanently (writes to config.yaml)
-   **deny** — Deny execution

Timeout (45 seconds) → default to deny (fail-closed).

### Dangerous Pattern Detection

Matching rules cover:
-   Destructive operations: `rm -rf`, `mkfs`, `dd`, `truncate`, etc.
-   Privilege escalation: `sudo`, `su`, `chmod 777`
-   Sensitive file writes: `/etc/`, `~/.ssh/`, `~/.hermes/.env`
-   Network operations: `curl | bash`, port listening
-   Environment variable manipulation: Overriding `PATH`, `LD_PRELOAD`

### Per-session State

Approval status is isolated by session (`contextvars.ContextVar`), ensuring no interference during multi-user concurrency in the gateway. "Session"-level permissions are only valid for the current session and do not persist across sessions.

## Additional Security Layers

-   `tools/tirith_security.py` — Tirith Security Policy Engine (homograph URL, pipe-to-shell, terminal injection)
-   `tools/url_safety.py` — URL Safety Check (SSRF protection: blocks private networks, cloud metadata addresses, validates redirects)
-   `tools/osv_check.py` — Dependency Malware Scan (OSV database)

## Related Pages

-   [[memory-system-architecture]] — Memory Content Security Scanning Mechanism
-   [[skills-system-architecture]] — Security Scanning and Trust Policies during Skill Installation
-   [[prompt-builder-architecture]] — Context File Injection Scanning Protection

## Related Files

-   `tools/skills_guard.py` — Skills Guard Security Scan
-   `tools/memory_tool.py` — Memory Content Scan
-   `agent/prompt_builder.py` — Context File Scan
-   `run_agent.py` — Terminal Command Heuristic Detection
-   `tools/approval.py` — Command Approval (31 patterns)
-   `tools/tirith_security.py` — Tirith Security Policy
-   `tools/url_safety.py` — SSRF Protection
-   `tools/osv_check.py` — Malware Scan