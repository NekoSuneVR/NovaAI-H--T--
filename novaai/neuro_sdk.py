"""NovaAI - Neuro Game SDK server (let NovaAI play real games).

This implements the **Neuro Game SDK** WebSocket API on the *AI* side, so NovaAI
becomes a drop-in replacement for "Neuro": any game built with the SDK connects
to NovaAI and NovaAI perceives the game and chooses the actions. One server
unlocks every SDK integration — Among Us, Liar's Bar, Buckshot Roulette,
Inscryption, Hollow Knight, Cyberpunk, Pokémon, Who Wants to Be a Millionaire, …

Protocol (spec: github.com/VedalAI/neuro-game-sdk):
  * Transport: plaintext-JSON WebSocket. The GAME is the client; the AI (this) is
    the server. Games connect to the URL in their ``NEURO_SDK_WS_URL`` env var,
    which defaults to ``ws://localhost:8000`` — so we host there by default.
  * Game→AI: ``startup``, ``actions/register``, ``actions/unregister``,
    ``context`` (message + silent), ``actions/force`` (state, query, action_names,
    priority…), ``action/result`` (id, success, message).
  * AI→Game: ``action`` (id, name, data) — the action NovaAI decided to take.

NovaAI's "brain" here is the shared LLM engine: on a forced decision we describe
the game state + the registered actions and ask the model to pick one and fill
its JSON schema; we validate/coerce the result, send it, and (optionally) speak a
one-line reaction. Mirrors the threaded-asyncio websockets pattern in avatar.py.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
from typing import Any, Callable

try:
    import websockets
except ImportError:  # pragma: no cover - optional dep (already in requirements)
    websockets = None  # type: ignore[assignment]

DEFAULT_PORT = 8000


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


def _extract_json(text: str) -> dict | None:
    """Pull the first balanced ``{...}`` object out of an LLM reply, tolerantly."""
    if not text:
        return None
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except Exception:
                            break
        start = text.find("{", start + 1)
    return None


def _default_for(spec: dict) -> Any:
    if "default" in spec:
        return spec["default"]
    if spec.get("enum"):
        return spec["enum"][0]
    t = spec.get("type")
    return {"integer": 0, "number": 0, "boolean": False, "string": "",
            "array": [], "object": {}}.get(t, None)


def _coerce_value(val: Any, spec: dict) -> Any:
    """Best-effort coerce a value to its declared JSON-schema type/enum."""
    enum = spec.get("enum")
    if enum and val not in enum:
        # Try a case-insensitive string match before falling back to the first.
        for opt in enum:
            if isinstance(opt, str) and isinstance(val, str) and opt.lower() == val.lower():
                return opt
        return enum[0]
    t = spec.get("type")
    try:
        if t == "integer":
            return int(float(val))
        if t == "number":
            return float(val)
        if t == "boolean":
            if isinstance(val, bool):
                return val
            return str(val).strip().lower() in {"1", "true", "yes", "on"}
        if t == "string":
            return str(val)
        if t == "array" and isinstance(val, list):
            item_spec = spec.get("items")
            return [_coerce_value(v, item_spec) for v in val] if isinstance(item_spec, dict) else val
    except (TypeError, ValueError):
        return _default_for(spec)
    return val


def coerce_to_schema(data: Any, schema: dict | None) -> dict:
    """Validate/repair LLM-produced ``data`` against a registered action schema."""
    if not schema or schema.get("type") != "object":
        return data if isinstance(data, dict) else {}
    if not isinstance(data, dict):
        data = {}
    props = schema.get("properties", {}) or {}
    required = schema.get("required", []) or []
    out: dict[str, Any] = {}
    for key, spec in props.items():
        spec = spec if isinstance(spec, dict) else {}
        if key in data and data[key] is not None:
            out[key] = _coerce_value(data[key], spec)
        elif "default" in spec:
            out[key] = spec["default"]
        elif key in required:
            out[key] = _default_for(spec)
    return out


class _GameConn:
    """Per-connection state for one connected game."""

    def __init__(self, ws: Any, cid: int) -> None:
        self.ws = ws
        self.id = cid
        self.game = "Game"
        self.actions: dict[str, dict] = {}          # name -> action def
        self.pending: dict[str, dict] = {}          # action id -> {force, attempt, name}
        self._counter = 0

    def next_id(self) -> str:
        self._counter += 1
        return f"{self.id}-{self._counter}"


class NeuroSdkServer:
    def __init__(
        self,
        *,
        host: str | None = None,
        port: int = DEFAULT_PORT,
        narrate: Callable[[str, str], None],
        generate: Callable[[str, int], tuple[str, str]],
        on_status: Callable[[str], None],
        on_state: Callable[[dict], None],
        remember: Callable[[str], None],
        options: Callable[[], dict[str, Any]],
    ) -> None:
        self.host = host or os.getenv("NOVA_NEURO_HOST") or os.getenv("NOVA_BIND_HOST") or "0.0.0.0"
        self.port = int(port or DEFAULT_PORT)
        self.narrate = narrate
        self.generate = generate
        self.on_status = on_status
        self.on_state = on_state
        self.remember = remember
        self._options = options

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop_event: asyncio.Event | None = None
        self._running = False
        self._conns: set[_GameConn] = set()
        self._conn_counter = 0
        self._last_action: dict | None = None
        self._last_context: str = ""

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        return self._running

    def start(self) -> dict[str, Any]:
        if websockets is None:
            return {"ok": False, "msg": "The 'websockets' package is required (pip install websockets)."}
        if self._running:
            return {"ok": True, "msg": "Already running."}
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="NovaAINeuroSDK", daemon=True)
        self._thread.start()
        self._running = True
        self.on_status(f"Neuro SDK server listening — point games to {self.connect_url()}")
        self._emit_state()
        return {"ok": True, "msg": f"Listening on {self.connect_url()}"}

    def stop(self) -> dict[str, Any]:
        self._running = False
        loop, ev = self._loop, self._stop_event
        if loop is not None and ev is not None:
            try:
                loop.call_soon_threadsafe(ev.set)
            except Exception:
                pass
        self._conns.clear()
        self._emit_state()
        return {"ok": True}

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()

        async def _serve() -> None:
            try:
                server = await websockets.serve(self._handler, self.host, self.port, max_size=2**22)
            except Exception as exc:
                self._running = False
                self.on_status(f"Neuro SDK server failed to start on {self.host}:{self.port} ({exc}).")
                return
            try:
                await self._stop_event.wait()
            finally:
                server.close()
                await server.wait_closed()

        try:
            self._loop.run_until_complete(_serve())
        except Exception:
            pass
        finally:
            self._running = False

    # ── connection handling ───────────────────────────────────────────────────

    async def _handler(self, websocket: Any, path: str | None = None) -> None:
        self._conn_counter += 1
        conn = _GameConn(websocket, self._conn_counter)
        self._conns.add(conn)
        self._emit_state()
        # Optional: let NovaAI act on her own between forces (for action games
        # that never call actions/force). Gated live by the "proactive" option.
        proactive_task = asyncio.create_task(self._proactive_loop(conn))
        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if isinstance(msg, dict):
                    await self._dispatch(conn, msg)
        except Exception:
            pass
        finally:
            proactive_task.cancel()
            self._conns.discard(conn)
            self.on_status(f"{conn.game} disconnected.")
            self._emit_state()

    async def _proactive_loop(self, conn: _GameConn) -> None:
        """When enabled, periodically decide whether to act unprompted."""
        loop = asyncio.get_event_loop()
        try:
            while conn in self._conns:
                opts = self._options() or {}
                interval = max(3.0, float(opts.get("proactive_seconds", 8)))
                await asyncio.sleep(interval)
                if not opts.get("proactive", False):
                    continue
                # Don't barge in while a forced/queued action is still resolving.
                if conn.pending or not conn.actions:
                    continue
                decision = await loop.run_in_executor(None, self._decide_proactive, conn)
                if decision and decision.get("act") and decision.get("name"):
                    await self._send_decision(conn, None, decision, attempt=1)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _dispatch(self, conn: _GameConn, msg: dict) -> None:
        command = msg.get("command")
        data = msg.get("data") or {}
        if command == "startup":
            conn.game = msg.get("game") or conn.game
            conn.actions.clear()
            conn.pending.clear()
            self.on_status(f"🎮 {conn.game} connected (Neuro SDK).")
            self._emit_state()
        elif command == "actions/register":
            for action in data.get("actions", []) or []:
                name = action.get("name")
                if name:
                    conn.actions[name] = action
            self._emit_state()
        elif command == "actions/unregister":
            for name in data.get("action_names", []) or []:
                conn.actions.pop(name, None)
            self._emit_state()
        elif command == "context":
            await self._handle_context(conn, data)
        elif command == "actions/force":
            asyncio.create_task(self._do_force(conn, data))
        elif command == "action/result":
            await self._handle_result(conn, data)
        # Unknown commands are ignored per the spec's forward-compatibility note.

    async def _handle_context(self, conn: _GameConn, data: dict) -> None:
        message = (data.get("message") or "").strip()
        if not message:
            return
        self._last_context = message
        self.on_status(f"[{conn.game}] {message}")
        try:
            self.remember(f"[{conn.game}] {message}")
        except Exception:
            pass
        self._emit_state()
        opts = self._options() or {}
        # silent=true → context only, no spoken reaction. Otherwise NovaAI may react.
        if not data.get("silent", False) and opts.get("speak_context", True):
            loop = asyncio.get_event_loop()
            prompt = (
                f"You are NovaAI playing {conn.game} live on stream. Something just "
                f"happened: \"{message}\". React in ONE short, in-character sentence "
                "(no quotes, under 20 words)."
            )
            text, emotion = await loop.run_in_executor(None, self.generate, prompt, 60)
            text = (text or "").strip().strip('"')
            if text:
                await loop.run_in_executor(None, self.narrate, text, emotion or "neutral")

    async def _do_force(self, conn: _GameConn, force: dict) -> None:
        names = [n for n in (force.get("action_names") or []) if n in conn.actions]
        if not names:
            self.on_status(f"{conn.game}: forced action with no registered actions — skipped.")
            return
        loop = asyncio.get_event_loop()
        decision = await loop.run_in_executor(None, self._decide, conn, force, names, None)
        await self._send_decision(conn, force, decision, attempt=1)

    async def _send_decision(self, conn: _GameConn, force: dict, decision: dict, attempt: int) -> None:
        aid = conn.next_id()
        conn.pending[aid] = {"force": force, "attempt": attempt, "name": decision["name"]}
        out: dict[str, Any] = {"command": "action", "data": {"id": aid, "name": decision["name"]}}
        if decision.get("has_schema"):
            out["data"]["data"] = json.dumps(decision.get("data") or {})
        try:
            await conn.ws.send(json.dumps(out))
        except Exception:
            conn.pending.pop(aid, None)
            return
        self._last_action = {"game": conn.game, "name": decision["name"], "data": decision.get("data")}
        self._emit_state()
        say = (decision.get("say") or "").strip()
        opts = self._options() or {}
        if say and opts.get("commentary", True):
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.narrate, say, decision.get("emotion", "neutral"))

    async def _handle_result(self, conn: _GameConn, data: dict) -> None:
        aid = data.get("id")
        pending = conn.pending.pop(aid, None) if aid else None
        if pending is None:
            return
        success = data.get("success")
        rmsg = (data.get("message") or "").strip()
        if success is False:
            opts = self._options() or {}
            max_retries = int(opts.get("max_retries", 2))
            force = pending.get("force")
            if force and pending["attempt"] < max_retries:
                names = [n for n in (force.get("action_names") or []) if n in conn.actions]
                if names:
                    loop = asyncio.get_event_loop()
                    decision = await loop.run_in_executor(
                        None, self._decide, conn, force, names, rmsg or "previous action was rejected"
                    )
                    await self._send_decision(conn, force, decision, pending["attempt"] + 1)
                    return
            self.on_status(f"{conn.game}: action '{pending['name']}' rejected — giving up. {rmsg}")
        elif rmsg:
            self.on_status(f"{conn.game}: {pending['name']} ✓ {rmsg}")

    # ── decision (LLM) ────────────────────────────────────────────────────────

    def _decide(self, conn: _GameConn, force: dict, names: list[str], feedback: str | None) -> dict:
        """Pick ONE action + its parameters via the LLM. Always returns something legal."""
        opts = self._options() or {}
        ai_name = opts.get("ai_name", "NovaAI")
        state = force.get("state") or ""
        query = force.get("query") or "It is your turn. Choose an action."
        lines = []
        for i, name in enumerate(names, 1):
            action = conn.actions.get(name, {})
            desc = action.get("description", "")
            schema = action.get("schema")
            schema_txt = json.dumps(schema) if schema else "no parameters"
            lines.append(f"{i}. {name} — {desc}\n   parameters: {schema_txt}")
        actions_block = "\n".join(lines)
        feedback_block = f"\nYour previous choice was rejected: {feedback}. Pick differently.\n" if feedback else ""
        prompt = (
            f"You are {ai_name}, an AI playing the game \"{conn.game}\" live on stream.\n"
            f"Current game state:\n{state}\n\n"
            f"Instruction: {query}\n\n"
            f"Choose EXACTLY ONE of these actions:\n{actions_block}\n"
            f"{feedback_block}\n"
            "Respond with ONLY a JSON object (no other text):\n"
            '{"action": "<one action name from the list>", '
            '"data": <object matching that action\'s parameters, or {} if none>, '
            '"say": "<one short in-character sentence reacting>"}'
        )
        try:
            text, emotion = self.generate(prompt, 240)
        except Exception:
            text, emotion = "", "neutral"
        parsed = _extract_json(text) or {}
        name = parsed.get("action")
        if name not in names:
            name = self._closest_name(name, names) or names[0]
        action = conn.actions.get(name, {})
        schema = action.get("schema")
        data = coerce_to_schema(parsed.get("data"), schema) if schema else {}
        say = parsed.get("say") if isinstance(parsed.get("say"), str) else ""
        return {"name": name, "data": data, "has_schema": bool(schema),
                "say": say or "", "emotion": emotion or "neutral"}

    def _decide_proactive(self, conn: _GameConn) -> dict:
        """Decide whether to act unprompted (proactive mode). May choose to wait."""
        opts = self._options() or {}
        ai_name = opts.get("ai_name", "NovaAI")
        names = list(conn.actions.keys())
        if not names:
            return {"act": False}
        lines = []
        for name in names:
            a = conn.actions.get(name, {})
            schema = a.get("schema")
            lines.append(f"- {name} — {a.get('description', '')}"
                         + (f" (params: {json.dumps(schema)})" if schema else ""))
        prompt = (
            f"You are {ai_name}, playing \"{conn.game}\" live on stream, acting on your own.\n"
            f"Recent events: {self._last_context or '(nothing notable yet)'}\n\n"
            f"Available actions:\n" + "\n".join(lines) + "\n\n"
            "Decide whether to take an action right now. If nothing is clearly worth doing, WAIT.\n"
            "Respond with ONLY JSON: {\"act\": true|false, \"action\": \"<name or empty>\", "
            "\"data\": <object or {}>, \"say\": \"<one short sentence or empty>\"}"
        )
        try:
            text, emotion = self.generate(prompt, 200)
        except Exception:
            return {"act": False}
        parsed = _extract_json(text) or {}
        if not parsed.get("act"):
            return {"act": False}
        name = parsed.get("action")
        if name not in names:
            name = self._closest_name(name, names)
        if not name:
            return {"act": False}
        schema = conn.actions.get(name, {}).get("schema")
        data = coerce_to_schema(parsed.get("data"), schema) if schema else {}
        say = parsed.get("say") if isinstance(parsed.get("say"), str) else ""
        return {"act": True, "name": name, "data": data, "has_schema": bool(schema),
                "say": say or "", "emotion": emotion or "neutral"}

    @staticmethod
    def _closest_name(guess: Any, names: list[str]) -> str | None:
        if not isinstance(guess, str):
            return None
        g = guess.strip().lower()
        for n in names:
            if n.lower() == g:
                return n
        for n in names:
            if g and (g in n.lower() or n.lower() in g):
                return n
        return None

    # ── status ────────────────────────────────────────────────────────────────

    def advertised_host(self) -> str:
        return _local_ip() if self.host in {"0.0.0.0", "::", ""} else self.host

    def connect_url(self) -> str:
        return f"ws://{self.advertised_host()}:{self.port}"

    def status(self) -> dict[str, Any]:
        games = [{"game": c.game, "actions": sorted(c.actions.keys())} for c in list(self._conns)]
        return {
            "running": self._running,
            "host": self.host,
            "port": self.port,
            "connect_url": self.connect_url(),
            "env_var": "NEURO_SDK_WS_URL",
            "games": games,
            "connections": len(self._conns),
            "last_action": self._last_action,
            "last_context": self._last_context,
        }

    def _emit_state(self) -> None:
        try:
            self.on_state(self.status())
        except Exception:
            pass
