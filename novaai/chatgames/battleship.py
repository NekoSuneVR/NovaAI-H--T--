"""Battleship — Twitch chat vs NovaAI.

Both fleets are placed at random on a 10x10 grid (A-J, 1-10). Players take turns
firing one shot: chat votes a target like ``e5`` at NovaAI's waters; NovaAI fires
back with a proper hunt-and-target AI (checkerboard search until a hit, then it
chases the ship along its axis). Sink the whole enemy fleet to win. It's a duel
of shots — you don't place your own ships, you just out-hunt Nova.
"""
from __future__ import annotations

import random
import re
from typing import Any

from .base import AI, CHAT, ChatGame

SIZE = 10
SHIP_SIZES = (5, 4, 3, 3, 2)
_LETTERS = "abcdefghij"
_ADJ = [(-1, 0), (1, 0), (0, -1), (0, 1)]


def _tok(r: int, c: int) -> str:
    return f"{_LETTERS[c]}{r + 1}"


def _place_fleet() -> list[set[tuple[int, int]]]:
    """Randomly place the standard fleet without overlaps or touching out of bounds."""
    ships: list[set[tuple[int, int]]] = []
    occupied: set[tuple[int, int]] = set()
    for size in SHIP_SIZES:
        for _ in range(500):
            horizontal = random.random() < 0.5
            if horizontal:
                r = random.randint(0, SIZE - 1)
                c = random.randint(0, SIZE - size)
                cells = {(r, c + i) for i in range(size)}
            else:
                r = random.randint(0, SIZE - size)
                c = random.randint(0, SIZE - 1)
                cells = {(r + i, c) for i in range(size)}
            if cells & occupied:
                continue
            occupied |= cells
            ships.append(cells)
            break
    return ships


