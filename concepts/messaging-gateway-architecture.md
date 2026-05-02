```
---
title: Messaging Gateway Architecture
created: 2026-04-07
updated: 2026-04-29
type: concept
tags: [gateway, architecture, module, telegram, discord, messaging, qq, proxy]
sources: [gateway/run.py, gateway/platforms/, hermes_cli/config.py]
---

# Messaging Gateway Architecture

## Overview

Gateway is the **unified messaging gateway** for Hermes Agent, supporting 14+ messaging platforms and managing connections and message distribution for all platforms from a single process.

## Architecture

```
gateway/
├── run.py              # Main loop, slash commands, message distribution
├── session.py          # SessionStore — Session persistence
├── delivery.py         # Message delivery
├── config.py           # Gateway configuration
├── hooks.py            # Hook system
├── pairing.py          # DM pairing
├── status.py           # Status management
├── mirror.py           # Cross-platform mirroring
├── sticker_cache.py    # Sticker cache
├── stream_consumer.py  # Stream consumption
├── channel_directory.py # Channel directory
└── platforms/          # Platform adapters
    ├── telegram.py
    ├── telegram_network.py
    ├── discord.py
    ├── slack.py
    ├── whatsapp.py
    ├── signal.py
    ├── email.py
    ├── sms.py
    ├── matrix.py
    ├── mattermost.py
    ├── dingtalk.py
    ├── feishu.py
    ├── wecom.py
    ├── weixin.py
    ├── bluebubbles.py
    ├── homeassistant.py
    ├── webhook.py
    ├── api_server.py
    └── base.py
```

## Platform Support

| Platform | Type | Features |
|---|---|---|
| Telegram | Bot API | Groups/DMs, Voice Transcription, Stickers, Proxy Support, Link Preview Control |
| Discord | Bot API | Servers/DMs, Voice Channels, Slash Commands, Role-based Access Control, channel_prompts |
| Slack | Bot API | Workspace Integration, Thread Support |
| WhatsApp | Bridge (Node.js) | Groups/DMs, Allowlist |
| Signal | Bot API | Encrypted Messages, Native Formatting, Reply Quotes, Reactions (v2026.4.23+) |
| Email | IMAP/SMTP | Email Interaction |
| SMS | Twilio | SMS, Character Limits |
| Home Assistant | WebSocket | Smart Home Events |
| Matrix | E2E Encryption | Decentralized Messaging |
| Mattermost | Bot API | Self-hosted Team Messaging |
| DingTalk | Stream | Enterprise Messaging, QR Code Authentication, require_mention + allowed_users Access Control |
| Feishu/Lark | Stream | Enterprise Messaging |
| WeCom | Stream | WeCom Messaging |
| BlueBubbles | REST + Webhook | iMessage (macOS), Tapbacks, Read Receipts |
| WeChat | iLink Bot API | Long Polling for Messages, AES-128-ECB Media Encryption, QR Login |
| QQ Bot | Official API v2 | WebSocket Inbound (C2C/Groups/Channels/DMs) + REST Outbound, Voice Transcription (Tencent ASR), Allowlist + DM Pairing |
| Webhook | HTTP | External Event Reception |
| **Tencent Yuanbao** | API | Native Text + Media Delivery, Sticker Support (v2026.4.23+) |
| **IRC** (Plugin) | TLS asyncio | Zero External Dependencies, TLS, PING/PONG, Nick Collision, NickServ, Channel Addressing (v2026.4.23+, Reference Implementation) |

## Pluggable Platform Adapters (v2026.4.23+)

`gateway/platform_registry.py` introduces the `PlatformRegistry` singleton and `PlatformEntry` dataclass, allowing anyone to integrate new platforms (e.g., IRC, Viber, Line) as **pure plugins** without modifying the gateway's core code.

```python
# Plugin registration entry point
def register(ctx):
    ctx.register_platform(
        name="irc",
        label="IRC",
        adapter_factory=create_irc_adapter,
        check_fn=check_irc_available,
        validate_config=validate_irc_config,
        required_env=["IRC_NICK", "IRC_PASS"],
        install_hint="pip install ...",
    )
