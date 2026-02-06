import cv2
import numpy as np
import warnings
# Suppress pkg_resources deprecation warning from pygame
warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")
import pygame
from pygame.locals import K_ESCAPE
from PySide6.QtWidgets import QLabel, QProgressBar, QWidget, QHBoxLayout
from PySide6.QtCore import Qt, QTimer, Signal, QThread, QCoreApplication
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QColor
import threading
from collections import OrderedDict
import time
from annotator_libs.annotation_logic import update_annotations_on_frame_change # Import the function


class FrameCache:
    """LRU cache for video frames to improve performance"""

    def __init__(self, max_size=500):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.lock = threading.Lock()

    def get(self, frame_number):
        """Get frame from cache"""
        with self.lock:
            if frame_number in self.cache:
                # Move to end (most recently used)
                self.cache.move_to_end(frame_number)
                return self.cache[frame_number]
        return None

    def put(self, frame_number, frame_data):
        """Put frame in cache"""
        with self.lock:
            if frame_number in self.cache:
                # Update existing
                self.cache.move_to_end(frame_number)
                self.cache[frame_number] = frame_data
            else:
                # Add new
                self.cache[frame_number] = frame_data
                if len(self.cache) > self.max_size:
                    # Remove least recently used
                    self.cache.popitem(last=False)

    def clear(self):
        """Clear all cached frames"""
        with self.lock:
            self.cache.clear()

    def preload_frames(self, video_capture, start_frame, num_frames, callback=None):
        """Preload frames in background"""
        def preload_worker():
            for i in range(num_frames):
                frame_num = start_frame + i
                if frame_num >= 0 and frame_num < int(video_capture.get(cv2.CAP_PROP_FRAME_COUNT)):
                    # Check if already cached
                    if self.get(frame_num) is None:
                        # Read and cache frame
                        video_capture.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                        ret, frame = video_capture.read()
                        if ret:
                            # Convert BGR to RGB
                            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                            # Convert to QImage
                            h, w, ch = frame_rgb.shape
                            bytes_per_line = ch * w
                            q_img = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
                            # Store as QPixmap for faster display
                            pixmap = QPixmap.fromImage(q_img)
                            self.put(frame_num, pixmap)
                            if callback:
                                callback(frame_num)
        thread = threading.Thread(target=preload_worker, daemon=True)
        thread.start()


class FramePreloader(QThread):
    """Background thread for preloading frames"""

    frame_loaded = Signal(int, int, int)  # Signal emitted when a frame is loaded (current, total, total_frames_to_preload)
    preload_finished = Signal() # Signal emitted when preloading is complete

    def __init__(self, video_capture, cache, start_frame, num_frames_to_preload, total_frames_in_video, lock):
        super().__init__()
        self.video_capture = video_capture
        self.cache = cache
        self.start_frame = start_frame
        self.num_frames_to_preload = num_frames_to_preload
        self.total_frames_in_video = total_frames_in_video
        self.lock = lock
        self._is_running = True # Flag to control thread execution

    def stop(self):
        self._is_running = False

    def run(self):
        """Preload frames in background thread"""
        preloaded_count = 0
        for i in range(self.num_frames_to_preload):
            if not self._is_running:
                break
            frame_num = self.start_frame + i
            if frame_num >= 0 and frame_num < self.total_frames_in_video:
                # Check if already cached
                if self.cache.get(frame_num) is None:
                    # Read and cache frame
                    with self.lock:
                        self.video_capture.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                        ret, frame = self.video_capture.read()
                    if ret:
                        # Convert BGR to RGB
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        # Convert to QImage
                        h, w, ch = frame_rgb.shape
                        bytes_per_line = ch * w
                        q_img = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
                        # Store as QPixmap for faster display
                        pixmap = QPixmap.fromImage(q_img)
                        self.cache.put(frame_num, pixmap)
                        preloaded_count += 1
                        self.frame_loaded.emit(preloaded_count, self.num_frames_to_preload, self.total_frames_in_video)
        self.preload_finished.emit() # Emit when preloading is done


