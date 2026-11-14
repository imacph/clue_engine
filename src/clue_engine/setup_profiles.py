"""Validation for reusable setup profiles, which never contain a game seed."""

from dataclasses import fields

from .board_setup import BoardSetup
from .board_state import create_board
from .game_settings import (
    BoardRules,
    GameRules,
    LearnedStrategy,
    bot_strategy_from_dict,
)
from .policies import POLICY_NAMES


def validate_setup_profile(value: object) -> None:
    if not isinstance(value, dict):
        raise TypeError("Setup profile must be an object.")
    required = {"mode", "game_type", "players", "seat", "bots", "progress", "max_steps", "debug"}
    board_fields = {"seat_suspects", "board_rules"}
    game_type = value.get("game_type")
    expected = required | board_fields if game_type == "board" else required
    if (
        not expected <= set(value)
        or set(value) - expected - {"notebook_mode", "game_rules", "shuffle_bots", "shuffle_seat"}
        or game_type not in {"board", "card_only"}
    ):
        raise ValueError("Invalid setup profile fields or game type.")
    if "game_rules" in value:
        rules = value["game_rules"]
        if not isinstance(rules, dict) or set(rules) - {item.name for item in fields(GameRules)}:
            raise ValueError("Invalid game rules in setup profile.")
        GameRules(**rules)
    players = value["players"]
    seat = value["seat"]
    if type(players) is not int or players < 2:
        raise ValueError("Profile player count must be at least two.")
    if type(seat) is not int or not 0 <= seat < players:
        raise ValueError("Profile seat must identify an existing player.")
    if value["mode"] not in {"play", "spectate"} or value["progress"] not in {"auto", "turn", "step"}:
        raise ValueError("Invalid profile mode or progression.")
    if "notebook_mode" in value and value["notebook_mode"] not in ("manual", "automatic"):
        raise ValueError("Invalid profile notebook mode.")
    if type(value["max_steps"]) is not int or value["max_steps"] < 0:
        raise ValueError("Profile action limit must be non-negative.")
    if type(value["debug"]) is not bool:
        raise ValueError("Profile debug must be true or false.")
    if "shuffle_bots" in value and type(value["shuffle_bots"]) is not bool:
        raise ValueError("Profile bot seat shuffle must be true or false.")
    if "shuffle_seat" in value and type(value["shuffle_seat"]) is not bool:
        raise ValueError("Profile human seat shuffle must be true or false.")
    bots = value["bots"]
    if (
        not isinstance(bots, list)
        or (len(bots) != players and not (
            value.get("shuffle_bots") is True and 2 <= len(bots) < players
        ))
    ):
        raise ValueError("Profile requires one bot configuration per seat unless profile shuffling is enabled.")
    for bot in bots:
        if isinstance(bot, str):
            if bot == "learned" and game_type != "board":
                raise ValueError("The learned policy supports board games only.")
            if bot in POLICY_NAMES or bot == "learned":
                continue
        if not isinstance(bot, dict):
            raise ValueError("Invalid bot configuration in setup profile.")  # noqa: TRY004
        strategy = bot_strategy_from_dict(bot)
        if isinstance(strategy, LearnedStrategy) and game_type != "board":
            raise ValueError("The learned policy supports board games only.")
    if game_type == "board":
        suspects = value["seat_suspects"]
        if not isinstance(suspects, list):
            raise ValueError("Profile character assignments must be an array.")
        create_board(BoardSetup(players), seat_suspects=suspects)
        rules = value["board_rules"]
        if (
            not isinstance(rules, dict)
            or not {"move_suspect", "move_weapon", "summoned_suggestion", "secret_passages"} <= set(rules)
            or set(rules) - {item.name for item in fields(BoardRules)}
        ):
            raise ValueError("Invalid board rules in setup profile.")
        BoardRules(**rules)