```

### Key Changes

| Module | Change |
|---|---|
| `Platform` enum | `_missing_()` accepts unknown strings, creates cached pseudo-members (e.g., `Platform('irc') is Platform('irc')` is always true) |
| `GatewayConfig.from_dict` | Parses plugin platform names from config.yaml; no longer rejects unknown platforms |
| `_create_adapter()` in `gateway/run.py` | Checks registry first, then falls through to the built-in if/elif chain if not found |
| `get_connected_platforms()` | Delegates unknown platforms to the registry |
| `PluginContext.register_platform()` | Mirrors the `register_tool()` / `register_hook()` pattern |

### IRC Reference Implementation

`plugins/platforms/irc/` is the first plugin platform:
- Fully asynchronous (`asyncio` stdlib, zero external dependencies)
- TLS connection, PING/PONG heartbeats, nick collision renaming, NickServ automatic authentication
- Channel messages require `nick: msg` addressing, all DMs are dispatched
- Markdown stripping for output (IRC does not support), message fragmentation (IRC length limits)
- Interactive `setup` wizard (v2026.4.23+)

### Complete Coverage of 12 Platform Plugin Integration Points

`feat: complete plugin platform parity` (2e20f6ae2) + `feat: final platform plugin parity` (e464cde58) ensures consistent behavior between plugin platforms and built-in platforms:
- Webhook delivery, PLATFORM_HINTS, `get_connected_platforms`, cron delivery, dynamic toolset generation, setup wizard, etc.
- Bundled plugin platforms (e.g., IRC) are automatically loaded at startup (`feat(plugins): bundled platform plugins auto-load by default`)

## Platform Adapter Base Class

```python
# gateway/platforms/base.py
class BasePlatform:
    """Base class for platform adapters"""
    
    def __init__(self, config: dict, gateway):
        self.config = config
        self.gateway = gateway
        self.platform_name = self.__class__.__name__.lower()
    
    async def start(self):
        """Starts the platform connection"""
        raise NotImplementedError
    
    async def stop(self):
        """Stops the platform connection"""
        raise NotImplementedError
    
    async def send_message(self, chat_id: str, text: str, **kwargs):
        """Sends a message"""
        raise NotImplementedError
    
    async def handle_message(self, event: MessageEvent):
        """Handles incoming messages"""
        await self.gateway.process_event(event)
```

## Message Processing Flow

```
User sends message
  ↓
Platform adapter receives
  ↓
MessageEvent created
  ↓
GatewayRunner.process_event(event)
  ↓
Slash command parsed (if any)
  ↓
Session found or created
  ↓
AIAgent invoked
  ↓
Response received
  ↓
Reply sent via platform adapter
```

## Session Management

```python
# gateway/session.py
class SessionStore:
    """Persistent storage for sessions"""
    
    def get_or_create_session(self, chat_id, platform):
        """Gets or creates a session"""
    
    def save_session(self, session_id, messages):
        """Saves a session"""
    
    def get_session(self, session_id):
        """Gets a session"""
```

## Slash Commands

Slash command system shared with the CLI:

| Command | Description |
|---|---|
| `/new` | New conversation |
| `/reset` | Reset conversation |
| `/model [provider:model]` | Switch model |
| `/personality [name]` | Set personality |
| `/retry` | Retry last turn |
| `/undo` | Undo last turn |
| `/compress` | Compress context |
| `/usage` | Check token usage |
| `/insights [days]` | Usage insights |
| `/skills` | Browse skills |
| `/stop` | Interrupt current work |
| `/status` | Platform status |
| `/sethome` | Set home platform |

## DM Pairing

Controls who can converse with the bot via the `GATEWAY_ALLOWED_USERS` environment variable:

```bash
# Allowed Telegram user IDs
GATEWAY_ALLOWED_USERS=telegram:123456789,discord:987654321
```

When unauthorized users send messages, the bot will not respond (silent ignore).

## Media Handling

```
User sends image/file
  ↓
Platform adapter downloads
  ↓
Saved to temporary directory
  ↓
Passed to Agent (vision_analyze or file processing)
  ↓
Agent response includes MEDIA: path
  ↓
Local file extracted
  ↓
Sent via native platform method
```

## Gateway Service Management

### Linux (systemd)

```ini
# ~/.config/systemd/user/hermes-gateway.service
[Unit]
Description=Hermes Agent Gateway
After=network-online.target

[Service]
ExecStart=/path/to/hermes gateway run
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
hermes gateway start    # Start service
hermes gateway stop     # Stop service
hermes gateway status   # Check status
```

Service unit: `hermes-gateway.service` or `hermes-gateway-<profile>.service`

### macOS (launchd)

```xml
<!-- ~/Library/LaunchAgents/com.nousresearch.hermes-gateway.plist -->
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nousresearch.hermes-gateway</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/hermes</string>
        <string>gateway</string>
        <string>run</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

