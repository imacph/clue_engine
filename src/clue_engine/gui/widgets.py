"""Widgets for a single interactive game."""

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from ..cards import CARDS, CARDS_BY_ID
from ..engine import IllegalActionError
from ..knowledge import Mark, knowledge_for
from ..models import (
    Accuse,
    Action,
    CardType,
    Combination,
    EndTurn,
    Pass,
    Reveal,
    Suggest,
)
from ..observations import EventKind, PlayerView
from ..presentation import (
    format_clauses,
    format_debug_information,
    format_event,
    format_hand,
    notebook_activity,
    notebook_actor,
)
from ..session import GameSession, SessionSnapshot

HISTORY_KINDS = tuple(EventKind)
CLAUSE_KINDS = (EventKind.REFUTE, EventKind.ACCUSE)


class GameFrame(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        session: GameSession,
        *,
        paused: bool = False,
        on_setup: Callable[[], None] | None = None,
    ):
        super().__init__(parent, padding=10)
        self.session = session
        self.paused = paused
        self.scheduled: str | None = None
        self._event_count = 0
        self._history_match_count = 0
        self.status_text = tk.StringVar(master=self)
        self.turn_text = tk.StringVar(master=self)
        self.hand_title = tk.StringVar(master=self)
        self.hand_text = tk.StringVar(master=self)
        self.debug_text = tk.StringVar(master=self)
        self._build(on_setup)
        self._refresh()
        self._schedule()

    def _build(self, on_setup: Callable[[], None] | None) -> None:
        snapshot = self.session.snapshot()
        num_players = snapshot.num_players
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(3, weight=1)

        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        ttk.Label(top, textvariable=self.status_text).grid(row=0, column=0, sticky="w")
        ttk.Label(top, textvariable=self.turn_text).grid(row=0, column=1, padx=4)
        self.pause_button = ttk.Button(top, command=self.toggle_pause)
        self.pause_button.grid(row=0, column=2, padx=4)
        self.next_button = ttk.Button(top, text="Next action", command=self.next_action)
        self.next_button.grid(row=0, column=3, padx=4)
        if on_setup is not None:
            ttk.Button(top, text="New game", command=on_setup).grid(row=0, column=4, padx=4)

        debug = ttk.Label(self, textvariable=self.debug_text, foreground="red", justify="left")
        debug.grid(row=1, column=0, sticky="w", pady=4)

        panels = ttk.Panedwindow(self, orient="horizontal")
        panels.grid(row=2, column=0, sticky="nsew", pady=4)
        left = ttk.Frame(panels, padding=5)
        right = ttk.Frame(panels, padding=5)
        panels.add(left, weight=1)
        panels.add(right, weight=1)
        left.columnconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        ttk.Label(left, textvariable=self.hand_title, font=("TkDefaultFont", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(left, textvariable=self.hand_text, wraplength=420, justify="left").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=5
        )
        choices = []
        for row, card_type in enumerate((CardType.SUSPECT, CardType.WEAPON, CardType.ROOM), 2):
            ttk.Label(left, text=card_type.name.title()).grid(row=row, column=0, sticky="w")
            choice = ttk.Combobox(
                left, state="readonly", values=[card.name for card in CARDS[card_type]]
            )
            choice.current(0)
            choice.grid(row=row, column=1, sticky="ew", padx=5, pady=2)
            choices.append(choice)
        self.suspect_choice, self.weapon_choice, self.room_choice = choices
        buttons = ttk.Frame(left)
        buttons.grid(row=5, column=0, columnspan=2, sticky="w", pady=5)
        self.suggest_button = ttk.Button(buttons, text="Suggest", command=self._suggest)
        self.suggest_button.pack(side="left", padx=2)
        self.accuse_button = ttk.Button(buttons, text="Accuse", command=self._accuse)
        self.accuse_button.pack(side="left", padx=2)
        self.end_button = ttk.Button(buttons, text="End turn", command=lambda: self._submit(EndTurn()))
        self.end_button.pack(side="left", padx=2)
        ttk.Label(left, text="Card to reveal").grid(row=6, column=0, sticky="w")
        self.reveal_choice = ttk.Combobox(left, state="disabled", values=())
        self.reveal_choice.grid(row=6, column=1, sticky="ew", padx=5)
        responses = ttk.Frame(left)
        responses.grid(row=7, column=0, columnspan=2, sticky="w", pady=5)
        self.reveal_button = ttk.Button(responses, text="Reveal", command=self._reveal)
        self.reveal_button.pack(side="left", padx=2)
        self.pass_button = ttk.Button(responses, text="Pass", command=lambda: self._submit(Pass()))
        self.pass_button.pack(side="left", padx=2)

        ttk.Label(right, text="Game history", font=("TkDefaultFont", 10, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        history_filters = ttk.Frame(right)
        history_filters.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.history_actor_vars = {
            player: tk.BooleanVar(self, value=True) for player in range(num_players)
        }
        self.history_type_vars = {
            kind: tk.BooleanVar(self, value=True) for kind in HISTORY_KINDS
        }
        self.history_actor_choice = self._history_filter_menu(
            history_filters,
            "Actor",
            [(player, f"Player {player}") for player in range(num_players)],
            self.history_actor_vars,
            "All players",
            0,
        )
        self.history_type_choice = self._history_filter_menu(
            history_filters,
            "Type",
            [(kind, kind.name.replace("_", " ").capitalize()) for kind in HISTORY_KINDS],
            self.history_type_vars,
            "All types",
            1,
        )
        self.history = tk.Text(right, height=10, width=48, wrap="word", state="disabled")
        self.history.grid(row=2, column=0, sticky="nsew")
        history_scroll = ttk.Scrollbar(right, orient="vertical", command=self.history.yview)
        history_scroll.grid(row=2, column=1, sticky="ns")
        self.history.configure(yscrollcommand=history_scroll.set)

        notebook_frame = ttk.LabelFrame(self, text="Detective notebook (+ held, - not held, ? unknown)")
        notebook_frame.grid(row=3, column=0, sticky="nsew")
        notebook_frame.rowconfigure(1, weight=1)
        notebook_frame.columnconfigure(0, weight=1)
        selector = ttk.Frame(notebook_frame)
        selector.grid(row=0, column=0, columnspan=2, sticky="w", padx=4, pady=4)
        ttk.Label(selector, text="Knowledge of:").pack(side="left")
        players = (
            range(num_players) if snapshot.human_player is None else (snapshot.human_player,)
        )
        self.knowledge_player_choice = ttk.Combobox(
            selector, values=[f"Player {player}" for player in players], width=12,
            state="readonly" if snapshot.human_player is None else "disabled",
        )
        self.knowledge_player_choice.current(0)
        self.knowledge_player_choice.pack(side="left", padx=5)
        self.knowledge_player_choice.bind("<<ComboboxSelected>>", self._knowledge_selected)
        ttk.Label(selector, text="Highlighted rows: current cards; T: turn, A: acting").pack(side="left")

        notebook_panels = ttk.Panedwindow(notebook_frame, orient="horizontal")
        notebook_panels.grid(row=1, column=0, columnspan=2, sticky="nsew")
        matrix_frame = ttk.Frame(notebook_panels)
        clauses_frame = ttk.LabelFrame(notebook_panels, text="Clauses")
        notebook_panels.add(matrix_frame, weight=3)
        notebook_panels.add(clauses_frame, weight=2)
        matrix_frame.rowconfigure(0, weight=1)
        matrix_frame.columnconfigure(0, weight=1)
        clauses_frame.rowconfigure(1, weight=1)
        clauses_frame.columnconfigure(0, weight=1)
        clause_filters = ttk.Frame(clauses_frame)
        clause_filters.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.clause_actor_choice, self.clause_type_choice = self._filter_choices(
            clause_filters, num_players, ("Refutation", "Incorrect accusation"),
            self._clause_filter_selected,
        )
        columns = ("card", *(f"p{i}" for i in range(num_players)), "envelope")
        self.notebook = ttk.Treeview(matrix_frame, columns=columns, show="headings", height=8)
        self.notebook.tag_configure("activity", background="#e6f2f6", foreground="#173847")
        self.notebook.heading("card", text="Card")
        self.notebook.column("card", width=150, anchor="w")
        for i in range(num_players):
            self.notebook.heading(f"p{i}", text=f"Player {i} ({snapshot.hand_sizes[i]})")
            self.notebook.column(f"p{i}", width=75, anchor="center")
        self.notebook.heading("envelope", text="Envelope")
        self.notebook.column("envelope", width=85, anchor="center")
        self.notebook.grid(row=0, column=0, sticky="nsew")
        notebook_scroll = ttk.Scrollbar(matrix_frame, orient="vertical", command=self.notebook.yview)
        notebook_scroll.grid(row=0, column=1, sticky="ns")
        horizontal_scroll = ttk.Scrollbar(
            matrix_frame, orient="horizontal", command=self.notebook.xview
        )
        horizontal_scroll.grid(row=1, column=0, sticky="ew")
        self.notebook.configure(
            yscrollcommand=notebook_scroll.set, xscrollcommand=horizontal_scroll.set
        )
        self.clauses = tk.Text(clauses_frame, height=8, width=36, wrap="word", state="disabled")
        self.clauses.grid(row=1, column=0, sticky="nsew")
        clause_scroll = ttk.Scrollbar(clauses_frame, orient="vertical", command=self.clauses.yview)
        clause_scroll.grid(row=1, column=1, sticky="ns")
        self.clauses.configure(yscrollcommand=clause_scroll.set)

    def _history_filter_menu(
        self,
        parent: ttk.Frame,
        title: str,
        choices: list[tuple[object, str]],
        variables: dict[object, tk.BooleanVar],
        all_label: str,
        column: int,
    ) -> ttk.Menubutton:
        button = ttk.Menubutton(parent, text=f"{title}: All")
        menu = tk.Menu(button, tearoff=False)
        button.configure(menu=menu)
        menu.add_command(
            label=all_label,
            command=lambda: self._select_all_history_filter(variables),
        )
        menu.add_separator()
        for value, label in choices:
            menu.add_checkbutton(
                label=label,
                variable=variables[value],
                command=self._history_filter_selected,
            )
        button.grid(row=0, column=column, sticky="w", padx=3)
        return button

    def _select_all_history_filter(self, variables: dict[object, tk.BooleanVar]) -> None:
        for variable in variables.values():
            variable.set(True)
        self._history_filter_selected()

    @staticmethod
    def _filter_choices(
        parent: ttk.Frame,
        num_players: int,
        types: tuple[str, ...],
        callback: Callable[[tk.Event], None],
    ) -> tuple[ttk.Combobox, ttk.Combobox]:
        parent.columnconfigure(1, weight=1)
        ttk.Label(parent, text="Actor:").grid(row=0, column=0, sticky="w")
        actor = ttk.Combobox(
            parent, state="readonly", width=11,
            values=("All players", *(f"Player {player}" for player in range(num_players))),
        )
        actor.current(0)
        actor.grid(row=0, column=1, sticky="ew", padx=3)
        ttk.Label(parent, text="Type:").grid(row=1, column=0, sticky="w")
        kind = ttk.Combobox(parent, state="readonly", width=20, values=("All types", *types))
        kind.current(0)
        kind.grid(row=1, column=1, sticky="ew", padx=3)
        actor.bind("<<ComboboxSelected>>", callback)
        kind.bind("<<ComboboxSelected>>", callback)
        return actor, kind

    @staticmethod
    def _set_enabled(widget: ttk.Widget, enabled: bool) -> None:
        widget.configure(state="normal" if enabled else "disabled")

    def _refresh(self) -> None:
        snapshot = self.session.snapshot()
        if snapshot.is_over:
            status = (
                "Game over: all players were eliminated."
                if snapshot.winner is None else f"Game over: Player {snapshot.winner} wins."
            )
        elif snapshot.limit_reached:
            status = f"Game stopped at the {snapshot.max_steps}-action limit."
        else:
            status = f"Player {snapshot.to_move} to act. Actions: {snapshot.steps}"
        self.status_text.set(status)
        self.turn_text.set(f"Player 0 turns: {snapshot.player0_turns}")
        if snapshot.view is None:
            view = self.session.spectator_view(self.knowledge_player_choice.current())
            self.hand_title.set(f"Player {view.player}'s hand (spectator)")
        else:
            view = snapshot.view
            self.hand_title.set("Your hand")
        self.hand_text.set(format_hand(view.own_hand))
        if snapshot.debug_info is not None:
            self.debug_text.set(format_debug_information(
                snapshot.debug_info.solution, snapshot.debug_info.hands
            ))
        self._refresh_history(snapshot)
        self._refresh_notebook(snapshot, view)
        self._refresh_actions(snapshot)

    def _refresh_history(self, snapshot: SessionSnapshot) -> None:
        actors = {
            actor for actor, variable in self.history_actor_vars.items() if variable.get()
        }
        kinds = {
            kind for kind, variable in self.history_type_vars.items() if variable.get()
        }
        self.history.configure(state="normal")
        if self._history_match_count == 0:
            self.history.delete("1.0", "end")
        for index in range(self._event_count, len(snapshot.events)):
            event = snapshot.events[index]
            if event.actor not in actors or event.kind not in kinds:
                continue
            previous = snapshot.events[index - 1] if index else None
            self.history.insert("end", format_event(event, previous) + "\n")
            self._history_match_count += 1
        filtered = not all(variable.get() for variable in (
            *self.history_actor_vars.values(), *self.history_type_vars.values()
        ))
        if self._history_match_count == 0 and filtered:
            self.history.insert("end", "No events match the current filters.\n")
        self._event_count = len(snapshot.events)
        self.history.see("end")
        self.history.configure(state="disabled")

    def _history_filter_selected(self, _event: tk.Event | None = None) -> None:
        self.history_actor_choice.configure(
            text=self._history_filter_label("Actor", self.history_actor_vars)
        )
        self.history_type_choice.configure(
            text=self._history_filter_label("Type", self.history_type_vars)
        )
        self._event_count = 0
        self._history_match_count = 0
        self._refresh_history(self.session.snapshot())

    @staticmethod
    def _history_filter_label(title: str, variables: dict[object, tk.BooleanVar]) -> str:
        selected = sum(variable.get() for variable in variables.values())
        total = len(variables)
        summary = "All" if selected == total else "None" if selected == 0 else f"{selected} selected"
        return f"{title}: {summary}"

    def _clause_filter_selected(self, _event: tk.Event) -> None:
        self._refresh()

    def _knowledge_selected(self, _event: tk.Event) -> None:
        self._refresh()

    def _refresh_notebook(self, snapshot: SessionSnapshot, view: PlayerView) -> None:
        knowledge = knowledge_for(view, snapshot.num_players)
        focus, _ = notebook_activity(view.events)
        cards_in_focus = (
            {focus.combo.suspect_id, focus.combo.weapon_id, focus.combo.room_id}
            if focus is not None and focus.combo is not None else set()
        )
        actor = notebook_actor(
            snapshot.turn_player, snapshot.to_move, view.player,
            public_refutations=self.session.game_rules.public_refutations,
            omniscient=snapshot.debug_info is not None,
        )
        for seat in range(snapshot.num_players):
            labels = []
            if not snapshot.is_over and not snapshot.limit_reached and seat == snapshot.turn_player:
                labels.append("T")
            if not snapshot.is_over and not snapshot.limit_reached and seat == actor:
                labels.append("A")
            suffix = f" [{'/'.join(labels)}]" if labels else ""
            self.notebook.heading(
                f"p{seat}", text=f"P{seat} ({snapshot.hand_sizes[seat]}){suffix}",
            )
        symbols = {Mark.UNKNOWN: "?", Mark.HELD: "+", Mark.NOT_HELD: "-"}
        for cards in CARDS.values():
            for card in cards:
                values = (card.name, *(
                    symbols[knowledge.mark_of(holder, card.id)]
                    for holder in range(snapshot.num_players + 1)
                ))
                item_id = str(card.id)
                tags = ("activity",) if card.id in cards_in_focus else ()
                if self.notebook.exists(item_id):
                    self.notebook.item(item_id, values=values, tags=tags)
                else:
                    self.notebook.insert("", "end", iid=item_id, values=values, tags=tags)
        self.clauses.configure(state="normal")
        self.clauses.delete("1.0", "end")
        actor_index = self.clause_actor_choice.current() - 1
        kind_index = self.clause_type_choice.current() - 1
        self.clauses.insert("1.0", format_clauses(
            knowledge,
            view=view,
            actor=actor_index if actor_index >= 0 else None,
            kind=CLAUSE_KINDS[kind_index] if kind_index >= 0 else None,
        ))
        self.clauses.configure(state="disabled")

    def _refresh_actions(self, snapshot: SessionSnapshot) -> None:
        legal = snapshot.legal_actions
        for button, action_type in (
            (self.suggest_button, Suggest), (self.accuse_button, Accuse),
            (self.end_button, EndTurn), (self.reveal_button, Reveal), (self.pass_button, Pass),
        ):
            self._set_enabled(button, any(isinstance(action, action_type) for action in legal))
        can_select = any(isinstance(action, (Suggest, Accuse)) for action in legal)
        for choice in (self.suspect_choice, self.weapon_choice, self.room_choice):
            choice.configure(state="readonly" if can_select else "disabled")
        reveals = [CARDS_BY_ID[action.card_id].name for action in legal if isinstance(action, Reveal)]
        selected = self.reveal_choice.get()
        self.reveal_choice.configure(values=reveals, state="readonly" if reveals else "disabled")
        if reveals:
            self.reveal_choice.set(selected if selected in reveals else reveals[0])
        else:
            self.reveal_choice.set("")
        active = not snapshot.is_over and not snapshot.limit_reached
        self.pause_button.configure(text="Resume" if self.paused else "Pause")
        self._set_enabled(self.pause_button, active)
        self._set_enabled(
            self.next_button,
            active and self.paused and snapshot.to_move != snapshot.human_player,
        )

    def _selected_combination(self) -> Combination:
        def selected(card_type: CardType, choice: ttk.Combobox) -> int:
            return next(card.id for card in CARDS[card_type] if card.name == choice.get())

        return Combination(
            selected(CardType.SUSPECT, self.suspect_choice),
            selected(CardType.WEAPON, self.weapon_choice),
            selected(CardType.ROOM, self.room_choice),
        )

    def _submit(self, action: Action) -> None:
        try:
            self.session.submit(action)
        except ValueError as exc:
            self.status_text.set(str(exc))
            return
        self._refresh()
        self._schedule()

    def _suggest(self) -> None:
        self._submit(Suggest(self._selected_combination()))

    def _accuse(self) -> None:
        if messagebox.askyesno(
            "Confirm accusation", "An incorrect accusation eliminates you. Continue?", parent=self
        ):
            self._submit(Accuse(self._selected_combination()))

    def _reveal(self) -> None:
        card = next(card for card in CARDS_BY_ID.values() if card.name == self.reveal_choice.get())
        self._submit(Reveal(card.id))

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        if self.paused:
            self._cancel_scheduled()
        self._refresh()
        self._schedule()

    def next_action(self) -> None:
        snapshot = self.session.snapshot()
        if (
            self.paused and not snapshot.is_over and not snapshot.limit_reached
            and snapshot.to_move != snapshot.human_player
        ):
            self._advance_bot()

    def _advance_bot(self) -> None:
        self.scheduled = None
        try:
            self.session.advance_bot()
        except IllegalActionError:
            self.paused = True
            self._refresh()
            self.status_text.set("Bot attempted an illegal action; game paused.")
            return
        self._refresh()
        self._schedule()

    def _schedule(self) -> None:
        snapshot = self.session.snapshot()
        if (
            not self.paused and self.scheduled is None
            and not snapshot.is_over and not snapshot.limit_reached
            and snapshot.to_move != snapshot.human_player
        ):
            self.scheduled = self.after(200, self._advance_bot)

    def _cancel_scheduled(self) -> None:
        if self.scheduled is not None:
            self.after_cancel(self.scheduled)
            self.scheduled = None

    def destroy(self) -> None:
        self._cancel_scheduled()
        super().destroy()
