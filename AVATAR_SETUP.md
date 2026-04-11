# NovaAI Avatar System

This document details the VRM avatar frontend, WebSocket bridge, local reminders, and emotion/danger detection features added to NovaAI.

## Features

### 1. VRM Frontend Portal

A modern web-based avatar viewer with Three.js rendering and drag-and-drop VRM model upload.

**Access:**
- Open the NovaAI desktop GUI
- Go to the **Main** tab
- Click **"Open Avatar Portal"** button
- Or navigate to `http://localhost:8766/` in your browser

**Features:**
- Real-time VRM model preview
- Drag-and-drop file upload for `.vrm` models  
- File picker for VRM selection
- WebSocket-connected state updates (emotion, danger detection)
- Connection status indicator
- Auto-reconnection

### 2. VRM Upload & Persistence

Upload and manage VRM models through the GUI or web portal.

**Upload Methods:**
1. **Web Portal**: Drag and drop `.vrm` files in the "VRM Upload" section
2. **GUI File Picker**: Click "Load VRM File" in the Main tab
3. **Avatar Bridge**: Upload directly via the HTTP API

**Persistence:**
- Last loaded VRM path is saved in the profile
- Auto-loads and restores the VRM when the app restarts
- Models are copied to `data/avatars/` for reliable local access

### 3. Local Alarms & Reminders

Create time-based reminders that trigger alerts and notify the avatar frontend.

**Create Reminders:**
1. Open the **Main** tab in the NovaAI GUI
2. In the "Local Alarms & Reminders" section, click **"Add Reminder"**
3. Enter a reminder title (e.g., "Take a break")
4. Enter time in one of these formats:
   - `HH:MM` (e.g., `14:30` — next occurrence)
   - `YYYY-MM-DD HH:MM` (e.g., `2025-03-15 09:00`)

**Reminder Behavior:**
- Reminders are checked every 30 seconds
- When triggered:
  - A system message appears in the chat history
  - If Voice Replies are on, the reminder is spoken
  - The avatar frontend is notified via WebSocket
- Completed reminders are marked with ✓ in the list
- Click "Delete Selected" to remove reminders

### 4. Emotion Detection

The system analyzes conversation text to detect the user's emotional state.

**Detected Emotions:**
- `happy` — Positive words: "happy", "love", "excited", "awesome", "joy"
- `sad` — Negative words: "sad", "upset", "hurt", "depressed"
- `anxious` — Worried words: "scared", "afraid", "nervous", "worried"
- `angry` — Conflict words: "angry", "mad", "furious", "irritated"
- `neutral` — (default)

**Implementation:**
- Simple keyword matching on user input + assistant response
- Emotion state is published to the WebSocket bridge
- Avatar frontend receives real-time emotion updates

### 5. Danger Detection

The system flags safety-critical keywords that might indicate an emergency.

**Trigger Keywords:**
- "danger", "fire", "help", "emergency", "attack", "threat", "warning", "alarm"

**Behavior:**
- Danger state is detected and published to the avatar frontend
- Can be used to trigger visual/audio alerts or avatar animations
- Works in conjunction with emotion detection

## Architecture

### Backend: Avatar Bridge (`novaai/avatar.py`)

HTTP server + WebSocket server for managing avatar uploads and state.

**HTTP Server (port 8766):**
- `GET /` → Avatar portal HTML
- `POST /upload` → Receive VRM files
- `GET /uploads/` → Serve uploaded files

**WebSocket Server (port 8765):**
- Listen on `ws://127.0.0.1:8765`
- Broadcast avatar state, reminders, and emotion/danger updates
- Echo server (receive and ignore incoming messages)

**Payload Types:**
```json
{ "type": "avatar", "event": "load", "url": "/uploads/model.vrm" }
{ "type": "state", "payload": { "emotion": "happy", "danger": false } }
{ "type": "reminder", "event": "due", "reminder": { "id": "...", "title": "..." } }
{ "type": "hello", "status": "connected" }
```

### Frontend: Avatar Portal (`novaai/static/avatar.html`)

Standalone HTML5 web app using:
- **Three.js** for 3D rendering  
- **@pixiv/three-vrm** for VRM model support
- **WebSocket API** for real-time state updates

**UI Sections:**
- **VRM Upload**: Drag-drop or file picker for VRM upload
- **Avatar Viewer**: Canvas for 3D model rendering
- **Connection Status**: WebSocket connection indicator
- **Model Status**: Currently loaded VRM information
- **Activity Log**: Real-time update messages

