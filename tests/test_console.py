import io
import random
import subprocess
import sys

import pytest

from clue_engine.console import ConsoleGame, main
from clue_engine.engine import Engine
from clue_engine.models import Accuse, Combination, EndTurn, Pass, Reveal, Suggest
from clue_engine.policies import DeductivePolicy
from clue_engine.state import GameState, deal

SOLUTION = Combination(0, 6, 12)
SUGGESTION = Combination(0, 7, 13)


def make_engine():
    return Engine(GameState(
        solution=SOLUTION,
        player_hands=[
            frozenset({1, 2, 3, 4, 5}),
            frozenset({7, 8, 9, 10, 11}),
            frozenset({13, 14, 15, 16}),
            frozenset({17, 18, 19, 20}),
        ],
        current_player=0,
    ))


class ScriptedPolicy:
    def __init__(self, *actions):
        self.actions = iter(actions)

    def choose(self, view, num_players, legal):
        action = next(self.actions)
        assert action in legal
        return action


def run_game(engine, policies, text="", **kwargs):
    output = io.StringIO()
    game = ConsoleGame(engine, policies, io.StringIO(text), output, **kwargs)
    return game.run(), output.getvalue()


def scripted_policies():
    return [
        ScriptedPolicy(Suggest(SUGGESTION), Accuse(SOLUTION)),
        ScriptedPolicy(Reveal(7)),
        ScriptedPolicy(),
        ScriptedPolicy(),
    ]


@pytest.mark.parametrize("step_mode", [False, True])
def test_spectator_sees_public_events_not_private_card(step_mode):
    engine = make_engine()
    text = "\n\n\n" if step_mode else ""
    result, output = run_game(engine, scripted_policies(), text, step_mode=step_mode)
    assert result == 0
    assert output.count("Player 0 suggested") == 1
    assert output.count("Player 1 refuted") == 1
    assert "showed Dagger" not in output
    assert "Player 0 wins" in output


def test_play_shows_own_hand_knowledge_and_private_reveal():
    policies = [ScriptedPolicy(), ScriptedPolicy(Reveal(7)), ScriptedPolicy(), ScriptedPolicy()]
    inputs = "hand\nknowledge\ninvalid\nsuggest\n0\n7\n13\naccuse\n0\n6\n12\n"
    result, output = run_game(make_engine(), policies, inputs, human_player=0)
    assert result == 0
    assert "Your hand:" in output
    assert "Knowledge" in output
    assert "Invalid choice" in output
    assert output.count("Player 1 showed Dagger to Player 0") == 1
    assert "Player 0 wins" in output


def test_omniscient_mode_warns_and_shows_hands_solution_and_private_events():
    result, output = run_game(make_engine(), scripted_policies(), debug=True)
    assert result == 0
    assert "WARNING" in output
    assert "Solution:" in output
    assert "Player 1 hand:" in output
    assert "Player 1 showed Dagger to Player 0" in output


def test_no_debug_information_in_normal_spectator_mode():
    result, output = run_game(make_engine(), scripted_policies())
    assert result == 0
    assert "Solution:" not in output
    assert "hand:" not in output


def test_uninvolved_player_does_not_see_private_reveal():
    policies = [
        ScriptedPolicy(Suggest(SUGGESTION), EndTurn()),
        ScriptedPolicy(Reveal(7), EndTurn()),
        ScriptedPolicy(),
        ScriptedPolicy(),
    ]
    result, output = run_game(make_engine(), policies, "history\nquit\n", human_player=2)
    assert result == 0
    assert "Player 1 refuted" in output
    assert "showed Dagger" not in output
    assert "Player 1 hand:" not in output


def test_card_selection_reprompts_and_accepts_names():
    policies = [ScriptedPolicy(), ScriptedPolicy(Reveal(7)), ScriptedPolicy(), ScriptedPolicy()]
    inputs = "suggest\nbad\nmiss scarlet\ndagger\nballroom\naccuse\n0\n6\n12\n"
    result, output = run_game(make_engine(), policies, inputs, human_player=0)
    assert result == 0
    assert "Enter a listed card ID or name" in output
    assert "Player 0 wins" in output


