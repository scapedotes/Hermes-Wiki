---
title: Skin Engine (Skin/Theme)
created: 2026-04-10
updated: 2026-04-10
type: concept
tags: [cli, theme, customization]
sources: [hermes_cli/skin_engine.py]
---

# Skin Engine

## Overview

The visual appearance of Hermes CLI is entirely YAML-driven, allowing users to customize colors, spinner animations, and branding copy without modifying any code.

## Skin File Structure

Skin files are located at `~/.hermes/skins/*.yaml`. All fields are optional, and missing values are inherited from the `default` skin.

```yaml
name: mytheme
description: Custom Theme

colors:
  banner_border: "#CD7F32"     # Banner Border
  banner_title: "#FFD700"      # Banner Title
  banner_accent: "#FFBF00"     # Section Title
  ui_accent: "#FFBF00"         # UI Accent Color
  ui_ok: "#4caf50"             # Success
  ui_error: "#ef5350"          # Error
  ui_warn: "#ffa726"           # Warning
  prompt: "#FFF8DC"            # Input Prompt
  response_border: "#FFD700"   # Response Box Border

spinner:
  waiting_faces: ["(⚔)", "(⛨)"]
  thinking_faces: ["(⌁)", "(<>)"]
  thinking_verbs: ["forging", "plotting"]
  wings: [["⟪⚔", "⚔⟫"], ["⟪▲", "▲⟫"]]

branding:
  agent_name: "My Agent"
  welcome: "Welcome!"
  goodbye: "Bye! ⚕"
  response_label: " ⚕ Response "
  prompt_symbol: "❯ "
```

## Switching Skins

```bash
/skin mytheme          # In-session switch
hermes config set display.skin mytheme  # Persistent configuration
```

## Each Profile Can Have Different Skins

Skin files are located in the `skins/` directory of each Profile. Different Profiles can use different visual themes.

## Related Pages

- [[configuration-and-profiles]] — Profile System (Each Profile has an independent skins directory)
- [[cli-architecture]] — CLI Architecture

## Key Source Files

- `hermes_cli/skin_engine.py` — Skin loading, inheritance, and rendering