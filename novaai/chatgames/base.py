"""Chat-vs-AI game contract.

These are turn-based games where **Twitch chat plays one side and NovaAI plays
the other** (Neuro-sama style): chat votes a move during a countdown, the most
voted legal move is played, then NovaAI replies with a deterministic engine move
and some in-character trash talk. This is a different interaction model from the
autonomous ``GameAgent`` (which plays single-player games by itself), so it lives
in its own subsystem with its own turn/vote loop (see ``manager.py``).

A ``ChatGame`` owns ONLY the rules + the AI move. It knows nothing about Twitch,
timers, voting, TTS, or the overlay — the ``ChatGameManager`` drives all of that
through this small interface, exactly like ``GameDriver`` keeps the agent brain
game-agnostic.
"""
from __future__ import annotations

from typing import Any

# The two sides. "chat" = Twitch chat (votes), "ai" = NovaAI (engine move).
CHAT = "chat"
AI = "ai"


class ChatGame:
    """Base class for a turn-based chat-vs-AI game.

    Subclasses implement the rules; the manager only ever calls this interface.
    Move "tokens" are short strings (e.g. ``"4"`` for a Connect 4 column or
    ``"c4"`` for a Minesweeper cell) so they round-trip cleanly through chat
    votes, the overlay, and JSON.
    """

    key: str = "game"
    title: str = "Game"

    def __init__(self, starter: str = CHAT, **_: Any) -> None:
        self.starter = starter if starter in (CHAT, AI) else CHAT
        self.current_player: str = self.starter
        self.over: bool = False
        self.winner: str | None = None  # "chat" | "ai" | "draw" | None
        self.last_move: dict[str, Any] | None = None
        self.reset()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Reset to a fresh game (also called once by __init__)."""
        self.current_player = self.starter
        self.over = False
        self.winner = None
        self.last_move = None

    # ── rules (subclass responsibilities) ─────────────────────────────────────

    def legal_moves(self) -> list[str]:
        """All move tokens that are currently playable."""
        raise NotImplementedError

    def parse_vote(self, text: str) -> str | None:
        """Turn a raw chat line into a legal move token, or None if it isn't one."""
        raise NotImplementedError

    def apply_move(self, move: str, player: str) -> dict[str, Any]:
        """Play ``move`` for ``player``; update state, turn, over/winner.

        Returns a small event dict describing what happened (used to drive
        commentary), e.g. ``{"ok": True, "move": "4", "note": "win"}``.
        """
        raise NotImplementedError

    def ai_choose(self) -> str:
        """Return NovaAI's move token (must be legal). Deterministic engine."""
        raise NotImplementedError

    def render(self) -> dict[str, Any]:
        """Game-specific board snapshot for the overlay (no turn/vote info)."""
        raise NotImplementedError

    # ── presentation helpers (override when useful) ───────────────────────────

    def move_label(self, move: str) -> str:
        """Human-friendly label for a move token (for chat + commentary)."""
        return str(move)

    def vote_hint(self) -> str:
        """Short instruction shown to chat for how to vote."""
        return "type your move"

    def status_text(self) -> str:
        """One-line status for the overlay header."""
        if self.over:
            if self.winner == "draw":
                return "Draw!"
            if self.winner == AI:
                return "NovaAI wins!"
            if self.winner == CHAT:
                return "Chat wins!"
            return "Game over"
        return "Chat's turn" if self.current_player == CHAT else "NovaAI's turn"

    def _switch(self) -> None:
        self.current_player = AI if self.current_player == CHAT else CHAT
