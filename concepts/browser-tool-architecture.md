---
title: Browser Tool Browser Automation Architecture
created: 2026-04-08
updated: 2026-04-08
type: concept
tags: [tool, toolset, architecture, component, browser]
sources: [tools/browser_tool.py, tools/browser_providers/]
---

# Browser Tool — Browser Automation Architecture

## Overview

The Browser Tool, located at `tools/browser_tool.py` (84KB/2202 lines), provides **multi-backend browser automation** capabilities. It supports 4 operating modes, all of which expose identical tool interfaces (navigate/click/type/scroll/vision, etc.) to the Agent.

Core Concept: **Textual page representation based on the accessibility tree (ariaSnapshot)**, enabling LLM Agents to interact with web pages without requiring visual capabilities.

## Architecture Principles

### Multiple Backends

| Backend | Mode | Dependencies | Cost |
|---|---|---|---|
| **Local Chromium** | Default | `agent-browser` CLI + Chromium | Zero Cost |
| **Browser Use** | Cloud | BROWSER_USE_API_KEY or Nous managed | Pay-as-you-go |
| **Browserbase** | Cloud | BROWSERBASE_API_KEY + PROJECT_ID | Pay-as-you-go |
| **Firecrawl** | Cloud | FIRECRAWL_API_KEY | Pay-as-you-go |
| **Camofox** | Anti-detection | CAMOFOX_URL environment variable | Self-hosted/Paid |
| **CDP Override** | Direct Connection | BROWSER_CDP_URL | Existing browser instance |

### Backend Resolution Chain

```python
def _get_cloud_provider():
    """Resolution priority:
    1. config.yaml browser.cloud_provider (explicitly specified)
    2. Browser Use (managed Nous gateway or direct API key)
    3. Browserbase (direct credentials)
    4. None → Local mode
    """
```

**Key Design**: If `cloud_provider` is set to `local`, cloud fallback is completely disabled, forcing the use of local Chromium.

## Core Components

### 1. Unified Provider Interface

```python
class CloudBrowserProvider:
    """Abstract base class for all cloud browser providers"""
    def is_configured() -> bool
    def create_session(task_id) -> Dict  # Returns {session_name, cdp_url, features}
    def close_session(session_id) -> None
    def provider_name() -> str

# Concrete implementations
class BrowserbaseProvider(CloudBrowserProvider)
class BrowserUseProvider(CloudBrowserProvider)
class FirecrawlProvider(CloudBrowserProvider)
```

**Advantages**: Adding a new backend only requires implementing 4 methods; the tool logic remains entirely unchanged.

### 2. Session Management (Thread-Safe)

```python
_active_sessions: Dict[str, Dict[str, str]] = {}  # task_id → session_info
_session_last_activity: Dict[str, float] = {}     # task_id → timestamp
_cleanup_lock = threading.Lock()
```

**Design Details**:
- Each `task_id` has an independent session, supporting parallel browser operations by sub-agents.
- Double-checked locking pattern: network calls are executed outside the lock to prevent holding the lock from blocking other threads.
- Race condition protection: `_active_sessions` is re-checked after network calls complete to prevent duplicate session creation.

### 3. Command Execution Architecture

```python
def _run_browser_command(task_id, command, args, timeout):
    # 1. Locate the agent-browser CLI
    # 2. Get session information (create/reuse)
    # 3. Construct command: --cdp <websocket> (cloud) or --session <name> (local)
    # 4. Capture stdout/stderr using temporary files (not pipes)
    # 5. Parse JSON output
```

**Key Decision — Temporary Files Instead of Pipes**:

`agent-browser` starts a background daemon process, and the daemon inherits file descriptors. If `capture_output=True` (pipes) is used, the daemon keeps the pipe's file descriptor open, causing `communicate()` to wait indefinitely for EOF and time out.

Solution: Use `os.open()` to create temporary files, close the file descriptor immediately after execution, preventing the daemon from blocking reads.

### 4. Concurrency Safety — Independent Socket Directory

```python
task_socket_dir = os.path.join(
    tempfile.gettempdir(),
    f"agent-browser-{session_name}"
)
os.makedirs(task_socket_dir, mode=0o700, exist_ok=True)
browser_env["AGENT_BROWSER_SOCKET_DIR"] = task_socket_dir
```

**Problem**: Parallel sub-agents share the default socket path, leading to "Failed to create socket directory: Permission denied".

**Solution**: Each `task_id` gets an independent socket directory, with 0o700 permissions to ensure isolation.

### 5. macOS Unix Socket Path Fix

```python
def _socket_safe_tmpdir():
    """macOS TMPDIR=/var/folders/xx/.../T/ (~51 chars)
    Appending agent-browser-hermes_... exceeds the 104-byte AF_UNIX limit
    → macOS forces the use of /tmp"""
    if sys.platform == "darwin":
        return "/tmp"
    return tempfile.gettempdir()
```

## Security Design

### Three-Layer Security Protection

| Layer | Protection | Implementation |
|---|---|---|
| **URL Injection Protection** | Prevents embedding API Keys in URLs | `_PREFIX_RE` detects prefixes like sk-ant- |
| **SSRF Protection** | Prevents access to private/internal addresses | `_is_safe_url()` detects 10.x/192.168.x/localhost |
| **Website Policy** | Blacklisted domain interception | `check_website_access(url)` |
| **Post-redirect Check** | Prevents redirection to internal addresses | Checks final_url after navigation |
| **Key Redaction** | Redacts sensitive keys before sending snapshots to auxiliary LLMs | `redact_sensitive_text()` |

**Important**: SSRF protection is only enabled for cloud backends. Local backends (Camofox/Local Chromium) skip this check because the Agent already has full local network access via terminal tools.

