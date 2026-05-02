---
title: Web Tools Search/Extraction Architecture
created: 2026-04-08
updated: 2026-04-08
type: concept
tags: [tool, toolset, architecture, component]
sources: [tools/web_tools.py]
---

# Web Tools — Search/Extraction Architecture

## Overview

Web Tools, located at `tools/web_tools.py` (88KB/2099 lines), provides **multi-backend web search/extraction/crawling** capabilities. It supports 4 backend providers, all exposing the same `web_search`, `web_extract`, `web_crawl` tool interfaces to the Agent.

Core philosophy: **Content acquisition takes precedence over browser automation** — use `web_search`/`web_extract` for simple information retrieval (faster, cheaper), and only resort to browser tools when interaction is required.

## Architectural Principles

### The Four Backends

| Backend | Search | Extract | Crawl | Authentication |
|---|---|---|---|---|
| **Firecrawl** | ✅ | ✅ | ✅ | API Key or Nous Gateway |
| **Exa** | ✅ | ✅ | ❌ | EXA_API_KEY |
| **Parallel** | ✅ | ✅ | ❌ | PARALLEL_API_KEY |
| **Tavily** | ✅ | ✅ | ✅ | TAVILY_API_KEY |

### Backend Selection Chain

```python
def _get_backend():
    """Resolution priority:
    1. config.yaml web.backend (explicitly specified: parallel/firecrawl/tavily/exa)
    2. FIRECRAWL_API_KEY / FIRECRAWL_API_URL / tool-gateway
    3. PARALLEL_API_KEY
    4. TAVILY_API_KEY
    5. EXA_API_KEY
    6. Default: firecrawl (for backward compatibility)
    """
```

### Firecrawl Dual-Path Architecture

Firecrawl is the default backend and supports two connection modes:

| Mode | Path | Applicability |
|---|---|---|
| **Direct Mode** | `FIRECRAWL_API_KEY` / `FIRECRAWL_API_URL` | All Users |
| **Managed Gateway** | Nous-hosted tool-gateway | Nous Subscribers |

```python
def _get_firecrawl_client():
    """Priority:
    1. Direct Firecrawl Configuration (api_key + api_url)
    2. Nous Managed Gateway (nous_user_token + gateway_origin)
    """
    # Client cache — reuse the same instance if configuration remains unchanged
    if _firecrawl_client is not None and _firecrawl_client_config == client_config:
        return _firecrawl_client
```

**Advantage**: Nous subscribers do not need to purchase Firecrawl separately; they gain shared access via the tool-gateway.

## Core Components

### 1. web_search_tool — Web Search

```python
def web_search_tool(query: str, limit: int = 5) -> str:
    """
    Backend routing:
    - parallel → _parallel_search() [Supports agentic/fast/one-shot modes]
    - exa → _exa_search() [Supports highlights extraction]
    - tavily → _tavily_request("search")
    - firecrawl → client.search()
    """
```

Returns a unified format: `{"success": true, "data": {"web": [{"title", "url", "description", "position"}]}}`

### 2. web_extract_tool — URL Content Extraction

```python
async def web_extract_tool(
    urls: List[str],
    format: str = "markdown",      # markdown or html
    use_llm_processing: bool = True,
    model: Optional[str] = None,
    min_length: int = 5000         # minimum length to trigger LLM processing
) -> str:
```

**Core Workflow**:
1. Security checks (key injection + SSRF + website policy)
2. Backend extraction (Firecrawl scrape / Exa get_contents / Parallel extract / Tavily extract)
3. LLM intelligent compression (`process_content_with_llm`)
4. Output trimming (only retains url/title/content/error)

### 3. web_crawl_tool — Website Crawling

```python
async def web_crawl_tool(
    url: str,
    instructions: str = None,    # Extraction instructions (Tavily only)
    depth: str = "basic",        # basic or advanced
    use_llm_processing: bool = True
) -> str:
```

Currently, only Firecrawl and Tavily support crawling. Parallel does not have a crawl API.

## LLM Content Processing Engine

This is the most innovative part of Web Tools — automatically compressing web content with LLMs.

### Processing Strategy

```python
def process_content_with_llm(content, url, title, model, min_length):
    """
    Content tiered processing:
    < 5000 chars → Skip processing, return original content directly
    5000 ~ 500K chars → Single LLM summary
    500K ~ 2M chars → Chunked processing + synthesis
    > 2M chars → Refuse to process
    """
```

### Chunked Processing

