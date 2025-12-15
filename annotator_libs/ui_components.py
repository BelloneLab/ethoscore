from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                              QScrollArea, QGridLayout, QInputDialog, QMessageBox, QGroupBox)
from PySide6.QtCore import Qt, Signal, QSize, QPropertyAnimation, QEasingCurve, QRect, QTimer
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QPaintEvent, QPixmap, QImage, QTransform
import os


class BehaviorButtonWidget(QWidget):
    """Widget containing a behavior button with preview bars"""

    clicked = Signal()

    def __init__(self, text, behavior, parent=None):
        super().__init__(parent)
        self.behavior = behavior
        self.parent_widget = parent
        self.show_bars = False
        self.prev_color = None
        self.next_color = None

        # Create layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Create button
        self.button = QPushButton(text)
        from PySide6.QtWidgets import QSizePolicy
        self.button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.button.clicked.connect(self.clicked.emit)
        layout.addWidget(self.button)

    def set_button_style(self, style_sheet):
        """Set the button style"""
        self.button.setStyleSheet(style_sheet)


class BehaviorButtons(QWidget):
    """Widget containing behavior selection buttons"""

    behavior_toggled = Signal(str)
    behavior_added = Signal(str)
    behavior_removed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.behaviors = []
        self.buttons = []
        self.behavior_colors = {
            "nose-to-nose": "#FF6B6B",  # Red
            "nose-to-body": "#A7DB50",  # Lime
            "anogenital": "#45B7D1",    # Blue
            "passive": "#BD23FF",       # Violet
            "rearing": "#ECFF1C",       # Yellow
            "fighting": "#00FFC8",     # Turquoise
            "mounting": "#FF8C00"      # Orange
        }
        self.current_frame = 0
        self.annotations = {}
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # Labels group box
        labels_group = QGroupBox("Labels")
        labels_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        labels_layout = QVBoxLayout(labels_group)
        labels_layout.setContentsMargins(5, 5, 5, 5)
        labels_layout.setSpacing(5)

        # Scroll area for behaviors
        self.scroll_area = QScrollArea()
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: 1px solid #cccccc;
                border-radius: 3px;
                background-color: #fafafa;
            }
        """)
        scroll_widget = QWidget()
        self.grid_layout = QGridLayout(scroll_widget)
        self.grid_layout.setContentsMargins(5, 5, 5, 5)
        self.grid_layout.setSpacing(5)
        self.scroll_area.setWidget(scroll_widget)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(150)
        labels_layout.addWidget(self.scroll_area)

        layout.addWidget(labels_group)

        # Add/Remove buttons in a separate group
        management_group = QGroupBox("Manage Labels")
        management_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        management_layout = QHBoxLayout(management_group)
        management_layout.setContentsMargins(5, 5, 5, 5)
        management_layout.setSpacing(10)

        self.add_btn = QPushButton("Add Label")
        self.add_btn.setStyleSheet("""
            QPushButton {
                padding: 8px 16px;
                font-weight: bold;
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3e8e41;
            }
        """)
        self.add_btn.clicked.connect(self.add_behavior)

        self.remove_btn = QPushButton("Remove Label")
        self.remove_btn.setStyleSheet("""
            QPushButton {
                padding: 8px 16px;
                font-weight: bold;
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
            QPushButton:pressed {
                background-color: #b71c1c;
            }
        """)
        self.remove_btn.clicked.connect(self.remove_behavior)

        management_layout.addWidget(self.add_btn)
        management_layout.addWidget(self.remove_btn)

        layout.addWidget(management_group)

    def load_behaviors(self, behaviors):
        """Load behaviors from list"""
        self.behaviors = behaviors
        self.layout_buttons()

    def layout_buttons(self):
        """Layout the behavior buttons based on available width"""
        self.buttons = []

        # Clear existing widgets safely
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item and item.widget():
                item.widget().setParent(None)

        if not self.behaviors:
            return

        # Calculate number of columns based on available width
        available_width = self.scroll_area.viewport().width() - 20
        if available_width <= 0:
            available_width = 300

        # Estimate button width
        estimated_btn_width = 120
        num_columns = max(1, available_width // estimated_btn_width)

        # Add buttons to grid
        for i, behavior in enumerate(self.behaviors):
            row = i // num_columns
            col = i % num_columns
            btn_widget = BehaviorButtonWidget(f"{i+1}. {behavior}", behavior, self)

            # Set button color based on behavior
            color = self.behavior_colors.get(behavior, "#CCCCCC")
            button_style = f"""
                QPushButton {{
                    background-color: {color};
                    border: 2px solid {self.darken_color(color)};
                    padding: 8px;
                    font-weight: bold;
                }}
                QPushButton:checked {{
                    background-color: {self.darken_color(color)};
                    border: 3px solid #000000;
                }}
                QPushButton:hover {{
                    background-color: {self.lighten_color(color)};
                }}
            """
            btn_widget.set_button_style(button_style)

            btn_widget.clicked.connect(lambda b=behavior: self.toggle_behavior(b))
            self.grid_layout.addWidget(btn_widget, row, col)
            self.buttons.append(btn_widget)

        # Set column stretches for equal sizing
        for col in range(num_columns):
            self.grid_layout.setColumnStretch(col, 1)

    def resizeEvent(self, event):
        """Handle resize to re-layout buttons with delay"""
        super().resizeEvent(event)
        if hasattr(self, '_resize_timer') and self._resize_timer.isActive():
            self._resize_timer.stop()
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self.layout_buttons)
        self._resize_timer.start(100)  # 100ms delay

    def darken_color(self, color):
        """Darken a hex color"""
        r = max(0, int(color[1:3], 16) - 40)
        g = max(0, int(color[3:5], 16) - 40)
        b = max(0, int(color[5:7], 16) - 40)
        return f"#{r:02x}{g:02x}{b:02x}"

    def lighten_color(self, color):
        """Lighten a hex color"""
        r = min(255, int(color[1:3], 16) + 40)
        g = min(255, int(color[3:5], 16) + 40)
        b = min(255, int(color[5:7], 16) + 40)
        return f"#{r:02x}{g:02x}{b:02x}"

    def toggle_behavior(self, behavior):
        """Toggle a behavior label"""
        self.behavior_toggled.emit(behavior)

    def get_selected_label(self):
        """Get currently selected behavior"""
        for btn in self.buttons:
            if btn.button.isChecked():
                return btn.button.text().split(". ")[1]
        return None

    def get_behavior_color(self, behavior):
        """Get color for a specific behavior"""
        return self.behavior_colors.get(behavior, "#CCCCCC")

    def add_behavior(self):
        """Add a new behavior"""
        name, ok = QInputDialog.getText(self, "Add Label", "Enter label name:")
        if ok and name.strip():
            name = name.strip()
            if name in self.behaviors:
                QMessageBox.warning(self, "Error", "Label already exists")
                return
            # Assign a random color
            import random
            color = f"#{random.randint(0, 255):02x}{random.randint(0, 255):02x}{random.randint(0, 255):02x}"
            self.behavior_colors[name] = color
            self.behaviors.append(name)
            self.load_behaviors(self.behaviors)
            self.behavior_added.emit(name)

    def remove_behavior(self):
        """Remove a behavior - show list to choose from"""
        if not self.behaviors:
            QMessageBox.warning(self, "Error", "No label to remove")
            return

        # Use combo box for ergonomic selection
        selected_label, ok = QInputDialog.getItem(
            self,
            "Remove Label",
            "Select label to remove:",
            self.behaviors,
            0,  # default
            False  # not editable
        )

        if not ok:
            return

        if QMessageBox.question(self, "Confirm", f"Remove label '{selected_label}'? This will delete all instances of this label for this video") == QMessageBox.Yes:
            self.behaviors.remove(selected_label)
            if selected_label in self.behavior_colors:
                del self.behavior_colors[selected_label]
            self.load_behaviors(self.behaviors)
            self.behavior_removed.emit(selected_label)



class TimelineWidget(QWidget):
    """Widget showing video timeline with zoom and click functionality"""

    frame_clicked = Signal(int)
    drag_started = Signal(int)
    drag_ended = Signal(int)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(60)
        self.setMaximumHeight(80)
        self.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
        self.setMouseTracking(True)

        # Timeline state
        self.current_frame = 0
        self.total_frames = 0
        self.zoom_level = 5.0  # pixels per frame (more zoomed in by default)
        self.scroll_offset = 0  # horizontal scroll position in frames
        self.annotations = {}  # frame -> behavior
        self.behavior_colors = {}  # behavior -> color

        # Set minimum zoom to show all frames, maximum zoom to show 1 frame per pixel
        self.min_zoom = 0.01
        self.max_zoom = 10.0

        # Drag state
        self.is_dragging = False
        self.last_mouse_x = 0
        self.drag_timer = QTimer(self)
        self.drag_timer.setSingleShot(True)
        self.drag_timer.timeout.connect(self.emit_pending_frame_change)
        self.pending_frame = None

        # Range labeling preview state
        self.preview_behavior = None
        self.preview_start_frame = -1
        self.preview_end_frame = -1 # Current_frame during drag

    def set_annotations(self, annotations, behavior_colors):
        """Set annotations and behavior colors for display"""
        self.annotations = annotations
        self.behavior_colors = behavior_colors
        self.update()

    def set_range_preview(self, behavior, start_frame, current_frame):
        """Set the range labeling preview for display"""
        self.preview_behavior = behavior
        self.preview_start_frame = start_frame
        self.preview_end_frame = current_frame
        self.update()

    def clear_range_preview(self):
        """Clear the range labeling preview"""
        self.preview_behavior = None
        self.preview_start_frame = -1
        self.preview_end_frame = -1
        self.update()

    def wheelEvent(self, event):
        """Handle mouse wheel for zooming"""
        if self.total_frames == 0:
            return

        # Get mouse position relative to timeline
        mouse_x = event.position().x()
        frame_at_mouse = self.x_to_frame(mouse_x)

        # Calculate zoom factor
        zoom_factor = 1.1 if event.angleDelta().y() > 0 else 0.9
        new_zoom = self.zoom_level * zoom_factor

        # Clamp zoom level
        new_zoom = max(self.min_zoom, min(self.max_zoom, new_zoom))

        if abs(new_zoom - self.zoom_level) > 0.001:
            # Adjust scroll offset to keep frame at mouse position
            self.zoom_level = new_zoom
            self.scroll_offset = frame_at_mouse - (mouse_x / self.get_pixels_per_frame())

            # Ensure scroll offset stays within bounds
            self.clamp_scroll_offset()
            self.update()

    def mousePressEvent(self, event):
        """Handle mouse press to start dragging"""
        if event.button() == Qt.LeftButton and self.total_frames > 0:
            self.is_dragging = True
            self.last_mouse_x = event.position().x()
            self.drag_start_frame = self.current_frame  # Store frame where dragging started

            # Emit signal for drag start
            self.drag_started.emit(self.drag_start_frame)

    def mouseMoveEvent(self, event):
        """Handle mouse movement during dragging"""
        if self.is_dragging and self.total_frames > 0:
            # Calculate mouse movement delta from drag start
            mouse_delta = event.position().x() - self.last_mouse_x

            # Convert mouse movement to frame movement
            # Use zoom level as sensitivity - more zoomed in = finer control
            # Reverse direction: moving mouse right = go backward in timeline
            frame_delta = -mouse_delta / self.get_pixels_per_frame()
            frame = int(self.drag_start_frame + frame_delta)
            frame = max(0, min(self.total_frames - 1, frame))

            # Update timeline marker position immediately for visual feedback
            self.current_frame = frame
            self.update()

            # Throttle frame changes to prevent excessive updates
            self.pending_frame = frame
            if not self.drag_timer.isActive():
                self.drag_timer.start(16)  # ~60 FPS throttling

    def mouseReleaseEvent(self, event):
        """Handle mouse release to stop dragging"""
        if event.button() == Qt.LeftButton:
            self.is_dragging = False

            # Calculate the final frame where mouse was released
            final_frame = self.x_to_frame(event.position().x())
            final_frame = max(0, min(self.total_frames - 1, final_frame))

            # Emit any pending frame change
            if self.pending_frame is not None:
                self.frame_clicked.emit(self.pending_frame)
                self.pending_frame = None

            # Emit signal for drag end with final frame
            self.drag_ended.emit(final_frame)

    def emit_pending_frame_change(self):
        """Emit the pending frame change from throttled dragging"""
        if self.pending_frame is not None and self.is_dragging:
            # Check if VideoPlayer has active range labeling - if so, don't emit frame changes
            # as they will interfere with range labeling
            if hasattr(self.parent(), 'video_player'):
                video_player = self.parent().video_player
                # Check if any range labeling is active
                has_active_range_labeling = any(video_player.range_labeling_active.values())
                if not has_active_range_labeling:
                    self.frame_clicked.emit(self.pending_frame)
            else:
                self.frame_clicked.emit(self.pending_frame)
            self.pending_frame = None

    def x_to_frame(self, x):
        """Convert x coordinate to frame number"""
        return int(self.scroll_offset + (x / self.get_pixels_per_frame()))

    def frame_to_x(self, frame):
        """Convert frame number to x coordinate"""
        return (frame - self.scroll_offset) * self.get_pixels_per_frame()

    def get_pixels_per_frame(self):
        """Get pixels per frame based on zoom level"""
        return self.zoom_level

    def clamp_scroll_offset(self):
        """Ensure scroll offset keeps timeline visible"""
        if self.total_frames == 0:
            return

        max_offset = max(0, self.total_frames - (self.width() / self.get_pixels_per_frame()))
        self.scroll_offset = max(0, min(max_offset, self.scroll_offset))

    def ensure_marker_visible(self):
        """Adjust scroll offset to keep current frame marker centered in view"""
        if self.total_frames == 0:
            return

        # Calculate scroll offset to center the current frame
        pixels_per_frame = self.get_pixels_per_frame()
        center_x = self.width() / 2
        self.scroll_offset = self.current_frame - (center_x / pixels_per_frame)

        # Clamp to valid range
        self.clamp_scroll_offset()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw timeline background
        painter.fillRect(self.rect(), QColor(240, 240, 240))

        if self.total_frames == 0:
            return

        width = self.width()
        height = self.height()

        # Draw behavior segments
        self.draw_behavior_segments(painter, width, height)

        # Draw range labeling preview if active
        self.draw_range_preview(painter, width, height)

        # Draw timeline axis
        painter.setPen(QPen(Qt.black, 1))
        painter.drawLine(0, height // 2, width, height // 2)

        # Draw frame markers
        self.draw_frame_markers(painter, width, height)

        # Draw current frame indicator
        if self.current_frame >= 0:
            x_pos = self.frame_to_x(self.current_frame)
            if 0 <= x_pos <= width:
                painter.setPen(QPen(Qt.red, 3))
                painter.drawLine(int(x_pos), 0, int(x_pos), height)

    def draw_behavior_segments(self, painter, width, height):
        """Draw colored segments for behavior annotations"""
        if not self.annotations:
            return

        # Group consecutive frames with same behavior
        segments = []
        current_behavior = None
        start_frame = 0

        for frame in range(self.total_frames):
            behavior = self.annotations.get(frame)

            if behavior != current_behavior:
                if current_behavior is not None:
                    segments.append((start_frame, frame - 1, current_behavior))
                current_behavior = behavior
                start_frame = frame

        # Add final segment
        if current_behavior is not None:
            segments.append((start_frame, self.total_frames - 1, current_behavior))

        # Draw segments
        for start, end, behavior in segments:
            color = self.behavior_colors.get(behavior, "#CCCCCC")
            q_color = QColor(color)

            start_x = self.frame_to_x(start)
            end_x = self.frame_to_x(end + 1)  # +1 to include the end frame

            if end_x > 0 and start_x < width:
                # Clip to visible area
                visible_start = max(0, start_x)
                visible_end = min(width, end_x)

                if visible_start < visible_end:
                    rect = painter.boundingRect(int(visible_start), 5, int(visible_end - visible_start), height - 10,
                                              Qt.AlignCenter, behavior[:3])  # Show first 3 chars

                    painter.fillRect(int(visible_start), 5, int(visible_end - visible_start), height - 10,
                                   QColor(q_color.red(), q_color.green(), q_color.blue(), 150))

                    # Draw behavior label if segment is wide enough
                    if visible_end - visible_start > 50:
                        painter.setPen(QPen(Qt.black, 1))
                        painter.drawText(rect, Qt.AlignCenter, behavior[:3])

    def draw_range_preview(self, painter, width, height):
        """Draw a temporary colored segment for range labeling preview"""
        if self.preview_behavior and self.preview_start_frame != -1 and self.preview_end_frame != -1:
            color = self.behavior_colors.get(self.preview_behavior, "#CCCCCC")
            q_color = QColor(color)

            start = min(self.preview_start_frame, self.preview_end_frame)
            end = max(self.preview_start_frame, self.preview_end_frame)

            start_x = self.frame_to_x(start)
            end_x = self.frame_to_x(end + 1) # +1 to include the end frame

            if end_x > 0 and start_x < width:
                visible_start = max(0, start_x)
                visible_end = min(width, end_x)

                if visible_start < visible_end:
                    # Draw with a lighter, more transparent color for preview
                    painter.fillRect(int(visible_start), 5, int(visible_end - visible_start), height - 10,
                                   QColor(q_color.red(), q_color.green(), q_color.blue(), 80)) # More transparent

                    # Draw a dashed border
                    painter.setPen(QPen(QColor(q_color.red(), q_color.green(), q_color.blue(), 200), 2, Qt.DashLine))
                    painter.drawRect(int(visible_start), 5, int(visible_end - visible_start), height - 10)

    def draw_frame_markers(self, painter, width, height):
        """Draw frame number markers"""
        pixels_per_frame = self.get_pixels_per_frame()

        # Determine marker spacing based on zoom level
        if pixels_per_frame > 50:  # High zoom, show every frame
            marker_interval = 1
        elif pixels_per_frame > 10:  # Medium zoom, show every 10 frames
            marker_interval = 10
        elif pixels_per_frame > 2:  # Low zoom, show every 100 frames
            marker_interval = 100
        else:  # Very low zoom, show every 1000 frames
            marker_interval = 1000

        painter.setPen(QPen(Qt.gray, 1))

        start_frame = max(0, int(self.scroll_offset))
        end_frame = min(self.total_frames, int(self.scroll_offset + width / pixels_per_frame) + 1)

        for frame in range(start_frame, end_frame, marker_interval):
            x_pos = self.frame_to_x(frame)
            if 0 <= x_pos <= width:
                painter.drawLine(int(x_pos), height // 2 - 5, int(x_pos), height // 2 + 5)
                if pixels_per_frame > 20:  # Only show text if there's space
                    painter.drawText(int(x_pos) + 2, height // 2 - 8, str(frame))


class LoadingScreen(QWidget):
    """
    A loading screen widget that displays a mouse logo SVG and a loading bar,
    both animating from left to right.
    """
    def __init__(self, parent=None, svg_path="assets/mouse-logo.svg"):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 200);")
        self.setWindowFlags(Qt.FramelessWindowHint)

        self.svg_path = svg_path
        self.mouse_logo = QPixmap()
        self.load_svg()

        self._animation_progress = 0.0 # Private attribute to store the actual progress
        self.loading_text = "Loading video..."

        self.animation = QPropertyAnimation(self, b"animation_progress")
        self.animation.setDuration(1500)
        self.animation.setEasingCurve(QEasingCurve.Linear)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setLoopCount(-1) # Loop indefinitely

        self.animation.start()

    def load_svg(self):
        """Loads the SVG file and converts it to a QPixmap."""
        if os.path.exists(self.svg_path):
            # QPixmap loading svg
            self.mouse_logo.load(self.svg_path)
            # Convert to a white-filled version
            if not self.mouse_logo.isNull():
                image = self.mouse_logo.toImage()
                for x in range(image.width()):
                    for y in range(image.height()):
                        pixel = image.pixelColor(x, y)
                        if pixel.alpha() > 0: # If not transparent
                            image.setPixelColor(x, y, QColor(255, 255, 255, pixel.alpha())) # Set to white
                self.mouse_logo = QPixmap.fromImage(image)
        else:
            print(f"Warning: SVG file not found at {self.svg_path}")

    def set_loading_text(self, text):
        """Sets the text displayed on the loading screen."""
        self.loading_text = text
        self.update()

    def set_animation_progress(self, progress):
        """Setter for animation_progress property."""
        self._animation_progress = progress
        self.update()

    def get_animation_progress(self):
        """Getter for animation_progress property."""
        return self._animation_progress

    # Define animation_progress as a Python property
    animation_progress = property(get_animation_progress, set_animation_progress)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # Draw background
        painter.fillRect(self.rect(), QColor(0, 0, 0, 200)) # Dark semi-transparent background

        width = self.width()
        height = self.height()

        # Calculate SVG size and position
        svg_target_height = min(height * 0.3, 150) # Max 30% of height or 150px
        if not self.mouse_logo.isNull():
            svg_scaled = self.mouse_logo.scaledToHeight(int(svg_target_height), Qt.SmoothTransformation)
            svg_width = svg_scaled.width()
            svg_height = svg_scaled.height()

            # Calculate fill width based on animation progress
            fill_width = svg_width * self.animation_progress

            # Center SVG horizontally
            svg_x = (width - svg_width) // 2
            svg_y = (height // 2) - (svg_height // 2) - 50 # Offset upwards

            # Draw the filled part of the SVG
            painter.setClipRect(svg_x, svg_y, int(fill_width), svg_height)
            painter.drawPixmap(svg_x, svg_y, svg_scaled)
            painter.setClipping(False) # Disable clipping

        # Draw loading bar
        bar_height = 20
        bar_width = width * 0.6
        bar_x = (width - bar_width) // 2
        bar_y = (height // 2) + 50

        # Draw loading bar background
        painter.setPen(QPen(Qt.white, 2))
        painter.drawRect(bar_x, bar_y, bar_width, bar_height)

        # Draw loading bar fill
        fill_bar_width = bar_width * self.animation_progress
        painter.fillRect(bar_x + 2, bar_y + 2, int(fill_bar_width) - 4, bar_height - 4, Qt.white)

        # Draw loading text
        painter.setPen(QPen(Qt.white))
        font = QFont("Arial", 16, QFont.Bold)
        painter.setFont(font)
        text_rect = QRect(0, bar_y + bar_height + 10, width, 30)
        painter.drawText(text_rect, Qt.AlignCenter, self.loading_text)

    def resizeEvent(self, event):
        """Ensures the loading screen covers the parent widget."""
        if self.parentWidget():
            self.setGeometry(self.parentWidget().rect())
        super().resizeEvent(event)
