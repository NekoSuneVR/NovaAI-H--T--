# NovaAI With Ollama + XTTS-v2

This project gives you `NovaAI`, a local AI friend / companion that:

- talks using an Ollama model such as `dolphin3`
- listens through your microphone with the Python `SpeechRecognition` package
- transcribes speech locally with `faster-whisper` for much better recognition than the basic web recognizer
- remembers a few personal details and recent chat history
- streams replies out loud with Coqui `XTTS-v2` as audio is generated
- feels more natural because it uses a friend-style system prompt instead of an assistant-style one

## What is included

- `app.py`: terminal chat app
- `data/profile.json`: created automatically for your companion's identity and memory notes
- `data/history.jsonl`: created automatically to keep recent conversation history
- `audio/latest_reply.wav`: the newest spoken reply

## 1. Install Ollama

Install Ollama for Windows, then pull your model:

```powershell
ollama pull dolphin3
```

If the Ollama server is not already running on your PC, start it before running the app.

## 2. Create a virtual environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If you have an NVIDIA GPU and want faster XTTS replies, upgrade PyTorch to CUDA wheels:

```powershell
python -m pip install --upgrade --index-url https://download.pytorch.org/whl/cu128 torch torchaudio torchcodec
```

## 3. Create your local config

```powershell
Copy-Item .env.example .env
```

You can edit `.env` if you want to change the Ollama model, XTTS voice, or speech settings.
By default, the app now starts in hands-free voice mode.
The default config also keeps Ollama loaded, caps reply length for faster voice turns, streams XTTS audio as it is generated, and uses local `faster-whisper` for speech recognition.

## 4. Run the companion

```powershell
python app.py
```

## Commands

- `/help` shows commands
- `/mode voice` turns on hands-free microphone input
- `/mode text` switches back to typing
- `/listen` captures one spoken turn immediately
- `/recalibrate` recalibrates the microphone if it starts clipping words
- `/mics` lists available microphone devices
- `/mic <index>` chooses a microphone
- `/mic default` switches back to the system default microphone
- `/speakers` lists the built-in XTTS voices
- `/speaker <name>` switches to a different XTTS built-in voice
- `/voice` toggles spoken replies on and off
- `/voice on` and `/voice off` set spoken replies directly
- `/profile` shows your saved profile
- `/name <new name>` renames the companion
- `/me <your name>` sets your name
- `/remember <fact>` stores something important for future chats
- `/reset` clears conversation history
- `/exit` quits the app

## Notes

- XTTS-v2 downloads roughly 2 GB of model files the first time it is used.
- On a clean machine, the first XTTS-v2 download may ask you to accept Coqui's CPML terms before it downloads the model.
- XTTS-v2 supports either built-in speakers or a custom reference voice file through `XTTS_SPEAKER_WAV`.
- If you want to clone a voice, put a clean sample like `voices/me.wav` in the project and set `XTTS_SPEAKER_WAV=voices/me.wav` in `.env`.
- `faster-whisper` downloads its speech model the first time you use it. After that, speech recognition works locally.
- `STT_MODEL=small.en` is the current default because it is a good quality/speed balance for English conversation.
- Leave `STT_COMPUTE_TYPE` blank unless you want to force a specific mode. The app will choose `float16` on CUDA and `int8` on CPU automatically.
- If you want an even stronger recognizer and do not mind extra latency, try `STT_MODEL=medium.en`.
- With streaming on, reply audio plays through `sounddevice` as XTTS generates chunks. If you turn streaming off, Windows falls back to the built-in media API for WAV playback.
- With `XTTS_STREAM_OUTPUT=true`, the app starts playing speech before the full WAV is finished. It still saves the complete reply to `audio/latest_reply.wav`.
- `XTTS_STREAM_BUFFER_SECONDS` adds a small startup buffer before streamed playback begins. Raising it can fix little audio cutouts on slower machines.
- `XTTS_CHUNK_MAX_CHARS` keeps each XTTS chunk below the model text limit. Leave this around `240` for XTTS.
- `XTTS_MAX_TEXT_CHARS` controls the total amount of text the app is willing to speak for one reply. You can set this much higher, such as `5000`.
- `OLLAMA_NUM_PREDICT` limits how long replies can run by default, which makes both response generation and voice playback feel quicker.
- `XTTS_SPEED` slightly increases speaking speed without changing the voice.
- If your spoken language is not `en-US`, change `STT_LANGUAGE` in `.env`.
- If the wrong microphone is used, run `/mics` and either set `MIC_DEVICE_INDEX` in `.env` or use `/mic <index>` while the app is running.
- The app now calibrates room noise once before listening, which helps stop the first words from being clipped. If the room changes, run `/recalibrate`.
- If the mic recognizer fails, the app falls back to text mode so the session does not get stuck.
- If voice playback does not work on your machine, the app still saves the WAV file in `audio/latest_reply.wav`.
