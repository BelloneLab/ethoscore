import sys
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                              QSpinBox, QCheckBox, QLabel, QDialogButtonBox,
                              QGroupBox, QWidget, QProgressBar, QPushButton)
from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QRect, QObject
from PySide6.QtGui import QPainter, QColor, QFont, QPen

class GamificationManager(QObject):
    """Manages gamification logic, including points, combos, and score."""

    score_updated = Signal(int, int, str) # total_score, points_gained, combo_text
    combo_activated = Signal(int) # combo_count
    combo_timer_progress = Signal(float) # progress from 0.0 to 1.0 (1.0 = full time remaining)
    combo_timer_visible = Signal(bool) # True to show progress bar, False to hide
    gamification_enabled_changed = Signal(bool) # New signal for when gamification is enabled/disabled

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.gamification_enabled = True
        self.total_score = 0
        self.high_score = 0 # Initialize high score
        self.points_per_label = 10
        self.combo_threshold = 3 
        self.combo_increment_value = 1
        self.combo_timeout_ms = 2000
        self.combo_across_behaviors = True
        self.combo_timer = QTimer(self.parent)
        self.combo_timer.setSingleShot(True)
        self.combo_timer.timeout.connect(self._reset_combo)

        # Visual progress timer
        self.progress_timer = QTimer(self.parent)
        self.progress_timer.timeout.connect(self._update_progress)
        self.progress_update_interval = 50

        self.current_combo_count = 0 
        self.last_completed_behavior = None 
        self.last_completed_frame = -1
        self.active_behavior_count = 0
        self.timer_paused = False

    def load_settings(self, settings):
        """Load gamification settings from QSettings."""
        self.gamification_enabled = settings.value('gamification/enabled', True, bool)
        self.high_score = settings.value('gamification/high_score', 0, int)
        self.points_per_label = settings.value('gamification/points_per_label', 1, int)
        self.combo_threshold = settings.value('gamification/combo_threshold', 3, int)
        self.combo_increment_value = settings.value('gamification/combo_increment_value', 1, int)
        self.combo_timeout_ms = settings.value('gamification/combo_timeout_ms', 1000, int)
        self.combo_across_behaviors = settings.value('gamification/combo_across_behaviors', True, bool)

    def save_settings(self, settings):
        """Save gamification settings to QSettings."""
        settings.setValue('gamification/enabled', self.gamification_enabled)
        settings.setValue('gamification/high_score', self.high_score)
        settings.setValue('gamification/points_per_label', self.points_per_label)
        settings.setValue('gamification/combo_threshold', self.combo_threshold)
        settings.setValue('gamification/combo_increment_value', self.combo_increment_value)
        settings.setValue('gamification/combo_timeout_ms', self.combo_timeout_ms)
        settings.setValue('gamification/combo_across_behaviors', self.combo_across_behaviors)

    def set_total_score(self, score):
        """Sets the total score from an external source."""
        self.total_score = score
        self.score_updated.emit(self.total_score, 0, "")

    def label_applied(self, frame_number, behavior):
        """Called when a label is applied to a frame (start frame set)."""
        if not self.gamification_enabled:
            return
        # No points awarded for label start, only per frame when label_completed
        points_gained = 0

    def label_removed(self, frame_number, behavior):
        """Called when a label is removed from a frame."""
        debug_log(f"label_removed called: frame={frame_number}, behavior='{behavior}'")
        if not self.gamification_enabled:
            return
        debug_log("  Resetting combo due to label removal")
        self._reset_combo()

    def label_completed(self, frame_number, behavior, duration_frames):
        """Called when a behavior segment is completed (last frame set)."""
        debug_log(f"label_completed called: frame={frame_number}, behavior='{behavior}', duration={duration_frames}")
        debug_log(f"  gamification_enabled={self.gamification_enabled}")
        debug_log(f"  combo_timer.isActive()={self.combo_timer.isActive()}")
        debug_log(f"  last_completed_behavior={self.last_completed_behavior}")
        debug_log(f"  current_combo_count={self.current_combo_count}")
        debug_log(f"  combo_threshold={self.combo_threshold}")
        debug_log(f"  combo_across_behaviors={self.combo_across_behaviors}")

        if not self.gamification_enabled:
            debug_log("  Skipping due to gamification disabled")
            return

        # Check if this continues a combo or starts a new one
        combo_continues = False

        # Combo continues if:
        # 1. Labeling same behavior consecutively
        # 2. OR combo_across_behaviors enabled
        if behavior == self.last_completed_behavior:
            # Same consecutive label, always continue
            self.current_combo_count += self.combo_increment_value
            combo_continues = True
            debug_log(f"  Continuing combo (same behavior): new count={self.current_combo_count}")
        elif self.combo_across_behaviors:
            # Different behavior, continue if combo_across_behaviors is enabled
            self.current_combo_count += self.combo_increment_value
            combo_continues = True
            debug_log(f"  Continuing combo (different behavior, across behaviors enabled): new count={self.current_combo_count}")
        else:
            # Start new combo
            self.current_combo_count = self.combo_increment_value
            debug_log(f"  Starting new combo: count={self.current_combo_count}")

        # Effective combo value (score calculation)
        effective_combo_for_score = self.current_combo_count if self.current_combo_count >= self.combo_threshold else 1
        debug_log(f"  effective_combo_for_score={effective_combo_for_score}")

        # Points gained
        points_gained = self.points_per_label * duration_frames * effective_combo_for_score
        debug_log(f"  points_per_label={self.points_per_label}, points_gained={points_gained}")

        # Text for display
        combo_display_value = self.current_combo_count
        if combo_display_value >= self.combo_threshold:
            combo_text_for_display = f"{duration_frames} x {combo_display_value} Combo!"
            debug_log(f"  Combo text: {combo_text_for_display}")
        else:
            # If below threshold, only show frames
            combo_text_for_display = f"{duration_frames}"
            debug_log(f"  Below threshold, text: {combo_text_for_display}")

        self.total_score += points_gained
        if self.total_score > self.high_score:
            self.high_score = self.total_score
        debug_log(f"  Total score: {self.total_score}")

        self.score_updated.emit(self.total_score, points_gained, combo_text_for_display)

        # Emit combo_activated signal only if combo threshold is met
        if self.current_combo_count >= self.combo_threshold:
            self.combo_activated.emit(self.current_combo_count)
            debug_log(f"  Combo activated: {self.current_combo_count}")

        # Update tracking variables
        self.last_completed_behavior = behavior
        self.last_completed_frame = frame_number

        # Start the combo countdown timer when last frame is set
        self.combo_timer.start(self.combo_timeout_ms)
        # Start progress timer for visual feedback
        self.progress_timer.start(self.progress_update_interval)
        self.remaining_time_ms = self.combo_timeout_ms  # Track remaining time
        self.combo_timer_visible.emit(True)
        debug_log(f"  Combo timer started with timeout={self.combo_timeout_ms}ms")
        debug_log(f"  Combo timer active after start: {self.combo_timer.isActive()}")
        debug_log(f"  Combo timer interval: {self.combo_timer.interval()}ms")

    def _update_progress(self):
        """Update the progress bar during combo countdown."""
        if not self.gamification_enabled:
            self.progress_timer.stop()
            self.combo_timer_visible.emit(False)
            return
        if self.remaining_time_ms > 0:
            self.remaining_time_ms -= self.progress_update_interval
            progress = max(0.0, self.remaining_time_ms / self.combo_timeout_ms)
            self.combo_timer_progress.emit(progress)
        else:
            self.progress_timer.stop()

    def _reset_combo(self):
        """Resets the global combo counter when timeout occurs."""
        debug_log("_reset_combo called - combo timeout occurred")
        if not self.gamification_enabled:
            return
        self.current_combo_count = 0
        self.last_completed_behavior = None
        self.combo_timer.stop()
        self.progress_timer.stop()
        self.combo_timer_visible.emit(False)
        debug_log("  Combo reset complete")

    def reset_score(self):
        """Resets the total score and combo."""
        self.total_score = 0
        self._reset_combo()
        if self.gamification_enabled:
            self.score_updated.emit(self.total_score, 0, "")

    def reset_high_score(self):
        """Resets the high score."""
        self.high_score = 0
        # Emit score_updated to refresh high score
        if self.gamification_enabled:
            self.score_updated.emit(self.total_score, 0, "")


    def behavior_activated(self):
        """Called when a behavior becomes active (key pressed or toggled on)."""
        if not self.gamification_enabled:
            return

        self.active_behavior_count += 1

        # If this is the first active behavior, pause the combo timer
        if self.active_behavior_count == 1 and not self.timer_paused:
            self._pause_combo_timer()

    def behavior_deactivated(self):
        """Called when a behavior becomes inactive (key released or toggled off)."""
        if not self.gamification_enabled:
            return

        self.active_behavior_count = max(0, self.active_behavior_count - 1)

        # If no more behaviors are active, resume the combo timer
        if self.active_behavior_count == 0 and self.timer_paused:
            self._resume_combo_timer()

    def _pause_combo_timer(self):
        """Pause the combo timer when behaviors become active."""
        if self.combo_timer.isActive():
            # Store remaining time
            self.remaining_time_ms = self.combo_timer.remainingTime()
            self.combo_timer.stop()
            self.progress_timer.stop()
            self.timer_paused = True

    def _resume_combo_timer(self):
        """Resume the combo timer when all behaviors become inactive."""
        if self.timer_paused and self.remaining_time_ms > 0:
            self.combo_timer.start(self.remaining_time_ms)
            self.progress_timer.start(self.progress_update_interval)
            self.timer_paused = False
        elif self.remaining_time_ms <= 0:
            # Reset combo
            self._reset_combo()


