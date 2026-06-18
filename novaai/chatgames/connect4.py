"""Connect 4 — Twitch chat vs NovaAI.

Chat votes a column (1-7); NovaAI answers with an alpha-beta minimax engine, so
its moves are always legal and genuinely strong (it really blocks and sets up
wins — the personality only does the trash talk). Standard 7x6 board, four in a
row wins.
"""
from __future__ import annotations

import re
from typing import Any

from .base import AI, CHAT, ChatGame

COLS = 7
ROWS = 6
EMPTY = 0
# Internal disc ids. The manager/overlay use "chat"/"ai"; we map here.
_DISC = {CHAT: 1, AI: 2}
_SIDE = {1: CHAT, 2: AI}

_AI_DEPTH = 6  # minimax plies — strong yet fast enough in pure Python


class Connect4Game(ChatGame):
    key = "connect4"
    title = "Connect Four"

    def reset(self) -> None:
        super().reset()
        # board[r][c], row 0 = TOP, row ROWS-1 = BOTTOM (gravity fills upward).
        self.board: list[list[int]] = [[EMPTY] * COLS for _ in range(ROWS)]
        self.win_cells: list[list[int]] = []

    # ── rules ─────────────────────────────────────────────────────────────────

    def _open_columns(self, board: list[list[int]]) -> list[int]:
        return [c for c in range(COLS) if board[0][c] == EMPTY]

    def legal_moves(self) -> list[str]:
        if self.over:
            return []
        return [str(c + 1) for c in self._open_columns(self.board)]

    def parse_vote(self, text: str) -> str | None:
        # Accept "3", "col 3", "!c4 3", "place 3" — first standalone 1-7 wins.
        for m in re.findall(r"\d+", text or ""):
            n = int(m)
            if 1 <= n <= COLS and self.board[0][n - 1] == EMPTY:
                return str(n)
        return None

    def _drop_row(self, board: list[list[int]], col: int) -> int:
        for r in range(ROWS - 1, -1, -1):
            if board[r][col] == EMPTY:
                return r
        return -1

    def apply_move(self, move: str, player: str) -> dict[str, Any]:
        try:
            col = int(move) - 1
        except (TypeError, ValueError):
            return {"ok": False}
        if not (0 <= col < COLS) or self.board[0][col] != EMPTY:
            return {"ok": False}
        disc = _DISC[player]
        row = self._drop_row(self.board, col)
        self.board[row][col] = disc
        self.last_move = {"player": player, "col": col + 1, "row": row}

        line = self._winning_line(self.board, row, col)
        note = "move"
        if line:
            self.over = True
            self.winner = player
            self.win_cells = line
            note = "win"
        elif not self._open_columns(self.board):
            self.over = True
            self.winner = "draw"
            note = "draw"
        else:
            # Did this move create / block an immediate 4-threat? (for commentary)
            opp = AI if player == CHAT else CHAT
            if self._threats(self.board, _DISC[opp]):
                note = "threat"
            self._switch()
        return {"ok": True, "move": move, "col": col + 1, "note": note}

    # ── win / threat detection ────────────────────────────────────────────────

    _DIRS = ((0, 1), (1, 0), (1, 1), (1, -1))

    def _winning_line(self, board, row, col) -> list[list[int]]:
        disc = board[row][col]
        if disc == EMPTY:
            return []
        for dr, dc in self._DIRS:
            cells = [[row, col]]
            for sign in (1, -1):
                r, c = row + dr * sign, col + dc * sign
                while 0 <= r < ROWS and 0 <= c < COLS and board[r][c] == disc:
                    cells.append([r, c])
                    r += dr * sign
                    c += dc * sign
            if len(cells) >= 4:
                return cells
        return []

    def _threats(self, board, disc) -> list[int]:
        """Columns where ``disc`` would complete a 4 next move."""
        out = []
        for c in self._open_columns(board):
            r = self._drop_row(board, c)
            board[r][c] = disc
            if self._winning_line(board, r, c):
                out.append(c)
            board[r][c] = EMPTY
        return out

    # ── AI (alpha-beta minimax) ───────────────────────────────────────────────

    def ai_choose(self) -> str:
        cols = self._open_columns(self.board)
        if not cols:
            return ""
        ai_disc, chat_disc = _DISC[AI], _DISC[CHAT]
        # Fast, certain tactics first: take a win, else block chat's win.
        for c in self._threats(self.board, ai_disc):
            return str(c + 1)
        blocks = self._threats(self.board, chat_disc)
        if len(blocks) == 1:
            return str(blocks[0] + 1)
        # Otherwise search. Center-first ordering makes alpha-beta prune hard.
        order = sorted(cols, key=lambda c: abs(c - COLS // 2))
        best_col, best_score = order[0], -10**9
        alpha, beta = -10**9, 10**9
        for c in order:
            r = self._drop_row(self.board, c)
            self.board[r][c] = ai_disc
            score = self._minimax(self.board, _AI_DEPTH - 1, alpha, beta, False)
            self.board[r][c] = EMPTY
            if score > best_score:
                best_score, best_col = score, c
            alpha = max(alpha, score)
        return str(best_col + 1)

    def _minimax(self, board, depth, alpha, beta, maximizing) -> int:
        ai_disc, chat_disc = _DISC[AI], _DISC[CHAT]
        # Terminal: did the LAST mover win? Cheaply test both via threat-free scan.
        win = self._board_winner(board)
        if win == ai_disc:
            return 1_000_000 + depth
        if win == chat_disc:
            return -1_000_000 - depth
        cols = self._open_columns(board)
        if depth == 0 or not cols:
            return self._evaluate(board)
        order = sorted(cols, key=lambda c: abs(c - COLS // 2))
        if maximizing:
            value = -10**9
            for c in order:
                r = self._drop_row(board, c)
                board[r][c] = ai_disc
                value = max(value, self._minimax(board, depth - 1, alpha, beta, False))
                board[r][c] = EMPTY
                alpha = max(alpha, value)
                if alpha >= beta:
                    break
            return value
        value = 10**9
        for c in order:
            r = self._drop_row(board, c)
            board[r][c] = chat_disc
            value = min(value, self._minimax(board, depth - 1, alpha, beta, True))
            board[r][c] = EMPTY
            beta = min(beta, value)
            if alpha >= beta:
                break
        return value

    def _board_winner(self, board) -> int:
        for r in range(ROWS):
            for c in range(COLS):
                if board[r][c] != EMPTY and self._winning_line(board, r, c):
                    return board[r][c]
        return EMPTY

    def _evaluate(self, board) -> int:
        """Heuristic: score every 4-cell window for the AI."""
        ai_disc = _DISC[AI]
        score = 0
        # Center column control is valuable.
        center = COLS // 2
        score += sum(3 for r in range(ROWS) if board[r][center] == ai_disc)
        # All horizontal / vertical / diagonal windows of length 4.
        for r in range(ROWS):
            for c in range(COLS):
                for dr, dc in self._DIRS:
                    er, ec = r + 3 * dr, c + 3 * dc
                    if 0 <= er < ROWS and 0 <= ec < COLS:
                        window = [board[r + i * dr][c + i * dc] for i in range(4)]
                        score += self._score_window(window, ai_disc)
        return score

    @staticmethod
    def _score_window(window, ai_disc) -> int:
        chat_disc = 3 - ai_disc
        a = window.count(ai_disc)
        o = window.count(chat_disc)
        e = window.count(EMPTY)
        if a and o:
            return 0  # mixed window, dead
        if a == 3 and e == 1:
            return 50
        if a == 2 and e == 2:
            return 10
        if a == 1 and e == 3:
            return 1
        if o == 3 and e == 1:
            return -80  # block opponent threats hard
        if o == 2 and e == 2:
            return -8
        return 0

    # ── presentation ──────────────────────────────────────────────────────────

    def move_label(self, move: str) -> str:
        return f"column {move}"

    def vote_hint(self) -> str:
        return "type a column number 1-7"

    def render(self) -> dict[str, Any]:
        grid = [[("" if v == EMPTY else _SIDE[v]) for v in row] for row in self.board]
        return {
            "cols": COLS,
            "rows": ROWS,
            "grid": grid,
            "win_cells": self.win_cells,
            "last_col": (self.last_move or {}).get("col"),
        }
