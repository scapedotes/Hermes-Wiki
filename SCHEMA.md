# Wiki Schema

## Domain
Hermes Agent — architecture and implementation details of the AI Agent framework, with a focus on the Skills System, Memory System, Tool System, and their interaction mechanisms. Covering the Nous Research hermes-agent open-source project.

## Conventions
- Filename: lowercase + hyphens, no spaces (e.g., `skills-system.md`)
- Each wiki page must start with YAML frontmatter
- Use wiki bidirectional links (e.g., [[tool-registry-architecture]]) to connect pages (at least 2 outbound links per page)
- The `updated` date must be updated when modifying a page
- New pages must be added under their respective category in `index.md`
- Each operation must be appended to `log.md`

## Frontmatter
```yaml
---
title: Page Title
created: YYYY-MM-DD
updated: YYYY-MM-DD
type: entity | concept | comparison | query | summary
tags: [from taxonomy below]
sources: [raw/articles/source-filename.md]
---
```

## Tag Taxonomy
- **Architecture**: architecture, module, component, interface, reliability, fault-tolerance, interrupt, extensibility
- **Meta**: comparison, architecture-diagram, code-pattern, best-practice
- **Skills**: skill, skill-sync, skill-management, skill-lifecycle, skills-guard
- **Memory**: memory, memory-provider, session-search, user-profile, session-store
- **Tools**: tool, toolset, tool-registry, terminal-tool, browser-tool, terminal, environments
- **Agent**: agent, agent-loop, prompt-builder, context-compression, delegation
- **Gateway**: gateway, platform, telegram, discord, messaging, multi-platform
- **CLI**: cli, command, setup, config, ux, profile
- **Performance**: performance, concurrency, cost-optimization, caching, model-routing, fuzzy-matching
- **Security**: security, injection-defense, credentials, isolation
- **Data**: data-generation, training, trajectory
- **Operations**: cron, automation, scheduling, mcp, plugins, configuration
- **Context**: context-management
- **Model**: anthropic

## Page Thresholds
- **Create Page**: When an entity/concept appears in 2+ sources, or is core content of a source
- **Update Existing Page**: When a source mentions content already covered
- **Do Not Create Page**: For incidental mentions, minor details, or content outside the domain
- **Split Page**: When exceeding ~200 lines, split into sub-topics and cross-link
- **Archive Page**: When content is completely superseded, move to `_archive/` and remove from index

## Entity Pages
One page per entity. Includes:
- Overview / What it is
- Key Facts (file path, class name, key functions)
- Relationships with other entities (using wiki bidirectional links)
- Source references

## Concept Pages
One page per concept. Includes:
- Definition / Explanation
- Current state of knowledge
- Open questions or controversies
- Related concepts (using wiki bidirectional links)

## Comparison Pages
Comparative analysis. Includes:
- What is being compared and why
- Comparison dimensions (table format recommended)
- Conclusion or synthesis
- Sources

## Update Policy
When new information conflicts with existing content:
1. Check date — newer sources typically supersede older ones
2. If a contradiction truly exists, document both statements with dates and sources
3. Mark in frontmatter: `contradictions: [page-name]`
4. Mark in lint report for user review