class LiveScoreWidget(QWidget):
    """Widget to display the live score and temporary point gains."""

    def __init__(self, gamification_manager, parent=None):
        super().__init__(parent)
        self.gamification_manager = gamification_manager
        self.setFixedSize(160, 120)
        self.total_score = 0
        self.high_score = 0
        self.points_gained_display = []
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Initially hide if gamification is disabled
        self.setVisible(self.gamification_manager.gamification_enabled)

        self.animation_duration = 5000
        self.animation_offset = 30

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(2)
        self.main_layout.setAlignment(Qt.AlignBottom | Qt.AlignLeft)

        # Combo timer progress bar
        self.combo_progress_bar = QProgressBar(self)
        self.combo_progress_bar.setMaximumHeight(8)
        self.combo_progress_bar.setRange(0, 100)
        self.combo_progress_bar.setValue(100)
        self.combo_progress_bar.setInvertedAppearance(False)
        self.combo_progress_bar.setTextVisible(False)
        self.combo_progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 4px;
                background-color: rgba(255, 255, 255, 100);
            }
            QProgressBar::chunk {
                background-color: rgba(255, 165, 0, 200);  /* Orange color */
                border-radius: 4px;
            }
        """)
        self.main_layout.addWidget(self.combo_progress_bar)
        self.combo_progress_bar.setVisible(False)

        # Total score label
        self.total_score_label = QLabel(f"Score: {self.total_score}")
        self.total_score_label.setFont(QFont("Arial", 16, QFont.Bold))
        self.total_score_label.setStyleSheet("color: white; background-color: rgba(0,0,0,150); border-radius: 5px; padding: 3px 5px;")
        self.total_score_label.setAlignment(Qt.AlignLeft)
        self.main_layout.addWidget(self.total_score_label)

        # High score label
        self.high_score_label = QLabel(f"High Score: {self.high_score}")
        self.high_score_label.setFont(QFont("Arial", 10))
        self.high_score_label.setStyleSheet("color: white; background-color: rgba(0,0,0,100); border-radius: 3px; padding: 1px 3px;")
        self.high_score_label.setAlignment(Qt.AlignLeft)
        self.main_layout.addWidget(self.high_score_label)

        # Connect the new signal to update visibility
        self.gamification_manager.gamification_enabled_changed.connect(self.setVisible)

    def update_combo_progress(self, progress):
        """Update the combo timer progress bar."""
        if not self.gamification_manager.gamification_enabled:
            self.combo_progress_bar.setVisible(False)
            return
        self.combo_progress_bar.setValue(int(progress * 100))
        self.combo_progress_bar.setVisible(True)

    def update_combo_visibility(self, visible):
        """Show or hide the combo timer progress bar."""
        if not self.gamification_manager.gamification_enabled:
            self.combo_progress_bar.setVisible(False)
            return
        self.combo_progress_bar.setVisible(visible)

    def update_score_display(self, total_score, points_gained, combo_text=""):
        """Updates the total score and shows temporary points gained."""
        self.total_score = total_score
        self.high_score = self.gamification_manager.high_score
        self.total_score_label.setText(f"Score: {self.total_score}")
        self.high_score_label.setText(f"High Score: {self.high_score}")

        # Hide the widget if gamification is disabled
        self.setVisible(self.gamification_manager.gamification_enabled)
        if not self.gamification_manager.gamification_enabled:
            return

        if points_gained > 0:
            # Clearing any existing animations
            for points_data in self.points_gained_display[:]:
                if points_data.get('animation'):
                    points_data['animation'].stop()
                self.points_gained_display.remove(points_data)

            # Creating a new animation for the points gained
            points_data = {
                'points': points_gained,
                'combo_text': combo_text,
                'opacity': 1.0,
                'y_offset': 0,
                'animation': None
            }
            self.points_gained_display.append(points_data)

            animation = QPropertyAnimation(self, b"dummy_property") 
            animation.setDuration(self.animation_duration)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            animation.setStartValue(0)
            animation.setEndValue(1) 

            animation.valueChanged.connect(lambda value, pd=points_data: self._animate_points_gained(value, pd))
            animation.finished.connect(lambda pd=points_data: self._remove_points_gained(pd))
            points_data['animation'] = animation
            animation.start()

        self.update()

    def _animate_points_gained(self, value, points_data):
        """Updates opacity and position of points gained during animation."""
        # Fade out
        points_data['opacity'] = 1.0 - value
        # Float up
        points_data['y_offset'] = -int(self.animation_offset * value)
        self.update()

    def _remove_points_gained(self, points_data):
        """Removes points gained display after animation finishes."""
        if points_data in self.points_gained_display:
            self.points_gained_display.remove(points_data)
            self.update()

    def paintEvent(self, event):
        if not self.gamification_manager.gamification_enabled:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw floating points gained
        for points_data in self.points_gained_display:
            points = points_data['points']
            combo_text = points_data.get('combo_text', '')
            opacity = points_data['opacity']
            y_offset = points_data['y_offset']

            if opacity > 0:
                painter.setOpacity(opacity)

                # Determine color based on combo level
                combo_value_for_color = 0
                if "combo" in combo_text:
                    try:
                        # Extract combo value from "XXX x YYY combo"
                        parts = combo_text.split('x')
                        if len(parts) > 1:
                            combo_value_str = parts[1].strip().split(' ')[0]
                            combo_value_for_color = int(combo_value_str)
                    except ValueError:
                        combo_value_for_color = 0

                if combo_value_for_color >= self.gamification_manager.combo_threshold:
                    # Interpolate from green to red
                    if combo_value_for_color <= self.gamification_manager.combo_threshold:
                        r, g, b = 0, 255, 0
                    elif combo_value_for_color >= self.gamification_manager.combo_threshold + 5:
                        r, g, b = 255, 0, 0
                    else:
                        ratio = (combo_value_for_color - self.gamification_manager.combo_threshold) / 5
                        r = int(255 * ratio)
                        g = int(255 * (1 - ratio))
                        b = 0
                    color = QColor(r, g, b, int(255 * opacity))
                else:
                    color = QColor(0, 255, 0, int(255 * opacity))  # Default green

                painter.setPen(QPen(color, 2))
                font = QFont("Arial", 14, QFont.Bold)
                painter.setFont(font)
                combo_bar_rect = self.combo_progress_bar.geometry()
                
                # Checking text height
                font_metrics = painter.fontMetrics()
                text_height = font_metrics.height()
                
                # Y_offset adjustment
                text_rect = QRect(combo_bar_rect.x(), combo_bar_rect.y() + y_offset - text_height,
                                  combo_bar_rect.width(), text_height)

                display_text = combo_text

                painter.drawText(text_rect, Qt.AlignCenter, display_text)
        painter.setOpacity(1.0) # Reset opacity


class GamificationSettingsDialog(QDialog):
    """Dialog for configuring gamification settings."""

    def __init__(self, gamification_manager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gamification Settings")
        self.setModal(True)
        self.gamification_manager = gamification_manager
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        # Enable Gamification checkbox
        self.enable_gamification_checkbox = QCheckBox("Enable Gamification")
        self.enable_gamification_checkbox.setChecked(self.gamification_manager.gamification_enabled)
        form_layout.addRow(self.enable_gamification_checkbox)

        # Points per labeled frame
        self.points_per_label_spin = QSpinBox()
        self.points_per_label_spin.setRange(1, 1000)
        self.points_per_label_spin.setValue(self.gamification_manager.points_per_label)
        form_layout.addRow("Points per labeled frame:", self.points_per_label_spin)

        # Combo threshold
        self.combo_threshold_spin = QSpinBox()
        self.combo_threshold_spin.setRange(2, 20)
        self.combo_threshold_spin.setValue(self.gamification_manager.combo_threshold)
        form_layout.addRow("Combo threshold (labels):", self.combo_threshold_spin)

        # Combo increment value
        self.combo_increment_value_spin = QSpinBox()
        self.combo_increment_value_spin.setRange(1, 10)
        self.combo_increment_value_spin.setValue(self.gamification_manager.combo_increment_value)
        form_layout.addRow("Combo increment value:", self.combo_increment_value_spin)

        # Combo timeout
        self.combo_timeout_spin = QSpinBox()
        self.combo_timeout_spin.setRange(100, 5000)
        self.combo_timeout_spin.setSuffix(" ms")
        self.combo_timeout_spin.setValue(self.gamification_manager.combo_timeout_ms)
        form_layout.addRow("Combo timeout:", self.combo_timeout_spin)

        # Combo across behaviors checkbox
        self.combo_across_behaviors_checkbox = QCheckBox("Allow combos across different behaviors")
        self.combo_across_behaviors_checkbox.setChecked(self.gamification_manager.combo_across_behaviors)
        self.combo_across_behaviors_checkbox.setToolTip("When enabled, consecutive labels of different behaviors within the timeout period will continue the combo")
        form_layout.addRow(self.combo_across_behaviors_checkbox)



        layout.addLayout(form_layout)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults,
            Qt.Horizontal, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_default_settings)
        layout.addWidget(buttons)

        # Add a button to reset high score
        reset_high_score_button = QPushButton("Reset High Score")
        reset_high_score_button.clicked.connect(self._reset_high_score_and_update_ui)
        layout.addWidget(reset_high_score_button)

    def restore_default_settings(self):
        """Restores default gamification settings."""
        self.enable_gamification_checkbox.setChecked(True)
        self.points_per_label_spin.setValue(1)
        self.combo_threshold_spin.setValue(3)
        self.combo_increment_value_spin.setValue(1)
        self.combo_timeout_spin.setValue(1000)

    def _reset_high_score_and_update_ui(self):
        """Resets the high score in the manager and updates the UI."""
        self.gamification_manager.reset_high_score()
        # LiveScoreWidget automatically updates via the score_updated signal.

    def accept(self):
        """Saves settings and accepts the dialog."""
        # Checking if the enabled state has changed before emitting the signal
        if self.gamification_manager.gamification_enabled != self.enable_gamification_checkbox.isChecked():
            self.gamification_manager.gamification_enabled = self.enable_gamification_checkbox.isChecked()
            self.gamification_manager.gamification_enabled_changed.emit(self.gamification_manager.gamification_enabled)

        self.gamification_manager.points_per_label = self.points_per_label_spin.value()
        self.gamification_manager.combo_threshold = self.combo_threshold_spin.value()
        self.gamification_manager.combo_increment_value = self.combo_increment_value_spin.value()
        self.gamification_manager.combo_timeout_ms = self.combo_timeout_spin.value()
        self.gamification_manager.combo_across_behaviors = self.combo_across_behaviors_checkbox.isChecked()
        super().accept()
