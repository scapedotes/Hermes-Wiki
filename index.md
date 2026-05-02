# Wiki Index

> Table of Contents. Each wiki page is listed by type, with a one-line summary.
> Consult this file to locate relevant pages before performing a query.
> Last updated: 2026-04-08 | Total pages: 33

## Entities

- [[aiagent-class]] — Core conversational loop class, managing LLM interactions and tool calls
- [[memorystore-class]] — Core memory system class, managing MEMORY.md and USER.md

## Concepts

### Core Architecture
- [[tool-registry-architecture]] — Centralized Tool Registry System, featuring declarative registration, centralized dispatch, and circular import safety
- [[auxiliary-client-architecture]] — Auxiliary LLM Client Router, with multi-provider resolution chain, adapter pattern, and automatic fallback
- [[browser-tool-architecture]] — Multi-backend Browser Automation, featuring accessibility tree text representation, three-layer security protection, and concurrent isolation
- [[web-tools-architecture]] — Multi-backend Search/Extraction/Crawling, with LLM-driven intelligent content compression (chunking + synthesis) and four-layer security protection
- [[skills-system-architecture]] — Progressive Disclosure Architecture, covering skill discovery, conditional activation, and key management
- [[memory-system-architecture]] — Frozen snapshot mode, atomic writes, and security scanning
- [[agent-loop-and-prompt-assembly]] — Agent loop, system prompt construction, platform prompts, and execution guidance
- [[skills-and-memory-interaction]] — Complementary relationship and decision tree of Skills and Memory
- [[toolsets-system]] — Toolset Grouping System, recursive parsing, and 14+ platform toolsets
- [[session-search-and-sessiondb]] — Cross-session recall via FTS5 search and LLM summarization

### Performance and Optimization
- [[parallel-tool-execution]] — Intelligent concurrent safety detection, with three-layer classification and path conflict detection
- [[prompt-caching-optimization]] — Anthropic `system_and_3` caching strategy, yielding 75% cost savings
- [[fuzzy-matching-engine]] — 8-strategy chain fuzzy matching, ranging from exact to similarity matching
- [[smart-model-routing]] — Smart Model Routing, featuring a 10-level context length resolution chain and local server auto-detection
- [[large-tool-result-handling]] — Large result externalization, pre-flight compression, and Surrogate cleanup

### Security and Reliability
- [[security-defense-system]] — 5-layer defense system with 100+ threat pattern detections
- [[interrupt-and-fault-tolerance]] — Interrupt propagation, credential pool rotation, and Fallback model chain
- [[credential-pool-and-isolation]] — Multi-key automatic rotation and Profile isolation
- [[multi-agent-architecture]] — Multi-Agent Architecture, featuring sub-agent delegation, batch processing, and cross-platform communication

### Platform and Extension
- [[cli-architecture]] — CLI Architecture, slash command completion, and Skin engine
- [[configuration-and-profiles]] — Hierarchical configuration, Profile isolation, and automatic migration
- [[hook-system-architecture]] — Hook System (Gateway Hooks + Plugin System), featuring event-driven architecture, tool registration, and context injection
- [[mcp-and-plugins]] — MCP Integration, plugin hook system, and OAuth support
- [[terminal-backends]] — 6 Terminal Backends, environment abstraction, and persistent Shell
- [[cron-scheduling]] — Built-in scheduler, natural language scheduling, and multi-platform delivery
- [[trajectory-and-data-generation]] — Trajectory saving, batch runner, and RL training environment
- [[prompt-builder-architecture]] — Modular assembly of system prompts, incorporating injection protection, skill caching, and model-specific guidance
- [[context-compressor-architecture]] — Automatic context compression, with structured summarization, iterative updates, and tool integrity assurance
- [[model-tools-dispatch]] — Tool orchestration and dispatch, featuring asynchronous bridging, dynamic schema adjustment, and parameter type enforcement
- [[gateway-session-management]] — Gateway Session Management, offering multi-platform session isolation, PII anonymization, and reset policies
- [[messaging-gateway-architecture]] — Messaging Gateway Architecture, platform adapters, and DM pairing