def test_human_passes_when_unable_to_refute():
    policies = [
        ScriptedPolicy(Suggest(SOLUTION), Accuse(SOLUTION)),
        ScriptedPolicy(),
        ScriptedPolicy(Pass()),
        ScriptedPolicy(Pass()),
    ]
    result, output = run_game(make_engine(), policies, "reveal\npass\n", human_player=1)
    assert result == 0
    assert "Invalid choice" in output
    assert "Player 1 passed." in output
    assert "Player 0 wins" in output


def test_reveal_prompt_lists_only_legal_cards_and_reprompts():
    engine = make_engine()
    engine.step(Suggest(SUGGESTION))
    policies = [ScriptedPolicy(Accuse(SOLUTION)), *[ScriptedPolicy() for _ in range(3)]]
    result, output = run_game(engine, policies, "reveal\n8\nDagger\n", human_player=1)
    assert result == 0
    assert "7: Dagger" in output
    assert "8: Lead Pipe" not in output
    assert "Enter a listed card ID or name" in output
    assert "Player 1 showed Dagger to Player 0" in output


def test_input_eof_and_quit_stop_cleanly():
    for text in ("", "quit\n"):
        result, output = run_game(
            make_engine(), scripted_policies(), text, human_player=0
        )
        assert result == 0
        assert "Exiting" in output


def test_action_limit_reports_unfinished_game_after_exact_number_of_actions():
    policies = [ScriptedPolicy(EndTurn()), ScriptedPolicy(EndTurn()),
                ScriptedPolicy(), ScriptedPolicy()]
    engine = make_engine()
    result, output = run_game(engine, policies, max_steps=2)
    assert result == 1
    assert len(engine.log) == 2
    assert "action limit" in output


def test_game_finishing_on_action_limit_is_reported_as_won():
    policies = [ScriptedPolicy(Accuse(SOLUTION)), *[ScriptedPolicy() for _ in range(3)]]
    result, output = run_game(make_engine(), policies, max_steps=1)
    assert result == 0
    assert "Player 0 wins" in output
    assert "action limit" not in output


def test_all_players_eliminated_is_reported():
    policies = [ScriptedPolicy(Accuse(Combination(1, 6, 12))) for _ in range(4)]
    result, output = run_game(make_engine(), policies)
    assert result == 0
    assert output.count("was eliminated") == 4
    assert "all players were eliminated" in output


def test_eliminated_human_can_still_reveal():
    engine = make_engine()
    engine.step(Accuse(Combination(1, 6, 12)))
    policies = [
        ScriptedPolicy(),
        ScriptedPolicy(Suggest(Combination(1, 6, 12)), Accuse(SOLUTION)),
        ScriptedPolicy(Pass()),
        ScriptedPolicy(Pass()),
    ]
    result, output = run_game(engine, policies, "1\n", human_player=0)
    assert result == 0
    assert "Player 0 showed Colonel Mustard to Player 1" in output


def test_spectator_transcript_is_seed_reproducible():
    def transcript():
        engine = Engine(deal(random.Random(3), 4))
        policies = [DeductivePolicy(random.Random(i)) for i in range(4)]
        return run_game(engine, policies)
    assert transcript() == transcript()


def test_cli_validates_seat_and_supports_scripted_exit():
    with pytest.raises(SystemExit) as exc:
        main(["--players", "2", "--seat", "2"], io.StringIO(), io.StringIO())
    assert exc.value.code == 2
    output = io.StringIO()
    assert main(["--seed", "4"], io.StringIO("quit\n"), output) == 0
    assert "Exiting" in output.getvalue()


def test_step_mode_can_show_history_and_exit_without_advancing():
    engine = make_engine()
    result, output = run_game(engine, scripted_policies(), "history\nquit\n", step_mode=True)
    assert result == 0
    assert "No events yet." in output
    assert engine.log == ()


def test_console_module_runs_as_a_public_spectator():
    result = subprocess.run(
        [
            sys.executable, "-m", "clue_engine.console", "--mode", "spectate",
            "--players", "4", "--seed", "42",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Game over:" in result.stdout
    assert " showed " not in result.stdout
    assert "Solution:" not in result.stdout
    assert " hand:" not in result.stdout
