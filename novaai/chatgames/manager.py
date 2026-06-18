"""Drives a chat-vs-AI game: turns, the chat voting window, NovaAI's moves, and
commentary. This is the only stateful piece — the games themselves are pure rules.

The loop, per game:
  1. Chat's turn  → open a voting window; chatters type moves; at the buzzer the
     most-voted legal move is played (ties broken at random; silence → random move).
  2. NovaAI's turn → a short suspense delay, then the engine move + trash talk.
Repeat until someone wins / draws, announce it, and (optionally) auto-rematch.

All the I/O — pushing the overlay, posting to Twitch chat, speaking — is injected
as callbacks so this stays UI-agnostic (mirrors how ``GameAgent`` takes
``narrate``/``on_update`` from ``webgui.Api``).
"""
from __future__ import annotations

import random
import threading
import time
from collections import Counter
from typing import Any, Callable

from .base import AI, CHAT
from . import build_game


class ChatGameManager:
    def __init__(
        self,
        *,
        narrate: Callable[[str, str], None],
        on_update: Callable[[dict], None],
        send_chat: Callable[[str], None],
        commentate: Callable[[str, str, str], tuple[str, str]],
        get_options: Callable[[], dict[str, Any]],
    ) -> None:
        self._narrate = narrate
        self._on_update = on_update
        self._send_chat = send_chat
        self._commentate = commentate
        self._get_options = get_options

        self.game = None
        self.game_key: str | None = None
        self._thread: threading.Thread | None = None
        # The thread that is *authoritatively* the current game loop. A stop() may
        # not be able to join a thread blocked in a long vote window before the
        # next start() clears _stop, so we also gate every loop on being the
        # active thread — that way an old (zombie) loop exits instead of running
        # against torn-down state (which caused random.choice([]) crashes).
        self._active_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._votes: dict[str, str] = {}     # username -> move token (last vote wins)
        self._voting_open = False
        self._deadline = 0.0
        self._phase = "idle"                  # idle | voting | thinking | over
        self._opts: dict[str, Any] = {}
        self._last_vote_push = 0.0

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        return self.game is not None and self._thread is not None and self._thread.is_alive()

    def _alive(self) -> bool:
        """True only for the current loop thread that hasn't been stopped."""
        return threading.current_thread() is self._active_thread and not self._stop.is_set()

    def start(self, key: str) -> dict[str, Any]:
        if self.is_running():
            self.stop()
        opts = self._get_options() or {}
        starter = opts.get("starter") or CHAT
        try:
            self.game = build_game(key, starter=starter)
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}
        self.game_key = key
        self._stop.clear()
        self._votes = {}
        self._phase = "idle"
        self._thread = threading.Thread(target=self._loop, name="NovaAIChatGame", daemon=True)
        self._active_thread = self._thread
        self._thread.start()
        return {"ok": True, "msg": f"{self.game.title} started."}

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        self._voting_open = False
        # Disown the loop thread immediately so it can't act even if it's blocked
        # in a vote window and outlives the join below.
        self._active_thread = None
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=2.0)
        self.game = None
        self.game_key = None
        self._phase = "idle"
        self._push()
        return {"ok": True}

    # ── voting ────────────────────────────────────────────────────────────────

    def register_vote(self, username: str, text: str) -> None:
        """Feed a raw Twitch chat line in as a possible vote (no-op off-turn)."""
        game = self.game
        if not self._voting_open or game is None:
            return
        try:
            move = game.parse_vote(text)
        except Exception:
            return
        if move is None:
            return
        with self._lock:
            self._votes[username] = move
        # Throttle overlay refreshes so a busy chat doesn't spam the SSE stream.
        now = time.time()
        if now - self._last_vote_push > 0.35:
            self._last_vote_push = now
            self._push()

    def _tally(self) -> str | None:
        with self._lock:
            votes = list(self._votes.values())
        if not votes:
            return None
        counts = Counter(votes)
        top = max(counts.values())
        winners = [m for m, n in counts.items() if n == top]
        return random.choice(winners)

    def _vote_counts(self) -> dict[str, int]:
        with self._lock:
            return dict(Counter(self._votes.values()))

    # ── main loop ─────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._alive():
            game = self.game
            if game is None:
                return
            game.reset()
            self._opts = self._get_options() or {}
            self._announce_start()
            self._phase = "voting" if game.current_player == CHAT else "thinking"
            self._push()
            while self._alive() and not game.over:
                self._opts = self._get_options() or {}
                # A side with no legal move passes (e.g. Reversi). Games without a
                # pass concept never hit this (empty legal_moves ⇒ game over).
                if not game.legal_moves():
                    if hasattr(game, "pass_turn"):
                        passer = game.current_player
                        game.pass_turn()
                        self._phase = self._phase_after()
                        self._push()
                        if not game.over:
                            self._send_chat(f"{'Chat' if passer == CHAT else 'NovaAI'} has no move — pass!")
                        continue
                    break
                if game.current_player == CHAT:
                    self._chat_turn()
                else:
                    self._ai_turn()
            if not self._alive():
                return
            self._phase = "over"
            self._push()
            self._announce_winner()
            if not self._opts.get("auto_restart", True):
                return
            # Brief intermission before the rematch.
            if not self._sleep(float(self._opts.get("restart_seconds", 7))):
                return

    def _chat_turn(self) -> None:
        game = self.game
        if game is None:
            return
        secs = max(5, int(self._opts.get("vote_seconds", 15)))
        with self._lock:
            self._votes = {}
        self._voting_open = True
        self._deadline = time.time() + secs
        self._phase = "voting"
        self._push()
        self._send_chat(f"🗳️ Chat's turn! {game.vote_hint()} — {secs}s on the clock.")
        # Wait out the clock; votes arrive via register_vote(). Push ~1/s so the
        # overlay countdown + tallies stay fresh even with no new votes.
        while time.time() < self._deadline and self._alive():
            self._push()
            self._stop.wait(min(1.0, max(0.0, self._deadline - time.time())))
        self._voting_open = False
        # Bail if we were stopped/superseded or the game ended/changed under us —
        # otherwise random.choice() below can hit an empty move list and crash.
        if not self._alive() or game is not self.game or game.over:
            return
        legal = game.legal_moves()
        if not legal:
            return
        move = self._tally()
        quiet = move is None
        if quiet:
            move = random.choice(legal)
        event = game.apply_move(move, CHAT)
        self._phase = self._phase_after()
        self._push()
        label = game.move_label(move)
        if quiet:
            self._send_chat(f"⏱️ Chat was quiet — random move: {label}.")
        else:
            self._send_chat(f"Chat plays {label}.")
        self._maybe_comment(CHAT, move, event, quiet)

    def _ai_turn(self) -> None:
        game = self.game
        if game is None:
            return
        self._phase = "thinking"
        self._push()
        # Suspense beat before NovaAI commits (also lets her speak between turns).
        self._sleep(float(self._opts.get("ai_delay", 2.5)))
        if not self._alive() or game is not self.game or game.over:
            return
        move = game.ai_choose()
        if not move or move not in game.legal_moves():
            return
        event = game.apply_move(move, AI)
        self._phase = self._phase_after()
        self._push()
        self._maybe_comment(AI, move, event, False)

    def _phase_after(self) -> str:
        g = self.game
        if g is None or g.over:
            return "over"
        return "voting" if g.current_player == CHAT else "thinking"

    # ── commentary ────────────────────────────────────────────────────────────

    def _maybe_comment(self, player: str, move: str, event: dict, quiet: bool) -> None:
        if not self._opts.get("commentary", True):
            return
        game = self.game
        event = event or {}
        note = event.get("note", "move")
        react = event.get("react")
        desc = event.get("desc")
        label = game.move_label(move)
        ai_name = self._opts.get("ai_name", "NovaAI")
        # Comment on every NovaAI move, and on chat moves only when the game asked
        # (event["react"]) or chat just made a threat — so she isn't talking nonstop.
        if player == CHAT and not react and note not in {"threat"}:
            return
        if desc:
            # Game-supplied description of what just happened — most games use this.
            ctx = (f"In {game.title}, {desc}. React in ONE short, playful, in-character "
                   "sentence (no quotes, under 20 words).")
            fallback = desc[:1].upper() + desc[1:] + "."
            emo = "excited" if note in {"win", "sunk", "hit"} else ("sad" if note == "boom" else "neutral")
        elif player == AI:
            ctx, fallback, emo = self._ai_context(note, label, ai_name)
        else:
            ctx = (f"In {game.title}, Twitch chat just played {label} and now threatens "
                   f"to win next turn. React in ONE short, playful sentence.")
            fallback, emo = f"Ooh, nice one chat — {label}. But I'm not done yet. 😼", "surprised"
        try:
            text, emotion = self._commentate(ctx, fallback, emo)
        except Exception:
            text, emotion = fallback, emo
        if text:
            self._narrate(text, emotion or emo)

    def _ai_context(self, note: str, label: str, ai_name: str) -> tuple[str, str, str]:
        game_title = self.game.title
        if note == "win":
            return (
                f"You ({ai_name}) just played {label} and WON {game_title} against Twitch chat. "
                "Gloat in ONE short, cute-but-smug sentence.",
                f"And that's four — {label} for the win! Better luck next time, chat. 😏",
                "excited",
            )
        if note == "threat":
            return (
                f"You ({ai_name}) just played {label} in {game_title}, setting up a winning "
                "threat against Twitch chat. Taunt chat in ONE short sentence.",
                f"I'll take {label}. Careful chat, I'm one move from winning~",
                "happy",
            )
        if note == "boom":  # AI revealed a mine -> AI lost
            return (
                f"You ({ai_name}) just revealed a MINE at {label} and lost {game_title} to chat. "
                "React in ONE short, dramatic-but-good-humored sentence.",
                f"NO— {label} was a mine?! Okay chat, you win this one. 😵",
                "surprised",
            )
        if note == "safe":
            return (
                f"You ({ai_name}) safely revealed {label} in {game_title}. Say ONE short, "
                "confident sentence.",
                f"{label}? Safe. I read the board. 😎",
                "happy",
            )
        return (
            f"You ({ai_name}) just played {label} in {game_title} against Twitch chat. "
            "Say ONE short, in-character sentence.",
            f"My move: {label}. Your turn, chat~",
            "neutral",
        )

    def _announce_start(self) -> None:
        g = self.game
        self._narrate(f"New game — {g.title}! It's me versus chat. {g.vote_hint()} to play. 🎮", "excited")

    def _announce_winner(self) -> None:
        g = self.game
        if g.winner == AI:
            ctx = f"You just WON {g.title} against Twitch chat. Celebrate in ONE short sentence."
            fb, emo = "GG chat — I win! Rematch? 😼", "excited"
        elif g.winner == CHAT:
            ctx = f"Twitch chat just BEAT you at {g.title}. Be a good sport in ONE short sentence."
            fb, emo = "Okay okay, chat wins that one. Well played! Run it back? 😤", "surprised"
        else:
            ctx = f"{g.title} ended in a draw with Twitch chat. React in ONE short sentence."
            fb, emo = "A draw?! We're too evenly matched, chat. Again!", "happy"
        try:
            text, emotion = self._commentate(ctx, fb, emo)
        except Exception:
            text, emotion = fb, emo
        self._narrate(text or fb, emotion or emo)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _sleep(self, seconds: float) -> bool:
        """Sleep, but wake early if stopped. Returns False if a stop was requested."""
        return not self._stop.wait(max(0.0, seconds))

    def state(self) -> dict[str, Any]:
        g = self.game
        if g is None:
            return {"active": False}
        opts = self._opts or self._get_options() or {}
        return {
            "active": True,
            "key": g.key,
            "title": g.title,
            "turn": g.current_player,
            "phase": self._phase,
            "status_text": g.status_text(),
            "winner": g.winner,
            "over": g.over,
            "deadline_ms": int(self._deadline * 1000) if self._voting_open else 0,
            "vote_seconds": int(opts.get("vote_seconds", 15)),
            "votes": self._vote_counts(),
            "voters": len(self._votes),
            "vote_hint": g.vote_hint(),
            "players": {
                "ai": {"name": opts.get("ai_name", "NovaAI")},
                "chat": {"name": "Chat"},
            },
            "board": g.render(),
            "last": g.last_move,
        }

    def _push(self) -> None:
        try:
            self._on_update(self.state())
        except Exception:
            pass
