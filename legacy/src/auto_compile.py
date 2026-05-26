from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CompileTrigger = Literal["manual", "auto"]
ControllerDecisionKind = Literal["ignore", "schedule", "start", "queued"]


@dataclass(frozen=True)
class ControllerDecision:
    kind: ControllerDecisionKind
    trigger: CompileTrigger | None = None


class AutoCompileController:
    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.build_in_progress = False
        self.build_requested_while_running = False
        self._pending_trigger: CompileTrigger | None = None

    @property
    def pending_trigger(self) -> CompileTrigger | None:
        return self._pending_trigger

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled and self._pending_trigger == "auto":
            self.clear_pending_auto_rebuild()

    def on_document_edited(self) -> ControllerDecision:
        if not self.enabled:
            return ControllerDecision("ignore")
        if self.build_in_progress:
            self._queue_pending("auto")
            return ControllerDecision("queued", trigger="auto")
        return ControllerDecision("schedule", trigger="auto")

    def request_build(self, trigger: CompileTrigger) -> ControllerDecision:
        if trigger == "auto" and not self.enabled:
            return ControllerDecision("ignore")
        if self.build_in_progress:
            self._queue_pending(trigger)
            return ControllerDecision("queued", trigger=trigger)
        return ControllerDecision("start", trigger=trigger)

    def begin_build(self) -> None:
        self.build_in_progress = True

    def finish_build(self) -> ControllerDecision:
        self.build_in_progress = False
        if not self.build_requested_while_running:
            return ControllerDecision("ignore")

        trigger = self._pending_trigger or "auto"
        self.build_requested_while_running = False
        self._pending_trigger = None
        if trigger == "auto" and not self.enabled:
            return ControllerDecision("ignore")
        return ControllerDecision("start", trigger=trigger)

    def clear_pending_auto_rebuild(self) -> None:
        if self._pending_trigger == "auto":
            self._pending_trigger = None
        self.build_requested_while_running = self._pending_trigger is not None

    def reset(self) -> None:
        self.build_in_progress = False
        self.build_requested_while_running = False
        self._pending_trigger = None

    def _queue_pending(self, trigger: CompileTrigger) -> None:
        self.build_requested_while_running = True
        if trigger == "manual":
            self._pending_trigger = "manual"
        elif self._pending_trigger is None:
            self._pending_trigger = "auto"