```bash
hermes gateway start    # Start launchd service
hermes gateway stop     # Stop
hermes gateway status   # Status
```

Label: `com.nousresearch.hermes-gateway`

## Automatic Restart on Update

The `hermes update` command automatically:
1. Discovers all running gateway services
2. Restarts systemd/launchd services
3. Stops manually run processes not in service mode

## Platform-Specific Features

### Telegram
- Supports groups and direct messages (DMs)
- Group messages require @mention for activation
- Voice message transcription
- Sticker support
- Topic/Thread support
- **Proxy support** (v0.10.0): `TELEGRAM_PROXY` environment variable or `proxy_url` in `config.yaml`
- **Link preview control** (v0.10.0): `telegram.disable_link_preview` in `config.yaml` to disable message link previews

### Discord
- Supports servers and direct messages (DMs)
- Requires @mention or DM
- Voice channel support
- Opus audio encoding
- Slash commands integration
- **Role-based access control** (v0.10.0): `DISCORD_ALLOWED_ROLES` environment variable, comma-separated Role IDs. It's an OR relationship with `DISCORD_ALLOWED_USERS` - a match on either user ID or role grants access; if neither is configured, all users have access.
- **channel_prompts** (v0.10.0): Inject different system prompts per channel/topic, also extended to Telegram (groups/forum topics), Slack, Mattermost.
- **@everyone and role ping suppression**: `allowed_mentions` by default prevents the bot from triggering mass notifications.

### DingTalk
- Stream protocol connection
- **QR Code Authentication** (v0.10.0): `hermes_cli/dingtalk_auth.py` (line 292) implements the Device Flow—the terminal renders a QR code, which users scan with DingTalk to automatically obtain AppKey/AppSecret, eliminating the need for manual application creation.
- **require_mention + allowed_users access control** (v0.10.0): Aligned with Telegram/Discord.
- Supports dingtalk-stream 0.24+ SDK and oapi webhooks.

### WeChat
- SILK-encoded voice replies (v0.10.0)
- Media attachment extraction and sending
- Native Markdown rendering
- CDN whitelist for SSRF protection (security fix)
- macOS SSL certificate fix

### WhatsApp
- Requires WhatsApp Bridge (Node.js)
- Group messages require a prefix to trigger
- Allowlist control

### Home Assistant
- Smart home event monitoring
- Device control
- Automation triggers

### Gateway Operations Enhancements (v0.10.0)
- **Agent cache LRU + idle TTL eviction**: `_agent_cache` now includes a size limit and idle timeout to prevent memory leaks in long-running gateways.
- **Temporary agent shutdown**: Temporary agents are automatically shut down after one-time tasks are completed.
- **WebSocket reconnection wait**: Waits for reconnection to complete before sending, preventing message loss.

### v2026.4.18+ Enhancements

- **WeCom QR Code Authentication**: The setup wizard (`hermes_cli/gateway.py:_setup_wecom`) obtains bot credentials via `gateway.platforms.wecom.qr_scan_for_bot_info`, eliminating manual configuration.
- **Cross-platform native slash commands for plugins**: Plugin commands registered with `register_command()` are automatically exposed as Discord native slash commands, Telegram BotCommands, and Slack `/hermes` subcommands, removing the need for platform-specific implementations.
- **Decision-making command hook**: The `command:<name>` hook can return `{"decision": "deny"|"handled"|"rewrite"|"allow"}` to intercept commands before core processing.
- **Slack reaction lifecycle**: The `SLACK_REACTIONS` environment variable controls whether the bot uses reactions (emojis) when sending and receiving messages.
- **Feishu @mention context preservation**: Incoming messages retain @mention context.
- **Feishu streaming edit newline fix**: Streaming output no longer prepends extra blank lines.
- **Session state maintenance**: `hermes_state.py` introduces `maybe_auto_prune_and_vacuum()`, which executes idempotently on startup (last run time recorded cross-process via `state_meta` table). This prevents indefinite growth of sessions and FTS5 indices (one heavy user reported 384MB/982 sessions impacting performance, reduced to 43MB after prune + VACUUM).
- **MEDIA: tag extension**: Supports automatic extraction for PDF, document, and archive file extensions.
- **Global tunnel/proxy URL toggle**: `security.allow_private_urls` / `HERMES_ALLOW_PRIVATE_URLS` allows parsing of private IP ranges (198.18.0.0/15, 100.64.0.0/10), addressing scenarios like OpenWrt / TUN proxies (Clash/Mihomo/Sing-box) / Enterprise VPN / Tailscale. Cloud metadata endpoints (169.254.169.254, etc.) are always blocked.
- **Platform hints**: `PLATFORM_HINTS` overrides system prompts for Matrix, Mattermost, Feishu.

