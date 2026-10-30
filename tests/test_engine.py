import random

import pytest

from clue_engine.actions import ACCUSES, ENDTURNS, SUGGESTIONS
from clue_engine.engine import Engine, IllegalActionError
from clue_engine.knowledge import Mark, knowledge_for
from clue_engine.models import Accuse, Combination, EndTurn, Pass, Reveal, Suggest
from clue_engine.observations import EventKind
from clue_engine.state import GameState, deal

# Card ids: suspects 0-5, weapons 6-11, rooms 12-20.
SOLUTION = Combination(suspect_id=0, weapon_id=6, room_id=12)
WRONG = Combination(suspect_id=1, weapon_id=6, room_id=12)


def make_engine() -> Engine:
    hands = [
        frozenset({1, 2, 3, 4, 5}),
        frozenset({7, 8, 9, 10, 11}),
        frozenset({13, 14, 15, 16}),
        frozenset({17, 18, 19, 20}),
    ]
    return Engine(GameState(solution=SOLUTION, player_hands=hands, current_player=0))


def kinds(engine: Engine) -> list[EventKind]:
    return [event.kind for event in engine.log]


def test_game_starts_with_player_zero_to_move():
    engine = make_engine()
    assert engine.to_move == 0
    assert set(engine.legal_actions()) == {*SUGGESTIONS, *ACCUSES, *ENDTURNS}
    assert not engine.is_over


@pytest.mark.parametrize("current_player", [-1, 4])
def test_engine_rejects_invalid_current_player(current_player):
    state = deal(random.Random(0), 4)
    state.current_player = current_player
    with pytest.raises(ValueError, match="current_player"):
        Engine(state)


def test_engine_rejects_too_few_players():
    state = GameState(SOLUTION, [frozenset()], 0)
    with pytest.raises(ValueError, match="at least two"):
        Engine(state)


def test_illegal_action_is_rejected_and_changes_nothing():
    engine = make_engine()
    with pytest.raises(IllegalActionError):
        engine.step(Pass())
    with pytest.raises(IllegalActionError):
        engine.step(Reveal(1))
    assert engine.log == ()


def test_suggestion_hands_the_move_to_the_next_seat():
    engine = make_engine()
    engine.step(Suggest(Combination(0, 7, 13)))
    assert kinds(engine) == [EventKind.SUGGEST]
    assert engine.to_move == 1


def test_responder_without_matching_card_passes_to_the_next_seat():
    engine = make_engine()
    engine.step(Suggest(Combination(0, 6, 13)))
    assert engine.legal_actions() == (Pass(),)
    engine.step(Pass())
    assert engine.to_move == 2
    assert engine.legal_actions() == (Reveal(13),)


def test_passing_with_a_matching_card_is_illegal():
    engine = make_engine()
    engine.step(Suggest(Combination(0, 7, 13)))
    with pytest.raises(IllegalActionError):
        engine.step(Pass())


def test_refutation_stops_the_round_and_returns_the_move_to_the_suggester():
    engine = make_engine()
    engine.step(Suggest(Combination(0, 7, 13)))
    events = engine.step(Reveal(7))
    assert [e.kind for e in events] == [EventKind.REFUTE, EventKind.SHOW]
    assert engine.to_move == 0
    # Seat 2 and 3 never got to respond.
    assert EventKind.PASS not in kinds(engine)


def test_suggester_cannot_suggest_twice_but_may_accuse_or_end_turn():
    engine = make_engine()
    engine.step(Suggest(Combination(0, 7, 13)))
    engine.step(Reveal(7))
    assert set(engine.legal_actions()) == {*ACCUSES, *ENDTURNS}


def test_show_is_visible_only_to_suggester_and_refuter():
    engine = make_engine()
    engine.step(Suggest(Combination(0, 7, 13)))
    engine.step(Reveal(7))
    shown = {
        player: any(e.kind is EventKind.SHOW for e in engine.view(player).events)
        for player in range(4)
    }
    assert shown == {0: True, 1: True, 2: False, 3: False}