### Bot Detection Warning

```python
blocked_patterns = ["access denied", "bot detected", "cloudflare", 
                    "captcha", "just a moment", "checking your browser"]
if any(pattern in title_lower for pattern in blocked_patterns):
    response["bot_detection_warning"] = "..."
```

When the page title returned after navigation contains bot detection keywords, a warning is proactively issued, and solutions are suggested (delay operations/enable incognito mode/change site).

## Toolset (10 Tools)

| Tool | Functionality |
|---|---|
| `browser_navigate` | Navigates to a URL, automatically returns a compact snapshot |
| `browser_snapshot` | Retrieves an accessibility tree snapshot of the page |
| `browser_click` | Clicks the element identified by its ref (e.g., @e1, @e5) |
| `browser_type` | Types text into an input field |
| `browser_scroll` | Scrolls up/down (repeated 5 times to ensure effective movement) |
| `browser_back` | Navigates back in browser history |
| `browser_press` | Presses a key (Enter/Tab/Escape, etc.) |
| `browser_console` | Retrieves console output and JavaScript errors |
| `browser_get_images` | Extracts image URLs and alt text from the page |
| `browser_vision` | Takes a screenshot + performs visual AI analysis |

### Automatic Snapshot Optimization

After successful `browser_navigate`, a **compact snapshot is automatically retrieved**, eliminating the need for the model to explicitly call `browser_snapshot`. This reduces one API round trip.

### Vision Tool

```python
def browser_vision(question, annotate=False):
    # 1. Takes a screenshot (supports --annotate for overlaying element labels)
    # 2. Base64 encodes the image
    # 3. Calls the vision model via call_llm(task="vision")
    # 4. Returns analysis results + screenshot path
    # 5. If failed, preserves the screenshot file for user inspection
```

**Graceful Degradation**: If the screenshot is successful but visual analysis fails, the screenshot file is preserved, and the user is informed that it can be viewed via `MEDIA:<path>`.

### JavaScript Evaluation

`browser_console(expression="...")` executes JavaScript in the page context, equivalent to the DevTools Console:

```javascript
// Example: Get page title
document.title

// Example: Count links
document.querySelectorAll("a").length
```

## Lifecycle Management

### Background Cleanup Thread

```python
BROWSER_SESSION_INACTIVITY_TIMEOUT = 300  # 5 minutes of inactivity

def _browser_cleanup_thread_worker():
    """Checks every 30 seconds to clean up sessions inactive for more than 5 minutes"""
    while _cleanup_running:
        _cleanup_inactive_browser_sessions()
        time.sleep(30)
```

**Design Considerations**: The timeout is set to 5 minutes to allow sufficient time for LLM inference (especially when sub-agents perform multi-step browser tasks).

### Emergency Cleanup

```python
atexit.register(_emergency_cleanup_all_sessions)  # On process exit
```

**Only using `atexit`, not hijacking SIGINT/SIGTERM**: Earlier versions installed signal handlers that called `sys.exit()`, but this conflicted with `prompt_toolkit`'s asynchronous event loop, preventing the process from being killed.

### Automatic Recording

```yaml
# config.yaml
browser:
  record_sessions: true
```

Recording automatically starts on first navigation, and a `.webm` file is saved when the session closes. Recordings older than 72 hours are automatically cleaned up.

## Design Advantages

### Comparison with Traditional Selenium/Playwright Solutions

| Dimension | Traditional Solutions | Hermes Browser Tool |
|---|---|---|
| Page Representation | HTML/DOM (difficult for LLM to understand) | Accessibility tree (structured text) |
| Element Location | XPath/CSS selectors | Ref ID (e.g., @e1, @e5) |
| Multi-Backend | Requires code rewrite | Unified interface, automatic backend selection |
| Security | No built-in protection | SSRF + Injection + Policy (three-layer protection) |
| Concurrency | Requires manual management | `task_id` automatic isolation |
| Cleanup | Prone to leaks | Background thread + `atexit` dual guarantee |
| Vision | Requires additional integration | Built-in vision tool |

### Advantages of Accessibility Tree

Traditional HTML snapshots contain a lot of style and structural noise. The accessibility tree only preserves:
- Interactive elements (buttons, links, input fields)
- Semantic roles (heading, button, link, textbox)
- Visible text content
- Element relationships

This enables LLMs to understand page structure and make operational decisions with fewer tokens.

## Configuration and Operation

### Local Mode (Zero Cost)

```bash
# Install agent-browser
npm install -g agent-browser
agent-browser install --with-deps  # Download Chromium + system libraries
```

### Cloud Mode

```yaml
# config.yaml
browser:
  cloud_provider: browser-use  # or browserbase, firecrawl, local
  allow_private_urls: false    # SSRF protection (enabled by default)
  command_timeout: 30          # Command timeout (seconds)
  record_sessions: false       # Automatic recording
```

### CDP Direct Connection Mode

```bash
export BROWSER_CDP_URL="ws://localhost:9222/devtools/browser/xxx"
# Or HTTP discovery endpoint
export BROWSER_CDP_URL="http://localhost:9222"
```

### Camofox Anti-detection Mode

```bash
export CAMOFOX_URL="http://camofox-server:8080"
```

Once set, all browser operations are routed through the Camofox REST API.

## Relationship with Other Systems

- [[auxiliary-client-architecture]] — `browser_vision` calls the visual model via `call_llm(task="vision")`
- [[tool-registry-architecture]] — The 10 browser tools are registered via `registry.register()`
- [[web-tools-architecture]] — Documentation suggests prioritizing `web_search`/`web_extract` for simple information retrieval
- [[security-defense-system]] — Browser tool's SSRF and injection protection are part of the overall security system