### GUI Integration (`novaai/gui.py`)

New methods in `NovaAIGui` class:

**Avatar Management:**
- `_get_avatar_settings()` → Access avatar config in profile
- `_save_avatar_settings()` → Persist avatar config
- `_load_saved_vrm()` → Restore VRM on startup
- `_on_vrm_uploaded(path)` → Handle uploaded files
- `open_avatar_ui()` → Open browser to portal
- `pick_vrm_file()` → File picker dialog
- `reload_avatar()` → Reload in frontend

**Reminders:**
- `_standardize_reminders()` → Normalize reminder list
- `_refresh_reminders_list()` → Update UI list
- `add_reminder()` → Create new reminder
- `delete_reminder()` → Remove selected reminder
- `_schedule_reminder_check()` → Background check loop
- `_check_reminders()` → Trigger due reminders
- `_trigger_reminder()` → Execute reminder action

**Emotion & Danger Detection:**
- `_detect_emotion(text)` → Keyword-based emotion analysis
- `_detect_danger(text)` → Keyword-based danger detection
- `_send_avatar_state()` → Publish state on each reply

## Setup & Usage

### Prerequisites

- Python 3.9+
- `websockets>=11` (added to `requirements.txt`)
- Modern web browser (Chrome, Firefox, Safari, Edge)

### Installation

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Start the NovaAI GUI:
   ```bash
   python app.py --gui
   ```

3. Wait for the status to show the app is ready
4. Click **"Open Avatar Portal"** to access the web UI

### Uploading a VRM Model

**Method 1: Web Portal**
1. Click "Open Avatar Portal"
2. Drag a `.vrm` file into the drop zone
3. The model will load automatically in the viewer

**Method 2: GUI File Picker**
1. Click "Load VRM File" in the Main tab
2. Browse to your VRM model
3. The model is copied to `data/avatars/` and loaded

### Creating a Reminder

1. Go to the **Main** tab
2. In "Local Alarms & Reminders", click **"Add Reminder"**
3. Enter a title (e.g., "Water the plant")
4. Enter time format:
   - `09:30` (today at 9:30 AM, or tomorrow if past)
   - `2025-03-20 09:30` (specific date and time)

### Checking Emotion & Danger Detection

1. Type messages or have conversations
2. The avatar frontend receives emotion/danger updates via WebSocket
3. Check the browser console or logs for WebSocket messages

## Data Structure

### Profile Avatar Settings

Stored in `profile.json` under `profile_details.avatar`:

```json
{
  "avatar": {
    "enabled": false,
    "vrm_path": "path/to/model.vrm",
    "last_loaded_vrm_path": "data/avatars/model.vrm",
    "websocket_url": "ws://127.0.0.1:8765"
  }
}
```

### Profile Reminders

Stored in `profile.json` under `profile_details.reminders`:

```json
{
  "reminders": [
    {
      "id": "reminder-1234567890",
      "title": "Take a break",
      "due": "2025-03-15 14:30",
      "created_at": "2025-03-15T12:45:00",
      "completed": false
    }
  ]
}
```

## Troubleshooting

### Avatar Portal Won't Open

- Check if ports 8765 (WebSocket) and 8766 (HTTP) are available
- Firewall may be blocking local connections
- Try accessing `http://127.0.0.1:8766/` directly in your browser

### VRM Model Not Loading

- Ensure the file is valid VRM format (`.vrm`)
- Check browser console for error messages
- Uploaded models are in `data/avatars/` — verify the file is there
- Try reloading the portal or refreshing the page

### Reminders Not Triggering

- Check system time is correct
- Reminder due times are compared in local timezone
- Times should be in 24-hour format (e.g., `14:30`, not `2:30 PM`)
- Reminders are checked every 30 seconds

### WebSocket Connection Issues

- Ensure `websockets` package is installed (`pip install websockets>=11`)
- Check if port 8765 is free
- Try restarting the NovaAI application
- Check browser console for connection errors

## Future Enhancements

- [ ] Support animation/blend shape control from WebSocket messages
- [ ] Improved emotion detection (ML-based sentiment analysis)
- [ ] Recurring reminders (daily, weekly, etc.)
- [ ] Reminder snooze functionality
- [ ] Avatar expression/gesture mapping to emotion states
- [ ] Multi-model support (switch VRMs on the fly)
- [ ] Remote avatar deployment (CORS-enabled)

## License

Same as NovaAI (see LICENSE file)
