# Project Easton — Implementation Plan

## Overview

A distributed intelligence framework split across two nodes:

- **I/O Node**: Raspberry Pi 5 with 7" touchscreen, speakers, XVF3800 Mic Array
- **Inference Brain**: MacBook (runs AI/ML workloads, exposes WebSocket server)

The Pi operates as a standalone productivity HUD when the Mac is offline. When the Mac connects, it unlocks AI-powered features (voice assistant, inference, Mac control).

---

## Architecture Decisions (locked in during planning)

| Decision | Choice | Rationale |
|---|---|---|
| Pi UI Framework | React (web kiosk via Chromium) | Native WebSocket support, large ecosystem, polished UI possible, kiosk mode via `--kiosk --app=http://localhost:PORT` |
| Mac Backend Framework | FastAPI (Python) | Async-native, built-in WebSocket support, unified language for AI/ML workloads |
| Service Discovery | mDNS via `zeroconf` + `avahi-daemon` | Mac advertises as `easton-brain.local`, Pi resolves automatically on any shared LAN. Survives IP/WiFi changes. |
| STT Engine | `faster-whisper` on Mac (`small` model) | Mac does transcription, Pi streams raw audio chunks. No API cost, offline capable. |
| Wake Word | `openWakeWord` on Pi (custom "Hey Easton" model) | Always-on, runs locally on Pi even when Mac is offline. Triggers audio streaming pipeline. |
| Voice Activation | Wake word + Push-to-Talk (touchscreen button) | Both methods start the same audio capture → stream → transcribe pipeline. |
| TTS Engine | `kokoro-tts` on Mac | Local neural TTS, no API cost, no internet needed. Mac generates audio, sends to Pi via `audio.tts_play`. Pi plays through built-in display speakers (default audio out). |
| Mac Control | AppleScript via `subprocess` | Handles media control, focus modes, app launching, notifications. Non-destructive only. Shortcuts as escape hatch for complex flows. |
| Future: GPIO | Pi GPIO pins | Physical world control (lights, motors) — architecture already supports this since Pi has its own Python process. Add as new command types later. |
| Config | Shared `shared/config.yaml` with `[pi]` and `[mac]` sections | Single source of truth for ports, timeouts, model names, credentials paths. Each main script reads only its relevant section. |
| AI Command Brain | Ollama (local, M4 Pro via Metal) | `llama3.2:3b` or `mistral` parses voice transcript → returns structured JSON intent → routed against AppleScript command whitelist. Fully offline. |

---

---

## Connection Layer — Full Specification

### Topology
- **Mac** = WebSocket **server** (FastAPI, `ws://easton-brain.local:8765`)
- **Pi** = WebSocket **client** (initiates connection, reconnects automatically)
- Both sides can send and receive at any time (full duplex)

### Message Envelope — Single Source of Truth in `shared/schema.py`

```python
{
  "id": "uuid4",          # unique message ID (for correlation)
  "type": "category.action",  # dot-namespaced enum (see types below)
  "payload": {},          # type-specific data
  "ts": 1746700000.123,   # unix timestamp (float)
  "reply_to": "uuid4"     # nullable — set when this msg is a response to another
}
```

All message types live in `shared/schema.py` as string constants. React imports a mirrored `shared/schema.js` (or a generated JS file) so both sides share the same contract.

### Message Type Registry

| Category | Type | Direction | Description |
|---|---|---|---|
| `system` | `system.handshake` | Pi → Mac | Pi announces itself on connect |
| `system` | `system.handshake_ack` | Mac → Pi | Mac confirms + sends current state |
| `system` | `system.ping` | Both | Heartbeat probe |
| `system` | `system.pong` | Both | Heartbeat response |
| `system` | `system.mode_change` | Mac → Pi | Tells Pi to enter/exit connected mode |
| `audio` | `audio.chunk` | Pi → Mac | Raw mic audio chunk (base64) |
| `audio` | `audio.transcript` | Mac → Pi | STT result from Whisper |
| `audio` | `audio.tts_play` | Mac → Pi | TTS audio to play on Pi speakers |
| `ui` | `ui.state_update` | Mac → Pi | Push new data to Pi display |
| `command` | `command.request` | Pi → Mac | User intent (voice or touch) |
| `command` | `command.response` | Mac → Pi | Result of command execution |
| `mac_control` | `mac_control.action` | Mac → Mac (internal) | Trigger AppleScript/system action |

### Connection State Machine (Pi side)

```
[DISCONNECTED]
     │  mDNS resolves easton-brain.local
     ▼
[CONNECTING]
     │  WebSocket opens → sends system.handshake
     ▼
[CONNECTED / MAC MODE]
     │  heartbeat every 30s (ping/pong)
     │  miss 2 pongs → transition to DISCONNECTED
     ▼
[DISCONNECTED]
     │  retry mDNS resolution every 10s
     └──────────────────────────────────►  (loop)
```