```python
async def _process_large_content_chunked(content, chunk_size=100K):
    # 1. Split content into 100K char chunks
    # 2. Summarize each chunk in parallel (asyncio.gather)
    # 3. Synthesize all chunk summaries into a unified summary
    # 4. Hard limit: Final output ≤ 5000 chars
```

**Design Highlights**:
- Each chunk uses a **dedicated prompt** ("This is a section of a large document, do not write introductions or conclusions")
- Processes all chunks in parallel, no sequential waiting
- The synthesis step **removes redundancy** and integrates into a coherent summary
- If synthesis fails, **fall back to concatenating all chunk summaries**

### Compression Ratio

Typical compression ratio: 10-50x (original content → LLM summary)

```
Original: 50,000 chars → Processed: 2,000 chars (4%)
Original: 200,000 chars → Processed: 4,500 chars (2.25%)
```

## Security Design

### Four Layers of Protection

| Layer | Protection | Implementation |
|---|---|---|
| **URL Key Injection** | Prevents embedding API Keys in URLs | `_PREFIX_RE` detection |
| **SSRF Protection** | Prevents access to private addresses | `is_safe_url()` |
| **Website Policy** | Blacklisted domain interception | `check_website_access()` |
| **Redirection Check** | Prevents redirection to internal addresses | Checks `sourceURL` after extraction |

### Base64 Image Cleanup

```python
def clean_base64_images(text: str) -> str:
    """Removes base64 encoded images, replaces with [BASE64_IMAGE_REMOVED]"""
    # Prevents large amounts of base64 data from occupying the context window
```

## Standardization Layer

Different backends return different data formats. Web Tools unifies output through **standardization functions**:

```python
_extract_web_search_results(response)    # Firecrawl multi-format extraction
_normalize_tavily_search_results(raw)    # Tavily → Standard format
_normalize_tavily_documents(raw)         # Tavily extract/crawl → Standard format
_to_plain_object(value)                  # SDK object → Python dict
_normalize_result_list(values)           # Mixed SDK/list → dict list
```

**Advantage**: The Agent always receives data in a unified format, eliminating the need for different parsing based on backend type.

## Debug Mode

```bash
export WEB_TOOLS_DEBUG=true
```

When enabled, it automatically logs:
- All tool calls and parameters
- Raw API responses
- LLM compression metrics (original size / processed size / compression ratio)
- Final processing results

Logs are saved to: `~/.hermes/logs/web_tools_debug_UUID.json`

## Design Advantages

### Compared to Direct API Calls

| Dimension | Direct API Calls | Web Tools |
|---|---|---|
| Backend Switching | Requires code changes | `config.yaml` one-click switching |
| Content Compression | Manual processing | Automatic LLM summarization |
| Large Content Handling | Prone to context overflow | Chunking + synthesis |
| Security Protection | Requires self-implementation | SSRF + Injection + Policy three-layer protection |
| Format Unification | Each API has a different format | Unified output format |
| Debugging | Requires manual printing | Built-in Debug mode |

### Advantages of LLM Processing

Without LLM processing, the Agent receives the full original HTML/markdown text (potentially hundreds of thousands of characters). With LLM processing:
- **Context Saving**: 10-50x compression
- **Increased Information Density**: Only key facts and data are retained
- **Unified Format**: All pages are structured Markdown summaries
- **Graceful Degradation**: Falls back to truncated original content if LLM processing fails

## Configuration and Operation

### Selecting a Backend

```yaml
# config.yaml
web:
  backend: firecrawl  # or exa, parallel, tavily
```

### Environment Variables

```bash
# Firecrawl Direct Mode
export FIRECRAWL_API_KEY=fc-xxx
export FIRECRAWL_API_URL=https://your-self-hosted.com  # Optional

# Exa
export EXA_API_KEY=exa-xxx

# Parallel
export PARALLEL_API_KEY=par-xxx

# Tavily
export TAVILY_API_KEY=tav-xxx

# LLM Processing Configuration
export AUXILIARY_WEB_EXTRACT_MODEL=google/gemini-3-flash-preview
```

### Disabling LLM Processing

```python
# Fast extraction, no compression needed
content = await web_extract_tool(["https://example.com"], use_llm_processing=False)
```

## Relationship with Other Systems

- [[auxiliary-client-architecture]] — LLM content processing is invoked via `async_call_llm(task="web_extract")`
- [[tool-registry-architecture]] — `web_search`/`web_extract` are registered via the registry
- [[browser-tool-architecture]] — Documentation suggests prioritizing `web_tools` for simple information retrieval
- [[context-compressor-architecture]] — Similar LLM compression principles applied to different scenarios
