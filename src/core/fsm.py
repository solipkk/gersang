from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Optional


class State(ABC):
    name: str

    def __init__(self, name: str) -> None:
        self.name = name

    def on_enter(self, context: "StateContext") -> None:  # pragma: no cover - hooks
        pass

    @abstractmethod
    def execute(self, context: "StateContext") -> str | None:
        ...

    def on_exit(self, context: "StateContext") -> None:  # pragma: no cover - hooks
        pass


@dataclass
class StateContext:
    matcher: object
    controller: object
    logger: object
    notifier: object | None = None
    last_match: object | None = None
    stop_requested: bool = False
    extras: dict = field(default_factory=dict)


class StateMachine:
    def __init__(self, initial_state: str, states: Dict[str, State], sleep_interval: float = 0.05) -> None:
        if initial_state not in states:
            raise ValueError(f"Initial state '{initial_state}' not found")
        self.current: State = states[initial_state]
        self.states = states
        self.sleep_interval = sleep_interval

    def run(self, context: StateContext, max_steps: Optional[int] = None) -> None:
        steps = 0
        self.current.on_enter(context)
        while not context.stop_requested:
            try:
                next_state_name = self.current.execute(context)
            except Exception as exc:  # pragma: no cover - runtime safeguard
                context.logger(f"Error in state {self.current.name}: {exc}")
                next_state_name = "error"

            steps += 1
            if max_steps and steps >= max_steps:
                break

            if next_state_name is None:
                time.sleep(self.sleep_interval)
                continue

            if next_state_name not in self.states:
                raise ValueError(f"Unknown state transition to '{next_state_name}'")

            self.current.on_exit(context)
            self.current = self.states[next_state_name]
            self.current.on_enter(context)

            time.sleep(self.sleep_interval)


class IdleState(State):
    def __init__(self) -> None:
        super().__init__("idle")

    def execute(self, context: StateContext) -> str | None:
        context.logger("Idle: waiting for next scan")
        return "search"


class SearchingState(State):
    def __init__(self) -> None:
        super().__init__("search")

    def execute(self, context: StateContext) -> str | None:
        matches = context.matcher.locate()
        context.logger(f"Searching: found {len(matches)} candidates")
        best = context.matcher.locate_best()
        if best:
            context.last_match = best
            return "action"
        return None


class ActionState(State):
    def __init__(self) -> None:
        super().__init__("action")

    def execute(self, context: StateContext) -> str | None:
        match = context.last_match
        if not match:
            return "search"

        x, y = match.center
        context.logger(f"Action: clicking {match.template_name} at ({x}, {y}) with score {match.confidence:.3f}")
        context.controller.click(x, y)
        if context.notifier:
            context.notifier.send_message(
                f"Clicked {match.template_name} at ({x}, {y}) score={match.confidence:.3f}"
            )
        context.last_match = None
        return "search"


class ErrorState(State):
    def __init__(self) -> None:
        super().__init__("error")

    def execute(self, context: StateContext) -> str | None:
        context.logger("Error encountered; returning to idle")
        return "idle"
