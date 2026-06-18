"""Reversi / Othello — Twitch chat vs NovaAI.

Chat votes a square (e.g. ``d3``); NovaAI plays a positional engine that prizes
corners and edges. Flank the opponent's discs to flip them; most discs when the
board fills (or both sides are stuck) wins. A side with no legal move passes.
"""
from __future__ import annotations

import re
from typing import Any

from .base import AI, CHAT, ChatGame

SIZE = 8
EMPTY = 0
_DISC = {CHAT: 1, AI: 2}
_SIDE = {1: CHAT, 2: AI}
_LETTERS = "abcdefgh"
_DIRS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

# Positional weights — corners are gold, the squares next to them are traps.
_WEIGHTS = [
    [120, -20, 20, 5, 5, 20, -20, 120],
    [-20, -40, -5, -5, -5, -5, -40, -20],
    [20, -5, 15, 3, 3, 15, -5, 20],
    [5, -5, 3, 3, 3, 3, -5, 5],
    [5, -5, 3, 3, 3, 3, -5, 5],
    [20, -5, 15, 3, 3, 15, -5, 20],
    [-20, -40, -5, -5, -5, -5, -40, -20],
    [120, -20, 20, 5, 5, 20, -20, 120],
]


def _tok(r: int, c: int) -> str:
    return f"{_LETTERS[c]}{r + 1}"


class ReversiGame(ChatGame):
    key = "reversi"
    title = "Reversi"

    def reset(self) -> None:
        super().reset()
        self.board = [[EMPTY] * SIZE for _ in range(SIZE)]
        m = SIZE // 2
        self.board[m - 1][m - 1] = _DISC[AI]
        self.board[m][m] = _DISC[AI]
        self.board[m - 1][m] = _DISC[CHAT]
        self.board[m][m - 1] = _DISC[CHAT]
        self._passes = 0

    # ── rules ─────────────────────────────────────────────────────────────────

    def _flips(self, board, r, c, disc) -> list[tuple[int, int]]:
        if board[r][c] != EMPTY:
            return []
        opp = 3 - disc
        out: list[tuple[int, int]] = []
        for dr, dc in _DIRS:
            line: list[tuple[int, int]] = []
            nr, nc = r + dr, c + dc
            while 0 <= nr < SIZE and 0 <= nc < SIZE and board[nr][nc] == opp:
                line.append((nr, nc))
                nr += dr
                nc += dc
            if line and 0 <= nr < SIZE and 0 <= nc < SIZE and board[nr][nc] == disc:
                out.extend(line)
        return out

    def _legal_for(self, disc) -> list[tuple[int, int]]:
        return [(r, c) for r in range(SIZE) for c in range(SIZE) if self._flips(self.board, r, c, disc)]

    def legal_moves(self) -> list[str]:
        if self.over:
            return []
        return [_tok(r, c) for r, c in self._legal_for(_DISC[self.current_player])]

    def parse_vote(self, text: str) -> str | None:
        m = re.search(r"([a-h])\s*([1-8])", (text or "").lower())
        if not m:
            return None
        tok = m.group(1) + m.group(2)
        return tok if tok in self.legal_moves() else None

    def apply_move(self, move: str, player: str) -> dict[str, Any]:
        try:
            c = _LETTERS.index(move[0])
            r = int(move[1]) - 1
        except (ValueError, IndexError):
            return {"ok": False}
        disc = _DISC[player]
        flips = self._flips(self.board, r, c, disc)
        if not flips:
            return {"ok": False}
        self.board[r][c] = disc
        for fr, fc in flips:
            self.board[fr][fc] = disc
        self._passes = 0
        self.last_move = {"player": player, "cell": _tok(r, c), "flipped": len(flips)}
        self._switch()
        if not self._legal_for(_DISC[self.current_player]):
            # Opponent has no move; if neither side can move, the game is over.
            self._switch()
            if not self._legal_for(_DISC[self.current_player]):
                self._finish()
        return {"ok": True, "move": move, "note": "move", "react": len(flips) >= 4,
                "desc": f"chat flipped {len(flips)} discs at {move.upper()}" if player == CHAT
                        else f"you flipped {len(flips)} discs at {move.upper()}"}

    def pass_turn(self) -> None:
        """Current player has no legal move — pass (two passes ends the game)."""
        self._passes += 1
        self._switch()
        if self._passes >= 2 or not self._legal_for(_DISC[self.current_player]):
            self._finish()

    def _finish(self) -> None:
        chat = sum(row.count(_DISC[CHAT]) for row in self.board)
        ai = sum(row.count(_DISC[AI]) for row in self.board)
        self.over = True
        self.winner = AI if ai > chat else CHAT if chat > ai else "draw"

    # ── AI (positional greedy) ────────────────────────────────────────────────

    def ai_choose(self) -> str:
        moves = self._legal_for(_DISC[AI])
        if not moves:
            return ""
        best, best_score = moves[0], -10**9
        for r, c in moves:
            flips = self._flips(self.board, r, c, _DISC[AI])
            score = _WEIGHTS[r][c] + sum(_WEIGHTS[fr][fc] for fr, fc in flips)
            if score > best_score:
                best_score, best = score, (r, c)
        return _tok(*best)

    # ── presentation ──────────────────────────────────────────────────────────

    def move_label(self, move: str) -> str:
        return move.upper()

    def vote_hint(self) -> str:
        return "type a square like D3"

    def render(self) -> dict[str, Any]:
        grid = [[("" if v == EMPTY else _SIDE[v]) for v in row] for row in self.board]
        legal = [_tok(r, c) for r, c in self._legal_for(_DISC[self.current_player])] if not self.over else []
        chat = sum(row.count(_DISC[CHAT]) for row in self.board)
        ai = sum(row.count(_DISC[AI]) for row in self.board)
        return {
            "variant": "reversi", "cols": SIZE, "rows": SIZE, "grid": grid,
            "col_labels": [ch.upper() for ch in _LETTERS],
            "row_labels": [str(i + 1) for i in range(SIZE)],
            "legal": legal, "turn": self.current_player,
            "score": {"chat": chat, "ai": ai},
            "last_cell": (self.last_move or {}).get("cell"),
        }
