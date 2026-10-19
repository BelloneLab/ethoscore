"""Arena drawing, review, and export widgets used by the annotation window.

Rectangles always use source-video pixels. Display scaling only affects the
preview, so drawing on a small screen never changes the exported coordinates.
"""

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import cv2
from PySide6.QtCore import Qt, QRectF, QThread, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QGraphicsScene,
    QGraphicsView, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from annotator_libs.arena_model import Arena, detect_arenas, grid_arenas, sample_video_frame
from annotator_libs.arena_export import export_arenas


STATUS_COLORS = {"unlabeled": "#8b98aa", "ongoing": "#f5b94c", "completed": "#42d6a4"}
STATUS_NAMES = {"unlabeled": "Unlabeled", "ongoing": "Ongoing", "completed": "Completed"}
ARENA_COLORS = ("#54c7ec", "#b5a1ff", "#ffc36b", "#64e2bb", "#fa93be", "#a8d36f")

ARENA_STYLE = """
QDialog { background: #151c27; color: #e7edf6; }
QLabel { color: #c7d2e3; background: transparent; }
QLabel#title { color: #f4f7fc; font-size: 24px; font-weight: 700; }
QLabel#muted { color: #95a5bc; }
QPushButton { background: #273449; color: #edf3fc; border: 1px solid #3a4a61;
              border-radius: 6px; padding: 9px 13px; }
QPushButton:hover { background: #354962; }
QPushButton:disabled { color: #66778f; background: #202a39; }
QPushButton#primary { background: #167d72; border: none; font-weight: 700; }
QPushButton#primary:hover { background: #229c8d; }
QTableWidget { background: #1b2534; color: #edf3fc; gridline-color: #2f4056;
               border: 1px solid #33445b; selection-background-color: #315373; }
QHeaderView::section { background: #253347; color: #b6c6da; padding: 7px; border: none; }
QSpinBox { background: #26354a; color: #edf3fc; padding: 5px; border: 1px solid #3b506a; }
QCheckBox { color: #c7d2e3; padding: 6px; }
"""


class ArenaPreview(QGraphicsView):
    """Draw rectangles directly over a source-resolution video preview."""

    rectangle_drawn = Signal(int, int, int, int)

    def __init__(self, frame, parent=None):
        """Own a detached RGB preview and prepare a scene in video pixels."""
        super().__init__(parent)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        self.image_width, self.image_height = width, height
        image = QImage(rgb.data, width, height, int(rgb.strides[0]), QImage.Format_RGB888).copy()
        self.preview_scene = QGraphicsScene(self)
        self.setScene(self.preview_scene)
        self.preview_scene.addPixmap(QPixmap.fromImage(image))
        self.setSceneRect(0, 0, width, height)
        self.setBackgroundBrush(QColor("#0d121b"))
        self.setRenderHint(QPainter.Antialiasing)
        self.setMinimumSize(420, 320)
        self.setCursor(Qt.CrossCursor)
        self.draw_enabled = True
        self._start = None
        self._rubber = None
        self._overlays = []

    def resizeEvent(self, event):
        """Fit the complete source image without stretching its geometry."""
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def show_arenas(self, arenas, selected=-1):
        """Redraw named arena overlays, highlighting the selected table row."""
        for item in self._overlays:
            self.preview_scene.removeItem(item)
        self._overlays.clear()
        for index, arena in enumerate(arenas):
            color = QColor(ARENA_COLORS[index % len(ARENA_COLORS)])
            pen = QPen(color, 4 if index == selected else 2)
            pen.setCosmetic(True)
            rect = self.preview_scene.addRect(QRectF(arena.x, arena.y, arena.width, arena.height), pen)
            fill = QColor(color)
            fill.setAlpha(35 if index == selected else 15)
            rect.setBrush(fill)
            text = self.preview_scene.addText(arena.label)
            text.setDefaultTextColor(color)
            font = text.font()
            font.setPixelSize(max(13, round(self.image_width / 55)))
            font.setBold(True)
            text.setFont(font)
            text.setPos(arena.x + 5, arena.y + 3)
            self._overlays.extend((rect, text))

    def _point(self, event):
        """Clamp a pointer position to valid source-image boundaries."""
        point = self.mapToScene(event.position().toPoint())
        point.setX(max(0, min(self.image_width, point.x())))
        point.setY(max(0, min(self.image_height, point.y())))
        return point

    def mousePressEvent(self, event):
        """Begin a rectangular arena with a left-button drag."""
        if self.draw_enabled and event.button() == Qt.LeftButton:
            self._start = self._point(event)
            pen = QPen(QColor("#ffffff"), 2, Qt.DashLine)
            pen.setCosmetic(True)
            self._rubber = self.preview_scene.addRect(QRectF(self._start, self._start), pen)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Preview the rectangle while keeping coordinates in source pixels."""
        if self._rubber is not None:
            self._rubber.setRect(QRectF(self._start, self._point(event)).normalized())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Emit a nondegenerate crop, or discard an accidental short click."""
        if self._rubber is not None and event.button() == Qt.LeftButton:
            rect = QRectF(self._start, self._point(event)).normalized().toAlignedRect()
            self.preview_scene.removeItem(self._rubber)
            self._start = self._rubber = None
            if rect.width() >= 8 and rect.height() >= 8:
                self.rectangle_drawn.emit(rect.x(), rect.y(),
                                          min(rect.width(), self.image_width - rect.x()),
                                          min(rect.height(), self.image_height - rect.y()))
            event.accept()
            return
        super().mouseReleaseEvent(event)


