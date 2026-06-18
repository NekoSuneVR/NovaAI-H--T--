"""Nim — Twitch chat vs NovaAI.

Three heaps of objects. On your turn take any number (≥1) from a single heap.
Take the last object to win. Chat votes ``heap count`` (e.g. ``2 3`` = take 3
from heap 2). NovaAI plays the perfect XOR (nim-sum) strategy, so it only loses
if chat plays flawlessly from a winning position.
"""
from __future__ import annotations

import random
import re
from typing import Any

from .base import AI, CHAT, ChatGame

_START_HEAPS = (3, 4, 5)


class NimGame(ChatGame):
    key = "nim"
    title = "Nim"

    def reset(self) -> None:
        super().reset()
        self.heaps = list(_START_HEAPS)

    def legal_moves(self) -> list[str]:
        if self.over:
            return []
        return [f"{i + 1}-{k}" for i, n in enumerate(self.heaps) for k in range(1, n + 1)]

    def parse_vote(self, text: str) -> str | None:
        nums = re.findall(r"\d+", text or "")
        if len(nums) < 2:
            return None
        heap, count = int(nums[0]), int(nums[1])
        if 1 <= heap <= len(self.heaps) and 1 <= count <= self.heaps[heap - 1]:
            return f"{heap}-{count}"
        return None

    def apply_move(self, move: str, player: str) -> dict[str, Any]:
        try:
            heap_s, count_s = move.split("-")
            heap, count = int(heap_s) - 1, int(count_s)
        except (ValueError, AttributeError):
            return {"ok": False}
        if not (0 <= heap < len(self.heaps)) or not (1 <= count <= self.heaps[heap]):
            return {"ok": False}
        self.heaps[heap] -= count
        self.last_move = {"player": player, "heap": heap + 1, "count": count}
        desc = (f"chat took {count} from heap {heap + 1}" if player == CHAT
                else f"you took {count} from heap {heap + 1}")
        if all(n == 0 for n in self.heaps):
            self.over = True
            self.winner = player  # took the last object → win
            return {"ok": True, "move": move, "note": "win", "desc": desc + " and took the last object"}
        self._switch()
        return {"ok": True, "move": move, "note": "move", "desc": desc}

    # ── AI (optimal nim-sum strategy) ─────────────────────────────────────────

    def ai_choose(self) -> str:
        nim_sum = 0
        for n in self.heaps:
            nim_sum ^= n
        if nim_sum != 0:
            for i, n in enumerate(self.heaps):
                target = n ^ nim_sum
                if target < n:
                    return f"{i + 1}-{n - target}"
        # Already losing (nim-sum 0): take 1 from the largest heap and hope.
        i = max(range(len(self.heaps)), key=lambda j: self.heaps[j])
        return f"{i + 1}-1"

    # ── presentation ──────────────────────────────────────────────────────────

    def move_label(self, move: str) -> str:
        heap, count = move.split("-")
        return f"{count} from heap {heap}"

    def vote_hint(self) -> str:
        return "type 'heap count' (e.g. '2 3' = take 3 from heap 2)"

    def render(self) -> dict[str, Any]:
        return {"variant": "nim", "heaps": list(self.heaps),
                "last": self.last_move, "turn": self.current_player}