@pytest.mark.parametrize("player", [-1, 4])
def test_view_rejects_invalid_player_indexes(player):
    with pytest.raises(ValueError, match="player"):
        make_engine().view(player)


def test_unrefuted_suggestion_returns_the_move_to_the_suggester():
    engine = make_engine()
    engine.step(Suggest(SOLUTION))
    for _ in range(3):
        engine.step(Pass())
    assert engine.to_move == 0
    assert set(engine.legal_actions()) == {*ACCUSES, *ENDTURNS}


def test_end_turn_advances_to_the_next_player_who_may_suggest_again():
    engine = make_engine()
    engine.step(EndTurn())
    assert engine.to_move == 1
    assert engine.state.current_player == 1
    assert set(SUGGESTIONS) <= set(engine.legal_actions())


def test_turn_order_wraps_around():
    engine = make_engine()
    for _ in range(4):
        engine.step(EndTurn())
    assert engine.to_move == 0


def test_wrong_accusation_eliminates_and_passes_the_turn_automatically():
    engine = make_engine()
    engine.step(Accuse(WRONG))
    assert kinds(engine) == [EventKind.ACCUSE, EventKind.END_TURN]
    assert engine.to_move == 1
    assert not engine.is_over


def test_eliminated_player_is_skipped_but_still_refutes():
    engine = make_engine()
    engine.step(Accuse(WRONG))
    for _ in range(3):
        engine.step(EndTurn())
    assert engine.to_move == 1  # seat 0 was skipped

    engine.step(Suggest(Combination(1, 6, 12)))
    engine.step(Pass())  # seat 2
    engine.step(Pass())  # seat 3
    assert engine.to_move == 0
    assert engine.legal_actions() == (Reveal(1),)


def test_correct_accusation_ends_the_game():
    engine = make_engine()
    engine.step(Accuse(SOLUTION))
    assert engine.is_over
    assert engine.winner == 0
    assert engine.to_move is None
    assert engine.legal_actions() == ()
    with pytest.raises(IllegalActionError):
        engine.step(EndTurn())


def test_game_ends_with_no_winner_when_everyone_is_eliminated():
    engine = make_engine()
    for _ in range(4):
        engine.step(Accuse(WRONG))
    assert engine.is_over
    assert engine.winner is None
    assert engine.legal_actions() == ()


def play_random_game(seed: int, num_players: int = 4, max_steps: int = 10_000) -> Engine:
    rng = random.Random(seed)
    engine = Engine(deal(rng, num_players))
    for _ in range(max_steps):
        if engine.is_over:
            return engine
        engine.step(rng.choice(engine.legal_actions()))
    raise AssertionError("game did not finish")


@pytest.mark.parametrize("seed", range(20))
def test_random_games_finish(seed):
    engine = play_random_game(seed)
    assert engine.is_over
    if engine.winner is not None:
        assert engine.log[-1].combo == engine.state.solution


@pytest.mark.parametrize("num_players", range(2, 7))
def test_random_games_across_player_counts(num_players):
    engine = play_random_game(42, num_players=num_players)
    assert engine.is_over
    solution = {
        engine.state.solution.suspect_id,
        engine.state.solution.weapon_id,
        engine.state.solution.room_id,
    }
    for player in range(num_players):
        knowledge = knowledge_for(engine.view(player), num_players)
        for holder in range(num_players + 1):
            held_cards = solution if holder == num_players else engine.state.player_hands[holder]
            for card_id in range(21):
                mark = knowledge.mark_of(holder, card_id)
                if mark is Mark.HELD:
                    assert card_id in held_cards
                elif mark is Mark.NOT_HELD:
                    assert card_id not in held_cards


@pytest.mark.parametrize("seed", range(20))
def test_random_games_leave_every_players_knowledge_consistent(seed):
    engine = play_random_game(seed)
    for player in range(engine.num_players):
        knowledge_for(engine.view(player), engine.num_players)


def test_random_games_are_reproducible():
    assert play_random_game(7).log == play_random_game(7).log
