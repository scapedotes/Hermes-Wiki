# Wiki Log

> A chronological record of all wiki operations. Append-only, no modifications.
> Format: `## [YYYY-MM-DD] action | subject`
> Actions: ingest, update, query, lint, create, archive, delete
> When this file exceeds 500 entries, rotate: rename to log-YYYY.md and restart.

## [2026-04-07] create | Wiki initialized
- Domain: Hermes Agent — Skills System and Memory
- Structure created with SCHEMA.md, index.md, log.md
- Directory structure: raw/{articles,papers,transcripts,assets}, entities, concepts, comparisons, queries

## [2026-04-07] create | Bulk creation of 8 wiki pages
Based on an in-depth analysis of the hermes-agent codebase (814 files):

**Concept Pages (6):**
- skills-system-architecture — Progressive Disclosure Architecture
- memory-system-architecture — Frozen Snapshot Mode
- agent-loop-and-prompt-assembly — Agent Loop and Prompt Assembly
- skills-and-memory-interaction — Complementary Relationship between Skills and Memory
- toolsets-system — Tool Grouping System
- session-search-and-sessiondb — FTS5 Cross-Session Search
- messaging-gateway-architecture — Unified Gateway for 14+ Platforms
- context-compression — Context Compression

**Entity Pages (2):**
- aiagent-class — AIAgent Core Class
- memorystore-class — MemoryStore Core Class

## [2026-04-08] create | 16 Thematic System Analyses
Based on in-depth source code analysis, 16 topics completed:

**Core Architecture (6):**
- skills-system-architecture — Progressive Disclosure Architecture
- memory-system-architecture — Frozen Snapshot Mode
- agent-loop-and-prompt-assembly — Agent Loop and Prompt Assembly
- skills-and-memory-interaction — Complementary Relationship between Skills and Memory
- toolsets-system — Tool Grouping System
- session-search-and-sessiondb — FTS5 Cross-Session Search

**Performance and Optimization (5):**
- parallel-tool-execution — Intelligent Concurrent Safety Detection
- prompt-caching-optimization — Anthropic Caching Strategy
- fuzzy-matching-engine — 8-Strategy Chain Fuzzy Matching
- model-metadata-and-routing — Model Metadata Caching
- large-tool-result-handling — Large Result Handling

**Security and Reliability (4):**
- security-defense-system — 5-Layer Defense System
- interrupt-and-fault-tolerance — Interrupt Propagation and Fault Tolerance
- credential-pool-and-isolation — Credential Pool and Isolation
- iteration-budget-and-delegation — Iteration Budget and Delegation

**Platform and Extension (7):**
- cli-architecture — CLI Architecture
- gateway-multi-platform — Multi-Platform Gateway
- configuration-and-profiles — Configuration and Profiles
- mcp-and-plugins — MCP and Plugins
- terminal-backends — Terminal Backends
- cron-scheduling — Cron Scheduling
- trajectory-and-data-generation — Trajectory and Data Generation

- index.md updated to 24 pages, organized by category
- SCHEMA.md defines a complete tag taxonomy

## [2026-04-08] update | Tool Registry System wiki page created
- File: concepts/tool-registry-architecture.md
- Source: tools/registry.py (10KB/275 lines)
- Core content: Central tool registry system, declarative registration + centralized scheduling, circular import safe design, `__slots__` memory optimization, MCP dynamic unregistration support
- Cron job created: Hermes Wiki Topic Writing (one per hour), 8 repetitions
- index.md updated to 25 pages

## [2026-04-08] update | Auxiliary Client wiki page created
- File: concepts/auxiliary-client-architecture.md
- Source: agent/auxiliary_client.py (85KB/2127 lines)
- Core content: Auxiliary LLM client router, multi-provider resolution chain (8-level fallback), adapter pattern (Codex/Anthropic unified to chat.completions interface), client caching + event loop safety, automatic fallback on payment/quota exhaustion, task-level independent configuration
- index.md updated to 26 pages

