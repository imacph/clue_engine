import subprocess
import sys
import time
from threading import Event

import pytest

tk = pytest.importorskip("tkinter")

from clue_engine.engine import Engine
from clue_engine.gui.app import GuiApp
from clue_engine.gui.batch_window import BatchWindow
from clue_engine.gui.widgets import GameFrame
from clue_engine.models import Accuse, Combination, EndTurn, Pass, Reveal, Suggest
from clue_engine.session import GameSession
from clue_engine.state import GameState

SOLUTION = Combination(0, 6, 12)
SUGGESTION = Combination(0, 7, 13)


class ScriptedPolicy:
    def __init__(self, *actions):
        self.actions = iter(actions)

    def choose(self, view, num_players, legal):
        action = next(self.actions)
        assert action in legal
        return action


def make_engine():
    return Engine(GameState(
        SOLUTION,
        [
            frozenset({1, 2, 3, 4, 5}),
            frozenset({7, 8, 9, 10, 11}),
            frozenset({13, 14, 15, 16}),
            frozenset({17, 18, 19, 20}),
        ],
        0,
    ))


@pytest.fixture(scope="module")
def tk_root():
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    window.withdraw()
    yield window
    window.destroy()


@pytest.fixture
def root(tk_root):
    yield tk_root
    for child in tk_root.winfo_children():
        child.destroy()
    tk_root.update_idletasks()


def test_human_suggestion_and_private_reveal_in_real_widgets(root):
    policies = [ScriptedPolicy(), ScriptedPolicy(Reveal(7)), ScriptedPolicy(), ScriptedPolicy()]
    session = GameSession(make_engine(), policies, human_player=0)
    frame = GameFrame(root, session, paused=True)
    frame.pack()
    root.update()
    assert "Colonel Mustard" in frame.hand_text.get()
    assert len(frame.notebook.get_children()) == 21
    frame.weapon_choice.current(1)
    frame.room_choice.current(1)
    frame.suggest_button.invoke()
    assert session.snapshot().to_move == 1
    frame.next_button.invoke()
    root.update()
    assert session.snapshot().to_move == 0
    assert "Player 1 showed Dagger to Player 0" in frame.history.get("1.0", "end")
    assert str(frame.suggest_button["state"]) == "disabled"


def test_spectator_step_filters_private_information_and_reports_winner(root):
    policies = [ScriptedPolicy(Suggest(SUGGESTION), Accuse(SOLUTION)),
                ScriptedPolicy(Reveal(7)), ScriptedPolicy(), ScriptedPolicy()]
    session = GameSession(make_engine(), policies)
    frame = GameFrame(root, session, paused=True)
    frame.pack()
    for _ in range(3):
        frame.next_button.invoke()
        root.update()
    history = frame.history.get("1.0", "end")
    assert "Player 1 refuted" in history
    assert "showed Dagger" not in history
    assert "Player 0 wins" in frame.status_text.get()
    assert len(frame.notebook.get_children()) == 21
    assert str(frame.next_button["state"]) == "disabled"


def test_spectator_selects_each_players_knowledge_and_sees_clauses(root):
    policies = [ScriptedPolicy(Suggest(SUGGESTION), EndTurn()), ScriptedPolicy(Reveal(7)),
                ScriptedPolicy(), ScriptedPolicy()]
    frame = GameFrame(root, GameSession(make_engine(), policies), paused=True)
    frame.pack()
    assert len(frame.notebook.get_children()) == 21
    assert frame.knowledge_player_choice["values"] == ("Player 0", "Player 1", "Player 2", "Player 3")
    frame.next_button.invoke()
    frame.next_button.invoke()
    frame.knowledge_player_choice.current(2)
    frame.knowledge_player_choice.event_generate("<<ComboboxSelected>>")
    root.update()
    clause_text = frame.clauses.get("1.0", "end")
    assert "Player 1 holds at least one of" in clause_text
    assert "unresolved" in clause_text
    assert "showed Dagger" not in frame.history.get("1.0", "end")
    assert frame.notebook.item("13")["values"][3] == "+"
    frame.next_button.invoke()
    assert frame.knowledge_player_choice.current() == 2
    assert "Conservatory" in frame.hand_text.get()
    assert "1" in frame.turn_text.get()
    frame.knowledge_player_choice.current(0)
    frame.knowledge_player_choice.event_generate("<<ComboboxSelected>>")
    root.update()
    assert "satisfied" in frame.clauses.get("1.0", "end")
    assert frame.notebook.item("1")["values"][1] == "+"


def test_player_cannot_switch_to_another_players_knowledge(root):
    frame = GameFrame(
        root, GameSession(make_engine(), [ScriptedPolicy()] * 4, human_player=0), paused=True
    )
    frame.pack()
    assert str(frame.knowledge_player_choice["state"]) == "disabled"
    assert frame.knowledge_player_choice["values"] == ("Player 0",)


