"""Tk histogram controls and rendering for empirical batch distributions."""

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from ..distributions import METRICS, MODES, Distribution, Distributions


class DistributionView(ttk.Frame):
    def __init__(self, parent: tk.Misc, on_load: Callable[[], None]):
        super().__init__(parent, padding=8)
        self.metric = tk.StringVar(master=self, value="actions")
        self.width = tk.StringVar(master=self, value="10")
        self.mode = tk.StringVar(master=self, value="count")
        self.policy = tk.StringVar(master=self, value="all")
        self.seat = tk.StringVar(master=self, value="all")
        self.description = tk.StringVar(master=self, value="Run a batch or load a trace.")
        self.data: Distributions | None = None
        self.chart: Distribution | None = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        controls = ttk.Frame(self)
        controls.grid(row=0, column=0, sticky="ew")
        ttk.Label(controls, text="Metric").grid(row=0, column=0, padx=3)
        metric = ttk.Combobox(controls, textvariable=self.metric, values=METRICS, state="readonly", width=21)
        metric.grid(row=0, column=1, padx=3)
        ttk.Label(controls, text="Bin width").grid(row=0, column=2, padx=3)
        width_entry = ttk.Entry(controls, textvariable=self.width, width=5)
        width_entry.grid(row=0, column=3, padx=3)
        ttk.Label(controls, text="Display").grid(row=0, column=4, padx=3)
        mode = ttk.Combobox(controls, textvariable=self.mode, values=MODES, state="readonly", width=8)
        mode.grid(row=0, column=5, padx=3)
        ttk.Label(controls, text="Policy").grid(row=1, column=0, padx=3)
        self.policy_choice = ttk.Combobox(
            controls, textvariable=self.policy, values=("all",), state="disabled", width=11
        )
        self.policy_choice.grid(row=1, column=1, padx=3)
        ttk.Label(controls, text="Seat").grid(row=1, column=2, padx=3)
        self.seat_entry = ttk.Entry(controls, textvariable=self.seat, state="disabled", width=5)
        self.seat_entry.grid(row=1, column=3, padx=3)
        ttk.Label(controls, text="Filters apply to deduction only").grid(row=1, column=4, columnspan=2)
        ttk.Button(controls, text="Refresh chart", command=self.refresh).grid(row=0, column=6, padx=5)
        self.load_button = ttk.Button(controls, text="Load trace distributions", command=on_load)
        self.load_button.grid(row=1, column=6, padx=5)
        metric.bind("<<ComboboxSelected>>", self._metric_changed)
        mode.bind("<<ComboboxSelected>>", self._refresh_event)
        self.policy_choice.bind("<<ComboboxSelected>>", self._refresh_event)
        width_entry.bind("<Return>", self._refresh_event)
        self.seat_entry.bind("<Return>", self._refresh_event)
        ttk.Label(self, textvariable=self.description, wraplength=850).grid(row=1, column=0, sticky="w", pady=6)
        plot = ttk.Frame(self)
        plot.grid(row=2, column=0, sticky="nsew")
        plot.columnconfigure(0, weight=1)
        plot.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(plot, background="white", height=280, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(plot, orient="horizontal", command=self.canvas.xview)
        scrollbar.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=scrollbar.set)
        self.canvas.bind("<Configure>", self._resize)

    def set_data(self, data: Distributions | None) -> None:
        self.data = data
        names = sorted({name for name, _ in data.exposures}) if data is not None else []
        values = ("all", *names)
        self.policy_choice.configure(values=values)
        if self.policy.get() not in values:
            self.policy.set("all")
        self.refresh()

    def _metric_changed(self, event: tk.Event) -> None:
        deduction = self.metric.get() == "deduction"
        self.policy_choice.configure(state="readonly" if deduction else "disabled")
        self.seat_entry.configure(state="normal" if deduction else "disabled")
        self.refresh()

    def _refresh_event(self, event: tk.Event) -> None:
        self.refresh()

    def refresh(self) -> None:
        self.chart = None
        self.canvas.delete("all")
        if self.data is None:
            self.description.set("Run a batch or load a trace.")
            return
        try:
            width = int(self.width.get())
            policy = None
            seat = None
            if self.metric.get() == "deduction":
                policy_text = self.policy.get().strip()
                seat_text = self.seat.get().strip()
                policy = None if policy_text == "all" else policy_text
                seat = None if seat_text == "all" else int(seat_text)
            chart = self.data.chart(self.metric.get(), width=width, policy=policy, seat=seat)
            if self.mode.get() not in MODES:
                raise ValueError("invalid display mode")
        except ValueError as exc:
            self.description.set(f"Invalid chart settings: {exc}")
            return
        self.chart = chart
        self.description.set(f"{chart.title}: {chart.samples} {chart.denominator}. {chart.details}")
        self._draw()

    def _resize(self, event: tk.Event) -> None:
        if self.chart is not None:
            self._draw()

    def _draw(self) -> None:
        chart = self.chart
        assert chart is not None
        self.canvas.delete("all")
        height = max(250, self.canvas.winfo_height())
        slot = max(75, max((len(row.label) for row in chart.bins), default=0) * 8 + 16)
        width = max(600, self.canvas.winfo_width(), 100 + slot * len(chart.bins))
        self.canvas.configure(scrollregion=(0, 0, width, height))
        if not chart.samples:
            self.canvas.create_text(20, 30, text="No observations.", anchor="nw", tags=("empty",))
            return
        top, bottom = 35, height - 48
        self.canvas.create_line(65, top, 65, bottom, width - 15, bottom)
        values = [
            row.count if self.mode.get() == "count" else row.probability * 100
            for row in chart.bins
        ]
        maximum = max(values, default=0)
        max_label = str(maximum) if self.mode.get() == "count" else f"{maximum:.1f}%"
        self.canvas.create_text(60, top, text=max_label, anchor="e")
        self.canvas.create_text(60, bottom, text="0", anchor="e")
        for index, (row, value) in enumerate(zip(chart.bins, values, strict=True)):
            left = 75 + index * slot
            bar_width = slot - 26
            bar_top = bottom - (bottom - top) * value / maximum if maximum else bottom
            self.canvas.create_rectangle(left, bar_top, left + bar_width, bottom, fill="#3978b6", tags=("bar",))
            label = str(row.count) if self.mode.get() == "count" else f"{row.probability * 100:.1f}%"
            self.canvas.create_text(left + bar_width / 2, bar_top - 3, text=label, anchor="s", tags=("value",))
            self.canvas.create_text(left + bar_width / 2, bottom + 5, text=row.label, anchor="n", tags=("bin",))
