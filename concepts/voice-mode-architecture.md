---
title: Voice Mode Architecture
created: 2026-04-10
updated: 2026-04-18
type: concept
tags: [voice, stt, tts, architecture]
sources: [tools/voice_mode.py, tools/tts_tool.py, tools/transcription_tools.py, cli.py]
---

# Voice Mode Architecture

## Overview

Hermes supports Push-to-talk voice interaction: users press a key to record → STT transcribes to text → LLM processes → TTS broadcasts the reply. The entire pipeline is completed within the CLI and relies on optional audio libraries.

## Dependencies

```bash
pip install sounddevice numpy   # Or
pip install hermes-agent[voice]
```

Audio libraries are **lazily loaded on demand**; not installing them does not affect text mode. In environments without audio devices (SSH, Docker, WSL), they are automatically detected and disabled.

## Workflow

```text
User presses Ctrl+B to start recording
    ↓
sounddevice captures audio → WAV temporary file
    ↓
Press Ctrl+B again to stop recording
    ↓
STT transcription (3 Providers available):
  - local: faster-whisper (local, no API Key needed)
  - groq: Whisper via Groq (free tier)
  - openai: Whisper via OpenAI
    ↓
Transcribed text sent to LLM as a user message
    ↓
LLM replies (concise instruction automatically injected: "respond concisely, 2-3 sentences max")
    ↓
TTS voice broadcast (5 Providers available):
  - ElevenLabs (streaming, plays as it's generated)
  - OpenAI TTS
  - Google TTS
  - macOS say command
  - NeuTTS (self-hosted)
```

## STT Configuration

```yaml
# config.yaml
stt:
  provider: local   # local | groq | openai (priority: local > groq > openai)
  model: base       # faster-whisper model size (base ~150MB, automatically downloaded on first use)
```

```bash
# .env
GROQ_API_KEY=...              # Groq Whisper (free)
VOICE_TOOLS_OPENAI_KEY=...    # OpenAI Whisper
```

## TTS Configuration

TTS Provider selection and voice settings are managed via `tools/tts_tool.py`, supporting ElevenLabs' streaming broadcast—the LLM generates a sentence, and it plays immediately, without waiting for the full reply.

### New TTS Providers (v0.10.0)

| Provider | Source |
|----------|--------|
| ElevenLabs | Existing |
| OpenAI | Existing |
| **Google Gemini TTS** | New in v0.10.0, via Gemini API |
| **xAI TTS** | Introduced with xAI Responses API upgrade in v0.10.0 |
| **KittenTTS (Local)** | Introduced in v2026.4.18+, runs locally on CPU, no GPU or API key required. Default model `KittenML/kitten-tts-nano-0.8-int8` (25MB), default voice `Jasper`. Other voices provided by the KittenTTS package (25-80MB model range). |

These providers can also be accessed uniformly through Nous Tool Gateway (no self-provided API key required).

### STT Provider Extensions (v2026.4.18+)

| Provider | Description |
|----------|-------------|
| Groq Whisper (free) | Existing |
| OpenAI Whisper | Existing |
| Deepgram | Existing |
| **xAI Grok STT** | New, POST `/v1/stt`, supports ITN (Inverse Text Normalization) + optional diarization |

## Voice Mode Special Behavior

- When the LLM receives voice input, the system automatically injects a prefix instruction requesting a concise reply.
- This prefix is only used for API calls and **is not persisted to the session history** (the original transcribed text is saved via the `persist_user_message` parameter).
- In continuous voice mode, persistent errors (e.g., 429) will automatically stop the process to prevent an error → recording → error loop.

## Related Pages

- [[cli-architecture]] — Voice mode integration in the CLI
- [[auxiliary-client-architecture]] — STT/TTS using auxiliary model configuration

## Key Source Files

| File | Responsibility |
|------|----------------|
| `tools/voice_mode.py` (812 lines) | Audio recording, STT orchestration, audio playback |
| `tools/tts_tool.py` (983 lines) | TTS Provider routing, streaming broadcast |
| `tools/transcription_tools.py` | Unified interface for STT Providers |
| `cli.py` | Push-to-talk key binding (Ctrl+B) |