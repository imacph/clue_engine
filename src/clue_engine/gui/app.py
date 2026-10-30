"""Game setup and desktop application entry point."""

import tkinter as tk
from tkinter import messagebox, ttk

from ..policies import POLICY_NAMES, policies_for_players
from ..session import GameSession, create_game
from .batch_window import BatchWindow
from .widgets import GameFrame


class GuiApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Clue Engine")
        root.geometry("1000x720")
        root.minsize(720, 500)
        self.mode = tk.StringVar(master=root, value="play")
        self.players = tk.StringVar(master=root, value="4")
        self.seat = tk.StringVar(master=root, value="0")
        self.seed = tk.StringVar(master=root, value="0")
        self.policy = tk.StringVar(master=root, value="deductive")
        self.policy_by_seat = tk.StringVar(master=root)
        self.progress = tk.StringVar(master=root, value="auto")
        self.limit = tk.StringVar(master=root, value="10000")
        self.debug = tk.BooleanVar(master=root, value=False)
        self.game: GameFrame | None = None
        self.setup = ttk.Frame(root, padding=20)
        self._build_setup()
        self.setup.pack(fill="both", expand=True)

    def _build_setup(self) -> None:
        ttk.Label(self.setup, text="New game", font=("TkDefaultFont", 16, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )
        fields = (
            ("Mode", self.mode, ("play", "spectate")),
            ("Players (at least 2)", self.players, None),
            ("Your seat (zero-based)", self.seat, None),
            ("Random seed", self.seed, None),
            ("Bot policy", self.policy, POLICY_NAMES),
            ("Per-seat policies (all seats, optional)", self.policy_by_seat, None),
            ("Bot progression", self.progress, ("auto", "step")),
            ("Action limit", self.limit, None),
        )
        for row, (label, variable, values) in enumerate(fields, 1):
            ttk.Label(self.setup, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
            if values is None:
                widget = ttk.Entry(self.setup, textvariable=variable)
            else:
                widget = ttk.Combobox(self.setup, textvariable=variable, values=values, state="readonly")
            widget.grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Checkbutton(
            self.setup, text="Omniscient debug (reveals all hands and the solution)", variable=self.debug
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Label(
            self.setup, text="Spectator mode exposes each player's private hand and knowledge."
        ).grid(row=10, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Button(self.setup, text="Start game", command=self.start).grid(row=11, column=0, sticky="w")
        ttk.Button(self.setup, text="Batch statistics", command=self.open_batch).grid(
            row=11, column=1, sticky="w"
        )
        self.setup.columnconfigure(1, weight=1)

    def open_batch(self) -> None:
        BatchWindow(self.root)

    def start(self) -> None:
        try:
            num_players = int(self.players.get())
            seed = int(self.seed.get())
            max_steps = int(self.limit.get())
            human_player = int(self.seat.get()) if self.mode.get() == "play" else None
            if num_players < 2:
                raise ValueError("A game requires at least two players.")
            if human_player is not None and not 0 <= human_player < num_players:
                raise ValueError("Your seat must identify an existing player.")
            if max_steps < 0:
                raise ValueError("The action limit must be non-negative.")
            policy_selection = self.policy_by_seat.get().strip() or self.policy.get()
            policies_for_players(policy_selection, num_players)
        except ValueError as exc:
            messagebox.showerror("Invalid setup", str(exc), parent=self.root)
            return
        if self.debug.get() and not messagebox.askyesno(
            "Omniscient debug",
            "This reveals every hand, the solution, and private events. Continue?",
            parent=self.root,
        ):
            return
        engine, policies = create_game(num_players, seed, policy_selection)
        session = GameSession(
            engine, policies, human_player=human_player, debug=self.debug.get(), max_steps=max_steps
        )
        self.setup.pack_forget()
        self.game = GameFrame(
            self.root, session, paused=self.progress.get() == "step", on_setup=self.show_setup
        )
        self.game.pack(fill="both", expand=True)

    def show_setup(self) -> None:
        if self.game is not None:
            self.game.destroy()
            self.game = None
        self.setup.pack(fill="both", expand=True)


def main() -> None:
    root = tk.Tk()
    GuiApp(root)
    root.mainloop()
