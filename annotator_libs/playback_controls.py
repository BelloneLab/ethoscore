"""Compact frame-exact transport and coalesced whole-movie navigation."""

import math
import time

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QHBoxLayout,
                               QLabel, QSlider, QSpinBox, QStyle, QStyleOptionSlider,
                               QToolButton, QVBoxLayout, QWidget)


class SeekSlider(QSlider):
    """Jump directly to a clicked position, with precise wheel navigation."""

    seek_started = Signal()
    seek_finished = Signal()
    wheel_frames = Signal(int)

    def _position(self, event):
        """Map groove pixels to frames while respecting handle width."""
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        handle = self.style().subControlRect(QStyle.CC_Slider, option,
                                             QStyle.SC_SliderHandle, self)
        span = max(1, self.width() - handle.width())
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
                                              int(event.position().x() - handle.width() / 2),
                                              span, option.upsideDown)

    def mousePressEvent(self, event):
        """Start scrubbing anywhere on the groove without page-step jumps."""
        if event.button() == Qt.LeftButton:
            self.seek_started.emit()
            self.setSliderDown(True)
            self.setValue(self._position(event))
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Keep the latest pointer target; the controller throttles decoding."""
        if self.isSliderDown():
            self.setValue(self._position(event))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Commit the exact final target immediately on release."""
        if event.button() == Qt.LeftButton and self.isSliderDown():
            self.setValue(self._position(event))
            self.setSliderDown(False)
            self.seek_finished.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        """Wheel by one second, Shift by ten seconds, or Ctrl by one frame."""
        direction = 1 if event.angleDelta().y() > 0 else -1
        if not event.angleDelta().y():
            return
        modifier = event.modifiers()
        unit = 1 if modifier & Qt.ControlModifier else (10000 if modifier & Qt.ShiftModifier else 1000)
        self.wheel_frames.emit(direction * unit)
        event.accept()