def test_gui_displays_player_zero_completed_turns(root):
    engine = make_engine()
    frame = GameFrame(root, GameSession(engine, [ScriptedPolicy()] * 4, human_player=0), paused=True)
    frame.pack()
    assert "0" in frame.turn_text.get()
    frame.end_button.invoke()
    assert "1" in frame.turn_text.get()


def test_debug_mode_displays_hidden_information(root):
    session = GameSession(make_engine(), [ScriptedPolicy()] * 4, debug=True)
    frame = GameFrame(root, session, paused=True)
    frame.pack()
    root.update()
    assert "WARNING" in frame.debug_text.get()
    assert "Solution:" in frame.debug_text.get()
    assert "Player 1 hand:" in frame.debug_text.get()


def test_setup_starts_play_and_can_return_to_setup(root):
    app = GuiApp(root)
    app.start()
    root.update()
    assert isinstance(app.game, GameFrame)
    assert app.game.session.snapshot().human_player == 0
    app.show_setup()
    root.update()
    assert app.game is None


def test_setup_starts_spectator_with_knowledge_selector(root):
    app = GuiApp(root)
    app.mode.set("spectate")
    app.progress.set("step")
    app.start()
    assert app.game is not None
    assert app.game.session.snapshot().human_player is None
    assert app.game.session.snapshot().debug_info is None
    assert str(app.game.knowledge_player_choice["state"]) == "readonly"
    assert len(app.game.knowledge_player_choice["values"]) == 4


def test_batch_window_runs_and_opens_private_trace(root, tmp_path, monkeypatch):
    from clue_engine.gui import batch_window

    monkeypatch.setattr(batch_window.messagebox, "askyesno", lambda *args, **kwargs: True)
    app = GuiApp(root)
    app.open_batch()
    window = next(child for child in root.winfo_children() if isinstance(child, BatchWindow))
    window.games.set("2")
    window.players.set("2")
    window.policies.set("deductive,random")
    window.limit.set("0")
    window.trace.set(str(tmp_path / "trace.jsonl"))
    window.start()
    deadline = time.monotonic() + 10
    while window._future is not None and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert window._future is None
    assert "timeouts" in window.status.get()
    assert "timeout=2" in window.output.get("1.0", "end")
    window.open_trace()
    while (window._trace_future is not None or window._render_id is not None) and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert window._trace_future is None
    assert '"type": "game_start"' in window.output.get("1.0", "end")
    assert '"solution"' in window.output.get("1.0", "end")
    window.game_number.set("100")
    window.open_trace()
    while window._trace_future is not None and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert "not found" in window.status.get()
    existing = BatchWindow(root)
    existing.trace.set(str(tmp_path / "trace.jsonl"))
    existing.open_trace()
    while (existing._trace_future is not None or existing._render_id is not None) and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert "Showing game 0" in existing.status.get()
    assert '"type": "game_start"' in existing.output.get("1.0", "end")


def test_batch_window_reports_existing_trace_error(root, tmp_path, monkeypatch):
    from clue_engine.gui import batch_window

    monkeypatch.setattr(batch_window.messagebox, "askyesno", lambda *args, **kwargs: True)
    path = tmp_path / "existing.jsonl"
    path.write_text("keep", encoding="utf-8")
    window = BatchWindow(root)
    window.trace.set(str(path))
    window.start()
    deadline = time.monotonic() + 10
    while window._future is not None and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert window._future is None
    assert "Batch failed" in window.status.get()
    assert "FileExistsError" in window.output.get("1.0", "end")
    assert path.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("close_window", [False, True])
def test_batch_window_cancels_worker_and_callbacks(root, tmp_path, monkeypatch, close_window):
    from clue_engine.gui import batch_window

    started, finished = Event(), Event()
    real_run_batch = batch_window.run_batch

    def wait_for_cancel(config, path, *, progress, cancelled):
        started.set()
        while not cancelled():
            time.sleep(0.01)
        try:
            return real_run_batch(config, path, progress=progress, cancelled=cancelled)
        finally:
            finished.set()

    monkeypatch.setattr(batch_window, "run_batch", wait_for_cancel)
    monkeypatch.setattr(batch_window.messagebox, "askyesno", lambda *args, **kwargs: True)
    window = BatchWindow(root)
    window.trace.set(str(tmp_path / "cancel.jsonl"))
    window.start()
    assert started.wait(5)
    if close_window:
        window.destroy()
    else:
        window.cancel_button.invoke()
    assert finished.wait(5)
    if not close_window:
        deadline = time.monotonic() + 5
        while window._future is not None and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        assert window._future is None
        assert window.status.get() == "Batch cancelled."
        assert "Batch cancelled" in window.output.get("1.0", "end")
    root.update()


def test_setup_validates_input_and_confirms_debug(root, monkeypatch):
    from clue_engine.gui import app as app_module

    errors = []
    monkeypatch.setattr(app_module.messagebox, "showerror", lambda *args, **kwargs: errors.append(args))
    app = GuiApp(root)
    app.players.set("1")
    app.start()
    assert app.game is None
    assert errors

    app.players.set("4")
    app.debug.set(True)
    monkeypatch.setattr(app_module.messagebox, "askyesno", lambda *args, **kwargs: False)
    app.start()
    assert app.game is None
    monkeypatch.setattr(app_module.messagebox, "askyesno", lambda *args, **kwargs: True)
    app.start()
    assert app.game is not None
    assert app.game.session.snapshot().debug_info is not None