class BattleshipGame(ChatGame):
    key = "battleship"
    title = "Battleship"

    def reset(self) -> None:
        super().reset()
        self.nova_ships = _place_fleet()   # chat fires at these
        self.chat_ships = _place_fleet()   # NovaAI fires at these
        self.nova_shots: set[tuple[int, int]] = set()  # chat's shots at Nova
        self.chat_shots: set[tuple[int, int]] = set()  # Nova's shots at chat

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _hit(cell, ships) -> bool:
        return any(cell in ship for ship in ships)

    @staticmethod
    def _ship_of(cell, ships):
        for ship in ships:
            if cell in ship:
                return ship
        return None

    @staticmethod
    def _sunk(ship, shots) -> bool:
        return ship is not None and ship <= shots

    @staticmethod
    def _fleet_dead(ships, shots) -> bool:
        return all(ship <= shots for ship in ships)

    def _targets(self, ships, shots) -> list[str]:
        return [_tok(r, c) for r in range(SIZE) for c in range(SIZE) if (r, c) not in shots]

    # ── rules ─────────────────────────────────────────────────────────────────

    def legal_moves(self) -> list[str]:
        if self.over:
            return []
        if self.current_player == CHAT:
            return self._targets(self.nova_ships, self.nova_shots)
        return self._targets(self.chat_ships, self.chat_shots)

    def parse_vote(self, text: str) -> str | None:
        m = re.search(rf"([{_LETTERS}])\s*([1-9]|10)", (text or "").lower())
        if not m:
            return None
        c = _LETTERS.index(m.group(1))
        r = int(m.group(2)) - 1
        if 0 <= r < SIZE and 0 <= c < SIZE and (r, c) not in self.nova_shots:
            return _tok(r, c)
        return None

    def apply_move(self, move: str, player: str) -> dict[str, Any]:
        try:
            c = _LETTERS.index(move[0])
            r = int(move[1:]) - 1
        except (ValueError, IndexError):
            return {"ok": False}
        if not (0 <= r < SIZE and 0 <= c < SIZE):
            return {"ok": False}
        if player == CHAT:
            ships, shots = self.nova_ships, self.nova_shots
        else:
            ships, shots = self.chat_ships, self.chat_shots
        if (r, c) in shots:
            return {"ok": False}
        shots.add((r, c))
        self.last_move = {"player": player, "cell": _tok(r, c)}
        who = "chat" if player == CHAT else "you"
        if self._hit((r, c), ships):
            ship = self._ship_of((r, c), ships)
            if self._sunk(ship, shots):
                if self._fleet_dead(ships, shots):
                    self.over = True
                    self.winner = player
                    return {"ok": True, "move": move, "note": "win", "react": True,
                            "desc": f"{who} sank the last ship at {move.upper()} — fleet destroyed"}
                self._switch()
                return {"ok": True, "move": move, "note": "sunk", "react": True,
                        "desc": f"{who} sank a {len(ship)}-cell ship at {move.upper()}"}
            self._switch()
            return {"ok": True, "move": move, "note": "hit", "react": True,
                    "desc": f"{who} scored a hit at {move.upper()}"}
        self._switch()
        return {"ok": True, "move": move, "note": "miss",
                "desc": f"{who} fired at {move.upper()} and missed"}

    # ── AI (hunt and target) ──────────────────────────────────────────────────

    def ai_choose(self) -> str:
        ships, shots = self.chat_ships, self.chat_shots
        hits = [cell for cell in shots if self._hit(cell, ships)]
        unsunk = [cell for cell in hits if not self._sunk(self._ship_of(cell, ships), shots)]
        if unsunk:
            scored: list[tuple[int, tuple[int, int]]] = []
            hit_set = set(hits)
            for (r, c) in unsunk:
                for dr, dc in _ADJ:
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < SIZE and 0 <= nc < SIZE and (nr, nc) not in shots:
                        # Prefer continuing a straight line of two+ known hits.
                        weight = 3 if (r - dr, c - dc) in hit_set else 1
                        scored.append((weight, (nr, nc)))
            if scored:
                scored.sort(key=lambda x: x[0], reverse=True)
                top = [cell for w, cell in scored if w == scored[0][0]]
                return _tok(*random.choice(top))
        # Hunt: checkerboard parity covers all ships with half the shots.
        avail = [(r, c) for r in range(SIZE) for c in range(SIZE) if (r, c) not in shots]
        parity = [cell for cell in avail if (cell[0] + cell[1]) % 2 == 0]
        return _tok(*random.choice(parity or avail))

    # ── presentation ──────────────────────────────────────────────────────────

    def move_label(self, move: str) -> str:
        return move.upper()

    def vote_hint(self) -> str:
        return "type a target like A1-J10"

    def _render_grid(self, ships, shots) -> list[list[dict]]:
        grid = []
        for r in range(SIZE):
            row = []
            for c in range(SIZE):
                cell = (r, c)
                shot = cell in shots
                is_ship = self._hit(cell, ships)
                if shot and is_ship:
                    sunk = self._sunk(self._ship_of(cell, ships), shots)
                    row.append({"s": "sunk" if sunk else "hit"})
                elif shot:
                    row.append({"s": "miss"})
                elif self.over and is_ship:
                    row.append({"s": "ship"})   # reveal survivors at game end
                else:
                    row.append({"s": "sea"})
            grid.append(row)
        return grid

    def render(self) -> dict[str, Any]:
        nova_afloat = sum(1 for s in self.nova_ships if not (s <= self.nova_shots))
        chat_afloat = sum(1 for s in self.chat_ships if not (s <= self.chat_shots))
        return {
            "variant": "battleship", "size": SIZE,
            "col_labels": [ch.upper() for ch in _LETTERS],
            "row_labels": [str(i + 1) for i in range(SIZE)],
            "nova_grid": self._render_grid(self.nova_ships, self.nova_shots),  # chat fires here
            "chat_grid": self._render_grid(self.chat_ships, self.chat_shots),  # nova fires here
            "ships_left": {"ai": nova_afloat, "chat": chat_afloat},
            "turn": self.current_player,
            "last_cell": (self.last_move or {}).get("cell"),
        }
