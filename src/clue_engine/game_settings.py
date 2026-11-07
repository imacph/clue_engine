"""Validated, immutable configuration for optional game behavior."""

from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class BoardRules:
    move_suspect: bool = True
    move_weapon: bool = True
    summoned_suggestion: bool = True
    secret_passages: bool = True
    early_end: bool = True
    revisit_hallways: bool = False
    optional_suggestion: bool = False
    accuse_in_room: bool = False
    stay_to_suggest: bool = False

    def __post_init__(self) -> None:
        for item in fields(self):
            if type(getattr(self, item.name)) is not bool:
                raise TypeError(f"{item.name} must be true or false")
        if not self.move_suspect and self.summoned_suggestion:
            raise ValueError("summoned suggestions require suspect relocation")


DEFAULT_BOARD_RULES = BoardRules()


@dataclass(frozen=True, slots=True)
class GameRules:
    reverse_refutation: bool = False
    public_refutations: bool = False
    all_refute: bool = False
    face_up_card: bool = False

    def __post_init__(self) -> None:
        for item in fields(self):
            if type(getattr(self, item.name)) is not bool:
                raise TypeError(f"{item.name} must be true or false")


DEFAULT_GAME_RULES = GameRules()


@dataclass(frozen=True, slots=True)
class BotStrategy:
    candidate_suggestions: bool = False
    probe_suggestions: bool = False
    rank_suggestions: bool = False
    repeat_reveals: bool = False
    candidate_rooms: bool = False
    prefer_suggest: bool = False
    deal_analysis: bool = False
    risk_accusation: bool = False

    def __post_init__(self) -> None:
        for item in fields(self):
            if type(getattr(self, item.name)) is not bool:
                raise TypeError(f"{item.name} must be true or false")
