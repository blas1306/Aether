from __future__ import annotations

from auto_compile import AutoCompileController


def test_auto_compile_off_does_not_schedule_builds() -> None:
    controller = AutoCompileController(enabled=False)

    decision = controller.on_document_edited()

    assert decision.kind == "ignore"


def test_auto_compile_on_schedules_debounced_build() -> None:
    controller = AutoCompileController(enabled=True)

    decision = controller.on_document_edited()

    assert decision.kind == "schedule"
    assert decision.trigger == "auto"


def test_manual_build_still_starts_when_auto_compile_is_off() -> None:
    controller = AutoCompileController(enabled=False)

    decision = controller.request_build("manual")

    assert decision.kind == "start"
    assert decision.trigger == "manual"


def test_builds_are_not_overlapped_and_pending_auto_build_runs_after_finish() -> None:
    controller = AutoCompileController(enabled=True)
    controller.begin_build()

    queued = controller.request_build("auto")
    follow_up = controller.finish_build()

    assert queued.kind == "queued"
    assert controller.build_in_progress is False
    assert follow_up.kind == "start"
    assert follow_up.trigger == "auto"


def test_pending_manual_build_takes_priority_over_auto_follow_up() -> None:
    controller = AutoCompileController(enabled=True)
    controller.begin_build()

    controller.request_build("auto")
    queued = controller.request_build("manual")
    follow_up = controller.finish_build()

    assert queued.kind == "queued"
    assert follow_up.kind == "start"
    assert follow_up.trigger == "manual"


def test_disabling_auto_compile_clears_pending_auto_follow_up() -> None:
    controller = AutoCompileController(enabled=True)
    controller.begin_build()
    controller.request_build("auto")

    controller.set_enabled(False)
    follow_up = controller.finish_build()

    assert follow_up.kind == "ignore"
    assert controller.pending_trigger is None
