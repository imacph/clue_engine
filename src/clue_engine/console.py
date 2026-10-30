"""Interactive, privacy-aware console controller for the game engine."""

import argparse
import sys
from collections.abc import Sequence
from typing import TextIO

from .cards import CARDS
from .engine import Engine
from .models import (
    Accuse,
    Action,
    Card,
    CardType,
    Combination,
    EndTurn,
    Pass,
    Reveal,
    Suggest,
)
from .observations import Event
from .policies import Policy
from .presentation import (
    format_debug_information,
    format_event,
    format_hand,
    format_knowledge,
)
from .session import GameSession, create_game


class _ExitRequested(Exception):
    pass


class ConsoleGame:
    """Run a game using injected streams; normal output is filtered for the viewer."""

    def __init__(
        self,
        engine: Engine,
        policies: Sequence[Policy],
        input_stream: TextIO,
        output_stream: TextIO,
        *,
        human_player: int | None = None,
        step_mode: bool = False,
        debug: bool = False,
        max_steps: int = 10_000,
    ):
        self.session = GameSession(
            engine, policies, human_player=human_player, debug=debug, max_steps=max_steps
        )
        self.input = input_stream
        self.output = output_stream
        self.human_player = human_player
        self.step_mode = step_mode
        self._event_count = 0

    def _write(self, text: str) -> None:
        print(text, file=self.output, flush=True)

    def _read(self, prompt: str) -> str:
        self.output.write(prompt)
        self.output.flush()
        line = self.input.readline()
        if not line:
            raise _ExitRequested("Input closed. Exiting.")
        value = line.strip()
        if value.casefold() in {"quit", "q"}:
            raise _ExitRequested("Exiting.")
        return value

    def _visible_events(self) -> tuple[Event, ...]:
        return self.session.snapshot().events

    def _show_events(self, events: tuple[Event, ...], start: int = 0) -> None:
        for index in range(start, len(events)):
            previous = events[index - 1] if index else None
            self._write(format_event(events[index], previous))

    def _show_new_events(self) -> None:
        events = self._visible_events()
        self._show_events(events, self._event_count)
        self._event_count = len(events)

    def _command(self, command: str) -> bool:
        if command == "history":
            events = self._visible_events()
            if events:
                self._show_events(events)
            else:
                self._write("No events yet.")
            return True
        if command == "hand":
            if self.human_player is None:
                self._write("The hand command is available only in play mode.")
            else:
                snapshot = self.session.snapshot()
                view = snapshot.view
                assert view is not None
                self._write(f"Your hand: {format_hand(view.own_hand)}")
            return True
        parts = command.split()
        if parts and parts[0] == "knowledge":
            snapshot = self.session.snapshot()
            if self.human_player is not None:
                if len(parts) != 1:
                    self._write("In play mode, only your own knowledge is available.")
                else:
                    assert snapshot.view is not None
                    self._write(format_knowledge(snapshot.view, snapshot.num_players))
            elif len(parts) == 1:
                for player in range(snapshot.num_players):
                    self._write(f"Player {player} knowledge:")
                    self._write(format_knowledge(
                        self.session.spectator_view(player), snapshot.num_players
                    ))
            elif len(parts) == 2:
                try:
                    player = int(parts[1])
                    view = self.session.spectator_view(player)
                except ValueError:
                    self._write("Invalid player. Use knowledge followed by a valid player number.")
                else:
                    self._write(f"Player {player} knowledge:")
                    self._write(format_knowledge(view, snapshot.num_players))
            else:
                self._write("Use knowledge or knowledge followed by a player number.")
            return True
        if command == "help":
            self._write("Commands: hand, knowledge [player in spectator mode], history, help, quit.")
            return True
        return False

    def _wait_for_step(self) -> None:
        while True:
            value = self._read("Enter to advance, or hand/knowledge/history/help/quit: ").casefold()
            if not value:
                return
            if not self._command(value):
                self._write("Invalid choice. Press Enter to advance or type help.")

    def _select_card(self, cards: Sequence[Card], prompt: str) -> int:
        self._write(", ".join(f"{card.id}: {card.name}" for card in cards))
        while True:
            value = self._read(prompt).casefold()
            for card in cards:
                if value in {str(card.id), card.name.casefold()}:
                    return card.id
            self._write("Invalid choice. Enter a listed card ID or name.")

    def _select_combination(self) -> Combination:
        suspect = self._select_card(CARDS[CardType.SUSPECT], "Suspect: ")
        weapon = self._select_card(CARDS[CardType.WEAPON], "Weapon: ")
        room = self._select_card(CARDS[CardType.ROOM], "Room: ")
        return Combination(suspect, weapon, room)

    def _human_action(self, legal: tuple[Action, ...]) -> Action:
        names = []
        for action_type, name in (
            (Suggest, "suggest"), (Accuse, "accuse"), (Reveal, "reveal"),
            (Pass, "pass"), (EndTurn, "end"),
        ):
            if any(isinstance(action, action_type) for action in legal):
                names.append(name)
        reveals = tuple(action.card_id for action in legal if isinstance(action, Reveal))
        self._write("Available actions: " + ", ".join(names))
        while True:
            choice = self._read("Action (or hand/knowledge/history/help/quit): ").casefold()
            if self._command(choice):
                continue
            if choice in {"suggest", "accuse"} and choice in names:
                combo = self._select_combination()
                action: Action = Suggest(combo) if choice == "suggest" else Accuse(combo)
            elif choice == "reveal" and reveals:
                cards = tuple(card for group in CARDS.values() for card in group if card.id in reveals)
                action = Reveal(self._select_card(cards, "Card to reveal: "))
            elif choice == "pass":
                action = Pass()
            elif choice in {"end", "end turn", "endturn"}:
                action = EndTurn()
            elif reveals:
                # The reveal card can be entered directly when responding.
                cards = tuple(card for group in CARDS.values() for card in group if card.id in reveals)
                selected = next(
                    (card.id for card in cards if choice in {str(card.id), card.name.casefold()}),
                    None,
                )
                if selected is None:
                    self._write("Invalid choice. Choose a legal action.")
                    continue
                action = Reveal(selected)
            else:
                self._write("Invalid choice. Choose a legal action.")
                continue
            if action in legal:
                return action
            self._write("Invalid choice. That action is not legal now.")

    def run(self) -> int:
        """Return 0 on completion or exit, and 1 if the action limit is reached."""
        try:
            snapshot = self.session.snapshot()
            if snapshot.debug_info is not None:
                self._write(format_debug_information(
                    snapshot.debug_info.solution, snapshot.debug_info.hands
                ))
            if self.human_player is not None:
                assert snapshot.view is not None
                self._write(f"You are Player {self.human_player}.")
                self._write(f"Your hand: {format_hand(snapshot.view.own_hand)}")
            else:
                self._write("Spectator mode. Player knowledge includes private hands and shown cards.")

            while True:
                self._show_new_events()
                snapshot = self.session.snapshot()
                self._write(f"Player 0 completed turns: {snapshot.player0_turns}.")
                if snapshot.is_over:
                    if snapshot.winner is None:
                        self._write("Game over: all players were eliminated.")
                    else:
                        self._write(f"Game over: Player {snapshot.winner} wins.")
                    return 0
                if snapshot.limit_reached:
                    self._write(f"Game stopped at the {snapshot.max_steps}-action limit.")
                    return 1
                player = snapshot.to_move
                self._write(f"Player {player} to act.")
                if player == self.human_player:
                    action = self._human_action(snapshot.legal_actions)
                    self.session.submit(action)
                else:
                    if self.step_mode:
                        self._wait_for_step()
                    self.session.advance_bot()
        except _ExitRequested as exc:
            self._write(str(exc))
            return 0
        except KeyboardInterrupt:
            self._write("\nInterrupted. Exiting.")
            return 0


