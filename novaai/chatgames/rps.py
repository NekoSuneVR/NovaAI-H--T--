"""Rock-Paper-Scissors — Twitch chat vs NovaAI (best of 5).

Each round chat votes ``rock``/``paper``/``scissors`` (or r/p/s). NovaAI commits
its throw from a frequency model of chat's past throws — it predicts chat's most
common pick and counters it — so it's beatable but reads patterns. First to 3
wins. Both sides "throw" each round, so this game has chat-only turns: NovaAI's
throw is revealed when the round resolves.
"""
from __future__ import annotations

import random
from collections import Counter
from typing import Any

from .base import AI, CHAT, ChatGame

_NAMES = {"r": "Rock", "p": "Paper", "s": "Scissors"}
_BEATS = {"r": "s", "p": "r", "s": "p"}      # key beats value
_COUNTER = {"r": "p", "p": "s", "s": "r"}    # what beats key
_TARGET = 3                                   # first to 3 wins (best of 5)


class RockPaperScissorsGame(ChatGame):
    key = "rps"
    title = "Rock Paper Scissors"

    def reset(self) -> None:
        super().reset()
        self.current_player = CHAT  # RPS is resolved on chat's vote each round
        self.score = {CHAT: 0, AI: 0}
        self.round = 1
        self.history: list[str] = []   # chat's past throws (for the AI model)
        self.last_round: dict[str, Any] | None = None

    def legal_moves(self) -> list[str]:
        return [] if self.over else ["r", "p", "s"]

    def parse_vote(self, text: str) -> str | None:
        low = (text or "").lower()
        for word, tok in (("rock", "r"), ("paper", "p"), ("scissors", "s")):
            if word in low:
                return tok
        for ch in low:
            if ch in ("r", "p", "s"):
                return ch
        return None

    def _ai_throw(self) -> str:
        if not self.history:
            return random.choice("rps")
        predicted = Counter(self.history).most_common(1)[0][0]
        return _COUNTER[predicted]  # counter chat's most frequent throw

    def apply_move(self, move: str, player: str) -> dict[str, Any]:
        chat_throw = move if move in ("r", "p", "s") else None
        if chat_throw is None:
            return {"ok": False}
        ai_throw = self._ai_throw()
        self.history.append(chat_throw)
        if chat_throw == ai_throw:
            result = "draw"
        elif _BEATS[chat_throw] == ai_throw:
            result = "chat"
            self.score[CHAT] += 1
        else:
            result = "ai"
            self.score[AI] += 1
        self.last_round = {"chat": chat_throw, "ai": ai_throw, "result": result, "round": self.round}
        self.last_move = self.last_round
        outcome = ("you both threw " + _NAMES[chat_throw] if result == "draw"
                   else f"chat threw {_NAMES[chat_throw]}, you threw {_NAMES[ai_throw]} — "
                        + ("chat won the round" if result == "chat" else "you won the round"))
        if self.score[CHAT] >= _TARGET or self.score[AI] >= _TARGET:
            self.over = True
            self.winner = CHAT if self.score[CHAT] > self.score[AI] else AI
            return {"ok": True, "move": move, "note": "win", "react": True, "desc": outcome + " and the match"}
        self.round += 1
        # current_player stays CHAT — every round is a chat vote.
        return {"ok": True, "move": move, "note": result, "react": True, "desc": outcome}

    def ai_choose(self) -> str:
        return self._ai_throw()  # unused (chat-only turns) but kept for the interface

    # ── presentation ──────────────────────────────────────────────────────────

    def move_label(self, move: str) -> str:
        return _NAMES.get(move, move)

    def vote_hint(self) -> str:
        return "type rock, paper, or scissors (r/p/s)"

    def status_text(self) -> str:
        if self.over:
            return "NovaAI wins the match!" if self.winner == AI else "Chat wins the match!"
        return f"Round {self.round} — first to {_TARGET}"

    def render(self) -> dict[str, Any]:
        return {
            "variant": "rps", "target": _TARGET, "round": self.round,
            "score": {"chat": self.score[CHAT], "ai": self.score[AI]},
            "names": _NAMES, "last": self.last_round,
        }
