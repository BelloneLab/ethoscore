"""Arena drawing, review, and export widgets used by the annotation window.

Rectangles always use source-video pixels. Display scaling only affects the
preview, so drawing on a small screen never changes the exported coordinates.
"""

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import cv2
from PySide6.QtCore import Qt, QPointF, QRectF, QThread, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
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
QPushButton:checked { background: #167d72; border-color: #64e2bb; }
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
    """Edit source-pixel geometry with screen-sized handles and guided tracing."""

    rectangle_drawn = Signal(int, int, int, int)
    polygon_drawn = Signal(object)
    selected = Signal(int)
    geometry_updated = Signal(int, object)
    tracing_changed = Signal(int)
    editing_error = Signal(str)

    def __init__(self, frame, parent=None):
        """Keep geometry independent of preview zoom and source image scaling."""
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
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.draw_enabled = True
        self.mode = "rectangle"
        self._start = self._rubber = self._drag = None
        self._overlays, self._arenas, self._points = [], [], []
        self._selected = -1
        self._hover = None
        self.setCursor(Qt.CrossCursor)

    def resizeEvent(self, event):
        """Fit the source without distorting it, then refresh screen-sized handles."""
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)
        self.show_arenas(self._arenas, self._selected)

    def set_mode(self, mode):
        """Cancel an unfinished trace when explicitly changing drawing tools."""
        self.cancel_drawing()
        self.mode = mode
        self.setCursor(Qt.ArrowCursor if mode == "edit" else Qt.CrossCursor)
        self.show_arenas(self._arenas, self._selected)

    def _radius(self):
        """Convert a generous nine-screen-pixel hit target into source pixels."""
        return 9 / max(self.transform().m11(), 0.001)

    @staticmethod
    def _vertices(arena):
        """Expose polygon points or the four corners of a rectangular crop."""
        return getattr(arena, "polygon", None) or [
            [arena.x, arena.y], [arena.x + arena.width, arena.y],
            [arena.x + arena.width, arena.y + arena.height], [arena.x, arena.y + arena.height]]

    def show_arenas(self, arenas, selected=-1):
        """Paint outlines, labels and drag handles over the unmodified source."""
        self._arenas, self._selected = arenas, selected
        for item in self._overlays:
            self.preview_scene.removeItem(item)
        self._overlays.clear()
        for index, arena in enumerate(arenas):
            color = QColor(ARENA_COLORS[index % len(ARENA_COLORS)])
            pen = QPen(color, 3 if index == selected else 2)
            pen.setCosmetic(True)
            shape = self.preview_scene.addPolygon(QPolygonF([QPointF(*p) for p in self._vertices(arena)]), pen)
            fill = QColor(color)
            fill.setAlpha(24 if index == selected else 10)
            shape.setBrush(fill)
            text = self.preview_scene.addText(arena.label)
            text.setDefaultTextColor(color)
            font = text.font()
            font.setPixelSize(max(13, round(self.image_width / 55)))
            font.setBold(True)
            text.setFont(font)
            text.setPos(arena.x + 5, arena.y + 3)
            self._overlays.extend((shape, text))
            if index == selected and self.draw_enabled and self.mode == "edit":
                points = self._vertices(arena)
                if not getattr(arena, "polygon", None):
                    points = points + [[arena.x + arena.width / 2, arena.y],
                        [arena.x + arena.width, arena.y + arena.height / 2],
                        [arena.x + arena.width / 2, arena.y + arena.height],
                        [arena.x, arena.y + arena.height / 2]]
                r = self._radius() * 0.45
                for x, y in points:
                    handle = self.preview_scene.addRect(QRectF(x-r, y-r, 2*r, 2*r), pen, QColor("#f5fbff"))
                    self._overlays.append(handle)

    def _point(self, event):
        """Clamp mouse geometry to the original video coordinate system."""
        point = self.mapToScene(event.position().toPoint())
        return QPointF(max(0, min(self.image_width, point.x())),
                       max(0, min(self.image_height, point.y())))

    def _hit(self, point):
        """Prefer selected handles, then edges, then polygon/rectangle interiors."""
        order = list(range(len(self._arenas)-1, -1, -1))
        if self._selected in order:
            order.remove(self._selected)
            order.insert(0, self._selected)
        radius = self._radius()
        for index in order:
            arena = self._arenas[index]
            vertices = self._vertices(arena)
            for vertex, (x, y) in enumerate(vertices):
                if abs(point.x()-x) <= radius and abs(point.y()-y) <= radius:
                    return index, ("vertex", vertex)
            if not getattr(arena, "polygon", None):
                x, y, right, bottom = arena.x, arena.y, arena.x+arena.width, arena.y+arena.height
                for edge, distance, inside in (("left", abs(point.x()-x), y-radius <= point.y() <= bottom+radius),
                    ("right", abs(point.x()-right), y-radius <= point.y() <= bottom+radius),
                    ("top", abs(point.y()-y), x-radius <= point.x() <= right+radius),
                    ("bottom", abs(point.y()-bottom), x-radius <= point.x() <= right+radius)):
                    if inside and distance <= radius:
                        return index, ("edge", edge)
            polygon = QPolygonF([QPointF(*p) for p in vertices])
            if polygon.containsPoint(point, Qt.OddEvenFill):
                return index, ("move", None)
        return -1, None

    def mousePressEvent(self, event):
        """Select a handle, begin a rectangle, or append a polygon vertex."""
        if event.button() != Qt.LeftButton or not self.draw_enabled:
            return super().mousePressEvent(event)
        self.setFocus()
        point = self._point(event)
        if self.mode == "polygon":
            if len(self._points) >= 3 and (point-self._points[0]).manhattanLength() <= self._radius()*1.5:
                self.finish_polygon()
            else:
                self._points.append(point)
                self._hover = point
                self._paint_trace()
                self.tracing_changed.emit(len(self._points))
        elif self.mode == "edit":
            index, operation = self._hit(point)
            if index >= 0:
                self.selected.emit(index)
                self._drag = (index, operation, point, deepcopy(self._arenas[index]))
        else:
            self._start = point
            pen = QPen(QColor("#ffffff"), 2, Qt.DashLine)
            pen.setCosmetic(True)
            self._rubber = self.preview_scene.addRect(QRectF(point, point), pen)
        event.accept()

    def _edit_to(self, point):
        """Resize or translate from the original drag snapshot, avoiding drift."""
        index, (kind, detail), origin, original = self._drag
        candidate = deepcopy(original)
        dx, dy = round(point.x()-origin.x()), round(point.y()-origin.y())
        try:
            if kind == "move":
                dx = max(-original.x, min(self.image_width-original.x-original.width, dx))
                dy = max(-original.y, min(self.image_height-original.y-original.height, dy))
                if getattr(original, "polygon", None):
                    candidate.set_polygon([[x+dx, y+dy] for x, y in original.polygon])
                else:
                    candidate.x += dx
                    candidate.y += dy
            elif getattr(original, "polygon", None):
                points = deepcopy(original.polygon)
                points[detail] = [round(point.x()), round(point.y())]
                candidate.set_polygon(points)
            else:
                left, top = original.x, original.y
                right, bottom = left+original.width, top+original.height
                edges = ({0: ("left", "top"), 1: ("right", "top"),
                          2: ("right", "bottom"), 3: ("left", "bottom")}[detail]
                         if kind == "vertex" else (detail,))
                if "left" in edges: left = min(round(point.x()), right-8)
                if "right" in edges: right = max(round(point.x()), left+8)
                if "top" in edges: top = min(round(point.y()), bottom-8)
                if "bottom" in edges: bottom = max(round(point.y()), top+8)
                candidate.x, candidate.y = left, top
                candidate.width, candidate.height = right-left, bottom-top
            if candidate.width >= 8 and candidate.height >= 8:
                self.geometry_updated.emit(index, candidate)
        except ValueError:
            # Keep the last valid polygon when a vertex would cross another edge.
            self.editing_error.emit("Keep polygon edges from crossing; the last valid outline is retained.")

    def mouseMoveEvent(self, event):
        """Provide live geometry feedback and edge-specific resize cursors."""
        point = self._point(event)
        if self._drag:
            self._edit_to(point)
        elif self.mode == "polygon" and self._points:
            self._hover = point
            self._paint_trace()
        elif self._rubber is not None and self._start is not None:
            self._rubber.setRect(QRectF(self._start, point).normalized())
        elif self.mode == "edit" and self.draw_enabled:
            index, operation = self._hit(point)
            cursor = Qt.ArrowCursor
            if index >= 0:
                kind, detail = operation
                if kind == "move": cursor = Qt.SizeAllCursor
                elif kind == "edge": cursor = Qt.SizeHorCursor if detail in ("left", "right") else Qt.SizeVerCursor
                elif getattr(self._arenas[index], "polygon", None): cursor = Qt.CrossCursor
                else: cursor = Qt.SizeFDiagCursor if detail in (0, 2) else Qt.SizeBDiagCursor
            self.setCursor(cursor)
        event.accept()

    def mouseReleaseEvent(self, event):
        """Commit the final drag location, including fast drags with no move event."""
        if event.button() == Qt.LeftButton and self._drag:
            self._edit_to(self._point(event))
            self._drag = None
        elif event.button() == Qt.LeftButton and self._start is not None:
            rect = QRectF(self._start, self._point(event)).normalized().toAlignedRect()
            self.cancel_drawing()
            if rect.width() >= 8 and rect.height() >= 8:
                self.rectangle_drawn.emit(rect.x(), rect.y(), min(rect.width(), self.image_width-rect.x()),
                                          min(rect.height(), self.image_height-rect.y()))
        event.accept()

    def _paint_trace(self):
        """Show the next segment and a faint closing edge while tracing."""
        if self._rubber is not None:
            self.preview_scene.removeItem(self._rubber)
            self._rubber = None
        if not self._points:
            return
        path = QPainterPath(self._points[0])
        for point in self._points[1:]: path.lineTo(point)
        if self._hover is not None: path.lineTo(self._hover)
        path.lineTo(self._points[0])
        radius = self._radius()*0.45
        for point in self._points: path.addEllipse(point, radius, radius)
        pen = QPen(QColor("#64e2bb"), 2, Qt.DashLine)
        pen.setCosmetic(True)
        self._rubber = self.preview_scene.addPath(path, pen)

    def finish_polygon(self):
        """Validate before emitting, leaving invalid traces available for undo."""
        if not self.draw_enabled or len(self._points) < 3:
            return
        points = [[round(p.x()), round(p.y())] for p in self._points]
        # A double-click may append the closing point twice; ignore that duplicate.
        points = [p for i, p in enumerate(points) if i == 0 or p != points[i-1]]
        try:
            draft = Arena("preview", "Preview", 0, 0, 8, 8)
            draft.set_polygon(points)
            if draft.width < 8 or draft.height < 8:
                raise ValueError("An arena must be at least 8 by 8 pixels.")
        except ValueError as error:
            self.editing_error.emit(str(error))
            return
        self.cancel_drawing()
        self.polygon_drawn.emit(points)

    def undo_vertex(self):
        """Remove the latest tracing point without discarding earlier work."""
        if self._points:
            self._points.pop()
            self._paint_trace()
            self.tracing_changed.emit(len(self._points))

    def cancel_drawing(self):
        """Discard only the unfinished gesture, preserving all saved draft arenas."""
        if self._rubber is not None:
            self.preview_scene.removeItem(self._rubber)
        self._rubber = self._start = self._drag = None
        self._points = []
        self.tracing_changed.emit(0)

    def mouseDoubleClickEvent(self, event):
        """Finish a traced polygon with the familiar double-click gesture."""
        if self.mode == "polygon" and self.draw_enabled:
            self.finish_polygon()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        """Keep Enter, Backspace and Escape local to unfinished drawing gestures."""
        if self._points or self._start is not None:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter): self.finish_polygon()
            elif event.key() in (Qt.Key_Backspace, Qt.Key_Delete): self.undo_vertex()
            elif event.key() == Qt.Key_Escape: self.cancel_drawing()
            else: return super().keyPressEvent(event)
            event.accept()
        else:
            super().keyPressEvent(event)


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
        self.preview.polygon_drawn.connect(self.add_polygon)
        self.preview.selected.connect(self.select_arena)
        self.preview.geometry_updated.connect(self.apply_geometry)
        self.preview.editing_error.connect(self.hint.setText)
        tools = QHBoxLayout()
        self.mode_buttons = {}
        for mode, label in (("edit", "Edit edges"), ("rectangle", "Draw rectangle"), ("polygon", "Trace polygon")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setEnabled(not geometry_locked)
            button.clicked.connect(lambda checked=False, mode=mode: self.set_edit_mode(mode))
            self.mode_buttons[mode] = button
            tools.addWidget(button)
        tools.addStretch()
        self.undo_vertex_button = QPushButton("Undo point")
        self.finish_polygon_button = QPushButton("Finish polygon")
        self.undo_vertex_button.clicked.connect(self.preview.undo_vertex)
        self.finish_polygon_button.clicked.connect(self.preview.finish_polygon)
        tools.addWidget(self.undo_vertex_button)
        tools.addWidget(self.finish_polygon_button)
        self.preview.tracing_changed.connect(self.update_trace_buttons)
        layout.addLayout(tools)
        self.edit_instructions = QLabel()
        self.edit_instructions.setWordWrap(True)
        self.edit_instructions.setObjectName("muted")
        layout.addWidget(self.edit_instructions)
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
        self.set_edit_mode("edit" if self.arenas else "rectangle")

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
                if column and (self.geometry_locked or getattr(arena, "polygon", None)):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)
        self.refresh_preview()
        self.validate_draft()

    def refresh_preview(self):
        """Keep the preview and selected coordinate row in agreement."""
        self.preview.show_arenas(self.arenas, self.table.currentRow())
        self.summary.setText(f"{len(self.arenas)} arenas. Coordinates use original video pixels. Polygon bounds follow their vertices; adjust them in the preview. Pixels outside polygons are masked in exported crops.")

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
            if self.geometry_locked or getattr(arena, "polygon", None):
                self.populate_table()
                return
            setattr(arena, ("label", "x", "y", "width", "height")[item.column()], value)
        self.refresh_preview()
        self.validate_draft()

    def set_edit_mode(self, mode):
        """Make the active tool explicit and explain its shortest useful gestures."""
        self.preview.set_mode(mode)
        for key, button in self.mode_buttons.items():
            button.setChecked(key == mode)
        instructions = {
            "edit": "Click an arena to select it. Drag an edge or corner to resize, or drag inside to move. Polygon points can be dragged individually.",
            "rectangle": "Drag from one corner to the opposite corner. Choose Edit edges to adjust an existing arena.",
            "polygon": "Click around the arena. Click the first point, double-click, or press Enter to finish. Backspace undoes a point; Esc cancels.",
        }
        self.edit_instructions.setText("Exported outlines are locked; arena names remain editable." if self.geometry_locked else instructions[mode])
        self.undo_vertex_button.setVisible(mode == "polygon")
        self.finish_polygon_button.setVisible(mode == "polygon")
        self.update_trace_buttons(0)

    def update_trace_buttons(self, count):
        """Enable completion only when a trace contains enough vertices."""
        self.undo_vertex_button.setEnabled(count > 0 and not self.geometry_locked)
        self.finish_polygon_button.setEnabled(count >= 3 and not self.geometry_locked)

    def select_arena(self, index):
        """Synchronize mouse selection with the table and its highlighted handles."""
        self.table.selectRow(index)
        self.refresh_preview()

    def apply_geometry(self, index, candidate):
        """Apply a live drag without recreating IDs, names, or annotation state."""
        if self.geometry_locked:
            return
        self.arenas[index] = candidate
        self.populate_table()
        self.table.selectRow(index)

    def add_polygon(self, points):
        """Create a named polygon with a validated source-coordinate bounding box."""
        if self.geometry_locked:
            return
        draft = Arena(f"arena_{uuid4().hex[:12]}", "Polygon", 0, 0, 8, 8)
        try:
            draft.set_polygon(points)
        except ValueError as error:
            self.hint.setText(str(error))
            return
        number = len(self.arenas) + 1
        labels = {arena.label for arena in self.arenas}
        while f"Arena {number}" in labels:
            number += 1
        draft.label = f"Arena {number}"
        self.arenas.append(draft)
        self.populate_table()
        self.table.selectRow(len(self.arenas)-1)
        self.set_edit_mode("edit")

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
        if self.geometry_locked:
            return
        self.arenas = grid_arenas(self.preview.image_width, self.preview.image_height,
                                  self.rows.value(), self.columns.value())
        self.populate_table()
        self.set_edit_mode("edit")

    def auto_detect(self):
        """Compute automatic proposals in the background; the user reviews them."""
        if self.geometry_locked:
            return
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
            self.set_edit_mode("edit")
            self.hint.setText(f"Found {len(arenas)} arena proposals with outer backgrounds trimmed. Review boundaries and names, then export.")
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
        if result == QDialog.Accepted and self.preview._points:
            self.hint.setText("Finish the polygon or press Esc in the preview to cancel its unfinished outline before exporting.")
            self.preview.setFocus()
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
