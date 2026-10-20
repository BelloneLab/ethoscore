"""Review and export behavior-bout overview movies without modifying annotations."""

from copy import deepcopy
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout,
                              QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton,
                              QSpinBox, QVBoxLayout)

from annotator_libs.arena_ui import ARENA_STYLE
from annotator_libs.bout_grid import GridConfig, GridSource, export_bout_grid, extract_bouts


class GridExportWorker(QThread):
    """Encode a frozen annotation snapshot off the GUI thread."""

    progress = Signal(int)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, sources, behavior, destination, config, parent=None):
        """Own independent input state so later GUI edits cannot alter the movie."""
        super().__init__(parent)
        self.sources = deepcopy(sources)
        self.behavior, self.destination, self.config = behavior, Path(destination), config

    def run(self):
        """Publish a complete movie and CSV, or report a clean cancellation/error."""
        try:
            result = export_bout_grid(self.sources, self.behavior, self.destination,
                                     config=self.config,
                                     progress=lambda value: self.progress.emit(round(value * 100)),
                                     cancel=self.isInterruptionRequested)
            self.succeeded.emit(result)
        except Exception as error:
            self.failed.emit(str(error))


class BoutGridDialog(QDialog):
    """A compact export sheet with explicit source scope and full-bout coverage."""

    def __init__(self, window):
        """Keep the original editor alive while exporting an isolated snapshot."""
        super().__init__(window)
        self.window = window
        self.worker = None
        self.sources = []
        self.output = None
        self.setWindowTitle("Ethoscore | Behavior grid movie")
        self.setStyleSheet(ARENA_STYLE + """
            QComboBox, QLineEdit { background: #26354a; color: #edf3fc;
                border: 1px solid #3b506a; border-radius: 5px; padding: 6px; }
            QComboBox QAbstractItemView { background: #26354a; color: #edf3fc;
                selection-background-color: #167d72; }
            QProgressBar { background: #0d1520; color: #dcebe8;
                border: 1px solid #33445b; border-radius: 4px; text-align: center; }
            QProgressBar::chunk { background: #167d72; border-radius: 3px; }
        """)
        self.setMinimumWidth(670)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        title = QLabel("Every bout. One overview.")
        title.setObjectName("title")
        layout.addWidget(title)
        description = QLabel("Labeled tiles loop independently in a paginated grid, in the style of MAMIR. "
                             "Each page lasts long enough to show its longest bout.")
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QFormLayout()
        self.scope = QComboBox()
        self.scope.addItem("Current video / arena", False)
        if window.arena_project:
            self.scope.addItem("All arenas in this recording", True)
        self.behavior = QComboBox()
        form.addRow("Annotations", self.scope)
        form.addRow("Behavior", self.behavior)
        grid = QHBoxLayout()
        self.rows, self.columns = QSpinBox(), QSpinBox()
        for spin, value in ((self.rows, 4), (self.columns, 5)):
            spin.setRange(1, 6)
            spin.setValue(value)
            grid.addWidget(spin)
        grid.addWidget(QLabel("rows × columns"))
        form.addRow("Grid", grid)
        self.tile = QComboBox()
        for size in (176, 240, 320, 480):
            self.tile.addItem(f"{size} × {size} pixels", size)
        form.addRow("Tile size", self.tile)
        self.fps = QSpinBox()
        self.fps.setRange(1, 60)
        self.fps.setValue(12)
        form.addRow("Movie frames / second", self.fps)
        self.seconds = QSpinBox()
        self.seconds.setRange(1, 120)
        self.seconds.setValue(4)
        form.addRow("Minimum seconds / page", self.seconds)
        layout.addLayout(form)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        location = QHBoxLayout()
        suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        source = Path(window.arena_project.source_path if window.arena_project else window.video_path)
        self.folder_name = f"{source.stem}_bout_grid_{suffix}"
        self.destination = QLineEdit(str(source.parent / self.folder_name))
        self.destination.setCursorPosition(0)
        self.browse = QPushButton("Browse…")
        self.browse.clicked.connect(self.choose_directory)
        location.addWidget(self.destination, 1)
        location.addWidget(self.browse)
        layout.addWidget(QLabel("New output folder (movie + bout manifest CSV)"))
        layout.addLayout(location)
        note = QLabel("Uses current unsaved labels for the active arena and saved labels for other arenas. "
                      "The grid movie resamples playback for review; source videos and annotations remain intact.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        actions = QHBoxLayout()
        self.open_folder = QPushButton("Open output folder")
        self.open_folder.setEnabled(False)
        self.open_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output))))
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.cancel_or_close)
        self.export_button = QPushButton("Export grid movie")
        self.export_button.setObjectName("primary")
        self.export_button.clicked.connect(self.start_export)
        actions.addWidget(self.open_folder)
        actions.addStretch()
        actions.addWidget(self.close_button)
        actions.addWidget(self.export_button)
        layout.addLayout(actions)
        self.scope.currentIndexChanged.connect(self.refresh_sources)
        for control in (self.behavior,):
            control.currentIndexChanged.connect(self.refresh_summary)
        self.rows.valueChanged.connect(self.refresh_summary)
        self.columns.valueChanged.connect(self.refresh_summary)
        self.refresh_sources()

    def refresh_sources(self):
        """Load read-only annotation snapshots for the selected source scope."""
        try:
            window = self.window
            sources = []
            if self.scope.currentData() and window.arena_project:
                for arena in window.arena_project.arenas:
                    path = arena.video_path(window.arena_project_dir)
                    annotations = (window.annotations if arena.id == window.active_arena_id else
                                   window.read_arena_annotations(path)[0])
                    sources.append(GridSource(str(path), deepcopy(annotations), arena.label))
            else:
                active = window.active_arena()
                sources.append(GridSource(window.video_path, deepcopy(window.annotations),
                                          active.label if active else Path(window.video_path).stem))
            selected = self.behavior.currentText()
            names = list(window.behavior_buttons.behaviors)
            for source in sources:
                for labels in source.annotations.values():
                    names.extend([labels] if isinstance(labels, str) else labels)
            self.sources = sources
            self.behavior.blockSignals(True)
            self.behavior.clear()
            self.behavior.addItems(list(dict.fromkeys(names)))
            if selected in names:
                self.behavior.setCurrentText(selected)
            self.behavior.blockSignals(False)
            self.refresh_summary()
        except Exception as error:
            self.sources = []
            self.summary.setText(f"Cannot read annotations: {error}")
            self.export_button.setEnabled(False)

    def refresh_summary(self):
        """Show how many bouts will be included, with no hidden sampling."""
        count = sum(len(extract_bouts(source.annotations, self.behavior.currentText())) for source in self.sources)
        capacity = self.rows.value() * self.columns.value()
        pages = (count + capacity - 1) // capacity
        self.summary.setText(f"{count} bouts · {len(self.sources)} source(s) · {pages} page(s). All bouts included.")
        self.export_button.setEnabled(count > 0 and self.worker is None)

    def choose_directory(self):
        """Choose the parent for a fresh export folder without overwriting files."""
        directory = QFileDialog.getExistingDirectory(self, "Choose output parent folder", str(Path(self.destination.text()).parent))
        if directory:
            self.destination.setText(str(Path(directory) / self.folder_name))

    def start_export(self):
        """Validate options and start one cancellable background export."""
        try:
            size = self.tile.currentData()
            config = GridConfig(rows=self.rows.value(), columns=self.columns.value(),
                                tile_width=size, tile_height=size, output_fps=self.fps.value(),
                                page_seconds=self.seconds.value())
            destination = Path(self.destination.text()).expanduser()
            if not self.destination.text().strip() or destination.exists():
                raise ValueError("Choose a new output folder that does not already exist.")
            self.output = destination
            self.progress.setValue(0)
            self.open_folder.setEnabled(False)
            self.worker = GridExportWorker(self.sources, self.behavior.currentText(), destination, config, self)
            self.worker.progress.connect(self.progress.setValue)
            self.worker.succeeded.connect(self.export_succeeded)
            self.worker.failed.connect(lambda message: self.summary.setText(message))
            self.worker.finished.connect(self.export_finished)
            for widget in self.editable_controls():
                widget.setEnabled(False)
            self.close_button.setText("Cancel export")
            self.summary.setText("Encoding bout pages…")
            self.worker.start()
        except Exception as error:
            self.summary.setText(str(error))

    def editable_controls(self):
        """Enumerate controls whose values must remain fixed during encoding."""
        return (self.scope, self.behavior, self.rows, self.columns, self.tile, self.fps,
                self.seconds, self.destination, self.browse, self.export_button)

    def export_succeeded(self, result):
        """Reveal the successfully published movie and exact source-frame manifest."""
        self.progress.setValue(100)
        self.summary.setText(f"Exported {result['bouts']} bouts across {result['pages']} pages. Movie and CSV are ready.")
        self.open_folder.setEnabled(True)

    def export_finished(self):
        """Release the stopped worker and permit another export or closing."""
        self.worker.deleteLater()
        self.worker = None
        for widget in self.editable_controls():
            widget.setEnabled(True)
        self.close_button.setText("Close")

    def cancel_or_close(self):
        """Request cancellation without terminating an encoder mid-publication."""
        if self.worker:
            self.worker.requestInterruption()
            self.summary.setText("Cancelling export…")
        else:
            self.accept()

    def reject(self):
        """Route Escape through cancellation while a worker owns resources."""
        if self.worker:
            self.cancel_or_close()
        else:
            super().reject()

    def closeEvent(self, event):
        """Keep the worker alive until its temporary outputs are cleaned up."""
        if self.worker:
            self.cancel_or_close()
            event.ignore()
        else:
            event.accept()


def open_bout_grid_export(window):
    """Enter export from the main menu after ending held annotation gestures."""
    if not window.video_path:
        window.statusBar().showMessage("Open a video before exporting behavior bouts.", 5000)
        return
    if hasattr(window, "playback_controls"):
        window.playback_controls.pause()
    window._settle_arena_input()
    BoutGridDialog(window).exec()