### Comparison with Other Agent Frameworks

| Feature | Hermes | OpenClaw | Claude |
|---|---|---|---|
| Number of Platforms | 14+ | 14+ | 1 |
| Unified Gateway | Single Process | Supported | N/A |
| Session Sharing | Cross-Platform | Supported | N/A |
| Voice Transcription | Telegram/Discord | Supported | N/A |
| Group Support | Multi-Platform | Supported | N/A |
| Service Management | systemd/launchd | Supported | N/A |

## Gateway Proxy Mode (Thin Relay Mode, 2026-04-14)

Typically, Gateway and Agent run in the same process: Gateway receives messages → directly calls `AIAgent.run_conversation()`. **Proxy mode** separates the two—Gateway only handles platform I/O (encryption, fragmentation, media), while all Agent work is forwarded to a remote Hermes API server.

### Typical Use Case

```
[Matrix/Discord/...]  ←→  [Gateway (Linux Docker, E2EE keys)]
                                    │ POST /v1/chat/completions (SSE)
                                    ↓
                              [Hermes API server (macOS host)]
                                    │
                                    ↓
                     Local files, memory, skills, unified session store
```

### Problem Solved

Desire to use Matrix E2EE, but E2EE requires persistent encryption keys, which are more stable when run in Docker. The agent itself, however, needs to run on a macOS host to access local files/skills/memory. Previously, it was an either/or choice; proxy mode connects them.

### Activation

```yaml
# ~/.hermes/config.yaml — Configuration priority
gateway:
  proxy_url: "http://host.docker.internal:8080"
```

Or environment variables (Docker-friendly, no config mounting needed):

```bash
GATEWAY_PROXY_URL=http://host.docker.internal:8080
GATEWAY_PROXY_KEY=<matches upstream API_SERVER_KEY>
```

### Implementation Details

Starting from `gateway/run.py:7709`:
- `_get_proxy_url()` — Checks env var first, then config.yaml
- `_run_agent_via_proxy()` — HTTP + SSE streaming forwarding, parses streaming responses
- `_run_agent()` — If `proxy_url` is detected, takes the proxy path; otherwise, uses the local agent
- `GatewayStreamConsumer` operates as usual; streaming fragmentation is still handled on the Gateway side

### Key Features

| Mechanism | Description |
|---|---|
| `X-Hermes-Session-Id` header | Carries session ID to ensure session continuity across requests |
| `GATEWAY_PROXY_KEY` | Matches remote `API_SERVER_KEY`, uses Bearer authentication |
| SSE streaming | Responses arrive in chunks, Gateway streams them to the platform |
| Error compatibility | Returned result dict structure matches local agent, session store records as usual |
| Platform agnostic | Not just Matrix, any platform adapter can use proxy mode |

### Call Chain

```
User sends message in Matrix
    ↓ E2EE decryption (Gateway side)
gateway.process_event()
    ↓
_run_agent() → proxy_url detected
    ↓
_run_agent_via_proxy():
    POST {proxy_url}/v1/chat/completions
      + X-Hermes-Session-Id: <sid>
      + Authorization: Bearer <GATEWAY_PROXY_KEY>
      + body: { messages: [...], stream: true }
    ↓ SSE stream arrives
    Each chunk forwarded to platform via GatewayStreamConsumer
    ↓ E2EE encryption (Gateway side)
Sent back to user
```

## Related Pages

- [[gateway-session-management]] — Gateway Session Management Architecture
- [[cron-scheduling]] — Cron Scheduler Driven by Gateway
- [[hook-system-architecture]] — Gateway Event Hook System

## Related Files

- `gateway/run.py` — Main Loop and Message Distribution
- `gateway/session.py` — SessionStore
- `gateway/platforms/base.py` — Platform Base Class
- `gateway/delivery.py` — Message Delivery
- `gateway/config.py` — Gateway Configuration
- `gateway/platforms/` — Platform Adapters Directory
- `hermes_cli/gateway.py` — Gateway CLI Commands
```