## [2026-04-08] update | Browser Tool automation wiki page created
- File: concepts/browser-tool-architecture.md
- Source: tools/browser_tool.py (84KB/2202 lines)
- Core content: Multi-backend browser automation (local/Cloud/CDP/Camofox), accessibility tree text-based page representation, three-layer security protection (SSRF/injection/policy), concurrent session isolation (independent socket directory), background cleanup thread + atexit dual guarantee
- index.md updated to 27 pages

## [2026-04-08] update | Web Tools search/extraction wiki page created
- File: concepts/web-tools-architecture.md
- Source: tools/web_tools.py (85KB/2099 lines)
- Core content: Multi-backend search/extraction/crawling (Firecrawl/Exa/Parallel/Tavily), LLM intelligent content compression (single-pass + chunked parallel + synthesis), Firecrawl dual-path architecture (direct API + Nous Gateway), four-layer security protection, standardization layer for unified output format
- index.md updated to 28 pages

## [2026-04-08] update | Dual topic wiki pages created (Prompt Builder + Context Compressor)
- File: concepts/prompt-builder-architecture.md
  - Source: agent/prompt_builder.py (40KB/959 lines)
  - Core content: Modular assembly of system prompts, context file injection protection (10 threat patterns + 11 invisible Unicode characters), skill index caching + snapshot persistence, platform prompt adaptation, model-specific execution guidance
- File: concepts/context-compressor-architecture.md
  - Source: agent/context_compressor.py (30KB/696 lines)
  - Core content: Automatic context compression, structured summary templates (Goal/Progress/Decisions/Files/Next Steps), iterative updates, tool output pruning, integrity assurance for tool calls, failure cooling
- index.md updated to 30 pages

## [2026-04-08] update | Final 2 topic wiki pages created (Model Tools + Gateway Session)
- File: concepts/model-tools-dispatch.md
  - Source: model_tools.py (22KB/577 lines, refactored from 2400 lines)
  - Core content: Tool orchestration and scheduling, asynchronous bridging of three paths, dynamic schema adjustment (execute_code/browser_navigate), parameter type enforcement, Agent-level tool interception, three-layer tool discovery mechanism
- File: concepts/gateway-session-management.md
  - Source: gateway/session.py (41KB/1081 lines)
  - Core content: Multi-platform session management, unified SessionSource abstraction, SessionKey construction rules, PII anonymization (Discord exception), dynamic system prompt injection, dual storage strategy (SQLite+JSON), atomic saving, session reset policy
- index.md updated to 32 pages

## [2026-04-08] update | Multi-Agent System wiki page created
- File: concepts/multi-agent-architecture.md
- Source: tools/delegate_tool.py (40KB/978 lines), batch_runner.py (54KB/1285 lines), tools/send_message_tool.py (39KB/952 lines)
- Core content: Layered sub-agent delegation (single task / up to 3 in parallel), security sandbox (5 types of prohibited tools + depth limits), credential inheritance and pool sharing, ACP heterogeneous Agent orchestration, batch processing engine, cross-platform message delivery
- index.md updated to 35 pages

## [2026-04-08] update | Three topic wiki pages created (Prompt Caching + Smart Model Routing + Hook System)
- File: concepts/prompt-caching-optimization.md (updated)
  - Source: agent/prompt_caching.py (2KB/72 lines)
  - Core content: Anthropic `system_and_3` caching strategy, 4-breakpoint rolling window, pure function design
- File: concepts/smart-model-routing.md
  - Source: agent/model_metadata.py (36KB/941 lines), agent/models_dev.py (25KB/781 lines), hermes_cli/model_switch.py (32KB/927 lines)
  - Core content: 10-level context length resolution chain, `models.dev` 4000+ model database, local server auto-detection (4 types), alias system, token estimation
- File: concepts/hook-system-architecture.md
  - Source: gateway/hooks.py (170 lines), hermes_cli/plugins.py (609 lines)
  - Core content: Gateway Hooks event-driven (8 event types + wildcards), Plugin System three-level sources (user/project/pip), PluginContext API (tool registration/message injection/CLI commands/hooks), cache-friendly context injection
- index.md updated to 37 pages