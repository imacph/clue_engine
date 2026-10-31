import pytest

from clue_engine.board_setup import BoardSetup


@pytest.mark.parametrize("num_players", [3, 4, 5, 6])
def test_board_setup_accepts_official_player_counts(num_players):
    assert BoardSetup(num_players).num_players == num_players


@pytest.mark.parametrize("num_players", [-1, 0, 1, 2, 7, 8])
def test_board_setup_rejects_player_counts_outside_official_range(num_players):
    with pytest.raises(ValueError, match="between 3 and 6"):
        BoardSetup(num_players)


@pytest.mark.parametrize("num_players", [True, None, "4", 3.5])
def test_board_setup_rejects_non_integer_player_counts(num_players):
    with pytest.raises(TypeError, match="integer"):
        BoardSetup(num_players)
