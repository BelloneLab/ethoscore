"""Per-video arena projects integrated into the existing annotation window.

The selected crop is a real video file. The established annotation editor,
keyboard controls, timeline, and CSV format therefore operate on exactly one
arena at a time, with unchanged source frame numbering.
"""

from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QProgressDialog, QPushButton, QVBoxLayout,
)

from annotator_libs.annotation_logic import apply_range_label
from annotator_libs.arena_model import ArenaProject, default_project_dir
from annotator_libs.arena_ui import ArenaEditor, ExportWorker, STATUS_COLORS, STATUS_NAMES


class ArenaWorkflow:
    """Add arena management without duplicating the existing video editor."""

    def init_arena_workflow(self):
        """Initialize state before any menu, video, or settings callbacks run."""
        self.arena_project = None
        self.arena_project_dir = None
        self.active_arena_id = None
        self.arena_export_worker = None
        self.arena_progress_dialog = None
        self._loading_arena = False

    def create_arena_panel(self):
        """Build a compact arena selector with accessible status text and colors."""
        group = QGroupBox("ARENAS")
        group.setStyleSheet("""
            QGroupBox { color: #9fb0c5; font-weight: bold; border: 1px solid #3d4a5a;
                        border-radius: 8px; margin-top: 10px; padding-top: 14px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QPushButton { color: #eaf2fa; background: #2b3a4b; border: none;
                          border-radius: 5px; padding: 7px; }
            QPushButton:hover { background: #3a5067; }
            QPushButton:disabled { color: #657487; background: #252d37; }
            QComboBox { color: #eaf2fa; background: #273544; border: 1px solid #45556a;
                        border-radius: 5px; padding: 6px; min-height: 20px; }
            QComboBox QAbstractItemView { color: #eaf2fa; background: #273544;
                                         selection-background-color: #326473; }
        """)
        layout = QVBoxLayout(group)
        self.arena_setup_button = QPushButton("Set up arenas...")
        self.arena_setup_button.clicked.connect(self.configure_arenas)
        layout.addWidget(self.arena_setup_button)
        row = QHBoxLayout()
        self.arena_previous_button = QPushButton("<")
        self.arena_previous_button.setMaximumWidth(34)
        self.arena_previous_button.setToolTip("Previous arena")
        self.arena_previous_button.clicked.connect(lambda: self.step_arena(-1))
        row.addWidget(self.arena_previous_button)
        self.arena_selector = QComboBox()
        self.arena_selector.setMinimumContentsLength(12)
        self.arena_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.arena_selector.currentIndexChanged.connect(self.select_arena_from_combo)
        row.addWidget(self.arena_selector, 1)
        self.arena_next_button = QPushButton(">")
        self.arena_next_button.setMaximumWidth(34)
        self.arena_next_button.setToolTip("Next arena")
        self.arena_next_button.clicked.connect(lambda: self.step_arena(1))
        row.addWidget(self.arena_next_button)
        layout.addLayout(row)
        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("Status"))
        self.arena_status_selector = QComboBox()
        for key, label in STATUS_NAMES.items():
            self.arena_status_selector.addItem(self.status_icon(key), label, key)
        self.arena_status_selector.currentIndexChanged.connect(self.change_arena_status)
        status_row.addWidget(self.arena_status_selector, 1)
        layout.addLayout(status_row)
        self.arena_hint = QLabel("Split a video into independent annotation sessions.")
        self.arena_hint.setWordWrap(True)
        self.arena_hint.setStyleSheet("color: #93a2b5; font-size: 11px; font-weight: normal;")
        layout.addWidget(self.arena_hint)
        self.arena_folder_button = QPushButton("Open arena folder")
        self.arena_folder_button.clicked.connect(self.open_arena_folder)
        layout.addWidget(self.arena_folder_button)
        self.refresh_arena_panel()
        return group

    @staticmethod
    def status_icon(status):
        """Make a color swatch while retaining readable status text beside it."""
        pixmap = QPixmap(12, 12)
        pixmap.fill(QColor(STATUS_COLORS.get(status, STATUS_COLORS["unlabeled"])))
        return QIcon(pixmap)

    def active_arena(self):
        """Return the active arena definition, or None for a normal full video."""
        if self.arena_project:
            return next((arena for arena in self.arena_project.arenas if arena.id == self.active_arena_id), None)
        return None

    def refresh_arena_panel(self):
        """Synchronize selector names, icons, status, and enabled controls."""
        if not hasattr(self, "arena_selector"):
            return
        self.arena_selector.blockSignals(True)
        self.arena_selector.clear()
        arenas = self.arena_project.arenas if self.arena_project else []
        for arena in arenas:
            self.arena_selector.addItem(self.status_icon(arena.status),
                                         f"{arena.label}  |  {STATUS_NAMES[arena.status]}", arena.id)
        selected = self.arena_selector.findData(self.active_arena_id)
        if selected >= 0:
            self.arena_selector.setCurrentIndex(selected)
        self.arena_selector.blockSignals(False)
        active = self.active_arena()
        self.arena_selector.setEnabled(bool(arenas))
        self.arena_previous_button.setEnabled(len(arenas) > 1)
        self.arena_next_button.setEnabled(len(arenas) > 1)
        self.arena_status_selector.setEnabled(active is not None)
        self.arena_status_selector.blockSignals(True)
        self.arena_status_selector.setCurrentIndex(self.arena_status_selector.findData(active.status if active else "unlabeled"))
        self.arena_status_selector.blockSignals(False)
        self.arena_folder_button.setEnabled(self.arena_project_dir is not None)
        self.arena_setup_button.setEnabled(bool(getattr(self, "video_path", "")))
        self.arena_setup_button.setText("Manage arena names..." if arenas else "Set up arenas...")
        if active:
            completed = sum(arena.status == "completed" for arena in arenas)
            self.arena_hint.setText(f"{completed}/{len(arenas)} completed. Only {active.label} is displayed and annotated.")
        else:
            self.arena_hint.setText("Split a video into independent annotation sessions.")

    def _settle_arena_input(self):
        """Finish pending ranges and stop held input before changing videos.

        Without this boundary, a range started in one arena could end in the
        next. Timer cancellation also prevents delayed key handlers leaking.
        """
        player = self.video_player
        if self.video_path and not self.view_only_mode:
            for behavior, enabled in list(player.range_labeling_active.items()):
                if enabled:
                    start = player.range_labeling_start.get(behavior, player.current_frame)
                    apply_range_label(self.annotations, behavior, start, player.current_frame,
                                      player.available_behaviors, player.include_last_frame_in_range,
                                      player.multitrack_enabled)
        for name in ("navigation_timer", "navigation_delay_timer", "deferred_seek_timer", "scrubbing_timer", "preload_timer"):
            getattr(player, name).stop()
        for name in ("hold_timers", "clear_timers"):
            for timer in getattr(player, name).values():
                timer.stop()
            getattr(player, name).clear()
        for name in ("active_labels", "is_toggled_active", "is_stopping_toggle", "label_key_held",
                     "range_labeling_active", "range_labeling_start", "key_press_start_time"):
            getattr(player, name).clear()
        player.held_behavior = player.current_label_behavior = player.last_created_label = None
        player.removing_mode = player.left_key_held = player.right_key_held = False
        player._qt_escape_held = player._pygame_escape_held = False
        player.navigation_direction = 0
        player.gamepad_frame_accumulator = 0
        self.timeline.clear_range_preview()
        for button in self.behavior_buttons.buttons:
            button.button.setChecked(False)

    def prepare_video_change(self):
        """Save the current arena before switching; failed saves cancel the switch."""
        self._settle_arena_input()
        if self.video_path and not self.view_only_mode and (self.active_arena() is not None or self.annotations):
            self.save_annotations()

    def persist_arena_progress(self):
        """Persist the reviewed status and last frame using the atomic manifest."""
        arena = self.active_arena()
        if arena:
            arena.last_frame = max(0, int(self.video_player.current_frame))
            self.arena_project.save(self.arena_project_dir)

    def read_arena_annotations(self, video_path):
        """Validate a crop's CSV before replacing the current editor session.

        Opening a file is read-only. Unknown behavior columns are retained and
        shown in the editor, rather than silently discarded or synchronized.
        Invalid row numbering or values stops the switch and preserves both
        the current session and the problematic CSV for inspection.
        """
        csv_path = Path(video_path).with_suffix('.csv')
        if not csv_path.exists():
            return {}, list(self.behavior_buttons.behaviors)
        frame = pd.read_csv(csv_path)
        expected_count = self.arena_project.source_metadata['frame_count']
        if 'Frames' not in frame.columns or len(frame) != expected_count:
            raise ValueError(f"{csv_path.name} must contain one row for each of the {expected_count} source frames.")
        if not np.array_equal(frame['Frames'].to_numpy(), np.arange(1, expected_count + 1)):
            raise ValueError(f"{csv_path.name} has missing, duplicate, or reordered frame numbers.")
        columns = [column for column in frame.columns if column != 'Frames']
        if not columns or not frame[columns].isin([0, 1]).all().all():
            raise ValueError(f"{csv_path.name} must have behavior columns containing only 0 and 1.")
        behaviors = list(dict.fromkeys([*self.behavior_buttons.behaviors, *columns]))
        rows, indices = np.where(frame[columns].to_numpy() == 1)
        annotations = {}
        for row, column in zip(rows, indices):
            annotations.setdefault(int(row), []).append(columns[int(column)])
        return annotations, behaviors

    def mark_arena_edited(self):
        """A first edit starts work; editing a completed arena reopens it."""
        arena = self.active_arena()
        if arena and arena.status != "ongoing":
            arena.status = "ongoing"
            self.persist_arena_progress()
            self.refresh_arena_panel()

    def configure_arenas(self):
        """Review arena geometry and export validated, independent subvideos."""
        if not self.video_path or self.arena_export_worker:
            return
        source = str(self.arena_project.source_path) if self.arena_project else self.video_path
        capture = cv2.VideoCapture(source)
        ok, frame = capture.read()
        capture.release()
        if not ok:
            QMessageBox.warning(self, "Cannot read source", f"Could not read a preview from {source}")
            return
        existing = self.arena_project.arenas if self.arena_project else []
        editor = ArenaEditor(source, frame, existing, geometry_locked=bool(existing), parent=self)
        if editor.exec() != QDialog.Accepted:
            return
        try:
            self.prepare_video_change()
            if existing:
                self.arena_project.arenas = editor.arenas
                self.arena_project.save(self.arena_project_dir)
                self.refresh_arena_panel()
                self.update_arena_title()
                return
            project_dir = default_project_dir(source)
            self._pending_arena_project = ArenaProject.create(source, editor.arenas)
            self._pending_arena_dir = project_dir
            self.arena_progress_dialog = QProgressDialog("Exporting arena videos. Source frames remain unchanged.", "Cancel", 0, 100, self)
            self.arena_progress_dialog.setWindowTitle("Ethoscore | Export arenas")
            self.arena_progress_dialog.setWindowModality(Qt.WindowModal)
            self.arena_progress_dialog.setMinimumDuration(0)
            self.arena_progress_dialog.setAutoClose(False)
            self.arena_progress_dialog.setAutoReset(False)
            self.arena_export_worker = ExportWorker(source, editor.arenas, project_dir, editor.lossless, self)
            self.arena_export_worker.progress.connect(self.arena_progress_dialog.setValue)
            self.arena_progress_dialog.canceled.connect(self.arena_export_worker.requestInterruption)
            self.arena_export_worker.exported.connect(self.arena_export_succeeded)
            self.arena_export_worker.failed.connect(self.arena_export_failed)
            self.arena_export_worker.finished.connect(self.arena_export_finished)
            self.arena_export_worker.start()
            self.arena_progress_dialog.show()
        except Exception as error:
            QMessageBox.warning(self, "Arena setup failed", str(error))

    def arena_export_succeeded(self, paths):
        """Publish the project only after the exporter has verified every crop."""
        try:
            self.arena_project = ArenaProject.load(self._pending_arena_dir)
            self.arena_project_dir = self._pending_arena_dir
            self.active_arena_id = None
            self.refresh_arena_panel()
            self.switch_arena(self.arena_project.arenas[0].id)
            self.statusBar().showMessage(f"Exported {len(paths)} arenas. Source frame numbers preserved.", 8000)
        except Exception as error:
            QMessageBox.warning(self, "Could not save arena project", str(error))

    def arena_export_failed(self, message):
        """Report an export failure without redirecting the current annotation session."""
        QMessageBox.warning(self, "Arena export did not finish", message)

    def arena_export_finished(self):
        """Release worker ownership after its thread has actually stopped."""
        if self.arena_progress_dialog:
            self.arena_progress_dialog.close()
            self.arena_progress_dialog.deleteLater()
        self.arena_progress_dialog = None
        if self.arena_export_worker:
            self.arena_export_worker.deleteLater()
        self.arena_export_worker = None

    def select_arena_from_combo(self, index):
        """Resolve a combo selection by stable ID rather than a mutable label."""
        arena_id = self.arena_selector.itemData(index)
        if arena_id and arena_id != self.active_arena_id:
            self.switch_arena(arena_id)

    def step_arena(self, direction):
        """Cycle through the video's arenas in one click, saving the current one."""
        count = self.arena_selector.count()
        if count:
            index = (self.arena_selector.currentIndex() + direction) % count
            self.switch_arena(self.arena_selector.itemData(index))

    def switch_arena(self, arena_id):
        """Save the current crop and load only the requested arena's video and CSV."""
        if self._loading_arena or not self.arena_project:
            return False
        target = next((arena for arena in self.arena_project.arenas if arena.id == arena_id), None)
        if target is None:
            return False
        crop_path = target.video_path(self.arena_project_dir)
        if not crop_path.is_file():
            QMessageBox.warning(self, "Arena video missing", f"The exported crop was not found:\n{crop_path}")
            self.refresh_arena_panel()
            return False
        previous_id = self.active_arena_id
        try:
            self.prepare_video_change()
            self._loading_arena = True
            self.active_arena_id = target.id
            self.last_frame_positions[str(crop_path)] = target.last_frame
            if not self.load_video_by_path(str(crop_path), arena_switch=True):
                self.active_arena_id = previous_id
                return False
            self.update_arena_title()
            self.refresh_arena_panel()
            self.video_player.setFocus()
            return True
        except Exception as error:
            self.active_arena_id = previous_id
            QMessageBox.warning(self, "Could not switch arena", str(error))
            return False
        finally:
            self._loading_arena = False
            self.refresh_arena_panel()

    def discover_arena_project(self, file_path):
        """Open a known project before the full source CSV can be touched.

        Return None for an ordinary video, True on success, or False when an
        existing project cannot be safely opened. A failure must not silently
        fall back to editing the original source's annotation file.
        """
        path = Path(file_path).resolve()
        candidates = [default_project_dir(path), path.parent.parent]
        for directory in candidates:
            # Loading a nonexistent project should be silent. A damaged one is
            # reported rather than silently replaced with newly detected crops.
            if not (Path(directory) / "arenas.json").is_file():
                continue
            try:
                project = ArenaProject.load(directory)
                source_match = Path(project.source_path).resolve() == path
                matching = next((arena for arena in project.arenas
                                 if arena.video_path(directory).resolve() == path), None)
                if not source_match and matching is None:
                    continue
                previous = self.arena_project, self.arena_project_dir, self.active_arena_id
                self.arena_project, self.arena_project_dir = project, Path(directory)
                # The old arena was already saved before project resolution.
                # Clearing its ID prevents saving its dictionary into this one.
                self.active_arena_id = None
                target = matching or (project.arenas[0] if project.arenas else None)
                if target and self.switch_arena(target.id):
                    return True
                self.arena_project, self.arena_project_dir, self.active_arena_id = previous
                self.refresh_arena_panel()
                return False
            except Exception as error:
                QMessageBox.warning(self, "Could not reopen arena project", str(error))
                return False
        self.arena_project = None
        self.arena_project_dir = None
        self.active_arena_id = None
        self.refresh_arena_panel()
        self.update_arena_title()
        return None

    def update_arena_title(self):
        """Show both source and selected arena so the user always knows the scope."""
        arena = self.active_arena()
        if arena:
            source_name = Path(self.arena_project.source_path).name
            self.video_path_label.setText(f"{source_name}\n{arena.label}")
            self.video_path_label.setToolTip(str(arena.video_path(self.arena_project_dir)))
            self.setWindowTitle(f"Ethoscore | {arena.label} | {source_name}")
            self.last_video_path = str(self.arena_project.source_path)
        else:
            self.setWindowTitle("Ethoscore")

    def change_arena_status(self, index):
        """Save completion as an explicit user decision, including all-empty arenas."""
        arena = self.active_arena()
        if arena:
            previous = arena.status
            try:
                self._settle_arena_input()
                self.save_annotations()
                arena.status = self.arena_status_selector.itemData(index)
                self.persist_arena_progress()
                self.refresh_arena_panel()
            except Exception as error:
                arena.status = previous
                self.refresh_arena_panel()
                QMessageBox.warning(self, "Could not save arena status", str(error))

    def open_arena_folder(self):
        """Open the project output directory with the native file manager."""
        if self.arena_project_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.arena_project_dir)))