### Heartbeat & Reconnection Rules
- Pi sends `system.ping` every **30 seconds**
- Mac must respond with `system.pong` within **5 seconds**
- After **2 consecutive missed pongs**, Pi drops connection and enters standalone mode
- Pi retries mDNS lookup every **10 seconds** until Mac reappears
- On reconnect, Pi re-sends `system.handshake` — Mac replies with full current state so Pi can re-sync UI

### Shared Schema File Layout
```
shared/
  schema.py       ← Python: message type constants + dataclasses
  schema.js       ← JS mirror for React (can be auto-generated from schema.py)
```

---

## Issues to Create

### [INFRA-0] Shared Config (`shared/config.yaml`)

```yaml
pi:
  ui_port: 3000
  backend_port: 8000
  idle_timeout_seconds: 60
  mdns_poll_interval_seconds: 10
  heartbeat_interval_seconds: 30
  heartbeat_timeout_seconds: 5
  heartbeat_miss_limit: 2
  wake_word_model: "hey_easton.onnx"
  google_credentials_path: "shared/credentials/google_credentials.json"

mac:
  ws_port: 8765
  mdns_hostname: "easton-brain"
  ollama_model: "llama3.2:3b"
  ollama_host: "http://localhost:11434"
  whisper_model: "small"
  kokoro_voice: "default"
```

### [INFRA-1] Shared Message Schema (`shared/schema.py` + `shared/schema.js`)
- Define message envelope dataclass
- Define all message type constants as enums
- Write `schema.js` mirror for React
- Add validation helper: `validate_message(raw_json) → Message | Error`

### [INFRA-2] Repository & Monorepo Structure
**Important:** `shared/credentials/` is tracked in git (via `.gitkeep`) but all credential files inside it are gitignored. The OAuth Device Flow setup script generates these files on first run on each device.

Folder layout:
```
easton-os/
  shared/
    config.yaml         ← single config, read by both sides
    schema.py           ← message envelope + type constants
    schema.js           ← JS mirror for React
    credentials/
      .gitkeep          ← directory tracked, files inside are gitignored
      google_credentials.json   ← gitignored, generated on first OAuth run
      google_token.json         ← gitignored, auto-refreshed OAuth token
  mac/
    main.py             ← Mac entry point
    brain/
      ollama.py         ← Ollama client + intent parser
      command_router.py ← maps intent → action
    control/
      applescript.py    ← AppleScript runner
      actions.py        ← whitelisted action functions
    audio/
      whisper.py        ← faster-whisper transcription
      tts.py            ← kokoro-tts generation
    server/
      websocket.py      ← FastAPI WS endpoint + message dispatcher
      mdns.py           ← zeroconf registration
  pi/
    main.py             ← Pi entry point
    audio/
      capture.py        ← mic stream, chunking, VAD
      wakeword.py       ← openWakeWord listener
      playback.py       ← TTS audio playback
    connection/
      client.py         ← WebSocket client + reconnection loop
      mdns.py           ← mDNS resolver
    server/
      api.py            ← local FastAPI (serves connection state to React)
    ui/                 ← React app (Vite)
      src/
        components/
        hooks/
        schema.js       ← symlink or copy of shared/schema.js
```

### [INFRA-5] `mac/main.py` — Mac Entry Point
Boot sequence (in order):
1. Load `shared/config.yaml` → mac section
2. Check if Ollama is running (`GET /api/tags`) — if not, `subprocess.Popen(["ollama", "serve"])` and wait for it to be ready (poll with backoff)
3. Warm up Ollama model (send a dummy prompt to load it into memory)
4. Load `faster-whisper` model into memory
5. Initialize `kokoro-tts`
6. Register mDNS hostname `easton-brain.local` via `zeroconf`
7. Start FastAPI server at `ws_port` — blocks here, all other logic is async handlers

### [INFRA-6] `pi/main.py` — Pi Entry Point
Boot sequence (in order):
1. Load `shared/config.yaml` → pi section
2. Start wake word listener as background thread (openWakeWord)
3. Start local FastAPI server (`pi/server/api.py`) for React to poll connection state
4. Launch Chromium in kiosk mode: `chromium-browser --kiosk --app=http://localhost:{ui_port}`
5. Start mDNS polling loop — tries `easton-brain.local` every `mdns_poll_interval_seconds`
6. On resolve: open WebSocket, send `system.handshake`, start heartbeat loop
7. On disconnect: drop back to polling loop (Pi UI automatically reflects disconnected state)

### [INFRA-3] Mac WebSocket Server (FastAPI)
- Boot FastAPI with WebSocket endpoint at `/ws`
- Register mDNS hostname `easton-brain.local` via `zeroconf`
- Handle `system.handshake` → respond with `system.handshake_ack`
- Implement ping/pong heartbeat responder

