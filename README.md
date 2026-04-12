# NovaAI

**Your brutally honest AI companion that actually talks back.**

NovaAI is a voice-powered desktop companion built with Python. It listens through your mic, thinks with local or cloud LLMs, and speaks back with a cloned voice — all wrapped in a slick dark-themed UI. Think Alexa, but with attitude and zero cloud lock-in.

---

## What Can It Do?

- **Chat** via Ollama or any OpenAI-compatible endpoint (LM Studio, LiteLLM, etc.)
- **Listen** with `faster-whisper` local speech recognition — no audio leaves your machine
- **Talk back** with XTTS-v2 streamed voice synthesis (or Google TTS as a lightweight fallback)
- **Search the web** — manual lookups or auto-triggered when the LLM thinks it needs fresh info
- **Play music & radio** — SoundCloud search, internet radio stations, in-app playback with pause/resume/stop
- **Manage your life** — reminders, alarms, to-do lists, shopping lists, and a calendar
- **Multiple profiles** — create, clone, and switch between different companion personalities
- **Auto-tune performance** — detects your hardware and adjusts model sizes, GPU usage, and timeouts automatically
- **Self-update** — checks GitHub for new versions and can update itself on startup

## Quick Start

**One command to set everything up:**

```powershell
.\setup.bat
```

This handles Python 3.11, Ollama, model downloads, and all dependencies. Then:

```powershell
# Desktop GUI (recommended)
.\launch_gui.bat

# Terminal mode
.\.venv\Scripts\python.exe app.py
```

> **GPU users:** want faster voice replies? After setup, run:
> ```powershell
> .\.venv\Scripts\python.exe -m pip install --upgrade --index-url https://download.pytorch.org/whl/cu128 torch torchaudio torchcodec
> ```

## The GUI

NovaAI runs as a native desktop window powered by **pywebview + Tailwind CSS** — a real web-rendered UI, not a clunky toolkit widget.

**Pages:**

| Page | What It Does |
|------|-------------|
| **Dashboard** | Session controls, toggle voice/mic/hands-free, status at a glance |
| **Chat** | Full conversation view with text + voice input |
| **Reminders** | Set time-based reminders and recurring alarms |
| **Calendar** | Track upcoming events with date/time |
| **Shopping** | Checkbox-style shopping list |
| **To-Do** | Task list with done/delete |
| **Profiles** | Create, clone, switch, or delete companion personalities |
| **Settings** | Audio devices, web search config, LLM/TTS/STT info |

Voice replies, hands-free mode, and mic mute can all be toggled **before** starting a session.

## Terminal Commands

NovaAI has a full command set for terminal mode:

| Command | What It Does |
|---------|-------------|
| `/help` | Show all commands |
| `/mode voice` | Hands-free mic input |
| `/mode text` | Switch back to typing |
| `/listen` or `/ask` | Capture one spoken turn |
| `/voice` | Toggle spoken replies on/off |
| `/web <query>` | Search the web and feed results to the next reply |
| `/web auto on/off` | Auto-search for current-event questions |
| `/play <query>` | Play radio or search music |
| `/radio <station>` | Tune into a known station |
| `/music <query>` | Search your default music platform |
| `/pause` / `/resume` / `/stop` | Media playback controls |
| `/profile` | Show current profile |
| `/profiles` | List all profiles |
| `/profile use <id>` | Switch profiles |
| `/name <new name>` | Rename the companion |
| `/me <name>` | Set your name |
| `/remember <fact>` | Store a memory note |
| `/recalibrate` | Re-tune mic noise gate |
| `/mics` / `/speakers` | List audio devices |
| `/mic <index>` | Choose a microphone |
| `/performance` | Show hardware info and active tuning profile |
| `/reset` | Clear conversation history |
| `/exit` | Quit |

Natural language works too — say *"remind me to call the dentist at 3pm"* or *"play Capital FM"* and NovaAI handles it.

## Profiles

Each companion profile is deeply customisable:

- **Identity** — name, pronouns, role, relationship style
- **Conversation** — reply length, pacing, verbosity, formatting
- **Personality sliders** — warmth, sass, directness, patience, playfulness, formality
- **Boundaries** — roast intensity, avoided topics, safety overrides
- **Memory** — likes, dislikes, personal facts, inside jokes, projects
- **Voice** — speech style, delivery notes, persona keywords
- **Custom rules** — hard must-follow rules and soft preferences

## Data Storage

All runtime data lives in a single **SQLite database** at `data/novaai.db`:

