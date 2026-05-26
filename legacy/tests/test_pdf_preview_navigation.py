from __future__ import annotations

import pytest
from PySide6 import QtCore

from pdf_preview import PdfPreviewWidget


@pytest.fixture()
def preview_widget(qapp):
    widget = PdfPreviewWidget()
    widget.resize(800, 600)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()
    qapp.processEvents()


def _configure_preview_state(
    preview_widget: PdfPreviewWidget,
    monkeypatch: pytest.MonkeyPatch,
    *,
    total_pages: int = 7,
    current_page: int = 3,
) -> dict[str, int]:
    state = {"current_page": current_page}
    monkeypatch.setattr(preview_widget, "_document_is_ready", lambda: True)
    monkeypatch.setattr(preview_widget, "_document_page_count", lambda: total_pages)
    monkeypatch.setattr(preview_widget, "_current_page_number", lambda: state["current_page"])
    preview_widget._update_controls()
    return state


def test_confirming_valid_page_input_navigates_to_requested_page(
    preview_widget: PdfPreviewWidget,
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    state = _configure_preview_state(preview_widget, monkeypatch, total_pages=7, current_page=3)
    navigations: list[int] = []

    def _fake_go_to_page(page_number: int) -> None:
        navigations.append(page_number)
        state["current_page"] = page_number

    monkeypatch.setattr(preview_widget, "_go_to_page_number", _fake_go_to_page)

    preview_widget.page_input.setText("5")
    preview_widget._on_page_input_edited("5")
    preview_widget.page_input.editingFinished.emit()
    qapp.processEvents()

    assert navigations == [5]
    assert preview_widget.page_input.text() == "5"
    assert preview_widget.page_total_label.text() == "/ 7"


@pytest.mark.parametrize(
    ("typed_page", "expected_page"),
    [
        ("0", 1),
        ("99", 7),
    ],
)
def test_confirming_out_of_range_page_input_clamps_to_document_bounds(
    preview_widget: PdfPreviewWidget,
    monkeypatch: pytest.MonkeyPatch,
    qapp,
    typed_page: str,
    expected_page: int,
) -> None:
    state = _configure_preview_state(preview_widget, monkeypatch, total_pages=7, current_page=3)
    navigations: list[int] = []

    def _fake_go_to_page(page_number: int) -> None:
        navigations.append(page_number)
        state["current_page"] = page_number

    monkeypatch.setattr(preview_widget, "_go_to_page_number", _fake_go_to_page)

    preview_widget.page_input.setText(typed_page)
    preview_widget._on_page_input_edited(typed_page)
    preview_widget.page_input.editingFinished.emit()
    qapp.processEvents()

    assert navigations == [expected_page]
    assert preview_widget.page_input.text() == str(expected_page)


def test_scroll_updates_page_input_when_user_is_not_editing(
    preview_widget: PdfPreviewWidget,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _configure_preview_state(preview_widget, monkeypatch, total_pages=7, current_page=2)

    assert preview_widget.page_input.text() == "2"

    state["current_page"] = 4
    preview_widget._on_scrollbar_value_changed(120)

    assert preview_widget.page_input.text() == "4"
    assert preview_widget.page_total_label.text() == "/ 7"


def test_typed_page_waits_for_confirmation_and_is_not_overwritten_by_scroll(
    preview_widget: PdfPreviewWidget,
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    state = _configure_preview_state(preview_widget, monkeypatch, total_pages=7, current_page=2)
    navigations: list[int] = []

    def _fake_go_to_page(page_number: int) -> None:
        navigations.append(page_number)
        state["current_page"] = page_number

    monkeypatch.setattr(preview_widget, "_go_to_page_number", _fake_go_to_page)

    preview_widget.page_input.setText("6")
    preview_widget._on_page_input_edited("6")
    qapp.processEvents()

    assert navigations == []

    state["current_page"] = 4
    preview_widget._on_scrollbar_value_changed(180)

    assert navigations == []
    assert preview_widget.page_input.text() == "6"

    preview_widget.page_input.editingFinished.emit()
    qapp.processEvents()

    assert navigations == [6]
    assert preview_widget.page_input.text() == "6"


class _FakeLink:
    def __init__(
        self,
        *,
        url: str = "",
        page: int = -1,
        location: QtCore.QPointF | None = None,
        zoom: float = 0.0,
    ) -> None:
        self._url = QtCore.QUrl(url)
        self._page = page
        self._location = location or QtCore.QPointF()
        self._zoom = zoom

    def url(self) -> QtCore.QUrl:
        return self._url

    def page(self) -> int:
        return self._page

    def location(self) -> QtCore.QPointF:
        return self._location

    def zoom(self) -> float:
        return self._zoom


def test_external_links_use_desktop_services(
    preview_widget: PdfPreviewWidget,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened_urls: list[str] = []
    internal_jumps: list[_FakeLink] = []
    link = _FakeLink(url="https://example.com/docs")

    monkeypatch.setattr(preview_widget._view, "_open_external_url", lambda url: opened_urls.append(url.toString()) or True)
    monkeypatch.setattr(
        preview_widget._view,
        "_jump_to_internal_destination",
        lambda dest: internal_jumps.append(dest),
    )

    assert preview_widget._view._activate_link(link) is True
    assert opened_urls == ["https://example.com/docs"]
    assert internal_jumps == []


def test_internal_links_jump_within_the_embedded_preview(
    preview_widget: PdfPreviewWidget,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened_urls: list[str] = []
    internal_jumps: list[tuple[int, QtCore.QPointF, float]] = []
    location = QtCore.QPointF(24.0, 72.0)
    link = _FakeLink(page=4, location=location, zoom=1.5)

    monkeypatch.setattr(preview_widget._view, "_open_external_url", lambda url: opened_urls.append(url.toString()) or True)
    monkeypatch.setattr(
        preview_widget._view,
        "_jump_to_internal_destination",
        lambda dest: internal_jumps.append((dest.page(), dest.location(), dest.zoom())),
    )

    assert preview_widget._view._activate_link(link) is True
    assert opened_urls == []
    assert internal_jumps == [(4, location, 1.5)]