def main(
    argv: Sequence[str] | None = None,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Play or spectate a simplified Clue game.")
    parser.add_argument("--mode", choices=("play", "spectate"), default="play")
    parser.add_argument("--players", type=int, default=4)
    parser.add_argument("--seat", type=int, default=0, help="human seat in play mode (zero-based)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--policy", choices=("deductive", "random"), default="deductive")
    parser.add_argument("--progress", choices=("auto", "step"), default="auto")
    parser.add_argument("--max-steps", type=int, default=10_000)
    parser.add_argument(
        "--debug-omniscient", action="store_true", help="reveal all hands and the solution"
    )
    args = parser.parse_args(argv)
    if args.players < 2:
        parser.error("--players must be at least 2")
    if args.mode == "play" and not 0 <= args.seat < args.players:
        parser.error("--seat must identify an existing player")
    if args.max_steps < 0:
        parser.error("--max-steps must be non-negative")

    engine, policies = create_game(args.players, args.seed, args.policy)
    return ConsoleGame(
        engine,
        policies,
        input_stream if input_stream is not None else sys.stdin,
        output_stream if output_stream is not None else sys.stdout,
        human_player=args.seat if args.mode == "play" else None,
        step_mode=args.progress == "step",
        debug=args.debug_omniscient,
        max_steps=args.max_steps,
    ).run()


if __name__ == "__main__":
    raise SystemExit(main())
