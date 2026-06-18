"""Tic-Tac-Toe — Twitch chat vs NovaAI.

Chat votes a cell (1-9, left-to-right, top-to-bottom); NovaAI plays a full
minimax engine, so it never loses — the best chat can force is a draw.
"""
from __future__ import annotations

import re
from typing import Any

from .base import AI, CHAT, ChatGame

EMPTY = 0
_DISC = {CHAT: 1, AI: 2}
_SIDE = {1: CHAT, 2: AI}
_LINES = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),   # rows
    (0, 3, 6), (1, 4, 7), (2, 5, 8),   # cols
    (0, 4, 8), (2, 4, 6),              # diagonals
]


class TicTacToeGame(ChatGame):
    key = "tictactoe"
    title = "Tic-Tac-Toe"

    def reset(self) -> None:
        super().reset()
        self.cells = [EMPTY] * 9
        self.win_line: list[int] = []

    def legal_moves(self) -> list[str]:
        if self.over:
            return []
        return [str(i + 1) for i in range(9) if self.cells[i] == EMPTY]

    def parse_vote(self, text: str) -> str | None:
        for m in re.findall(r"\d", text or ""):
            n = int(m)
            if 1 <= n <= 9 and self.cells[n - 1] == EMPTY:
                return str(n)
        return None

    def apply_move(self, move: str, player: str) -> dict[str, Any]:
        try:
            idx = int(move) - 1
        except (TypeError, ValueError):
            return {"ok": False}
        if not (0 <= idx < 9) or self.cells[idx] != EMPTY:
            return {"ok": False}
        self.cells[idx] = _DISC[player]
        self.last_move = {"player": player, "cell": idx + 1}
        line = self._winner_line()
        if line:
            self.over = True
            self.winner = player
            self.win_line = list(line)
            return {"ok": True, "move": move, "note": "win"}
        if all(c != EMPTY for c in self.cells):
            self.over = True
            self.winner = "draw"
            return {"ok": True, "move": move, "note": "draw"}
        self._switch()
        return {"ok": True, "move": move, "note": "move"}

    def _winner_line(self):
        for a, b, c in _LINES:
            if self.cells[a] != EMPTY and self.cells[a] == self.cells[b] == self.cells[c]:
                return (a, b, c)
        return None

    # ── AI (minimax, perfect play) ────────────────────────────────────────────

    def ai_choose(self) -> str:
        best, best_score = None, -10
        for i in range(9):
            if self.cells[i] == EMPTY:
                self.cells[i] = _DISC[AI]
                score = self._minimax(False)
                self.cells[i] = EMPTY
                if score > best_score:
                    best_score, best = score, i
        return str((best if best is not None else 0) + 1)

    def _minimax(self, maximizing: bool) -> int:
        line = self._winner_line()
        if line:
            who = _SIDE[self.cells[line[0]]]
            return 1 if who == AI else -1
        if all(c != EMPTY for c in self.cells):
            return 0
        disc = _DISC[AI] if maximizing else _DISC[CHAT]
        scores = []
        for i in range(9):
            if self.cells[i] == EMPTY:
                self.cells[i] = disc
                scores.append(self._minimax(not maximizing))
                self.cells[i] = EMPTY
        return max(scores) if maximizing else min(scores)

    # ── presentation ──────────────────────────────────────────────────────────

    def move_label(self, move: str) -> str:
        return f"cell {move}"

    def vote_hint(self) -> str:
        return "type a cell number 1-9"

    def render(self) -> dict[str, Any]:
        grid = [["" if v == EMPTY else _SIDE[v] for v in self.cells[r * 3:r * 3 + 3]] for r in range(3)]
        win_cells = [[i // 3, i % 3] for i in self.win_line]
        return {"variant": "grid3", "cols": 3, "rows": 3, "grid": grid, "win_cells": win_cells,
                "last_cell": (self.last_move or {}).get("cell")}
