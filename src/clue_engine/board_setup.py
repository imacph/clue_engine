"""Validated setup constraints for the future board game."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BoardSetup:
    """Validate a board player count without starting a game."""

    num_players: int

    def __post_init__(self) -> None:
        if type(self.num_players) is not int:
            raise TypeError("board player count must be an integer")
        if not 3 <= self.num_players <= 6:
            raise ValueError("board player count must be between 3 and 6")