### [AUDIO-1] Wake Word Detection on Pi (`openWakeWord`)
- Install and configure `openWakeWord` with custom "Hey Easton" ONNX model
- Train or download a suitable custom wake word model
- Always-on background process listening to XVF3800 mic array
- On wake word detected → emit internal event to start audio capture pipeline
- Works in both standalone and connected modes (connected mode triggers stream to Mac)

### [AUDIO-2] Audio Capture & Streaming (Pi → Mac)
- On wake word OR push-to-talk press: open mic stream, chunk into ~100ms frames
- Send `audio.chunk` messages (base64-encoded PCM) over WebSocket to Mac
- On push-to-talk release OR silence detection (VAD): send `audio.end` signal
- Visual indicator on Pi UI: recording state (waveform or pulsing indicator)

### [AUDIO-3] Transcription on Mac (`faster-whisper`)
- Mac receives `audio.chunk` stream, buffers until `audio.end`
- Run `faster-whisper` (`small` model) on buffered audio
- Send `audio.transcript` message back to Pi with text + confidence
- Pi displays transcript and forwards as `command.request` for processing

### [PI-1] Standalone Mode — Ambient Lock Screen UI
- Idle timeout (configurable, default 60s of no touch) → transitions to ambient screen
- Touch anywhere to wake back to active UI
- Ambient screen displays:
  - Large clock + date
  - Upcoming Google Calendar events (next 2–3 events, pulled directly from Google Calendar API on Pi)
  - "Mac not connected" status badge
  - "Connect to Mac" button → triggers immediate mDNS lookup attempt (bypasses the 10s poll interval)
- Google Calendar integration:
  - Pi authenticates independently via Google Calendar API (OAuth2, credentials stored on Pi)
  - Polls calendar every 5 minutes, caches locally so display works even if internet drops
- Active (non-ambient) standalone screen: same clock/calendar, same Mac status, no voice features

### [PI-2] Mac-Connected Mode — Additional UI Panels
- Mac status changes to connected (green indicator, hostname shown)
- Wake word active indicator visible
- Push-to-talk button appears
- Now Playing panel (current track, media controls: play/pause, skip)
- Mac Focus Mode indicator + toggle button
- Notification feed panel (scrollable, pulled from Mac)
- App launcher shortcuts (configurable row of app icons)

### [MAC-2] Ollama Command Brain (`mac/brain/`)
- System prompt defines the command whitelist — Ollama's only job is to match intent to a known command
- Prompt format: `"Given: '{transcript}', return JSON: {command: str, params: dict} from this list: [whitelist]. Return {command: 'unknown'} if no match."`
- Command whitelist (initial set):
  - `media.play_pause`, `media.next`, `media.prev`, `media.volume_up`, `media.volume_down`
  - `focus.enable`, `focus.disable`, `focus.set {mode}`
  - `app.open {name}`
  - `notifications.read`
  - `now_playing.get`
- Ollama client: POST to `http://localhost:11434/api/generate`, parse JSON response
- Router: maps `command` string → AppleScript function → returns result string to TTS pipeline
- Unknown commands: TTS responds "I can't do that yet"

### [MAC-1] Mac Control Module (`mac/control/`)
- `applescript.py` — thin wrapper: `run_applescript(script: str) → str`
- Pre-built action functions (non-destructive only):
  - `media_play_pause()`, `media_next()`, `media_prev()`, `set_volume(level)`
  - `set_focus_mode(mode)` — Do Not Disturb, Focus modes via System Events
  - `open_app(name)` — launch by app name
  - `get_notifications()` — read Notification Center
  - `get_now_playing()` — current track/app
- Command router: maps `command.request` payload → correct action function → returns result
- Shortcut runner: `run_shortcut(name)` for future complex flows

### [AUDIO-4] TTS (Text-to-Speech) — Pi Speakers
- Mac generates TTS response audio (engine TBD — see open questions)
- Sends `audio.tts_play` message with base64 audio to Pi
- Pi plays audio through speakers via local audio output

### [INFRA-4] Pi WebSocket Client + Connection Manager
- Background thread/task polls mDNS for `easton-brain.local` every 10s
- On resolve: open WebSocket, send handshake, start heartbeat timer
- On 2 missed pongs: close connection, re-enter polling loop
- Expose connection state to React via local API (`GET /connection-status`)
- React polls or subscribes to connection state to switch UI modes

---

## Open Questions (to be resolved during grilling)

- Mac backend framework (FastAPI vs other)
- WebSocket protocol / message schema
- ~~Service discovery (how Pi finds Mac on LAN)~~ ✓ mDNS
- ~~Standalone vs Mac-connected feature split~~ ✓ defined below
- ~~WiFi / connection bootstrapping strategy~~ ✓ mDNS + reconnection state machine
- ~~Main script architecture~~ ✓ defined below
- Audio pipeline: STT engine, TTS engine, wake word
- Mac control mechanism (AppleScript, pyautogui, Shortcuts)
- Standalone Pi feature set
- Mac-connected feature set
- WiFi / connection bootstrapping strategy
- Main script architecture for Pi and Mac
