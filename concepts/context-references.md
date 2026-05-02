---
title: Context References (@ Reference System)
created: 2026-04-10
updated: 2026-04-10
type: concept
tags: [context, references, input, architecture]
sources: [agent/context_references.py, cli.py]
---

# Context References (@ Reference System)

## Overview

Hermes supports referencing external content using the `@` prefix in user input. The system automatically expands these references into their actual content and injects them into the message before sending it to the LLM.

## Supported Reference Types

| Syntax | Purpose | Example |
|---|---|---|
| `@file:path` | Inject file content | `@file:src/main.py` |
| `@file:path:line_numbers` | Inject specific lines from a file | `@file:main.py:10-50` |
| `@folder:path` | Inject directory structure | `@folder:src/` |
| `@diff` | Inject current git diff | `Check @diff for any issues` |
| `@staged` | Inject git staged changes | `Review the code in @staged` |
| `@url:address` | Fetch and inject web page content | `@url:https://example.com` |
| `@git:reference` | Inject git object content | `@git:HEAD~1` |

## Processing Flow

```text
User Input: "Help me check @file:main.py and @diff for any issues"
    ↓
parse_context_references() — Regex matches all @ references
    ↓
_expand_reference() — Expands each reference into actual content
    ↓
Security Checks:
  - Path must be within cwd or allowed_root (prevents path traversal)
  - Rejects sensitive files (.ssh/*, .env, .netrc, etc.)
  - Total injected content does not exceed 50% of context window (hard limit); warns if over 25%
    ↓
Injects into the "--- Attached Context ---" block at the end of the message
    ↓
Sends to LLM (@ reference markers are removed from the original text)
```

## Security Mechanisms

**Sensitive File Interception**: The following paths will be rejected for injection:
- `~/.ssh/*` (Keys, config)
- `~/.bashrc`, `~/.zshrc`, `~/.profile` (Shell configuration)
- `~/.netrc`, `~/.pgpass`, `~/.npmrc`, `~/.pypirc` (Credential files)
- `skills/.hub/` (Internal skill repository files)

**Injection Volume Limits**:
- Hard limit: Injected content must not exceed **50%** of the model's context window
- Soft limit: A warning is printed when exceeding **25%**
- The entire reference operation is rejected if the hard limit is exceeded (`blocked=True`)

**Path Security**: After reference paths are resolved to absolute paths, they must be within the `cwd` or `allowed_root` scope to prevent path traversal attacks like `@file:../../etc/passwd`.

## Distinction from Context Files

| | Context References (@ References) | Context Files (e.g., AGENTS.md) |
|---|---|---|
| Trigger Method | User explicitly writes `@` in input | System automatically loads |
| Injection Location | End of user message | System prompt |
| Content Source | File/Diff/URL/Git | Fixed filenames |
| Lifecycle | Single turn | Entire session |

## Related Pages

- [[prompt-builder-architecture]] — Loading mechanism for Context Files (e.g., AGENTS.md)
- [[security-defense-system]] — Security check system

## Key Source Files

| File | Responsibility |
|---|---|
| `agent/context_references.py` | Reference parsing, expansion, and security checks |
| `cli.py` | Entry point for calling `preprocess_context_references()` |