class VideoPlayer(QLabel):
    """Widget to display video frames and handle navigation"""

    frame_changed = Signal(int)
    label_toggled = Signal(str, bool, int, int)  # behavior, is_active, start_frame, end_frame
    current_behavior_changed = Signal(str)
    remove_labels = Signal()
    check_label_removal = Signal(int)  # target_frame
    about_to_change_annotations = Signal() # Signal to push undo state
    undo_requested = Signal() # Signal to request undo
    caching_complete = Signal() # New signal to indicate caching is complete
    preload_progress = Signal(int, int) # current_preloaded, total_to_preload
    preload_finished = Signal() # Signal emitted when all preloading is complete

    def __init__(self, timeline=None):
        super().__init__()
        self.program_start_time = None  # Will be set by main application
        self.timeline = timeline  # Reference to the TimelineWidget
        self.video_capture = None
        self.current_frame = 0
        self.total_frames = 0
        self.frame_rate = 0
        self.video_path = ""
        self.active_labels = {}  # behavior -> is_active
        self.labeling_mode = False  # This will be managed by the new logic
        self.current_label_behavior = None # This will be managed by the new logic
        self.key_press_start_time = {}  # behavior -> press start time
        self.is_toggled_active = {}  # behavior -> True if in toggle mode and currently active
        self.is_stopping_toggle = {} # behavior -> True if the current press is meant to stop a toggle
        self.removing_mode = False  # True if Escape is held to remove labels continuously
        self.label_key_held = {}  # behavior -> True if key is currently held down
        self.held_behavior = None  # Current behavior being held in hold mode
        self.current_behavior = None  # Current annotated behavior for display
        self.hold_timers = {}  # behavior -> QTimer for detecting long presses in 'both' mode
        self.clear_timers = {}  # behavior -> QTimer for delayed clearing in 'hold' mode

        # Navigation state
        self.navigation_timer = QTimer()
        self.navigation_timer.timeout.connect(self.on_navigation_timer)
        self.navigation_direction = 0  # -1 for left, 1 for right, 0 for stopped
        self.navigation_speed = 1  # frames per timer tick
        self.navigation_delay_timer = QTimer()  # Timer to delay continuous navigation
        self.navigation_delay_timer.timeout.connect(self.start_continuous_navigation)
        self.navigation_delay_timer.setSingleShot(True)
        self.current_jump_size = 1  # Current jump size for navigation
        self.last_direction_change_time = 0  # Track when direction last changed
        self.last_navigation_direction = 0  # Track the last non-zero direction for optimization
        self.navigation_start_time = None # Track start time for navigation timing
        self.left_key_held = False # Track if left arrow key is held
        self.right_key_held = False # Track if right arrow key is held

        # Gamepad state
        self.joystick = None
        self.right_stick_x_axis = -1
        self.right_stick_y_axis = -1
        self.gamepad_frame_speed = 5.0 # Frames to jump per stick movement unit (now can be fractional)
        self.gamepad_threshold = 0.1 # Minimum stick movement to register
        self.gamepad_frame_accumulator = 0.5 # Accumulator for sub-frame movements
        self._qt_escape_held = False # Track Escape key state from Qt events
        self._pygame_escape_held = False # Track Escape key state from Pygame events
        self.fast_mode_active = False # Flag for fast forward mode

        # Input settings (will be updated from main application)
        self.frame_step_size = 1
        self.shift_skip = 10
        self.hold_time = 500
        self.deadzone = 10  # percentage
        self.joystick_sensitivity = 5
        self.frame_skip = 1
        self.button_a_behavior = "None"
        self.button_b_behavior = "None"
        self.button_x_behavior = "None"
        self.button_y_behavior = "None"
        self.controller_mappings = {} # New attribute for automapped controller buttons
        self.gamepad_button_states = {} # To track button press/release for automapping
        self.label_key_mode = 'both'  # Default both modes
        self.show_overlay_bars = False # New attribute to control overlay bar visibility

        # Range-based labeling state
        self.range_labeling_active = {}  # behavior -> True if currently in range labeling mode
        self.range_labeling_start = {}  # behavior -> start frame for range labeling
        # self.range_labeling_preview = {}  # Removed, now handled by TimelineWidget directly

        # Range labeling settings
        self.include_last_frame_in_range = False  # Default to not include last frame

        # Display scaling state
        self.target_width = 640
        self.target_height = 480

        # Frame caching and preloading
        self.frame_cache = FrameCache(max_size=500)
        self.preloader = None
        self.preload_timer = QTimer()
        self.preload_timer.timeout.connect(self.start_preloading)
        self.preload_range = 200  # Preload frames ahead and behind
        self.is_caching_finished = False # Flag to track caching status
        self.total_frames_to_preload = 0 # Total frames expected to be preloaded in current cycle
        self.current_preloaded_count = 0 # Count of frames preloaded in current cycle
        self._undo_pushed_for_current_action = False # Flag to avoid redundant undo pushes during continuous actions

        # Thread safety for video_capture
        self.video_capture_lock = threading.Lock()

        self.setup_ui()

    def setup_ui(self):
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(640, 480)
        self.setStyleSheet("border: 2px solid gray; background-color: black; color: white;")
        self.setText("No video loaded")

        # Set focus policy to ensure keyboard events are received
        self.setFocusPolicy(Qt.StrongFocus)

        # Annotation overlay container
        self.annotation_overlay = QWidget(self)
        self.annotation_overlay.setStyleSheet("background-color: rgba(0, 0, 0, 150); border-radius: 5px;")
        self.annotation_overlay.move(10, 10)
        self.annotation_overlay.setVisible(False)

        # Layout for overlay
        overlay_layout = QHBoxLayout(self.annotation_overlay)
        overlay_layout.setContentsMargins(5, 5, 5, 5)
        overlay_layout.setSpacing(3)

        # Preview bars
        self.prev_bar = QLabel()
        self.prev_bar.setFixedWidth(8)
        self.prev_bar.setFixedHeight(32)
        self.prev_bar.setVisible(False)
        overlay_layout.addWidget(self.prev_bar)

        # Behavior label
        self.behavior_label = QLabel()
        self.behavior_label.setStyleSheet("color: white; font-weight: bold;")
        overlay_layout.addWidget(self.behavior_label)

        self.next_bar = QLabel()
        self.next_bar.setFixedWidth(8)
        self.next_bar.setFixedHeight(32)
        self.next_bar.setVisible(False)
        overlay_layout.addWidget(self.next_bar)

        # Progress bar at bottom
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #555;
                border-radius: 5px;
                text-align: center;
                background-color: rgba(0, 0, 0, 100);
                color: white;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2196F3, stop:1 #e6a5ff);
                border-radius: 3px;
            }
        """)
        self.progress_bar.setVisible(False)
        self.progress_bar.setFormat("%v / %m")

        # Initialize gamepad
        self.init_gamepad()

    def init_gamepad(self):
        """Initialize pygame and joystick"""
        pygame.init()
        pygame.joystick.init()
        if pygame.joystick.get_count() > 0:
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()
            # Based on debug output, Axis 0 is right stick X, Axis 1 is right stick Y
            self.right_stick_x_axis = 0
            self.right_stick_y_axis = 1 # Assuming Axis 1 is Y for the right stick
        else:
            print("No gamepad detected.")

    def update_input_settings(self, settings):
        """Update input settings from main application"""
        self.frame_step_size = settings.get('frame_step', 1)
        self.shift_skip = settings.get('shift_skip', 10)
        self.hold_time = settings.get('hold_time', 500)
        self.deadzone = settings.get('deadzone', 10)
        self.joystick_sensitivity = settings.get('joystick_sensitivity', 5)
        self.frame_skip = settings.get('frame_skip', 1)
        self.fast_forward_multiplier = settings.get('fast_forward_multiplier', 10)
        self.joystick_mode = settings.get('joystick_mode', 'quadratic')
        self.button_a_behavior = settings.get('button_a', "None")
        self.button_b_behavior = settings.get('button_b', "None")
        self.button_x_behavior = settings.get('button_x', "None")
        self.button_y_behavior = settings.get('button_y', "None")
        self.controller_mappings = settings.get('controller_automappings', {}) # Load automappings

        # Update gamepad settings
        self.gamepad_threshold = self.deadzone / 100.0  # Convert percentage to decimal
        self.gamepad_frame_speed = self.joystick_sensitivity / 2.0  # Scale sensitivity to frame speed

    def update_label_key_mode(self, mode):
        """Update label key mode setting"""
        self.label_key_mode = mode

    def set_show_overlay_bars(self, enabled):
        """Enable or disable the display of overlay preview bars"""
        self.show_overlay_bars = enabled
        self.update_frame_display() # Redraw to apply changes

    def set_include_last_frame_in_range(self, enabled):
        """Set whether to include the last selected frame in range labeling"""
        self.include_last_frame_in_range = enabled

    def load_video(self, video_path):
        """Load a video file"""
        # Stop any existing preloader gracefully before releasing video capture
        if self.preloader and self.preloader.isRunning():
            self.preloader.stop()
            self.preloader.wait()

        if self.video_capture:
            with self.video_capture_lock:
                self.video_capture.release()

        with self.video_capture_lock:
            self.video_capture = cv2.VideoCapture(video_path)
        if not self.video_capture.isOpened():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", f"Could not open video: {video_path}")
            return False

        self.video_path = video_path
        self.total_frames = int(self.video_capture.get(cv2.CAP_PROP_FRAME_COUNT))
        self.frame_rate = self.video_capture.get(cv2.CAP_PROP_FPS)
        self.current_frame = 0
        self.active_labels = {}  # Reset active labels
        self.held_behavior = None  # Reset held behavior
        self.current_behavior = None  # Reset current behavior

        # Clear frame cache for new video
        self.frame_cache.clear()
        self.is_caching_finished = False # Reset caching status for new video

        # Setup progress bar
        self.progress_bar.setMaximum(self.total_frames - 1)
        self.progress_bar.setVisible(True) # Make progress bar visible
        self.progress_bar.setValue(self.current_frame) # Set initial value

        # Position the progress bar
        self.resizeEvent(None)

        self.update_frame_display()

        # Set target dimensions to current label size for stable scaling
        self.target_width = self.width()
        self.target_height = self.height()

        # Start preloading frames around current position
        self.start_preloading()

        # Set focus to enable keyboard navigation
        self.setFocus()
        return True

    def update_frame_display(self):
        """Update the displayed frame with labels"""
        if not self.video_capture or not self.video_capture.isOpened():
            return

        # Try to get frame from cache first
        cached_pixmap = self.frame_cache.get(self.current_frame)

        if cached_pixmap is None:
            # Frame not in cache, read from disk
            with self.video_capture_lock:
                self.video_capture.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
                ret, frame = self.video_capture.read()

            if not ret:
                return

            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Convert to QImage
            h, w, ch = frame_rgb.shape
            bytes_per_line = ch * w
            q_img = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)

            # Create base pixmap
            pixmap = QPixmap.fromImage(q_img)

            # Cache the base pixmap (without labels)
            self.frame_cache.put(self.current_frame, pixmap.copy())
        else:
            # Use cached frame
            pixmap = cached_pixmap.copy()
            # Get dimensions from cached pixmap
            w, h = pixmap.width(), pixmap.height()

        # Emit frame changed before drawing to update current_behavior
        self.frame_changed.emit(self.current_frame)

        # Update annotation overlay
        label_text = ""
        label_color = "white" # Default color for the pipe symbol or no label

        # Get colors for adjacent frames
        prev_color, next_color = self.update_overlay_preview_bars()

        # Determine if the current frame has an actual label
        has_actual_label = isinstance(self.current_behavior, list) and len(self.current_behavior) > 0

        if has_actual_label:
            # Join behaviors if multiple
            label_text = ", ".join(self.current_behavior)
            # Set color based on first behavior
            first_behavior = self.current_behavior[0]
            label_color = self.get_behavior_color(first_behavior)
            self.behavior_label.setStyleSheet(f"color: {label_color}; font-weight: bold;")
            self.behavior_label.setText(label_text)
            self.annotation_overlay.setVisible(True)
        elif self.show_overlay_bars and (prev_color is not None or next_color is not None):
            # Current frame is empty, but adjacent frames have labels, and bars are enabled
            label_text = "|"
            label_color = "white" # Neutral color for the pipe symbol
            self.behavior_label.setStyleSheet(f"color: {label_color}; font-weight: bold;")
            self.behavior_label.setText(label_text)
            self.annotation_overlay.setVisible(True)
        else:
            self.behavior_label.setText("")
            self.annotation_overlay.setVisible(False)

        # Adjust size to fit content
        self.annotation_overlay.adjustSize()

        # Set stylesheet for the overlay (with or without border)
        if self.show_overlay_bars and self.annotation_overlay.isVisible():
            self.annotation_overlay.setStyleSheet("background-color: rgba(0, 0, 0, 150); border: none; border-radius: 5px;")
        else:
            self.annotation_overlay.setStyleSheet("background-color: rgba(0, 0, 0, 150); border: none; border-radius: 5px;")

        # Store the original pixmap for resizing
        self.original_pixmap = pixmap

        # Scale image to fit label while maintaining aspect ratio
        self.scale_and_set_pixmap()

        # Update frame info - need to add a label for this
        # self.frame_info_label.setText(f"Frame: {self.current_frame + 1}/{self.total_frames}")

        # Start preloading after displaying current frame, only if not already finished
        if not self.is_caching_finished:
            # Update timeline with range preview for all active behaviors
            active_range_behaviors = [b for b, active in self.range_labeling_active.items() if active]
            if self.timeline:
                if active_range_behaviors:
                    for behavior in active_range_behaviors:
                        start_frame = self.range_labeling_start.get(behavior, self.current_frame)
                        self.timeline.set_range_preview(behavior, start_frame, self.current_frame)
                else:
                    # Clear any lingering preview if no range labeling is active
                    self.timeline.clear_range_preview()

            self.preload_timer.start(100)  # Start preloading after 100ms delay
    def start_preloading(self):
        """Start preloading frames around current position"""
        if not self.video_capture or not self.video_capture.isOpened():
            return

        # Stop any existing preloader gracefully
        if self.preloader and self.preloader.isRunning():
            self.preloader.stop()
            self.preloader.wait()

        # Calculate preload range around current frame
        start_frame = max(0, self.current_frame - self.preload_range)
        end_frame = min(self.total_frames, self.current_frame + self.preload_range + 1)
        self.total_frames_to_preload = end_frame - start_frame
        self.current_preloaded_count = 0

        # Start new preloader
        self.preloader = FramePreloader(self.video_capture, self.frame_cache, start_frame,
                                         self.total_frames_to_preload, self.total_frames, self.video_capture_lock)
        self.preloader.frame_loaded.connect(self.on_frame_preloaded)
        self.preloader.preload_finished.connect(self._on_preload_finished) # Connect preload_finished signal
        self.preloader.start()

    def on_frame_preloaded(self, current_preloaded, total_to_preload, total_frames_in_video):
        """Handle when a frame has been preloaded"""
        self.current_preloaded_count = current_preloaded
        self.preload_progress.emit(self.current_preloaded_count, total_to_preload)

    def _on_preload_finished(self):
        """Handle when preloading is complete"""

        self.is_caching_finished = True
        self.caching_complete.emit()
        self.preload_finished.emit() # Emit the new signal
        self.preload_timer.stop() # Stop the timer to prevent further preloading

    def scale_and_set_pixmap(self):
        """Scale the original pixmap to fit the label while maintaining aspect ratio"""
        if hasattr(self, 'original_pixmap') and self.original_pixmap:
            scaled_pixmap = self.original_pixmap.scaled(
                self.target_width, self.target_height,
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.setPixmap(scaled_pixmap)
            self.update()  # Force repaint

    def resizeEvent(self, event):
        """Handle widget resize to rescale the video frame"""
        super().resizeEvent(event)
        # Update target dimensions when widget is resized
        self.target_width = self.width()
        self.target_height = self.height()
        self.scale_and_set_pixmap()

        # Reposition widgets
        if hasattr(self, 'progress_bar') and self.progress_bar.isVisible():
            progress_height = 25
            self.progress_bar.setGeometry(10, self.height() - progress_height - 10,
                                        self.width() - 20, progress_height)

    def update_overlay_preview_bars(self):
        """Update preview bars in the annotation overlay and return their colors"""
        prev_color = None
        next_color = None

        if not self.show_overlay_bars or not hasattr(self, 'annotations'):
            self.prev_bar.setVisible(False)
            self.next_bar.setVisible(False)
            return None, None

        # Check previous frame
        prev_frame = self.current_frame - 1
        if prev_frame >= 0:
            prev_behavior = self.annotations.get(prev_frame)
            if prev_behavior:
                # If prev_behavior is a list, take the first one for color
                color_key = prev_behavior[0] if isinstance(prev_behavior, list) else prev_behavior
                prev_color = self.get_behavior_color(color_key)

        # Check next frame
        next_frame = self.current_frame + 1
        if next_frame < self.total_frames:
            next_behavior = self.annotations.get(next_frame)
            if next_behavior:
                # If next_behavior is a list, take the first one for color
                color_key = next_behavior[0] if isinstance(next_behavior, list) else next_behavior
                next_color = self.get_behavior_color(color_key)

        # Update bar visibility and colors
        if prev_color:
            self.prev_bar.setStyleSheet(f"background-color: {prev_color}; border: 1px solid black;")
            self.prev_bar.setVisible(True)
        else:
            self.prev_bar.setVisible(False)

        if next_color:
            self.next_bar.setStyleSheet(f"background-color: {next_color}; border: 1px solid black;")
            self.next_bar.setVisible(True)
        else:
            self.next_bar.setVisible(False)
        
        return prev_color, next_color

    def is_any_behavior_actively_labeled(self):
        """Check if any behavior is currently active or being range-labeled."""
        is_active_toggle = any(self.active_labels.values())
        is_active_range_labeling = any(self.range_labeling_active.values())
        return is_active_toggle or is_active_range_labeling

    def get_behavior_color(self, behavior):
        """Get color for behavior (placeholder - will be connected to BehaviorButtons)"""
        colors = {
            "nose-to-nose": "#FF6B6B",
            "nose-to-body": "#A7DB50",
            "anogenital": "#45B7D1",
            "passive": "#BD23FF",
            "rearing": "#FFEAA7",
            "fighting": "#00FFC8",
            "mounting": "FF8C00"
        }
        return colors.get(behavior, "#CCCCCC")

    def goto_frame(self, frame_number):
        """Go to specific frame"""
        old_frame = self.current_frame
        
        if frame_number < 0:
            frame_number = 0
        elif frame_number >= self.total_frames:
            frame_number = self.total_frames - 1

        # If in removing mode, ensure all intermediate frames are cleared during "leaps" (like timeline dragging)
        if self.removing_mode and old_frame != frame_number:
            if not self._undo_pushed_for_current_action:
                self.about_to_change_annotations.emit()
                self._undo_pushed_for_current_action = True
            start_f = min(old_frame, frame_number)
            end_f = max(old_frame, frame_number)
            for f in range(start_f, end_f + 1):
                if f in self.annotations:
                    del self.annotations[f]

        self.current_frame = frame_number

        # Update progress bar only if no behavior is actively labeled
        if not self.is_any_behavior_actively_labeled():
            self.progress_bar.setValue(self.current_frame)

        # Update current_behavior for the new frame BEFORE updating display
        active_behaviors_list = update_annotations_on_frame_change(
            self.annotations, self.current_frame, self, self.available_behaviors
        )
        self.current_behavior = active_behaviors_list

        # Update timeline with range preview for all active behaviors
        active_range_behaviors = [b for b, active in self.range_labeling_active.items() if active]
        if self.timeline:
            if active_range_behaviors:
                for behavior in active_range_behaviors:
                    start_frame = self.range_labeling_start.get(behavior, self.current_frame)
                    self.timeline.set_range_preview(behavior, start_frame, self.current_frame)
            else:
                # Clear any lingering preview if no range labeling is active
                self.timeline.clear_range_preview()

        self.update_frame_display()

    def next_frame(self, step=1):
        """Go to next frame(s)"""
        target_frame = self.current_frame + step
        self.goto_frame(target_frame)

    def prev_frame(self, step=1):
        """Go to previous frame(s)"""
        target_frame = self.current_frame - step
        if target_frame >= 0:
            # Check if any behavior is active or held (which might cause label removal)
            has_active = any(self.active_labels.values()) or any(self.label_key_held.values())
            if has_active and not self._undo_pushed_for_current_action:
                self.about_to_change_annotations.emit()
                self._undo_pushed_for_current_action = True
            
            self.check_label_removal.emit(target_frame)
            self.goto_frame(target_frame)

    def toggle_label(self, behavior):
        """Toggle a label on/off"""
        self.about_to_change_annotations.emit()
        if behavior in self.active_labels:
            self.active_labels[behavior] = not self.active_labels[behavior]
        else:
            self.active_labels[behavior] = True

        # For simple toggle, start_frame and end_frame are the current_frame
        self.label_toggled.emit(behavior, self.active_labels[behavior], self.current_frame, self.current_frame)
        self.update_frame_display()

    def set_labeling_mode(self, behavior, active):
        """Set labeling mode for continuous labeling"""
        self.current_label_behavior = behavior
        self.labeling_mode = active

        # Update the active label state for the current behavior
        if active:
            self.active_labels[behavior] = True
        else:
            self.active_labels[behavior] = False

        self.update_frame_display()

    def on_navigation_timer(self):
        """Handle continuous navigation when arrow keys are held"""
        # Check if frame-by-frame navigation is needed (hold label)
        needs_frame_by_frame = hasattr(self, 'held_behavior') and self.held_behavior is not None

        if self.navigation_direction == 1:  # Right arrow
            if needs_frame_by_frame:
                self.next_frame(1)  # Move frame-by-frame when held behavior is active
            else:
                self.next_frame(self.navigation_speed)
        elif self.navigation_direction == -1:  # Left arrow
            if needs_frame_by_frame:
                self.prev_frame(1)  # Move frame-by-frame when held behavior is active
            else:
                self.prev_frame(self.navigation_speed)

    def start_continuous_navigation(self):
        """Start continuous navigation after delay"""
        current_time = time.time()
        self.navigation_timer.start(50)  # Faster continuous navigation (20 FPS)

    def keyPressEvent(self, event):
        """Handle keyboard navigation and labeling"""
        current_time = time.time()

        if event.key() == Qt.Key_Right:
            self.right_key_held = True # Mark right key as held
            # Determine jump size based on Shift modifier
            if event.modifiers() & Qt.ShiftModifier:
                jump_size = self.shift_skip
                self.navigation_speed = self.shift_skip
            else:
                jump_size = self.frame_step_size
                self.navigation_speed = self.frame_step_size
            # Handle initial press or direction change
            if self.navigation_direction != 1: # Only set if direction is changing or starting
                old_direction = self.last_navigation_direction
                self.navigation_direction = 1
                self.last_navigation_direction = 1
                self.last_direction_change_time = current_time
                self.navigation_start_time = current_time # Record start time for timing
                # Use hold detection time for delay before continuous navigation
                delay = self.hold_time
                self.navigation_delay_timer.start(delay)  # Delay before continuous navigation

            self.next_frame(jump_size)
        elif event.key() == Qt.Key_Left:
            self.left_key_held = True # Mark left key as held
            # Determine jump size based on Shift modifier
            if event.modifiers() & Qt.ShiftModifier:
                jump_size = self.shift_skip
                self.navigation_speed = self.shift_skip
            else:
                jump_size = self.frame_step_size
                self.navigation_speed = self.frame_step_size
            # Handle initial press or direction change
            if self.navigation_direction != -1: # Only set if direction is changing or starting
                old_direction = self.last_navigation_direction
                self.navigation_direction = -1
                self.last_navigation_direction = -1
                self.last_direction_change_time = current_time
                self.navigation_start_time = current_time # Record start time for timing
                # Use hold detection time for delay before continuous navigation
                delay = self.hold_time
                self.navigation_delay_timer.start(delay)  # Delay before continuous navigation

            self.prev_frame(jump_size)
        elif event.key() == Qt.Key_Escape:
            self.removing_mode = True
            self._qt_escape_held = True
            self.about_to_change_annotations.emit()
            self.remove_labels.emit() # Emit signal to remove labels

        elif event.key() == Qt.Key_Space:
            # Toggle play/pause if done one day
            pass
        elif event.key() in range(Qt.Key_1, Qt.Key_9 + 1):
            # Ignore auto-repeat for number keys to prevent flickering, except in hold and toggle modes
            if event.isAutoRepeat() and self.label_key_mode not in ['hold', 'toggle']:
                return
            # Number keys for label toggling
            behavior_index = event.key() - Qt.Key_1
            if hasattr(self, 'available_behaviors') and behavior_index < len(self.available_behaviors):
                behavior = self.available_behaviors[behavior_index]
                # Only start labeling if not already active (prevent auto-repeat from starting new ranges)
                if not self.label_key_held.get(behavior, False):
                    self._handle_label_input(behavior, True, 'keyboard')
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        """Handle key release for continuous labeling and navigation"""
        if event.key() == Qt.Key_Right:
            self.right_key_held = False # Mark right key as released
            if self.left_key_held: # If left key is still held, switch to left navigation
                self.navigation_direction = -1
                self.navigation_delay_timer.start(0) # Start continuous navigation immediately

            else: # No arrow keys held
                self.navigation_timer.stop()
                self.navigation_delay_timer.stop()
                self.navigation_direction = 0
                self.navigation_speed = 1  # Reset to default
                self._undo_pushed_for_current_action = False # Reset undo flag
        elif event.key() == Qt.Key_Left:
            self.left_key_held = False # Mark left key as released
            if self.right_key_held: # If right key is still held, switch to right navigation
                self.navigation_direction = 1
                self.navigation_delay_timer.start(0) # Start continuous navigation immediately

            else: # No arrow keys held
                self.navigation_timer.stop()
                self.navigation_delay_timer.stop()
                self.navigation_direction = 0
                self.navigation_speed = 1  # Reset to default
                self._undo_pushed_for_current_action = False # Reset undo flag
        elif event.key() in range(Qt.Key_1, Qt.Key_9 + 1):
            if event.isAutoRepeat(): # Ignore auto-repeated key releases
                return
            behavior_index = event.key() - Qt.Key_1
            if hasattr(self, 'available_behaviors') and behavior_index < len(self.available_behaviors):
                behavior = self.available_behaviors[behavior_index]
                self._handle_label_input(behavior, False, 'keyboard')
                self._undo_pushed_for_current_action = False # Reset flag on release
        elif event.key() == Qt.Key_Escape:
            self.removing_mode = False
            self._qt_escape_held = False
            self._undo_pushed_for_current_action = False

        super().keyReleaseEvent(event)

    def process_gamepad_input(self):
        """Process gamepad input for frame navigation and button mappings"""
        if not self.joystick:
            return

        current_time = time.time() # Define current_time for latency tracking
        pygame.event.pump() # Process pygame events

        # Check Escape key state using Pygame's direct polling
        keys = pygame.key.get_pressed()
        if keys[K_ESCAPE]:
            if not self._pygame_escape_held: # Only trigger on initial press
                self.removing_mode = True
                self._pygame_escape_held = True
                self.about_to_change_annotations.emit()
                self.remove_labels.emit() # Emit signal to remove labels instantly

        else:
            if self._pygame_escape_held: # Only trigger on release
                self.removing_mode = False
                self._pygame_escape_held = False
                self._undo_pushed_for_current_action = False

        # Process button mappings (both hardcoded and automapped)
        self._process_gamepad_buttons()
        self._process_automapped_buttons()

        # Right stick X-axis for frame navigation
        if self.right_stick_x_axis != -1 and self.joystick:
            try:
                axis_x_value = self.joystick.get_axis(self.right_stick_x_axis)
            except pygame.error:
                # Joystick not initialized, reinitialize
                self.init_gamepad()
                return

            if abs(axis_x_value) > self.gamepad_threshold:
                # Normalize axis value from threshold to 1.0
                normalized_axis = abs(axis_x_value)
                # Apply scaling based on joystick mode
                if self.joystick_mode == 'quadratic':
                    # Quadratic scaling: small movements = slow, large movements = fast
                    speed_factor = normalized_axis ** 2
                else:  # linear mode
                    # Linear scaling: direct proportional response
                    speed_factor = normalized_axis
                # Calculate raw frame change with max speed based on sensitivity
                frame_change = speed_factor * self.gamepad_frame_speed
                # Apply fast forward multiplier if active
                if self.fast_mode_active:
                    frame_change *= self.fast_forward_multiplier
                # Apply direction
                frame_change *= 1 if axis_x_value > 0 else -1
                self.gamepad_frame_accumulator += frame_change

                # Determine integer step and direction
                step = int(self.gamepad_frame_accumulator)

                if step != 0:
                    # Check if there are active labels for continuous labeling, removing mode, or held behavior
                    active_behaviors = [b for b, active in self.active_labels.items() if active]
                    has_active_labels = len(active_behaviors) > 0
                    has_held_behavior = hasattr(self, 'held_behavior') and self.held_behavior is not None
                    needs_frame_by_frame = has_active_labels or self.removing_mode or has_held_behavior

                    if step > 0: # Move forward
                        if needs_frame_by_frame:
                            # When labeling or removing is active, move frame by frame to ensure continuous operation
                            for _ in range(step):
                                self.next_frame(1)
                        else:
                            self.next_frame(step)
                    else: # Move backward
                        if needs_frame_by_frame:
                            # When labeling or removing is active, move frame by frame
                            for _ in range(abs(step)):
                                self.prev_frame(1)
                        else:
                            self.prev_frame(abs(step))
                    self.gamepad_frame_accumulator -= step # Subtract the integer part
            else:
                # If stick is within threshold, slowly decay the accumulator to prevent drift
                self._undo_pushed_for_current_action = False
                if abs(self.gamepad_frame_accumulator) < 0.1: # If very small, reset
                    self.gamepad_frame_accumulator = 0.0
                else: # Decay
                    self.gamepad_frame_accumulator *= 0.9 # Decay factor to prevent minor drift

        # Right stick Y-axis for frame navigation (if needed, currently not requested)
        # if self.right_stick_y_axis != -1:
        #     axis_y_value = self.joystick.get_axis(self.right_stick_y_axis)
        #     if abs(axis_y_value) > self.gamepad_threshold:
        #         # Implement Y-axis movement if desired
        #         pass

    def _on_long_press(self, behavior):
        """Handle long press detection for 'both' mode"""
        if self.label_key_mode == 'both' and self.label_key_held.get(behavior, False):
            self.held_behavior = behavior
            # Start range labeling for long press
            if not self.range_labeling_active.get(behavior, False):
                self.range_labeling_active[behavior] = True
                self.range_labeling_start[behavior] = self.current_frame
                # Emit signal for the start of the label (long press)
                if not self._undo_pushed_for_current_action:
                    self.about_to_change_annotations.emit()
                    self._undo_pushed_for_current_action = True
                self.label_toggled.emit(behavior, True, self.current_frame, self.current_frame) # Emit once for start with current_frame as start/end
            # Update timeline with range preview
            if self.timeline:
                self.timeline.set_range_preview(behavior, self.current_frame, self.current_frame)

    def _clear_hold_labels(self, behavior):
        """Clear held behavior and active labels for hold mode after delay"""
        self.held_behavior = None
        self.active_labels[behavior] = False
        # The label_toggled.emit(behavior, False, start_frame, end_frame) is already handled in _handle_label_input
        # when the key is released, so no need to emit again here.
        self.update_frame_display()
        # Clean up timer
        if behavior in self.clear_timers:
            del self.clear_timers[behavior]

    def _process_gamepad_buttons(self):
        """Process hardcoded gamepad button mappings for behaviors (A, B, X, Y)"""
        if not self.joystick:
            return

        # Hardcoded button mappings (assuming standard Xbox controller layout)
        hardcoded_button_mappings = {
            0: self.button_a_behavior,  # A button
            1: self.button_b_behavior,  # B button
            2: self.button_x_behavior,  # X button
            3: self.button_y_behavior,  # Y button
        }

        for button_id, behavior in hardcoded_button_mappings.items():
            if behavior != "None" and hasattr(self, 'available_behaviors') and behavior in self.available_behaviors:
                try:
                    is_pressed = self.joystick.get_button(button_id)
                    button_name = f"Button {button_id}" # Use generic name for state tracking

                    if is_pressed and not self.gamepad_button_states.get(button_name, False):
                        # Button was just pressed - start range labeling
                        self._handle_label_input(behavior, True, 'controller')
                        self.gamepad_button_states[button_name] = True
                    elif not is_pressed and self.gamepad_button_states.get(button_name, False):
                        # Button was just released - complete range labeling
                        self._handle_label_input(behavior, False, 'controller')
                        self.gamepad_button_states[button_name] = False
                        self._undo_pushed_for_current_action = False
                except pygame.error:
                    # Joystick not initialized, break to avoid repeated errors
                    break

    def _process_automapped_buttons(self):
        """Process automapped gamepad button mappings for behaviors and actions"""
        if not self.joystick or not self.controller_mappings:
            return

        for button_str, behavior in self.controller_mappings.items():
            if behavior == "None":
                continue

            is_pressed = False
            try:
                if button_str.startswith("Button "):
                    button_id = int(button_str.split(" ")[1])
                    if button_id < self.joystick.get_numbuttons():
                        is_pressed = self.joystick.get_button(button_id)
                elif button_str.startswith("Hat "):
                    parts = button_str.split(" ")
                    hat_id = int(parts[1])
                    hat_direction_str = parts[2]
                    if hat_id < self.joystick.get_numhats():
                        hat_x, hat_y = self.joystick.get_hat(hat_id)
                        if hat_direction_str == "Right": is_pressed = (hat_x == 1)
                        elif hat_direction_str == "Left": is_pressed = (hat_x == -1)
                        elif hat_direction_str == "Up": is_pressed = (hat_y == 1)
                        elif hat_direction_str == "Down": is_pressed = (hat_y == -1)
                elif button_str.startswith("Axis "):
                    parts = button_str.split(" ")
                    axis_id = int(parts[1])
                    axis_direction_str = parts[2]
                    if axis_id < self.joystick.get_numaxes():
                        axis_value = self.joystick.get_axis(axis_id)
                        if axis_direction_str == "Positive": is_pressed = (axis_value > 0.9) # Use threshold
                        elif axis_direction_str == "Negative": is_pressed = (axis_value < -0.9) # Use threshold
            except (ValueError, IndexError, pygame.error) as e:
                print(f"Error processing automapped button '{button_str}': {e}")
                continue

            if is_pressed and not self.gamepad_button_states.get(button_str, False):
                # Button was just pressed
                if hasattr(self, 'available_behaviors') and behavior in self.available_behaviors:
                    self._handle_label_input(behavior, True, 'controller')
                elif behavior == "fast_forward":
                    self.fast_mode_active = True
                elif behavior == "fast_backward":
                    self.fast_mode_active = True
                elif behavior == "erase":
                    self.removing_mode = True
                    self.remove_labels.emit()
                elif behavior == "undo":
                    self.undo_requested.emit()
                self.gamepad_button_states[button_str] = True
            elif not is_pressed and self.gamepad_button_states.get(button_str, False):
                # Button was just released
                if hasattr(self, 'available_behaviors') and behavior in self.available_behaviors:
                    self._handle_label_input(behavior, False, 'controller')
                elif behavior in ["fast_forward", "fast_backward"]:
                    self.fast_mode_active = False
                elif behavior == "erase":
                    self.removing_mode = False
                self.gamepad_button_states[button_str] = False
                self._undo_pushed_for_current_action = False

    def _handle_label_input(self, behavior, is_pressed, input_type):
        """
        Handle label input based on the current label key mode:
        - toggle: Press to toggle label on current frame
        - hold: Press and hold to label range from press to release
        - both: Short press to toggle, long press to label range
        """
        from annotator_libs.annotation_logic import apply_range_label

        if is_pressed:
            self.label_key_held[behavior] = True

            if self.label_key_mode == 'toggle':
                # Toggle mode: press once to start range, press again to end range
                if not self.range_labeling_active.get(behavior, False):
                    # First press: start range labeling
                    self.range_labeling_active[behavior] = True
                    self.range_labeling_start[behavior] = self.current_frame
                    # Emit signal for the start of the label
                    if not self._undo_pushed_for_current_action:
                        self.about_to_change_annotations.emit()
                        self._undo_pushed_for_current_action = True
                    self.label_toggled.emit(behavior, True, self.current_frame, self.current_frame) # Emit once for start with current_frame as start/end
                else:
                    # Second press: end range labeling
                    start_frame = self.range_labeling_start[behavior]
                    end_frame = self.current_frame

                    # Apply the range label to actual annotations (CSV)
                    from annotator_libs.annotation_logic import apply_range_label
                    apply_range_label(self.annotations, behavior, start_frame, end_frame, self.available_behaviors, 
                                      self.include_last_frame_in_range, self.multitrack_enabled)

                    # Emit signal for the end of the label
                    self.label_toggled.emit(behavior, False, start_frame, end_frame) # Emit once for end with actual range

                    # Clean up
                    del self.range_labeling_active[behavior]
                    del self.range_labeling_start[behavior]

                    # Clear timeline range preview
                    if self.timeline:
                        self.timeline.clear_range_preview(behavior)

            elif self.label_key_mode == 'hold':
                # Hold mode: start range labeling
                if not self.range_labeling_active.get(behavior, False):
                    self.range_labeling_active[behavior] = True
                    self.range_labeling_start[behavior] = self.current_frame
                    # Emit signal for the start of the label
                    if not self._undo_pushed_for_current_action:
                        self.about_to_change_annotations.emit()
                        self._undo_pushed_for_current_action = True
                    self.label_toggled.emit(behavior, True, self.current_frame, self.current_frame) # Emit once for start with current_frame as start/end
                # Update timeline with range preview
                if self.timeline:
                    self.timeline.set_range_preview(behavior, self.current_frame, self.current_frame)

            elif self.label_key_mode == 'both':
                # Both mode: start timer to detect short vs long press
                self.key_press_start_time[behavior] = time.time()
                # Start a timer for long press detection
                if behavior not in self.hold_timers:
                    self.hold_timers[behavior] = QTimer(self)
                    self.hold_timers[behavior].setSingleShot(True)
                    self.hold_timers[behavior].timeout.connect(lambda: self._on_long_press(behavior))
                self.hold_timers[behavior].start(self.hold_time)

        else:  # is_released
            self.label_key_held[behavior] = False

            if self.label_key_mode == 'toggle':
                # Toggle mode: do nothing on release
                pass

            elif self.label_key_mode == 'hold':
                # Hold mode: apply range labeling
                if self.range_labeling_active.get(behavior, False):
                    start_frame = self.range_labeling_start[behavior]
                    end_frame = self.current_frame

                    # Apply the range label to actual annotations (CSV)
                    apply_range_label(self.annotations, behavior, start_frame, end_frame, self.available_behaviors, 
                                      self.include_last_frame_in_range, self.multitrack_enabled)

                    # Emit signal for the end of the label
                    self.label_toggled.emit(behavior, False, start_frame, end_frame) # Emit once for end with actual range

                    # Clean up
                    del self.range_labeling_active[behavior]
                    del self.range_labeling_start[behavior]

                    # Clear timeline range preview
                    if self.timeline:
                        self.timeline.clear_range_preview(behavior)

                    # Start timer to clear held behavior after delay
                    if behavior not in self.clear_timers:
                        self.clear_timers[behavior] = QTimer(self)
                        self.clear_timers[behavior].setSingleShot(True)
                        self.clear_timers[behavior].timeout.connect(lambda: self._clear_hold_labels(behavior))
                    self.clear_timers[behavior].start(100)  # Short delay

            elif self.label_key_mode == 'both':
                # Both mode: check if it was a short or long press
                if behavior in self.hold_timers and self.hold_timers[behavior].isActive():
                    # Timer still active = short press. This should behave like 'toggle' mode.
                    self.hold_timers[behavior].stop()
                    if not self.range_labeling_active.get(behavior, False):
                        # First short press: start range labeling
                        self.range_labeling_active[behavior] = True
                        self.range_labeling_start[behavior] = self.current_frame
                        # Update timeline with range preview
                        if self.timeline:
                            self.timeline.set_range_preview(behavior, self.current_frame, self.current_frame)
                        
                        if not self._undo_pushed_for_current_action:
                            self.about_to_change_annotations.emit()
                            self._undo_pushed_for_current_action = True
                        # Emit signal for the start of the label
                        self.label_toggled.emit(behavior, True, self.current_frame, self.current_frame) # Emit once for start with current_frame as start/end
                    else:
                        # Second short press: end range labeling
                        start_frame = self.range_labeling_start[behavior]
                        end_frame = self.current_frame

                        # Apply the range label to actual annotations (CSV)
                        apply_range_label(self.annotations, behavior, start_frame, end_frame, self.available_behaviors, 
                                          self.include_last_frame_in_range, self.multitrack_enabled)

                        # Emit signal for the end of the label
                        self.label_toggled.emit(behavior, False, start_frame, end_frame) # Emit once for end with actual range

                        # Clean up
                        del self.range_labeling_active[behavior]
                        del self.range_labeling_start[behavior]

                        # Clear timeline range preview
                        if self.timeline:
                            self.timeline.clear_range_preview(behavior)
                else:
                    # Timer expired = long press = apply range labeling
                    if self.range_labeling_active.get(behavior, False):
                        start_frame = self.range_labeling_start[behavior]
                        end_frame = self.current_frame

                        # Apply the range label to actual annotations (CSV)
                        apply_range_label(self.annotations, behavior, start_frame, end_frame, self.available_behaviors, 
                                          self.include_last_frame_in_range, self.multitrack_enabled)

                        # Emit signal for the end of the label
                        self.label_toggled.emit(behavior, False, start_frame, end_frame) # Emit once for end with actual range

                        # Clean up
                        del self.range_labeling_active[behavior]
                        del self.range_labeling_start[behavior]

                        # Clear timeline range preview
                        if self.timeline:
                            self.timeline.clear_range_preview(behavior)

                        # Start timer to clear held behavior after delay
                        if behavior not in self.clear_timers:
                            self.clear_timers[behavior] = QTimer(self)
                            self.clear_timers[behavior].setSingleShot(True)
                            self.clear_timers[behavior].timeout.connect(lambda: self._clear_hold_labels(behavior))
                        self.clear_timers[behavior].start(100)  # Short delay

                # Clean up timer
                if behavior in self.hold_timers:
                    self.hold_timers[behavior].deleteLater()
                    del self.hold_timers[behavior]

            # Clean up press start time
            if behavior in self.key_press_start_time:
                del self.key_press_start_time[behavior]

        # Update UI to show current state (including preview if active)
        self.update_frame_display()

    def _start_timeline_drag(self, start_frame):
        """Handle the start of timeline dragging for range labeling"""
        # Check if any label keys are currently held
        active_behaviors = [b for b, held in self.label_key_held.items() if held]
        if active_behaviors:
            # Use the first active behavior for range labeling
            behavior = active_behaviors[0]
            # Only start range labeling if not already active (prevent overwriting existing start frame)
            if not self.range_labeling_active.get(behavior, False):
                self.range_labeling_active[behavior] = True
                self.range_labeling_start[behavior] = start_frame
                # Set timeline range preview
                if self.timeline:
                    self.timeline.set_range_preview(behavior, start_frame, self.current_frame)

    def _end_timeline_drag(self, end_frame=None):
        """Handle the end of timeline dragging for range labeling"""
        from annotator_libs.annotation_logic import apply_range_label
        # Use self.current_frame as the end_frame for applying the label.
        actual_end_frame = self.current_frame

        # Apply range labels for any active range labeling
        for behavior, is_active in self.range_labeling_active.items():
            if is_active:
                start_frame = self.range_labeling_start[behavior]

                # Apply the range label to actual annotations (CSV)
                apply_range_label(self.annotations, behavior, start_frame, actual_end_frame, self.available_behaviors, 
                                  self.include_last_frame_in_range, self.multitrack_enabled)

                # Clean up range labeling state
                del self.range_labeling_active[behavior]
                del self.range_labeling_start[behavior]

                # Clear timeline range preview
                if self.timeline:
                    self.timeline.clear_range_preview(behavior)

                # Only handle one behavior at a time
                break

        # Update UI
        self.update_frame_display()