- Chat history
- Profiles and their feature data (reminders, todos, shopping, calendar, alarms)
- App state (active profile, settings)

On first run, any existing JSON files (`profiles.json`, `history.jsonl`) are automatically migrated into the database.

## Configuration

Copy `.env.example` to `.env` and tweak what you need. Key settings:

| Setting | Default | What It Does |
|---------|---------|-------------|
| `LLM_PROVIDER` | `ollama` | Chat backend (`ollama` or `openai`) |
| `LLM_MODEL` | `dolphin3` | Which model to use |
| `TTS_PROVIDER` | `xtts` | Voice engine (`xtts` or `gtts`) |
| `WEB_BROWSING_ENABLED` | `true` | Web search features |
| `WEB_AUTO_SEARCH` | `false` | Auto-detect when to search |
| `VOICE_ENABLED` | `false` | Start with voice replies on |
| `AUTO_TUNE_PERFORMANCE` | `true` | Auto-detect hardware and tune |
| `AUTO_UPDATE_CHECK` | `true` | Check GitHub for updates on startup |
| `XTTS_SPEED` | `1.0` | Speaking pace multiplier |
| `STT_MODEL` | `small.en` | Whisper model size |
| `MIC_DEVICE_INDEX` | *(auto)* | Pin a specific microphone |
| `SPEAKER_DEVICE_INDEX` | *(auto)* | Pin a specific speaker |

See `.env.example` for the full list with descriptions.

## Project Layout

```
NovaAI/
|-- app.py                 # Entry point
|-- setup.bat              # One-click Windows setup
|-- launch_gui.bat         # Launch the desktop GUI
|-- update.bat             # Manual update
|-- requirements.txt       # Python dependencies
|-- VERSION                # Current version
|-- .env.example           # Configuration template
|-- data/
|   |-- novaai.db          # SQLite database (runtime)
|   |-- profile.example.json
|-- novaai/
|   |-- launcher.py        # CLI vs GUI routing + auto-update
|   |-- webgui.py          # pywebview desktop GUI backend
|   |-- cli.py             # Terminal chat loop + commands
|   |-- chat.py            # System prompt + LLM requests
|   |-- config.py          # Environment parsing + runtime config
|   |-- database.py        # SQLite schema + CRUD operations
|   |-- storage.py         # Profile/history API (SQLite-backed)
|   |-- features.py        # Reminders, alarms, todos, shopping, calendar
|   |-- audio_input.py     # Mic capture + faster-whisper STT
|   |-- tts.py             # XTTS-v2 / gTTS synthesis + playback
|   |-- media.py           # Radio + music platform integration
|   |-- media_player.py    # In-app audio playback (ffplay)
|   |-- performance.py     # Hardware detection + auto-tuning
|   |-- updater.py         # GitHub version check + self-update
|   |-- web_search.py      # SearXNG / DuckDuckGo search
|   |-- defaults.py        # Default profile template
|   |-- models.py          # Shared dataclasses
|   |-- paths.py           # Path constants
|   |-- static/
|       |-- index.html     # Tailwind CSS frontend
```

## Good to Know

- **First run downloads models** — XTTS-v2 and faster-whisper grab model files on first use. `setup.bat` preloads them so you're not waiting on first launch.
- **Mic mute is app-level** — it stops NovaAI from listening, it doesn't touch your Windows system mic settings.
- **Auto-tune won't mess with your voice** — `XTTS_SPEED` is never overridden, so your companion sounds the same on every machine.
- **Git-safe updates** — if NovaAI detects a git checkout with local edits, it skips self-updating to protect your work.
- **Audio output is saved** — voice replies land in `audio/latest_reply.wav` (XTTS) or `.mp3` (gTTS) even if playback fails.

## Contributing

The codebase is modular by design — pick an area and dive in:

| Area | File |
|------|------|
| Voice / mic issues | `novaai/audio_input.py` |
| Personality / responses | `novaai/chat.py` |
| TTS / playback | `novaai/tts.py` |
| Commands / app flow | `novaai/cli.py` |
| GUI frontend | `novaai/static/index.html` |
| GUI backend | `novaai/webgui.py` |
| Features (reminders etc.) | `novaai/features.py` |
| Data / profiles | `novaai/storage.py` + `novaai/database.py` |

## License

MIT License — see [LICENSE](LICENSE).

Built with spite, sarcasm, and way too much caffeine by [CacheNetworks](https://github.com/cachenetworks).
