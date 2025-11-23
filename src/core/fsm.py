from __future__ import annotations

import random
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
    human_behavior: "HumanBehaviorSettings" | None = None
    last_match: object | None = None
    stop_requested: bool = False
    extras: dict = field(default_factory=dict)


@dataclass
class HumanBehaviorSettings:
    rest_interval_min_minutes: int = 40
    rest_interval_max_minutes: int = 60
    rest_duration_min_minutes: int = 1
    rest_duration_max_minutes: int = 5
    micro_noise_chance: float = 0.015
    noise_keys: tuple[str, ...] = ("i", "s")


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
        detour = _human_checks(context)
        if detour:
            return detour
        context.logger("Idle: waiting for next scan")
        return "search"


class SearchingState(State):
    def __init__(self) -> None:
        super().__init__("search")

    def execute(self, context: StateContext) -> str | None:
        detour = _human_checks(context)
        if detour:
            return detour
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
        return _human_checks(context) or "search"


class ErrorState(State):
    def __init__(self) -> None:
        super().__init__("error")

    def execute(self, context: StateContext) -> str | None:
        context.logger("Error encountered; returning to idle")
        return "idle"


def _human_checks(context: StateContext) -> str | None:
    behavior = context.human_behavior or HumanBehaviorSettings()
    _ensure_rest_schedule(context, behavior)
    if behavior.rest_interval_max_minutes > 0 and _should_rest(context):
        return "resting"
    if behavior.micro_noise_chance > 0 and _should_noise(context):
        return "noise"
    return None


def _ensure_rest_schedule(context: StateContext, behavior: HumanBehaviorSettings) -> None:
    if "next_rest_at" in context.extras:
        return
    interval_minutes = random.uniform(
        max(0, behavior.rest_interval_min_minutes), max(behavior.rest_interval_min_minutes, behavior.rest_interval_max_minutes)
    )
    context.extras["next_rest_at"] = time.monotonic() + interval_minutes * 60


def _should_rest(context: StateContext) -> bool:
    next_rest = context.extras.get("next_rest_at")
    if next_rest is None:
        return False
    return time.monotonic() >= next_rest


def _schedule_next_rest(context: StateContext, behavior: HumanBehaviorSettings) -> None:
    interval_minutes = random.uniform(
        max(0, behavior.rest_interval_min_minutes), max(behavior.rest_interval_min_minutes, behavior.rest_interval_max_minutes)
    )
    context.extras["next_rest_at"] = time.monotonic() + interval_minutes * 60


def _should_noise(context: StateContext) -> bool:
    last_noise = context.extras.get("last_noise_at", 0)
    if time.monotonic() - last_noise < 30:
        return False
    behavior = context.human_behavior or HumanBehaviorSettings()
    return random.random() < behavior.micro_noise_chance


class RestingState(State):
    def __init__(self) -> None:
        super().__init__("resting")

    def on_enter(self, context: StateContext) -> None:
        behavior = context.human_behavior or HumanBehaviorSettings()
        duration_minutes = random.uniform(
            max(0.1, behavior.rest_duration_min_minutes),
            max(behavior.rest_duration_min_minutes, behavior.rest_duration_max_minutes),
        )
        rest_seconds = duration_minutes * 60
        context.extras["rest_until"] = time.monotonic() + rest_seconds
        context.logger(f"Resting for {rest_seconds:.0f} seconds to mimic downtime")

    def execute(self, context: StateContext) -> str | None:
        rest_until = context.extras.get("rest_until", 0)
        if time.monotonic() >= rest_until:
            behavior = context.human_behavior or HumanBehaviorSettings()
            _schedule_next_rest(context, behavior)
            context.logger("Rest complete; resuming search")
            return "search"
        return None

    def on_exit(self, context: StateContext) -> None:
        context.extras.pop("rest_until", None)


class NoiseState(State):
    def __init__(self) -> None:
        super().__init__("noise")

    def on_enter(self, context: StateContext) -> None:
        behavior = context.human_behavior or HumanBehaviorSettings()
        key = random.choice(behavior.noise_keys or ("i", "s"))
        context.extras["noise_key"] = key
        context.logger(f"Micro-noise: performing harmless check with '{key.upper()}'")

    def execute(self, context: StateContext) -> str | None:
        key = context.extras.get("noise_key")
        if key:
            context.controller.tap_key(key)
            context.controller.tap_key(key)
        context.extras["last_noise_at"] = time.monotonic()
        return "search"

    def on_exit(self, context: StateContext) -> None:
        context.extras.pop("noise_key", None)
