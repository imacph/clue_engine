"""Responsive desktop interface for batch simulations."""

import json
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from queue import Empty, Queue
from threading import Event
from tkinter import filedialog, messagebox, ttk

from ..batch import (
    BatchConfig,
    BatchSummary,
    batch_config_from_setup,
    format_summary,
    policy_profiles,
    read_game_trace,
    run_batch,
)
from ..distributions import Distributions, read_distributions
from .distribution_view import DistributionView


def _load_trace_text(path: Path, game: int) -> str:
    return "\n".join(json.dumps(record, indent=2) for record in read_game_trace(path, game))


class BatchWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.title("Batch statistics")
        self.geometry("920x680")
        self.minsize(680, 480)
        self.games = tk.StringVar(master=self, value="100")
        self.players = tk.StringVar(master=self, value="4")
        self.policies = tk.StringVar(master=self, value="deductive,random,random,random")
        self.seed = tk.StringVar(master=self, value="0")
        self.limit = tk.StringVar(master=self, value="10000")
        self.setup_json = tk.StringVar(master=self)
        self.trace = tk.StringVar(master=self)
        self.rotate = tk.BooleanVar(master=self, value=True)
        self.shuffle_bots = tk.BooleanVar(master=self, value=False)
        self.game_number = tk.StringVar(master=self, value="0")
        self.status = tk.StringVar(master=self, value="Choose a new trace file to begin.")
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clue-batch")
        self._cancel = Event()
        self._updates: Queue[BatchSummary] = Queue(maxsize=1)
        self._future: Future[BatchSummary] | None = None
        self._trace_future: Future[str] | None = None
        self._distribution_future: Future[Distributions] | None = None
        self._building_distributions: Distributions | None = None
        self._poll_id: str | None = None
        self._render_id: str | None = None
        self._render_text: str | None = None
        self._render_position = 0
        self._trace_game = 0
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        setup = ttk.Frame(self, padding=10)
        setup.grid(row=0, column=0, sticky="ew")
        setup.columnconfigure(1, weight=1)
        fields = (
            ("Games", self.games), ("Players", self.players),
            ("Policies (random/deductive/probing/strategic/analytical)", self.policies),
            ("Seed", self.seed), ("Action limit per game", self.limit),
            ("Game setup JSON (optional)", self.setup_json), ("Private JSONL trace", self.trace),
        )
        for row, (label, variable) in enumerate(fields):
            ttk.Label(setup, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
            ttk.Entry(setup, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=2)
        ttk.Button(setup, text="Setup...", command=self._browse_setup).grid(row=5, column=2, padx=4)
        ttk.Button(setup, text="Browse", command=self._browse).grid(row=6, column=2, padx=4)
        ttk.Button(setup, text="Existing...", command=self._browse_existing).grid(row=6, column=3, padx=4)
        ttk.Label(
            setup, text="Setup JSON supplies game type, players, bots, and rule settings; seed and limit above override it.",
        ).grid(row=7, column=0, columnspan=4, sticky="w", pady=2)
        ttk.Checkbutton(setup, text="Rotate policies over seats", variable=self.rotate).grid(
            row=8, column=0, columnspan=2, sticky="w"
        )
        ttk.Checkbutton(
            setup,
            text="Randomize bot profiles; balance assignments across complete seat rotations",
            variable=self.shuffle_bots,
        ).grid(row=9, column=0, columnspan=4, sticky="w")
        ttk.Label(
            setup, text="WARNING: traces contain private hands, shown cards, and solutions.",
            foreground="red",
        ).grid(row=10, column=0, columnspan=4, sticky="w", pady=4)
        buttons = ttk.Frame(setup)
        buttons.grid(row=11, column=0, columnspan=4, sticky="w")
        self.start_button = ttk.Button(buttons, text="Start batch", command=self.start)
        self.start_button.pack(side="left", padx=3)
        self.cancel_button = ttk.Button(buttons, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=3)
        ttk.Label(buttons, text="Game number (zero-based):").pack(side="left", padx=(12, 3))
        ttk.Entry(buttons, textvariable=self.game_number, width=8).pack(side="left")
        self.open_button = ttk.Button(buttons, text="Open trace", command=self.open_trace)
        self.open_button.pack(side="left", padx=3)
        ttk.Label(self, textvariable=self.status, padding=(10, 0)).grid(row=1, column=0, sticky="w")
        notebook = ttk.Notebook(self)
        notebook.grid(row=2, column=0, sticky="nsew")
        output_frame = ttk.Frame(notebook, padding=10)
        notebook.add(output_frame, text="Summary and trace")
        self.distribution_view = DistributionView(notebook, self.load_distributions)
        notebook.add(self.distribution_view, text="Distributions")
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        self.output = tk.Text(output_frame, wrap="word", state="disabled")
        self.output.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(output_frame, orient="vertical", command=self.output.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.output.configure(yscrollcommand=scroll.set)

    def _browse(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self, title="Save private trace", defaultextension=".jsonl",
            filetypes=(("JSON Lines", "*.jsonl"), ("All files", "*.*")),
        )
        if path:
            self.trace.set(path)

    def _browse_existing(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="Open private trace",
            filetypes=(("JSON Lines", "*.jsonl"), ("All files", "*.*")),
        )
        if path:
            self.trace.set(path)

    def _browse_setup(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="Open game setup JSON",
            filetypes=(("JSON", "*.json"), ("All files", "*.*")),
        )
        if path:
            self.setup_json.set(path)

    def _show(self, text: str) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")

    def start(self) -> None:
        if (self._future is not None or self._trace_future is not None
                or self._distribution_future is not None or self._render_id is not None):
            return
        try:
            count = int(self.games.get())
            seed = int(self.seed.get())
            limit = int(self.limit.get())
            setup_path = self.setup_json.get().strip()
            if setup_path:
                setup = json.loads(Path(setup_path).read_text(encoding="utf-8"))
                if self.shuffle_bots.get():
                    setup["shuffle_bots"] = True
                config = batch_config_from_setup(
                    setup, games=count, seed=seed, max_steps=limit, rotate=self.rotate.get(),
                )
            else:
                players = int(self.players.get())
                if players < 2:
                    raise ValueError("players must be at least 2")
                names = policy_profiles(self.policies.get(), players, self.shuffle_bots.get())
                config = BatchConfig(
                    count, names, seed, limit, self.rotate.get(),
                    shuffle_bots=self.shuffle_bots.get(), players=players,
                )
                config.validate()
            path_text = self.trace.get().strip()
            if not path_text:
                raise ValueError("choose a new trace file")
            path = Path(path_text)
        except (OSError, TypeError, ValueError) as exc:
            messagebox.showerror("Invalid batch settings", str(exc), parent=self)
            return
        warning = "The trace contains private hands, shown cards, and solutions. Save it locally?"
        if config.rotate and not config.shuffle_bots and config.games % len(config.policies):
            warning += "\n\nThe final rotation is incomplete; policy seat exposures may be unbalanced."
        if not messagebox.askyesno("Private trace", warning, parent=self):
            return
        self._cancel.clear()
        try:
            self._updates.get_nowait()
        except Empty:
            pass
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.open_button.configure(state="disabled")
        self.distribution_view.load_button.configure(state="disabled")
        self.distribution_view.set_data(None)
        self._building_distributions = Distributions()
        self.status.set("Running batch...")
        self._show("")

        updates = self._updates

        def progress(summary: BatchSummary) -> None:
            if not updates.full():
                updates.put_nowait(summary)

        self._future = self._executor.submit(
            run_batch, config, path, progress=progress, cancelled=self._cancel.is_set,
            on_game=self._building_distributions.add_game,
        )
        self._schedule_poll()

    def _schedule_poll(self) -> None:
        if self._poll_id is None:
            self._poll_id = self.after(100, self._poll)

    def _poll(self) -> None:
        self._poll_id = None
        try:
            summary = self._updates.get_nowait()
        except Empty:
            pass
        else:
            self.status.set(f"Running: {summary['started_games']}/{summary['requested_games']} games")
            self._show(format_summary(summary))
        if self._future is not None and self._future.done():
            error = self._future.exception()
            if error is not None:
                self.status.set(f"Batch failed: {error}")
                self._show(f"Batch failed: {type(error).__name__}: {error}")
            else:
                summary = self._future.result()
                if summary["cancelled"]:
                    self.status.set("Batch cancelled.")
                elif summary["outcomes"]["error"] or summary["outcomes"]["timeout"]:
                    self.status.set("Batch finished with errors or timeouts; see summary and trace.")
                else:
                    self.status.set("Batch complete.")
                self._show(format_summary(summary))
                self.distribution_view.set_data(self._building_distributions)
            self._building_distributions = None
            self._future = None
            self.start_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")
            self.open_button.configure(state="normal")
            self.distribution_view.load_button.configure(state="normal")
        if self._trace_future is not None and self._trace_future.done():
            error = self._trace_future.exception()
            if error is not None:
                self.status.set(f"Unable to open trace: {error}")
                self.open_button.configure(state="normal")
                self.start_button.configure(state="normal")
                self.distribution_view.load_button.configure(state="normal")
            else:
                self._render_text = self._trace_future.result()
                self._render_position = 0
                self.output.configure(state="normal")
                self.output.delete("1.0", "end")
                self._render_chunk()
            self._trace_future = None
        if self._distribution_future is not None and self._distribution_future.done():
            error = self._distribution_future.exception()
            if error is not None:
                self.status.set(f"Unable to load distributions: {error}")
            else:
                self.distribution_view.set_data(self._distribution_future.result())
                self.status.set("Loaded distributions from private trace.")
            self._distribution_future = None
            self.open_button.configure(state="normal")
            self.start_button.configure(state="normal")
            self.distribution_view.load_button.configure(state="normal")
        if self._future is not None or self._trace_future is not None or self._distribution_future is not None:
            self._schedule_poll()

    def _render_chunk(self) -> None:
        self._render_id = None
        assert self._render_text is not None
        end = self._render_position + 32_000
        self.output.insert("end", self._render_text[self._render_position:end])
        self._render_position = end
        if end < len(self._render_text):
            self._render_id = self.after(1, self._render_chunk)
        else:
            self._render_text = None
            self.output.configure(state="disabled")
            self.status.set(f"Showing game {self._trace_game} (private trace).")
            self.open_button.configure(state="normal")
            self.start_button.configure(state="normal")
            self.distribution_view.load_button.configure(state="normal")

    def cancel(self) -> None:
        self._cancel.set()
        self.status.set("Cancelling after the current action...")
        self.cancel_button.configure(state="disabled")

    def open_trace(self) -> None:
        if (self._future is not None or self._trace_future is not None
                or self._distribution_future is not None or self._render_id is not None):
            return
        try:
            path = self.trace.get().strip()
            if not path:
                raise ValueError("choose a trace file")
            game = int(self.game_number.get())
            if game < 0:
                raise ValueError("game number must be non-negative")
        except ValueError as exc:
            messagebox.showerror("Invalid game number", str(exc), parent=self)
            return
        self.status.set(f"Loading game {game}...")
        self.open_button.configure(state="disabled")
        self.start_button.configure(state="disabled")
        self.distribution_view.load_button.configure(state="disabled")
        self._trace_game = game
        self._trace_future = self._executor.submit(_load_trace_text, Path(path), game)
        self._schedule_poll()

    def load_distributions(self) -> None:
        if (self._future is not None or self._trace_future is not None
                or self._distribution_future is not None or self._render_id is not None):
            return
        path = self.trace.get().strip()
        if not path:
            messagebox.showerror("Invalid trace", "Choose a trace file.", parent=self)
            return
        self._cancel.clear()
        self.status.set("Loading distributions from private trace...")
        self.open_button.configure(state="disabled")
        self.start_button.configure(state="disabled")
        self.distribution_view.load_button.configure(state="disabled")
        self.distribution_view.set_data(None)
        self._distribution_future = self._executor.submit(
            read_distributions, Path(path), cancelled=self._cancel.is_set,
        )
        self._schedule_poll()

    def destroy(self) -> None:
        self._cancel.set()
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        if self._render_id is not None:
            self.after_cancel(self._render_id)
            self._render_id = None
        self._executor.shutdown(wait=False, cancel_futures=True)
        super().destroy()