class PlaybackControls(QWidget):
    """Transport owning its timers, without nested event-loop decoding.

    Normal playback follows elapsed monotonic time. During annotation it visits
    every frame and slows if decoding cannot keep up, preserving frame labels.
    Manual jumps finish the current annotation before moving the playhead.
    """

    def __init__(self, player, settle_input, parent=None):
        super().__init__(parent)
        self.player = player
        self.settle_input = settle_input
        self._pending = None
        self._seeking = False
        self._in_tick = False
        self._clock = time.monotonic
        self._anchor_time = self._clock()
        self._anchor_frame = 0
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self._tick)
        self.seek_timer = QTimer(self)
        self.seek_timer.setSingleShot(True)
        self.seek_timer.setInterval(40)
        self.seek_timer.timeout.connect(self._flush_seek)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 6)
        layout.setSpacing(4)
        self.slider = SeekSlider(Qt.Horizontal)
        self.slider.setAccessibleName('Video position')
        self.slider.setToolTip('Click or drag to seek. Wheel: 1 second; Shift+wheel: 10 seconds; Ctrl+wheel: 1 frame.')
        self.slider.seek_started.connect(self._begin_seek)
        self.slider.seek_finished.connect(self._finish_seek)
        self.slider.valueChanged.connect(self._queue_seek)
        self.slider.wheel_frames.connect(self._wheel_seek)
        layout.addWidget(self.slider)
        row = QHBoxLayout()
        row.setSpacing(5)
        layout.addLayout(row)
        self._button(row, QStyle.SP_MediaSkipBackward, 'First frame', lambda: self.seek(0))
        self._button(row, None, 'Back 5 seconds', lambda: self.step(-round(self.fps * 5)), '-5 s')
        self._button(row, QStyle.SP_MediaSeekBackward, 'Previous frame', lambda: self.step(-1))
        self.play_button = self._button(row, QStyle.SP_MediaPlay, 'Play / pause (Space)', self.toggle)
        self._button(row, QStyle.SP_MediaSeekForward, 'Next frame', lambda: self.step(1))
        self._button(row, None, 'Forward 5 seconds', lambda: self.step(round(self.fps * 5)), '+5 s')
        self._button(row, QStyle.SP_MediaSkipForward, 'Last frame', lambda: self.seek(player.total_frames - 1))
        self.speed = QComboBox()
        self.speed.setAccessibleName('Playback speed')
        for rate in (.25, .5, 1, 2, 4, 8):
            self.speed.addItem(f'{rate:g}×', rate)
        self.speed.setCurrentIndex(2)
        self.speed.currentIndexChanged.connect(self._rebase)
        self.speed.setToolTip('Playback speed. While labeling, every frame is visited, even if playback must slow down.')
        row.addWidget(self.speed)
        row.addStretch()
        row.addWidget(QLabel('Frame'))
        self.frame = QSpinBox()
        self.frame.setKeyboardTracking(False)
        self.frame.setMinimumWidth(90)
        self.frame.setAccessibleName('Frame number (starts at 1)')
        self.frame.valueChanged.connect(lambda value: self.seek(value - 1))
        row.addWidget(self.frame)
        self.time_label = QLabel()
        row.addWidget(self.time_label)
        self.setStyleSheet('QToolButton {padding: 5px; border-radius: 5px; color: #e4f2f0; background: #263540;} '
                           'QToolButton:hover {background: #365369;} '
                           'QComboBox, QSpinBox {color: #e4f2f0; background: #263540; border: 1px solid #415566; border-radius: 4px; padding: 3px;} '
                           'QSlider::groove:horizontal {height: 5px; background: #344354;} '
                           'QSlider::sub-page:horizontal {background: #63d6c4;} '
                           'QSlider::handle:horizontal {width: 12px; margin: -5px 0; background: #b8f4e9; border-radius: 5px;}')
        player.frame_changed.connect(self.sync_frame)
        player.transport_stopping.connect(self.pause)
        player.video_loaded.connect(self.refresh)
        QApplication.instance().installEventFilter(self)
        self.refresh()

    def _button(self, layout, icon, tip, callback, text=''):
        """Create a compact named control with a platform-rendered icon."""
        button = QToolButton()
        button.setText(text)
        if icon is not None:
            button.setIcon(self._transport_icon(icon))
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        button.setFocusPolicy(Qt.NoFocus)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _transport_icon(self, standard_icon):
        """Tint native glyphs for consistent contrast on the dark video panel."""
        pixmap = self.style().standardIcon(standard_icon).pixmap(18, 18)
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor('#e4f2f0'))
        painter.end()
        return QIcon(pixmap)

    @property
    def fps(self):
        """Use a safe display rate for containers lacking valid FPS metadata."""
        value = float(self.player.frame_rate)
        return value if math.isfinite(value) and value > 0 else 30.0

    def refresh(self):
        """Reset navigation after a successful source or arena load."""
        self.pause()
        self.setEnabled(self.player.total_frames > 0)
        with QSignalBlocker(self.slider), QSignalBlocker(self.frame):
            self.slider.setRange(0, max(0, self.player.total_frames - 1))
            self.frame.setRange(1, max(1, self.player.total_frames))
        self.sync_frame(self.player.current_frame)

    def _rebase(self, *_):
        """Anchor elapsed-time playback to the current exact frame."""
        self._anchor_time = self._clock()
        self._anchor_frame = self.player.current_frame

    def pause(self):
        """Stop playback and discard pending seeks before a session transition."""
        self.timer.stop()
        self.seek_timer.stop()
        self._pending = None
        self._seeking = False
        self.play_button.setIcon(self._transport_icon(QStyle.SP_MediaPlay))

    def toggle(self):
        """Start at the current frame; reaching the end never loops implicitly."""
        if self.timer.isActive():
            self.pause()
        elif self.player.total_frames > 0 and self.player.current_frame < self.player.total_frames - 1:
            self._flush_seek()
            self._rebase()
            self.timer.start()
            self.play_button.setIcon(self._transport_icon(QStyle.SP_MediaPause))
        self.player.setFocus()

    def _tick(self):
        """Advance with catchup only when no annotation input is active."""
        if QApplication.activeModalWidget() is not None:
            self.pause()
            return
        target = self._anchor_frame + int((self._clock() - self._anchor_time) * self.fps * self.speed.currentData())
        if target <= self.player.current_frame:
            return
        labeling = self.player.removing_mode or any(
            any(getattr(self.player, name, {}).values()) for name in
            ('active_labels', 'label_key_held', 'range_labeling_active', 'is_toggled_active'))
        if labeling:
            target = self.player.current_frame + 1
        target = min(target, self.player.total_frames - 1)
        self._in_tick = True
        try:
            self.player.goto_frame(target)
        finally:
            self._in_tick = False
        if labeling:
            self._rebase()
        if target >= self.player.total_frames - 1:
            self.pause()

    def _begin_seek(self):
        """Finish annotation before any whole-video navigation."""
        self.pause()
        self.settle_input()
        self._seeking = True

    def _queue_seek(self, target):
        """Coalesce rapid slider events to at most one decode per 40 ms."""
        if not self._seeking:
            self.pause()
            self.settle_input()
        self._pending = target
        if not self.seek_timer.isActive():
            self.seek_timer.start()

    def _flush_seek(self):
        """Decode the latest queued target without processing nested events."""
        self.seek_timer.stop()
        target, self._pending = self._pending, None
        if target is not None and self.player.total_frames:
            self.player.goto_frame(target)

    def _finish_seek(self):
        """Show the final frame before returning keyboard focus to the video."""
        self._flush_seek()
        self._seeking = False
        self.sync_frame(self.player.current_frame)
        self.player.setFocus()

    def seek(self, frame):
        """Perform an explicit clamped frame jump after settling input."""
        if not self.player.total_frames:
            return
        self._begin_seek()
        self._pending = max(0, min(int(frame), self.player.total_frames - 1))
        self._finish_seek()

    def step(self, frames):
        """Move by a signed number of frames."""
        self.seek(self.player.current_frame + frames)

    def _wheel_seek(self, units):
        """Translate the slider's wheel modifier into time or frame units."""
        self.step(units if abs(units) == 1 else round(units / 1000 * self.fps))

    def sync_frame(self, frame):
        """Synchronize external keyboard/gamepad navigation without seek loops."""
        if self.timer.isActive() and not self._in_tick:
            self._rebase()
        if not self._seeking and self._pending is None:
            with QSignalBlocker(self.slider):
                self.slider.setValue(frame)
        with QSignalBlocker(self.frame):
            self.frame.setValue(frame + 1)
        def stamp(value):
            """Display hours and milliseconds without losing long-video time."""
            milliseconds = round(value * 1000 / self.fps)
            seconds, ms = divmod(milliseconds, 1000)
            minutes, seconds = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            return f'{hours:02}:{minutes:02}:{seconds:02}.{ms:03}'
        self.time_label.setText(f'{stamp(frame)} / {stamp(max(0, self.player.total_frames - 1))}')

    def eventFilter(self, watched, event):
        """Pause on dialogs and competing navigation; Space controls playback."""
        if event.type() == QEvent.Show and isinstance(watched, QDialog):
            self.pause()
        elif watched is self.player and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Space:
                if not event.isAutoRepeat():
                    self.toggle()
                return True
            if event.key() in (Qt.Key_Left, Qt.Key_Right):
                self.pause()
        return super().eventFilter(watched, event)
