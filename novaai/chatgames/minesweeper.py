"""Minesweeper — Twitch chat vs NovaAI (competitive).

Chat and NovaAI take turns revealing cells on one shared board. Reveal a mine and
you lose; survive until every safe cell is uncovered and it's a draw. NovaAI plays
with a real constraint solver — it deduces guaranteed-safe cells from the numbers
and, when forced to guess, picks the lowest-probability cell — so it only knows
what's been revealed, same as chat. First reveal is always safe.

Cells are addressed like a chessboard: columns A-H, rows 1-8 (vote ``c4``).
"""
from __future__ import annotations

import random
import re
from typing import Any

from .base import AI, CHAT, ChatGame

ROWS = 8
COLS = 8
MINES = 10
_LETTERS = "abcdefghijklmnop"[:COLS]


def _tok(r: int, c: int) -> str:
    return f"{_LETTERS[c]}{r + 1}"


class MinesweeperGame(ChatGame):
    key = "minesweeper"
    title = "Minesweeper"

    def reset(self) -> None:
        super().reset()
        self.revealed = [[False] * COLS for _ in range(ROWS)]
        self.adj = [[0] * COLS for _ in range(ROWS)]
        self.owner: list[list[str | None]] = [[None] * COLS for _ in range(ROWS)]
        self.mines: set[tuple[int, int]] = set()
        self._placed = False
        self.exploded: tuple[int, int] | None = None

    # ── geometry ──────────────────────────────────────────────────────────────

    @staticmethod
    def _neighbors(r: int, c: int):
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr or dc:
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < ROWS and 0 <= nc < COLS:
                        yield nr, nc

    def _place_mines(self, safe_r: int, safe_c: int) -> None:
        """Place mines after the first reveal, keeping that cell's area clear."""
        forbidden = {(safe_r, safe_c), *self._neighbors(safe_r, safe_c)}
        cells = [(r, c) for r in range(ROWS) for c in range(COLS) if (r, c) not in forbidden]
        self.mines = set(random.sample(cells, min(MINES, len(cells))))
        for r in range(ROWS):
            for c in range(COLS):
                self.adj[r][c] = sum(1 for nr, nc in self._neighbors(r, c) if (nr, nc) in self.mines)
        self._placed = True

    # ── rules ─────────────────────────────────────────────────────────────────

    def _hidden_cells(self) -> list[tuple[int, int]]:
        return [(r, c) for r in range(ROWS) for c in range(COLS) if not self.revealed[r][c]]

    def legal_moves(self) -> list[str]:
        if self.over:
            return []
        return [_tok(r, c) for r, c in self._hidden_cells()]

    def parse_vote(self, text: str) -> str | None:
        low = (text or "").lower()
        m = re.search(rf"([{_LETTERS}])\s*([1-9][0-9]?)", low) or \
            re.search(rf"([1-9][0-9]?)\s*([{_LETTERS}])", low)
        if not m:
            return None
        a, b = m.group(1), m.group(2)
        letter, num = (a, b) if a in _LETTERS else (b, a)
        c = _LETTERS.index(letter)
        r = int(num) - 1
        if 0 <= r < ROWS and 0 <= c < COLS and not self.revealed[r][c]:
            return _tok(r, c)
        return None

    def _flood(self, r: int, c: int, player: str) -> int:
        """Reveal a safe cell, expanding through zero-adjacency cells. Returns count."""
        stack = [(r, c)]
        count = 0
        while stack:
            cr, cc = stack.pop()
            if self.revealed[cr][cc]:
                continue
            self.revealed[cr][cc] = True
            self.owner[cr][cc] = player
            count += 1
            if self.adj[cr][cc] == 0:
                for nr, nc in self._neighbors(cr, cc):
                    if not self.revealed[nr][nc] and (nr, nc) not in self.mines:
                        stack.append((nr, nc))
        return count

    def apply_move(self, move: str, player: str) -> dict[str, Any]:
        tok = (move or "").lower()
        try:
            c = _LETTERS.index(tok[0])
            r = int(tok[1:]) - 1
        except (ValueError, IndexError):
            return {"ok": False}
        if not (0 <= r < ROWS and 0 <= c < COLS) or self.revealed[r][c]:
            return {"ok": False}
        if not self._placed:
            self._place_mines(r, c)  # first reveal is guaranteed safe
        self.last_move = {"player": player, "cell": _tok(r, c)}

        if (r, c) in self.mines:
            self.revealed[r][c] = True
            self.owner[r][c] = player
            self.exploded = (r, c)
            self.over = True
            self.winner = AI if player == CHAT else CHAT
            return {"ok": True, "move": tok, "note": "boom"}

        self._flood(r, c, player)
        safe_total = ROWS * COLS - len(self.mines)
        revealed_safe = sum(self.revealed[rr][cc] for rr in range(ROWS) for cc in range(COLS)) \
            - (1 if self.exploded else 0)
        if revealed_safe >= safe_total:
            self.over = True
            self.winner = "draw"
            return {"ok": True, "move": tok, "note": "cleared"}
        self._switch()
        return {"ok": True, "move": tok, "note": "safe", "number": self.adj[r][c]}

    # ── AI solver ─────────────────────────────────────────────────────────────

    def ai_choose(self) -> str:
        hidden = self._hidden_cells()
        if not hidden:
            return ""
        if not self._placed:
            return _tok(*random.choice(hidden))  # opening move, forced-safe

        known_mine, known_safe = self._deduce()
        safe_pick = [cell for cell in hidden if cell in known_safe]
        if safe_pick:
            return _tok(*random.choice(safe_pick))

        # No certainty — guess the lowest mine-probability cell.
        candidates = [cell for cell in hidden if cell not in known_mine]
        if not candidates:
            candidates = hidden  # everything looks like a mine; we have to try one
        remaining_mines = max(0, len(self.mines) - len(known_mine))
        interior_p = remaining_mines / max(1, len(candidates))
        best, best_p = None, 2.0
        for cell in candidates:
            p = self._cell_probability(cell, known_mine, interior_p)
            if p < best_p:
                best_p, best = p, cell
        return _tok(*(best or random.choice(candidates)))

    def _numbered_constraints(self):
        """Yield (number-minus-known, [hidden unknown neighbors]) per revealed digit."""
        for r in range(ROWS):
            for c in range(COLS):
                if self.revealed[r][c] and self.adj[r][c] > 0:
                    yield r, c

    def _deduce(self):
        """Iteratively deduce certainly-mine and certainly-safe hidden cells."""
        known_mine: set[tuple[int, int]] = set()
        known_safe: set[tuple[int, int]] = set()
        changed = True
        while changed:
            changed = False
            for r, c in self._numbered_constraints():
                hidden_nb = [(nr, nc) for nr, nc in self._neighbors(r, c) if not self.revealed[nr][nc]]
                mines_here = sum(1 for cell in hidden_nb if cell in known_mine)
                unknown = [cell for cell in hidden_nb if cell not in known_mine and cell not in known_safe]
                if not unknown:
                    continue
                need = self.adj[r][c] - mines_here
                if need == 0:
                    for cell in unknown:
                        known_safe.add(cell)
                        changed = True
                elif need == len(unknown):
                    for cell in unknown:
                        known_mine.add(cell)
                        changed = True
        return known_mine, known_safe

    def _cell_probability(self, cell, known_mine, interior_p) -> float:
        """Estimate mine probability for a hidden cell from adjacent numbers."""
        r, c = cell
        estimates = []
        for nr, nc in self._neighbors(r, c):
            if self.revealed[nr][nc] and self.adj[nr][nc] > 0:
                hidden_nb = [(hr, hc) for hr, hc in self._neighbors(nr, nc) if not self.revealed[hr][hc]]
                mines_here = sum(1 for x in hidden_nb if x in known_mine)
                unknown = [x for x in hidden_nb if x not in known_mine]
                if unknown:
                    estimates.append((self.adj[nr][nc] - mines_here) / len(unknown))
        return max(estimates) if estimates else interior_p

    # ── presentation ──────────────────────────────────────────────────────────

    def move_label(self, move: str) -> str:
        return str(move).upper()

    def vote_hint(self) -> str:
        return f"type a cell like A1-{_LETTERS[-1].upper()}{ROWS}"

    def render(self) -> dict[str, Any]:
        grid = []
        for r in range(ROWS):
            row = []
            for c in range(COLS):
                if self.revealed[r][c]:
                    if (r, c) in self.mines:
                        row.append({"s": "mine", "by": self.owner[r][c]})
                    else:
                        row.append({"s": "open", "n": self.adj[r][c], "by": self.owner[r][c]})
                elif self.over and (r, c) in self.mines:
                    row.append({"s": "mine_hidden"})  # reveal field once the game ends
                else:
                    row.append({"s": "hidden"})
            grid.append(row)
        return {
            "cols": COLS,
            "rows": ROWS,
            "grid": grid,
            "col_labels": [ch.upper() for ch in _LETTERS],
            "row_labels": [str(i + 1) for i in range(ROWS)],
            "mines": len(self.mines) if self._placed else MINES,
            "exploded": list(self.exploded) if self.exploded else None,
            "last_cell": (self.last_move or {}).get("cell"),
        }
