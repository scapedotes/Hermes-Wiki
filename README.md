# Hermes Agent Architecture Wiki

<p align="center">
  <img src="https://img.shields.io/badge/Wiki-Hermes_Agent-blue?style=for-the-badge&logo=markdown" alt="Wiki" height="28">
  <img src="https://img.shields.io/badge/Source-hermes--agent-green?style=for-the-badge&logo=github" alt="Source" height="28">
  <img src="https://img.shields.io/badge/Knowledge_Base-37_pages-orange?style=for-the-badge&logo=obsidian" alt="Knowledge Base" height="28">
  <img src="https://img.shields.io/badge/Version-v2026.4.23-purple?style=for-the-badge" alt="Version" height="28">
  <img src="https://img.shields.io/badge/Verified-Source_Code-brightgreen?style=for-the-badge" alt="Verified" height="28">
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="License" height="28">
</p>

> In-depth architectural documentation based on the Nous Research [Hermes Agent](https://github.com/NousResearch/hermes-agent) source code.
> All pages have been **verified line-by-line against the source code** to ensure accuracy and timeliness.

---

## Table of Contents
### Core Architecture

[![Run on Google Cloud](https://deploy.cloud.google.com/networks/cloud-run/button.svg)](https://deploy.cloud.google.com/apps?repo=https://github.com/scapedotes/Hermes-Wiki&directory=translation-pipeline)

- [agent-loop-and-prompt-assembly](concepts/agent-loop-and-prompt-assembly.md): Agent Loop, System Prompt Construction, Platform Prompts, Execution Guidance
- [tool-registry-architecture](concepts/tool-registry-architecture.md): Centralized Tool Registry System, Declarative Registration + Centralized Scheduling
- [model-tools-dispatch](concepts/model-tools-dispatch.md): Tool Orchestration and Dispatch, Asynchronous Bridging + Dynamic Schema Adjustment + Parameter Type Enforcement
- [toolsets-system](concepts/toolsets-system.md): Toolset Grouping System, Recursive Parsing, 14+ Platform Toolsets
- [prompt-builder-architecture](concepts/prompt-builder-architecture.md): Modular System Prompt Assembly, Injection Protection + Skill Caching + Model-Specific Guidance
- [auxiliary-client-architecture](concepts/auxiliary-client-architecture.md): Auxiliary LLM Client Router, Multi-Provider Resolution Chain + Automatic Fallback
- [provider-transport-architecture](concepts/provider-transport-architecture.md): Provider Transport ABC, Unified Abstraction for Data Paths of Anthropic/Chat Completions/Responses API/Bedrock

### Memory and Session

- [memory-system-architecture](concepts/memory-system-architecture.md): Three-Layer Architecture (MemoryStore/MemoryManager/MemoryProvider), Frozen Snapshot Mode
- [session-search-and-sessiondb](concepts/session-search-and-sessiondb.md): FTS5 Search + LLM Summarization for Cross-Session Recall, Orphan Deletion Strategy
- [context-compressor-architecture](concepts/context-compressor-architecture.md): Automatic Context Compression v3, Three-Stage Preprocessing (MD5 Deduplication/Smart Collapse/Parameter Truncation) + Structured Summarization + OpenClaw Comparison
- [skills-and-memory-interaction](concepts/skills-and-memory-interaction.md): Complementary Relationship and Decision Tree of Skills and Memory
- [skills-system-architecture](concepts/skills-system-architecture.md): Progressive Disclosure Architecture, Skill Discovery, Conditional Activation, Key Management, Plugin Namespace Skills, Curator Background Maintenance

### Tools and Capabilities

- [browser-tool-architecture](concepts/browser-tool-architecture.md): Multi-Backend Browser Automation, Accessibility Tree + Three-Layer Security Protection
- [web-tools-architecture](concepts/web-tools-architecture.md): Multi-Backend Search/Extraction/Crawling, LLM Intelligent Content Compression
- [code-execution-sandbox](concepts/code-execution-sandbox.md): execute_code Sandbox, 7 Tool Restrictions + UDS/File RPC Communication Modes
- [voice-mode-architecture](concepts/voice-mode-architecture.md): Push-to-talk Voice Interaction, STT (3 Providers) + TTS (5 Providers, including Gemini/xAI TTS)
- [context-references](concepts/context-references.md): @file/@folder/@diff/@url/@git Reference System, Security Sandbox + Injection Volume Limits
- [fuzzy-matching-engine](concepts/fuzzy-matching-engine.md): 8-Strategy Chain Fuzzy Matching, from Exact to Similarity Matching
- [large-tool-result-handling](concepts/large-tool-result-handling.md): Three-Layer Overflow Protection (In-Tool Truncation/Single Result Persistence/Round Aggregation Budget)

### Performance and Optimization

- [parallel-tool-execution](concepts/parallel-tool-execution.md): Intelligent Concurrency Safety Detection, Three-Layer Classification + Path Conflict Detection
- [prompt-caching-optimization](concepts/prompt-caching-optimization.md): Frozen Snapshot Protected Prefix Cache, 75% Cost Savings
- [smart-model-routing](concepts/smart-model-routing.md): Smart Model Routing, Short Messages Routed to Cheaper Models, AWS Bedrock/Gemini OAuth/Ollama Cloud/Tool Gateway
### Security and Reliability

- [security-defense-system](concepts/security-defense-system.md): Multi-Layer Defense System + Dangerous Command Approval System (manual/smart/off modes)
- [interrupt-and-fault-tolerance](concepts/interrupt-and-fault-tolerance.md): Interrupt Propagation, Structured Error Classification (error_classifier), Fallback Model Chain
- [credential-pool-and-isolation](concepts/credential-pool-and-isolation.md): Automatic Multi-Key Rotation, 4 Pool Selection Strategies, Profile Isolation

### Multi-Agent

- [multi-agent-architecture](concepts/multi-agent-architecture.md): 4 Runtime Mechanisms (delegate_task/MoA/Background Review/send_message)
- [configuration-and-profiles](concepts/configuration-and-profiles.md): Multi-Profile Architecture, Fully Isolated Agent Instances (Second Multi-Agent Solution)

### Platform and Extensions

- [cli-architecture](concepts/cli-architecture.md): CLI Architecture, Slash Commands, hermes dump
- [terminal-backends](concepts/terminal-backends.md): 7 Terminal Backends (including Vercel Sandbox), Unified Spawn-Per-Call Execution Model
- [messaging-gateway-architecture](concepts/messaging-gateway-architecture.md): 18+ Platform Unified Gateway (including IRC/Tencent Yuanbao/WeChat/QQ Bot), Platform Adapter Pluginization (PlatformRegistry), Proxy Mode, channel_prompts, Role Permissions
- [gateway-session-management](concepts/gateway-session-management.md): Gateway Session Management, Multi-Platform Session Isolation + PII Anonymization + Reset Strategy
- [hook-system-architecture](concepts/hook-system-architecture.md): Dual Hook System (Gateway Hooks + Plugin System), register_command/dispatch_tool, Dashboard Plugins
- [mcp-and-plugins](concepts/mcp-and-plugins.md): MCP Integration, Plugin Hook System, OAuth Support
- [skin-engine](concepts/skin-engine.md): YAML-Driven Skin/Theme System
- [worktree-isolation](concepts/worktree-isolation.md): Git Worktree Parallel Isolation Mode
- [cron-scheduling](concepts/cron-scheduling.md): Built-in Scheduler, Natural Language Scheduling, Multi-Platform Delivery
- [trajectory-and-data-generation](concepts/trajectory-and-data-generation.md): Trajectory Saving, Batch Runner, RL Training Environment

### Changelog

- [2026-04-09-update](changelog/2026-04-09-update.md): 59 commits, Structured Error Classification, Unified Execution Layer, Three-Layer Overflow Protection, BlueBubbles, etc.
- [2026-04-10-update](changelog/2026-04-10-update.md): 293 commits, Context Engine Pluginization, watch_patterns, WeChat, xAI, Discord/Slack Enhancements
- [2026-04-17-update](changelog/2026-04-17-update.md): 641 commits (v0.10.0), Compression v3, New Providers (Bedrock/Gemini/Ollama), Tool Gateway, Plugin Namespace Skills, DingTalk QR Authentication, Dashboard Plugins
- [2026-04-18-update](changelog/2026-04-18-update.md): 410 commits post-v0.10.0, Transport ABC Refactoring, Shell Hooks, Delegate Orchestrator, Step Plan/AI Gateway/xAI STT/KittenTTS, WeCom QR, Subagent Observability
- [2026-04-29-update](changelog/2026-04-29-update.md): 182 commits (v2026.4.23), Platform Adapter Pluginization (PlatformRegistry + IRC Reference Implementation), Curator Background Skill Maintenance, MiniMax OAuth, Vercel Sandbox, Tencent Yuanbao, `on_session_switch`, `/reload-skills`

---

## Statistics

- **Concept Pages**: 37
- **Changelog Entries**: 5
- **Source Code Coverage**: Key modules verified line-by-line
- **Tracked Version**: v2026.4.23
- **Last Updated**: 2026-04-29

## Usage

- **GitHub Online Browsing**: Click the directory links above
- **Obsidian Local Knowledge Base**:
  ```bash
  git clone https://github.com/cclank/Hermes-Wiki.git ~/Hermes-Wiki
  ```
- **With Hermes Agent**: Set `skills.config.wiki.path: ~/Hermes-Wiki` in config.yaml

---

*This document is generated based on Hermes Agent source code analysis.*