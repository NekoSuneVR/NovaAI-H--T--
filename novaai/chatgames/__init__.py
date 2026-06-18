"""Chat-vs-AI mini-games (Twitch chat plays against NovaAI, Neuro-sama style).

Each game implements the small ``ChatGame`` rules interface (``base.py``); the
``ChatGameManager`` (``manager.py``) drives the shared turn/vote/timer loop and
NovaAI's commentary. To add a game, implement ``ChatGame`` and register it below.
"""
from __future__ import annotations

from typing import Any

from .base import AI, CHAT, ChatGame
from .connect4 import Connect4Game
from .minesweeper import MinesweeperGame
from .tictactoe import TicTacToeGame
from .reversi import ReversiGame
from .nim import NimGame
from .rps import RockPaperScissorsGame
from .battleship import BattleshipGame

# key -> metadata. ``cls`` builds a fresh game; label/desc drive the UI picker.
GAME_REGISTRY: dict[str, dict[str, Any]] = {
    "connect4": {
        "label": "Connect 4",
        "desc": "Chat votes a column; drop four in a row before NovaAI does.",
        "cls": Connect4Game,
    },
    "battleship": {
        "label": "Battleship",
        "desc": "Take turns firing — sink NovaAI's fleet before it sinks yours.",
        "cls": BattleshipGame,
    },
    "minesweeper": {
        "label": "Minesweeper",
        "desc": "Chat and NovaAI take turns revealing cells — don't hit a mine.",
        "cls": MinesweeperGame,
    },
    "reversi": {
        "label": "Reversi / Othello",
        "desc": "Flank NovaAI's discs to flip them; own the most when the board fills.",
        "cls": ReversiGame,
    },
    "tictactoe": {
        "label": "Tic-Tac-Toe",
        "desc": "Classic 3x3 — NovaAI plays perfectly, so go for the draw.",
        "cls": TicTacToeGame,
    },
    "rps": {
        "label": "Rock Paper Scissors",
        "desc": "Best of 5 — NovaAI reads chat's patterns and counters them.",
        "cls": RockPaperScissorsGame,
    },
    "nim": {
        "label": "Nim",
        "desc": "Take objects from heaps; grab the last one to win. NovaAI plays optimally.",
        "cls": NimGame,
    },
}


def list_games() -> list[dict[str, str]]:
    return [{"key": k, "label": v["label"], "desc": v["desc"]} for k, v in GAME_REGISTRY.items()]


def build_game(key: str, **opts: Any) -> ChatGame:
    meta = GAME_REGISTRY.get(key)
    if not meta:
        raise ValueError(f"Unknown chat game: {key}")
    return meta["cls"](**opts)


__all__ = ["GAME_REGISTRY", "list_games", "build_game", "ChatGame", "AI", "CHAT"]