class DetectionWorker(QThread):
    """Sample and detect in a worker so long-GOP source videos do not freeze Qt."""

    detected = Signal(object, object)
    failed = Signal(str)

    def __init__(self, source, parent=None):
        """Store the source path; no video handles cross thread boundaries."""
        super().__init__(parent)
        self.source = str(source)

    def run(self):
        """Return a median preview with detected proposals, or a useful error."""
        try:
            frame = sample_video_frame(self.source)
            self.detected.emit(frame, detect_arenas(frame))
        except Exception as error:
            self.failed.emit(str(error))


class ArenaEditor(QDialog):
    """Review automatic proposals, draw manual crops, and assign arena names."""

    def __init__(self, source, frame, arenas=None, geometry_locked=False, parent=None):
        """Initialize a reversible draft. Existing exported geometry is locked."""
        super().__init__(parent)
        self.source = str(source)
        self.arenas = deepcopy(arenas or [])
        self.geometry_locked = geometry_locked
        self.detection_worker = None
        self.setWindowTitle("Ethoscore | Set up arenas")
        self.resize(1140, 740)
        self.setMinimumSize(850, 600)
        self.setStyleSheet(ARENA_STYLE)
        layout = QVBoxLayout(self)
        title = QLabel("One video. Individual arenas.")
        title.setObjectName("title")
        layout.addWidget(title)
        self.hint = QLabel("Detect dividers automatically, or drag rectangles over the preview. Review every crop before exporting.")
        self.hint.setWordWrap(True)
        self.hint.setObjectName("muted")
        layout.addWidget(self.hint)
        toolbar = QHBoxLayout()
        self.detect_button = QPushButton("Auto-detect arenas")
        self.detect_button.clicked.connect(self.auto_detect)
        self.detect_button.setEnabled(not geometry_locked)
        toolbar.addWidget(self.detect_button)
        toolbar.addStretch()
        toolbar.addWidget(QLabel("Grid"))
        self.rows = QSpinBox()
        self.columns = QSpinBox()
        for spin in (self.rows, self.columns):
            spin.setRange(1, 8)
            spin.setValue(2)
            spin.setEnabled(not geometry_locked)
            toolbar.addWidget(spin)
        self.grid_button = QPushButton("Create grid")
        self.grid_button.clicked.connect(self.create_grid)
        self.grid_button.setEnabled(not geometry_locked)
        toolbar.addWidget(self.grid_button)
        layout.addLayout(toolbar)
        splitter = QSplitter()
        self.preview = ArenaPreview(frame)
        self.preview.draw_enabled = not geometry_locked
        self.preview.rectangle_drawn.connect(self.add_rectangle)
        splitter.addWidget(self.preview)
        sidebar = QWidget()
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(8, 0, 0, 0)
        side.addWidget(QLabel("ARENAS  /  SOURCE PIXELS"))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Name", "X", "Y", "Width", "Height"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 5):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self.update_draft)
        self.table.itemSelectionChanged.connect(self.refresh_preview)
        side.addWidget(self.table)
        self.remove_button = QPushButton("Remove selected arena")
        self.remove_button.clicked.connect(self.remove_selected)
        self.remove_button.setEnabled(not geometry_locked)
        side.addWidget(self.remove_button)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setObjectName("muted")
        side.addWidget(self.summary)
        splitter.addWidget(sidebar)
        splitter.setSizes([720, 400])
        layout.addWidget(splitter, 1)
        self.lossless_box = QCheckBox("Lossless crops (larger files)")
        self.lossless_box.setToolTip("Both modes preserve frame count and frame order. Lossless uses lossless YUV encoding; RGB conversion may slightly change pixel values.")
        self.lossless_box.setEnabled(not geometry_locked)
        layout.addWidget(self.lossless_box)
        self.validation = QLabel()
        self.validation.setWordWrap(True)
        layout.addWidget(self.validation)
        footer = QHBoxLayout()
        footer.addWidget(QLabel("Original video stays untouched. Each arena gets its own video and annotations."), 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.apply_button = buttons.addButton("Save names" if geometry_locked else "Export arenas", QDialogButtonBox.AcceptRole)
        self.apply_button.setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        layout.addLayout(footer)
        if geometry_locked:
            self.hint.setText("Rename the existing arenas here. Exported crop geometry is fixed to protect existing annotations.")
        self.populate_table()

    @property
    def lossless(self):
        """Expose the user's encoding choice without coupling the worker to Qt."""
        return self.lossless_box.isChecked()

    def populate_table(self):
        """Rebuild the coordinate table without triggering intermediate edits."""
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.arenas))
        for row, arena in enumerate(self.arenas):
            for column, value in enumerate((arena.label, arena.x, arena.y, arena.width, arena.height)):
                item = QTableWidgetItem(str(value))
                if self.geometry_locked and column:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)
        self.refresh_preview()
        self.validate_draft()

    def refresh_preview(self):
        """Keep the preview and selected coordinate row in agreement."""
        self.preview.show_arenas(self.arenas, self.table.currentRow())
        self.summary.setText(f"{len(self.arenas)} arenas. Coordinates are measured from the top-left of the original video. Overlapping crops are allowed.")

    def validate_draft(self):
        """Prevent empty names, duplicate names, and out-of-frame rectangles."""
        message = ""
        labels = [arena.label.strip().casefold() for arena in self.arenas]
        if not self.arenas:
            message = "Draw an arena, create a grid, or run auto-detection to continue."
        elif any(not label for label in labels) or len(set(labels)) != len(labels):
            message = "Give every arena a unique, nonempty name."
        elif any(arena.x < 0 or arena.y < 0 or arena.width < 8 or arena.height < 8
                 or arena.x + arena.width > self.preview.image_width
                 or arena.y + arena.height > self.preview.image_height for arena in self.arenas):
            message = "Every crop must stay inside the source and be at least 8 by 8 pixels."
        self.validation.setText(message)
        self.apply_button.setEnabled(not message)
        return not message

    def update_draft(self, item):
        """Apply table edits to the draft and reject invalid numeric entries."""
        arena = self.arenas[item.row()]
        if item.column() == 0:
            arena.label = item.text().strip()
        else:
            try:
                value = int(item.text())
            except ValueError:
                self.populate_table()
                return
            setattr(arena, ("label", "x", "y", "width", "height")[item.column()], value)
        self.refresh_preview()
        self.validate_draft()

    def add_rectangle(self, x, y, width, height):
        """Append a stable-identity arena, using a friendly default label."""
        if self.geometry_locked:
            return
        number = len(self.arenas) + 1
        existing = {arena.label for arena in self.arenas}
        while f"Arena {number}" in existing:
            number += 1
        self.arenas.append(Arena(f"arena_{uuid4().hex[:12]}", f"Arena {number}", x, y, width, height))
        self.populate_table()
        self.table.selectRow(len(self.arenas) - 1)

    def remove_selected(self):
        """Remove a draft rectangle without touching any on-disk media."""
        row = self.table.currentRow()
        if row >= 0 and not self.geometry_locked:
            self.arenas.pop(row)
            self.populate_table()

    def create_grid(self):
        """Offer an explicit equal-sized grid when automatic detection is unsuitable."""
        self.arenas = grid_arenas(self.preview.image_width, self.preview.image_height,
                                  self.rows.value(), self.columns.value())
        self.populate_table()

    def auto_detect(self):
        """Compute automatic proposals in the background; the user reviews them."""
        self.detect_button.setEnabled(False)
        self.grid_button.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.hint.setText("Sampling the video and looking for stable arena dividers...")
        self.detection_worker = DetectionWorker(self.source, self)
        self.detection_worker.detected.connect(self.detection_finished)
        self.detection_worker.failed.connect(self.detection_failed)
        self.detection_worker.start()

    def detection_finished(self, frame, arenas):
        """Present detected rectangles without treating uncertain proposals as truth."""
        self.detect_button.setEnabled(True)
        self.grid_button.setEnabled(True)
        if arenas:
            self.arenas = arenas
            self.hint.setText(f"Found {len(arenas)} arena proposals. Review boundaries and names, then export.")
        else:
            self.hint.setText("No reliable dividers found. Draw arenas manually or create a grid.")
        self.populate_table()

    def detection_failed(self, message):
        """Restore editing after a sampling failure and surface its cause."""
        self.detect_button.setEnabled(True)
        self.grid_button.setEnabled(True)
        self.hint.setText(f"Detection could not finish: {message}")
        self.validate_draft()

    def done(self, result):
        """Keep the dialog alive while its detection worker owns video resources."""
        if self.detection_worker and self.detection_worker.isRunning():
            self.hint.setText("Please wait for detection to finish before closing this dialog.")
            return
        if result == QDialog.Accepted and not self.validate_draft():
            return
        super().done(result)


class ExportWorker(QThread):
    """Export and validate crops without blocking the annotation interface."""

    progress = Signal(int)
    exported = Signal(object)
    failed = Signal(str)

    def __init__(self, source, arenas, project_dir, lossless=False, parent=None):
        """Copy the reviewed arena definitions before passing them to FFmpeg."""
        super().__init__(parent)
        self.source, self.arenas = str(source), deepcopy(arenas)
        self.project_dir, self.lossless = Path(project_dir), lossless

    def run(self):
        """Forward progress, cooperative cancellation, and validated output paths."""
        try:
            paths = export_arenas(self.source, self.arenas, self.project_dir,
                                  progress=lambda value: self.progress.emit(round(value * 100)),
                                  cancel=self.isInterruptionRequested, lossless=self.lossless)
            self.exported.emit(paths)
        except Exception as error:
            self.failed.emit(str(error))
