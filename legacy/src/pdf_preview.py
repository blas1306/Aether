from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets, QtPdf, QtPdfWidgets  # type: ignore


PREVIEW_BG = "#1e1e1e"
PREVIEW_SECTION_SPACING = 8


@dataclass
class PreviewState:
    pdf_path: Path | None = None
    page: int = 0
    zoom_mode: str = "fit_width"
    zoom_factor: float = 1.0
    location_x: float = 0.0
    location_y: float = 0.0
    horizontal_scroll: int = 0
    vertical_scroll: int = 0


class InteractivePdfView(QtPdfWidgets.QPdfView):  # type: ignore[misc]
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._link_model = QtPdf.QPdfLinkModel(self)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def setDocument(self, document) -> None:  # noqa: N802
        super().setDocument(document)
        if document is not None:
            self._link_model.setDocument(document)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.unsetCursor()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        link = self._link_at_view_position(event.position())
        self.setCursor(
            QtCore.Qt.CursorShape.PointingHandCursor if link.isValid() else QtCore.Qt.CursorShape.ArrowCursor
        )
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        link = self._link_at_view_position(event.position())
        if not link.isValid():
            super().mouseReleaseEvent(event)
            return
        if self._activate_link(link):
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _activate_link(self, link: QtPdf.QPdfLink) -> bool:
        url = link.url()
        if url.isValid() and not url.isEmpty():
            return self._open_external_url(url)
        if link.page() >= 0:
            self._jump_to_internal_destination(link)
            return True
        return False

    def _open_external_url(self, url: QtCore.QUrl) -> bool:
        return QtGui.QDesktopServices.openUrl(url)

    def _jump_to_internal_destination(self, link: QtPdf.QPdfLink) -> None:
        self.pageNavigator().jump(link.page(), link.location(), link.zoom())

    def _link_at_view_position(self, position: QtCore.QPointF) -> QtPdf.QPdfLink:
        document = self.document()
        if document is None or document.status() != QtPdf.QPdfDocument.Status.Ready:
            return QtPdf.QPdfLink()
        viewport_rect = self._viewport_rect()
        for page, page_geometry, page_scale in self._iter_page_geometries(document, viewport_rect):
            visible_page_geometry = page_geometry.translated(-viewport_rect.topLeft())
            if not visible_page_geometry.contains(position.toPoint()):
                continue
            screen_inv_transform, invertible = self._screen_scale_transform(page_scale).inverted()
            if not invertible:
                return QtPdf.QPdfLink()
            pos_in_points = screen_inv_transform.map(position - QtCore.QPointF(visible_page_geometry.topLeft()))
            self._link_model.setPage(page)
            return self._link_model.linkAt(pos_in_points)
        return QtPdf.QPdfLink()

    def _viewport_rect(self) -> QtCore.QRect:
        return QtCore.QRect(
            self.horizontalScrollBar().value(),
            self.verticalScrollBar().value(),
            self.viewport().width(),
            self.viewport().height(),
        )

    def _iter_page_geometries(self, document, viewport_rect: QtCore.QRect):
        page_count = int(document.pageCount())
        if page_count <= 0:
            return

        zoom_mode = self.zoomMode()
        zoom_factor = float(self.zoomFactor() or 1.0)
        margins = self.documentMargins()
        page_spacing = int(self.pageSpacing())
        screen_resolution = self._screen_resolution()

        if self.pageMode() == QtPdfWidgets.QPdfView.PageMode.SinglePage:
            start_page = min(max(self.pageNavigator().currentPage(), 0), max(0, page_count - 1))
            end_page = start_page + 1
        else:
            start_page = 0
            end_page = page_count

        page_layouts: list[tuple[int, QtCore.QSize, float]] = []
        total_width = 0
        for page in range(start_page, end_page):
            page_size = document.pagePointSize(page)
            base_size = QtCore.QSizeF(
                page_size.width() * screen_resolution,
                page_size.height() * screen_resolution,
            ).toSize()
            page_scale = zoom_factor
            if zoom_mode == QtPdfWidgets.QPdfView.ZoomMode.Custom:
                render_size = QtCore.QSizeF(
                    base_size.width() * zoom_factor,
                    base_size.height() * zoom_factor,
                ).toSize()
            elif zoom_mode == QtPdfWidgets.QPdfView.ZoomMode.FitToWidth:
                available_width = max(1, viewport_rect.width() - margins.left() - margins.right())
                width = max(1, base_size.width())
                page_scale = float(available_width) / float(width)
                render_size = QtCore.QSizeF(
                    base_size.width() * page_scale,
                    base_size.height() * page_scale,
                ).toSize()
            else:
                available_size = viewport_rect.size() + QtCore.QSize(
                    -margins.left() - margins.right(),
                    -page_spacing,
                )
                available_size.setWidth(max(1, available_size.width()))
                available_size.setHeight(max(1, available_size.height()))
                render_size = base_size.scaled(available_size, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
                width = max(1, base_size.width())
                page_scale = float(render_size.width()) / float(width)
            total_width = max(total_width, render_size.width())
            page_layouts.append((page, render_size, page_scale))

        total_width += margins.left() + margins.right()
        page_y = margins.top()
        for page, render_size, page_scale in page_layouts:
            page_x = (max(total_width, viewport_rect.width()) - render_size.width()) // 2
            yield page, QtCore.QRect(QtCore.QPoint(page_x, page_y), render_size), page_scale
            page_y += render_size.height() + page_spacing

    def _screen_scale_transform(self, page_scale: float) -> QtGui.QTransform:
        return QtGui.QTransform.fromScale(self._screen_resolution() * page_scale, self._screen_resolution() * page_scale)

    def _screen_resolution(self) -> float:
        screen = self.windowHandle().screen() if self.windowHandle() else QtGui.QGuiApplication.primaryScreen()
        if screen is None:
            return 96.0 / 72.0
        return float(screen.logicalDotsPerInch()) / 72.0


class PdfPreviewWidget(QtWidgets.QWidget):  # type: ignore[misc]
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("pdfPreviewRoot")
        self._document = QtPdf.QPdfDocument(self)
        self._current_pdf_path: Path | None = None
        self._pending_restore_state: PreviewState | None = None
        self._closing = False
        self._page_input_editing = False
        self.setStyleSheet(
            """
            QWidget#pdfPreviewRoot {
                background: transparent;
            }
            QFrame#pdfPreviewToolbar {
                background: #24292f;
                border: 1px solid #363c44;
                border-radius: 6px;
            }
            QToolButton#pdfPreviewButton {
                background: #2a3037;
                border: 1px solid #434b55;
                border-radius: 5px;
                color: #d7dde3;
                padding: 3px 9px;
                min-height: 24px;
            }
            QToolButton#pdfPreviewButton:hover {
                background: #333941;
                border-color: #56606c;
            }
            QToolButton#pdfPreviewButton:disabled {
                color: #838c95;
                border-color: #3b424a;
            }
            QLabel#pdfPageTotalLabel {
                color: #cfcfcf;
                padding-left: 4px;
            }
            """
        )

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(PREVIEW_SECTION_SPACING)

        toolbar_frame = QtWidgets.QFrame()
        toolbar_frame.setObjectName("pdfPreviewToolbar")
        toolbar = QtWidgets.QHBoxLayout(toolbar_frame)
        toolbar.setContentsMargins(6, 6, 6, 6)
        toolbar.setSpacing(6)
        self.prev_btn = self._make_button("Prev", "Previous page")
        self.next_btn = self._make_button("Next", "Next page")
        self.zoom_out_btn = self._make_button("-", "Zoom out")
        self.zoom_in_btn = self._make_button("+", "Zoom in")
        self.fit_width_btn = self._make_button("Fit Width", "Fit page width")
        self.fit_page_btn = self._make_button("Fit Page", "Fit whole page")
        self.reload_btn = self._make_button("Reload", "Reload PDF")
        self.open_external_btn = self._make_button("Open External", "Open PDF in the system viewer")
        self.page_input = QtWidgets.QLineEdit("-")
        self.page_input.setObjectName("pdfPageInput")
        self.page_input.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.page_input.setFixedWidth(56)
        self.page_input.setMaxLength(6)
        self.page_input.setToolTip("Current page")
        self.page_input.setStyleSheet(
            "color: #cfcfcf; background: #2b2b2b; border: 1px solid #4a4a4a; border-radius: 4px; padding: 2px 6px;"
        )
        self.page_input.setValidator(
            QtGui.QRegularExpressionValidator(QtCore.QRegularExpression(r"\d*"), self.page_input)
        )
        self.page_total_label = QtWidgets.QLabel("/ -")
        self.page_total_label.setObjectName("pdfPageTotalLabel")
        for button in (
            self.prev_btn,
            self.next_btn,
            self.zoom_out_btn,
            self.zoom_in_btn,
            self.fit_width_btn,
            self.fit_page_btn,
            self.reload_btn,
            self.open_external_btn,
        ):
            toolbar.addWidget(button)
        toolbar.addStretch()
        toolbar.addWidget(self.page_input)
        toolbar.addWidget(self.page_total_label)
        root.addWidget(toolbar_frame)

        self._stack = QtWidgets.QStackedWidget()
        self._message_label = QtWidgets.QLabel("Compile an .mtex file to preview it.")
        self._message_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._message_label.setWordWrap(True)
        self._message_label.setMinimumHeight(240)
        self._message_label.setStyleSheet(
            f"background: {PREVIEW_BG}; color: #f2f2f2; border: 1px solid #3c3c3c; border-radius: 6px;"
        )

        self._view = InteractivePdfView(self)
        self._view.setPageMode(QtPdfWidgets.QPdfView.PageMode.MultiPage)
        self._view.setZoomMode(QtPdfWidgets.QPdfView.ZoomMode.FitToWidth)
        self._view.setStyleSheet(f"background: {PREVIEW_BG}; border: 1px solid #3c3c3c; border-radius: 6px;")
        self._view.setDocument(self._document)

        self._stack.addWidget(self._message_label)
        self._stack.addWidget(self._view)
        root.addWidget(self._stack, 1)

        self.prev_btn.clicked.connect(self._go_to_previous_page)
        self.next_btn.clicked.connect(self._go_to_next_page)
        self.zoom_out_btn.clicked.connect(lambda: self._set_custom_zoom(self._effective_zoom_factor() / 1.15))
        self.zoom_in_btn.clicked.connect(lambda: self._set_custom_zoom(self._effective_zoom_factor() * 1.15))
        self.fit_width_btn.clicked.connect(self._fit_width)
        self.fit_page_btn.clicked.connect(self._fit_page)
        self.reload_btn.clicked.connect(self.reload_pdf)
        self.open_external_btn.clicked.connect(self.open_external)
        self.page_input.textEdited.connect(self._on_page_input_edited)
        self.page_input.editingFinished.connect(self._commit_page_input)
        self._document.statusChanged.connect(self._on_document_status_changed)
        self._document.pageCountChanged.connect(self._update_page_label)
        self._view.pageNavigator().currentPageChanged.connect(self._update_page_label)
        self._view.horizontalScrollBar().valueChanged.connect(self._on_scrollbar_value_changed)
        self._view.verticalScrollBar().valueChanged.connect(self._on_scrollbar_value_changed)
        self._update_controls()

    def _make_button(self, text: str, tooltip: str) -> QtWidgets.QToolButton:
        button = QtWidgets.QToolButton()
        button.setObjectName("pdfPreviewButton")
        button.setText(text)
        button.setToolTip(tooltip)
        button.setAutoRaise(False)
        return button

    def current_pdf_path(self) -> Path | None:
        return self._current_pdf_path

    def current_page_index(self) -> int | None:
        current_page = self._current_page_number()
        if current_page <= 0:
            return None
        return current_page - 1

    def jump_to_page_index(self, page_index: int) -> bool:
        total = self._document_page_count()
        if total <= 0 or not self._document_is_ready():
            return False
        clamped_page = min(max(int(page_index), 0), total - 1)
        if self.current_page_index() == clamped_page:
            self._update_page_label()
            return True
        self._view.pageNavigator().jump(clamped_page, QtCore.QPointF(), self._jump_zoom_value())
        self._update_page_label()
        return True

    def set_message(self, text: str) -> None:
        self._pending_restore_state = None
        self._current_pdf_path = None
        self._message_label.setText(text)
        self._stack.setCurrentWidget(self._message_label)
        self._document.close()
        self._update_controls()

    def load_pdf(self, pdf_path: str | Path, preserve_state: bool = True) -> bool:
        resolved = Path(pdf_path).expanduser().resolve()
        if not resolved.exists():
            return False

        restore_state = None
        if preserve_state and self._current_pdf_path is not None and resolved == self._current_pdf_path:
            restore_state = self.capture_state()

        self._pending_restore_state = restore_state
        error = self._document.load(str(resolved))
        if error != QtPdf.QPdfDocument.Error.None_:
            self._message_label.setText(f"Could not load the PDF.\n{resolved}")
            self._stack.setCurrentWidget(self._message_label)
            self._update_controls()
            return False

        self._current_pdf_path = resolved
        self._stack.setCurrentWidget(self._view)
        self._update_controls()
        if self._document.status() == QtPdf.QPdfDocument.Status.Ready:
            self._restore_pending_state()
        return True

    def reload_pdf(self) -> bool:
        if self._current_pdf_path is None:
            return False
        return self.load_pdf(self._current_pdf_path, preserve_state=True)

    def capture_state(self) -> PreviewState:
        navigator = self._view.pageNavigator()
        location = navigator.currentLocation()
        zoom_mode = self._serialize_zoom_mode(self._view.zoomMode())
        return PreviewState(
            pdf_path=self._current_pdf_path,
            page=max(0, navigator.currentPage()),
            zoom_mode=zoom_mode,
            zoom_factor=max(0.1, self._effective_zoom_factor()),
            location_x=float(location.x()),
            location_y=float(location.y()),
            horizontal_scroll=self._view.horizontalScrollBar().value(),
            vertical_scroll=self._view.verticalScrollBar().value(),
        )

    def open_external(self) -> bool:
        if self._current_pdf_path is None or not self._current_pdf_path.exists():
            return False
        return QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self._current_pdf_path)))

    def _go_to_previous_page(self) -> None:
        page_count = self._document.pageCount()
        if page_count <= 0:
            return
        navigator = self._view.pageNavigator()
        target_page = max(0, navigator.currentPage() - 1)
        navigator.jump(target_page, QtCore.QPointF(), self._jump_zoom_value())
        self._update_page_label()

    def _go_to_next_page(self) -> None:
        page_count = self._document.pageCount()
        if page_count <= 0:
            return
        navigator = self._view.pageNavigator()
        target_page = min(page_count - 1, navigator.currentPage() + 1)
        navigator.jump(target_page, QtCore.QPointF(), self._jump_zoom_value())
        self._update_page_label()

    def _fit_width(self) -> None:
        self._view.setZoomMode(QtPdfWidgets.QPdfView.ZoomMode.FitToWidth)
        self._update_controls()

    def _fit_page(self) -> None:
        self._view.setZoomMode(QtPdfWidgets.QPdfView.ZoomMode.FitInView)
        self._update_controls()

    def _set_custom_zoom(self, factor: float) -> None:
        bounded = min(max(factor, 0.2), 8.0)
        self._view.setZoomMode(QtPdfWidgets.QPdfView.ZoomMode.Custom)
        self._view.setZoomFactor(bounded)
        self._update_controls()

    def _effective_zoom_factor(self) -> float:
        navigator_zoom = float(self._view.pageNavigator().currentZoom())
        if navigator_zoom > 0:
            return navigator_zoom
        return float(self._view.zoomFactor() or 1.0)

    def _jump_zoom_value(self) -> float:
        if self._view.zoomMode() == QtPdfWidgets.QPdfView.ZoomMode.Custom:
            return self._effective_zoom_factor()
        return 0.0

    def _serialize_zoom_mode(self, zoom_mode) -> str:
        if zoom_mode == QtPdfWidgets.QPdfView.ZoomMode.FitInView:
            return "fit_page"
        if zoom_mode == QtPdfWidgets.QPdfView.ZoomMode.Custom:
            return "custom"
        return "fit_width"

    def _deserialize_zoom_mode(self, name: str):
        if name == "fit_page":
            return QtPdfWidgets.QPdfView.ZoomMode.FitInView
        if name == "custom":
            return QtPdfWidgets.QPdfView.ZoomMode.Custom
        return QtPdfWidgets.QPdfView.ZoomMode.FitToWidth

    def _restore_pending_state(self) -> None:
        state = self._pending_restore_state
        self._pending_restore_state = None
        if state is None or self._document.pageCount() <= 0:
            self._update_page_label()
            return

        zoom_mode = self._deserialize_zoom_mode(state.zoom_mode)
        self._view.setZoomMode(zoom_mode)
        if zoom_mode == QtPdfWidgets.QPdfView.ZoomMode.Custom:
            self._view.setZoomFactor(min(max(state.zoom_factor, 0.2), 8.0))

        target_page = min(max(state.page, 0), max(0, self._document.pageCount() - 1))
        location = QtCore.QPointF(state.location_x, state.location_y)
        zoom_value = state.zoom_factor if zoom_mode == QtPdfWidgets.QPdfView.ZoomMode.Custom else 0.0
        self._view.pageNavigator().jump(target_page, location, zoom_value)

        def _restore_scrollbars() -> None:
            self._view.horizontalScrollBar().setValue(state.horizontal_scroll)
            self._view.verticalScrollBar().setValue(state.vertical_scroll)
            self._update_page_label()

        QtCore.QTimer.singleShot(0, _restore_scrollbars)
        QtCore.QTimer.singleShot(60, _restore_scrollbars)

    def _on_document_status_changed(self, status) -> None:
        if self._closing:
            return
        if status == QtPdf.QPdfDocument.Status.Ready:
            self._stack.setCurrentWidget(self._view)
            self._restore_pending_state()
        elif status == QtPdf.QPdfDocument.Status.Error:
            target = str(self._current_pdf_path) if self._current_pdf_path else "PDF"
            self._message_label.setText(f"Could not load the PDF.\n{target}")
            self._stack.setCurrentWidget(self._message_label)
        self._update_controls()

    def _on_scrollbar_value_changed(self, _value: int) -> None:
        if self._closing:
            return
        self._update_page_label()

    def _on_page_input_edited(self, _text: str) -> None:
        self._page_input_editing = True

    def _commit_page_input(self) -> None:
        total = self._document_page_count()
        self._page_input_editing = False
        if total <= 0:
            self._update_page_label()
            return

        current = self._current_page_number() or 1
        try:
            requested_page = int(self.page_input.text().strip())
        except ValueError:
            requested_page = current

        self._go_to_page_number(min(max(requested_page, 1), total))
        self._update_page_label()

    def _document_page_count(self) -> int:
        if self._closing or self._document is None:
            return 0
        try:
            return int(self._document.pageCount())
        except RuntimeError:
            return 0

    def _document_is_ready(self) -> bool:
        if self._closing or self._document is None:
            return False
        try:
            return self._document.status() == QtPdf.QPdfDocument.Status.Ready
        except RuntimeError:
            return False

    def _current_page_number(self) -> int:
        total = self._document_page_count()
        if total <= 0:
            return 0
        try:
            current = max(0, self._view.pageNavigator().currentPage()) + 1
        except RuntimeError:
            return 0
        return min(current, total)

    def _go_to_page_number(self, page_number: int) -> None:
        total = self._document_page_count()
        if total <= 0:
            return
        clamped_page = min(max(int(page_number), 1), total)
        self._view.pageNavigator().jump(clamped_page - 1, QtCore.QPointF(), self._jump_zoom_value())

    def _update_page_label(self) -> None:
        total = self._document_page_count()
        if total <= 0:
            self.page_total_label.setText("/ -")
            self.page_input.setEnabled(False)
            self.page_input.setText("-")
            return
        self.page_total_label.setText(f"/ {total}")
        self.page_input.setEnabled(self._document_is_ready())
        current = self._current_page_number()
        if current <= 0:
            self.page_input.setText("-")
            return
        if not self._page_input_editing:
            self.page_input.setText(str(current))

    def _update_controls(self) -> None:
        has_document = self._document_is_ready() and self._document_page_count() > 0
        for button in (
            self.prev_btn,
            self.next_btn,
            self.zoom_out_btn,
            self.zoom_in_btn,
            self.fit_width_btn,
            self.fit_page_btn,
            self.reload_btn,
        ):
            button.setEnabled(has_document)
        self.open_external_btn.setEnabled(self._current_pdf_path is not None and self._current_pdf_path.exists())
        self._update_page_label()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._closing = True
        for signal, handler in (
            (self._document.statusChanged, self._on_document_status_changed),
            (self._document.pageCountChanged, self._update_page_label),
            (self._view.pageNavigator().currentPageChanged, self._update_page_label),
            (self._view.horizontalScrollBar().valueChanged, self._on_scrollbar_value_changed),
            (self._view.verticalScrollBar().valueChanged, self._on_scrollbar_value_changed),
        ):
            try:
                signal.disconnect(handler)
            except Exception:
                pass
        try:
            self._document.close()
        except Exception:
            pass
        super().closeEvent(event)