def test_human_reveal_and_accusation_confirmation(root, monkeypatch):
    from clue_engine.gui import widgets as widget_module

    engine = make_engine()
    engine.step(Suggest(SUGGESTION))
    policies = [ScriptedPolicy(Accuse(SOLUTION)), *[ScriptedPolicy() for _ in range(3)]]
    session = GameSession(engine, policies, human_player=1)
    frame = GameFrame(root, session, paused=True)
    frame.pack()
    assert frame.reveal_choice["values"] == ("Dagger",)
    frame.reveal_button.invoke()
    assert "showed Dagger" in frame.history.get("1.0", "end")
    frame.next_button.invoke()
    assert session.snapshot().is_over

    session = GameSession(make_engine(), [ScriptedPolicy()] * 4, human_player=0)
    frame = GameFrame(root, session, paused=True)
    frame.pack()
    monkeypatch.setattr(widget_module.messagebox, "askyesno", lambda *args, **kwargs: False)
    frame.accuse_button.invoke()
    assert session.snapshot().steps == 0
    monkeypatch.setattr(widget_module.messagebox, "askyesno", lambda *args, **kwargs: True)
    frame.accuse_button.invoke()
    assert session.snapshot().winner == 0
    assert str(frame.accuse_button["state"]) == "disabled"


def test_human_pass_and_eliminated_player_reveal(root):
    engine = make_engine()
    engine.step(Suggest(SOLUTION))
    session = GameSession(engine, [ScriptedPolicy()] * 4, human_player=1)
    frame = GameFrame(root, session, paused=True)
    frame.pack()
    assert str(frame.reveal_button["state"]) == "disabled"
    frame.pass_button.invoke()
    assert session.snapshot().to_move == 2
    assert "Player 1 passed." in frame.history.get("1.0", "end")
    frame.destroy()

    engine = make_engine()
    engine.step(Accuse(Combination(1, 6, 12)))
    engine.step(Suggest(Combination(1, 6, 12)))
    engine.step(Pass())
    engine.step(Pass())
    session = GameSession(engine, [ScriptedPolicy()] * 4, human_player=0)
    frame = GameFrame(root, session, paused=True)
    frame.pack()
    assert frame.reveal_choice["values"] == ("Colonel Mustard",)
    frame.reveal_button.invoke()
    assert "Player 0 showed Colonel Mustard to Player 1" in frame.history.get("1.0", "end")


def test_action_limit_disables_controls(root):
    session = GameSession(make_engine(), [ScriptedPolicy()] * 4, human_player=0, max_steps=0)
    frame = GameFrame(root, session, paused=False)
    frame.pack()
    assert "action limit" in frame.status_text.get()
    assert str(frame.suggest_button["state"]) == "disabled"
    assert str(frame.pause_button["state"]) == "disabled"
    assert frame.scheduled is None


def test_invalid_bot_action_pauses_and_shows_error(root):
    class IllegalPolicy:
        def choose(self, view, num_players, legal):
            return Reveal(7)

    session = GameSession(make_engine(), [IllegalPolicy()] * 4)
    frame = GameFrame(root, session, paused=True)
    frame.pack()
    frame.next_button.invoke()
    assert frame.paused
    assert "illegal action" in frame.status_text.get()
    assert "Reveal" not in frame.status_text.get()
    assert session.snapshot().steps == 0


def test_auto_progress_and_pause_cancel_next_action(root):
    policies = [ScriptedPolicy(Suggest(SUGGESTION)), ScriptedPolicy(Reveal(7)),
                ScriptedPolicy(), ScriptedPolicy()]
    session = GameSession(make_engine(), policies)
    frame = GameFrame(root, session, paused=False)
    frame.pack()
    root.after(300, root.quit)
    root.mainloop()
    assert session.snapshot().steps == 1
    assert frame.scheduled is not None
    frame.pause_button.invoke()
    assert frame.paused
    assert frame.scheduled is None


def test_pending_callback_is_cancelled_when_frame_is_destroyed(root):
    session = GameSession(make_engine(), [ScriptedPolicy(Suggest(SUGGESTION)),
                                          ScriptedPolicy(), ScriptedPolicy(), ScriptedPolicy()])
    frame = GameFrame(root, session, paused=False)
    frame.pack()
    assert frame.scheduled is not None
    frame.destroy()
    root.update()
    assert session.snapshot().steps == 0


def test_gui_module_entry_point_starts_and_closes(root):
    script = (
        "import runpy, tkinter as tk\n"
        "original = tk.Tk\n"
        "def hidden_root():\n"
        "    window = original()\n"
        "    window.withdraw()\n"
        "    window.after(10, window.destroy)\n"
        "    return window\n"
        "tk.Tk = hidden_root\n"
        "runpy.run_module('clue_engine.gui', run_name='__main__')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr
