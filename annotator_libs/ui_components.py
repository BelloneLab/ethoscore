from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                              QScrollArea, QGridLayout, QInputDialog, QMessageBox, QGroupBox)
from PySide6.QtCore import Qt, Signal, QSize, QPropertyAnimation, QEasingCurve, QRect, QTimer
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QPaintEvent, QPixmap, QImage, QTransform
import os
import sys

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def get_friendly_controller_name(button_str):
    """Returns a human-readable name for a controller button string."""
    if not button_str:
        return ""
    
    # Standard Xbox-like mapping (common for many controllers in Pygame/SDL)
    BUTTON_MAP = {
        0: "Button A",
        1: "Button B",
        2: "Button X",
        3: "Button Y",
        4: "LB",
        5: "RB",
        6: "Back",
        7: "Start",
        8: "LSB",
        9: "RSB",
        10: "Guide"
    }

    if button_str.startswith("Button "):
        try:
            button_id = int(button_str.split(" ")[1])
            return BUTTON_MAP.get(button_id, button_str)
        except (ValueError, IndexError):
            return button_str
    
    if button_str.startswith("Axis "):
        try:
            parts = button_str.split(" ")
            axis_id = int(parts[1])
            direction = parts[2]
            
            # Common trigger assignments
            if axis_id == 2:
                if direction == "Positive": return "Left Trigger"
                if direction == "Negative": return "Right Trigger" # Combined axis case
                return "Left Trigger"
            if axis_id == 4: return "Left Trigger"
            if axis_id == 5: return "Right Trigger"
            
            return f"Axis {axis_id} {direction}"
        except (ValueError, IndexError):
            return button_str
            
    if button_str.startswith("Hat "):
        try:
            parts = button_str.split(" ")
            # hat_id = parts[1]
            direction = parts[2]
            return f"D-Pad {direction}"
        except (ValueError, IndexError):
            return button_str

    return button_str


class BehaviorButtonWidget(QWidget):
    """Widget containing a behavior button with mapping display and modern styling"""

    clicked = Signal()

    def __init__(self, text, behavior, parent=None):
        super().__init__(parent)
        self.behavior = behavior
        self.base_text = text
        self.parent_widget = parent
        self.is_active = False

        # Create layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        # Create button-like container
        self.button = QPushButton()
        from PySide6.QtWidgets import QSizePolicy
        self.button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.button.setCheckable(True)
        self.button.clicked.connect(self.clicked.emit)
        
        # Internal layout for labels
        btn_layout = QVBoxLayout(self.button)
        btn_layout.setContentsMargins(8, 6, 8, 6)
        btn_layout.setSpacing(2)
        
        self.name_label = QLabel(text)
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setStyleSheet("""
            font-weight: bold; 
            color: white; 
            background: transparent; 
            border: none; 
            font-size: 13px;
        """)
        # Adding a shadow effect for better readability
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(4)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(1, 1)
        self.name_label.setGraphicsEffect(shadow)
        
        self.mapping_label = QLabel("")
        self.mapping_label.setAlignment(Qt.AlignCenter)
        self.mapping_label.setStyleSheet("font-size: 10px; font-weight: bold; color: rgba(255, 255, 255, 0.9); background: rgba(0, 0, 0, 0.2); border-radius: 3px; padding: 1px 4px; border: none;")
        self.mapping_label.setVisible(False)
        
        btn_layout.addWidget(self.name_label)
        btn_layout.addWidget(self.mapping_label)
        
        layout.addWidget(self.button)
        self.setMinimumHeight(65)
        self.setMaximumHeight(80)

    def set_mapping_text(self, mapping_text):
        """Update the mapping label"""
        if mapping_text:
            friendly_name = get_friendly_controller_name(mapping_text)
            self.mapping_label.setText(friendly_name.upper())
            self.mapping_label.setVisible(True)
        else:
            self.mapping_label.setVisible(False)

    def set_button_style(self, style_sheet):
        """Set the button style"""
        self.button.setStyleSheet(style_sheet)


class BehaviorButtons(QWidget):
    """Widget containing behavior selection buttons with modern dark theme"""

    behavior_toggled = Signal(str)
    behavior_added = Signal(str)
    behavior_removed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.behaviors = []
        self.buttons = []
        self.behavior_colors = {
            "nose-to-nose": "#E74C3C",  # Soft Red
            "nose-to-body": "#2ECC71",  # Soft Green
            "anogenital": "#3498DB",    # Soft Blue
            "passive": "#9B59B6",       # Soft Purple
            "rearing": "#F1C40F",       # Soft Yellow
            "fighting": "#1ABC9C",      # Soft Turquoise
            "mounting": "#E67E22"       # Soft Orange
        }
        self.current_frame = 0
        self.annotations = {}
        self.controller_mappings = {} # Store mappings for persistence during re-layouts
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # Labels group box
        labels_group = QGroupBox("LABELS")
        labels_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 11px;
                letter-spacing: 1px;
                border: 1px solid #3d3d3d;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 15px;
                color: #888888;
                background-color: #252525;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 5px 0 5px;
            }
        """)
        labels_layout = QVBoxLayout(labels_group)
        labels_layout.setContentsMargins(8, 8, 8, 8)
        labels_layout.setSpacing(8)

        # Scroll area for behaviors
        self.scroll_area = QScrollArea()
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: #252525;
                width: 10px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #3d3d3d;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #4d4d4d;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background-color: transparent;")
        self.button_layout = QVBoxLayout(scroll_widget)
        self.button_layout.setContentsMargins(0, 0, 0, 0)
        self.button_layout.setSpacing(8)
        self.button_layout.addStretch() # Add stretch at the end
        self.scroll_area.setWidget(scroll_widget)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(200)
        labels_layout.addWidget(self.scroll_area)

        layout.addWidget(labels_group)

        # Add/Remove buttons in a separate group
        management_group = QGroupBox("MANAGEMENT")
        management_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 11px;
                letter-spacing: 1px;
                border: 1px solid #3d3d3d;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 15px;
                color: #888888;
                background-color: #252525;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 5px 0 5px;
            }
        """)
        management_layout = QHBoxLayout(management_group)
        management_layout.setContentsMargins(10, 10, 10, 10)
        management_layout.setSpacing(8)

        self.add_btn = QPushButton("Add Label")
        self.add_btn.setStyleSheet("""
            QPushButton {
                padding: 8px;
                font-weight: bold;
                background-color: #2ecc71;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #27ae60;
            }
            QPushButton:pressed {
                background-color: #1e8449;
            }
        """)
        self.add_btn.clicked.connect(self.add_behavior)

        self.remove_btn = QPushButton("Remove Label")
        self.remove_btn.setStyleSheet("""
            QPushButton {
                padding: 8px;
                font-weight: bold;
                background-color: #e74c3c;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            QPushButton:pressed {
                background-color: #922b21;
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
        """Layout the behavior buttons in a single column"""
        self.buttons = []

        # Clear existing widgets safely (excluding the stretch)
        while self.button_layout.count() > 1:
            item = self.button_layout.takeAt(0)
            if item and item.widget():
                item.widget().setParent(None)

        if not self.behaviors:
            return

        # Add buttons to layout
        for i, behavior in enumerate(self.behaviors):
            btn_widget = BehaviorButtonWidget(f"{i+1}. {behavior}", behavior, self)

            # Set button color based on behavior
            color = self.behavior_colors.get(behavior, "#555555")
            dark_color = self.darken_color(color)
            light_color = self.lighten_color(color)
            
            button_style = f"""
                QPushButton {{
                    background-color: {color};
                    border: 1px solid {dark_color};
                    border-radius: 6px;
                    padding: 0px;
                }}
                QPushButton:checked {{
                    background-color: {dark_color};
                    border: 2px solid white;
                }}
                QPushButton:hover {{
                    background-color: {light_color};
                }}
            """
            btn_widget.set_button_style(button_style)

            btn_widget.clicked.connect(lambda b=behavior: self.toggle_behavior(b))
            self.button_layout.insertWidget(self.button_layout.count() - 1, btn_widget)
            self.buttons.append(btn_widget)

        # Apply stored mappings to the newly created buttons
        if self.controller_mappings:
            self.apply_button_mappings()

    def update_button_mappings(self, mappings):
        """Update all behavior buttons with their controller mappings"""
        self.controller_mappings = mappings
        self.apply_button_mappings()

    def apply_button_mappings(self):
        """Apply stored controller mappings to the current buttons"""
        # Create reverse mapping: behavior -> button_name
        reverse_mappings = {}
        for btn_name, behavior in self.controller_mappings.items():
            reverse_mappings[behavior] = btn_name
            
        for btn_widget in self.buttons:
            mapping_text = reverse_mappings.get(btn_widget.behavior)
            btn_widget.set_mapping_text(mapping_text)

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
    segment_clicked = Signal(str, int, int, int, int, Qt.MouseButton)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(60)
        self.setStyleSheet("background-color: #1a1a1a; border-top: 1px solid #333;")
        self.setMouseTracking(True)

        # Timeline state
        self.current_frame = 0
        self.total_frames = 0
        self.zoom_level = 5.0  # pixels per frame (more zoomed in by default)
        self.scroll_offset = 0  # horizontal scroll position in frames
        self.annotations = {}  # frame -> behavior
        self.behavior_colors = {}  # behavior -> color
        self.max_tracks = 1

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
        self.preview_behaviors = {} # behavior -> (start_frame, end_frame)
        
        # Click state
        self.press_pos = None

    def _update_height(self):
        """Update timeline height based on number of tracks"""
        all_present_behaviors = self.get_sorted_behaviors()
        num_tracks = max(1, len(all_present_behaviors))
        
        # Dynamically adjust height: base 60px + 20px per additional track
        # Max height capped at 200px to avoid taking over the UI
        new_height = 60 + (num_tracks - 1) * 20
        new_height = min(200, new_height)
        
        if self.height() != new_height:
            self.setFixedHeight(new_height)

    def set_annotations(self, annotations, behavior_colors):
        """Set annotations and behavior colors for display"""
        self.annotations = annotations
        self.behavior_colors = behavior_colors
        self._update_height()
        self.update()

    def set_range_preview(self, behavior, start_frame, current_frame):
        """Set the range labeling preview for display"""
        self.preview_behaviors[behavior] = (start_frame, current_frame)
        self._update_height()
        self.update()

    def clear_range_preview(self, behavior=None):
        """Clear the range labeling preview. If behavior is None, clear all."""
        if behavior is None:
            self.preview_behaviors = {}
        else:
            if behavior in self.preview_behaviors:
                del self.preview_behaviors[behavior]
        self._update_height()
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

    def get_segment_at(self, x, y):
        """Identify if a behavior segment exists at the given coordinates"""
        sorted_behaviors = self.get_sorted_behaviors()
        if not sorted_behaviors:
            return None

        num_total_behaviors = len(sorted_behaviors)
        track_height = (self.height() - 10) / num_total_behaviors
        
        # Calculate which track was clicked
        behavior_idx = int((y - 5) / track_height)
        if 0 <= behavior_idx < num_total_behaviors:
            behavior = sorted_behaviors[behavior_idx]
            clicked_frame = self.x_to_frame(x)
            
            # Use the same logic as draw_behavior_segments to find the segment
            behavior_frames = sorted([f for f, behaviors in self.annotations.items() 
                                     if (isinstance(behaviors, list) and behavior in behaviors) 
                                     or (not isinstance(behaviors, list) and behaviors == behavior)])
            
            if clicked_frame in behavior_frames:
                # Find start and end of this contiguous segment
                start = clicked_frame
                while start - 1 in behavior_frames:
                    start -= 1
                end = clicked_frame
                while end + 1 in behavior_frames:
                    end += 1
                return behavior, start, end
        return None

    def mousePressEvent(self, event):
        """Handle mouse press to start dragging or segment actions"""
        if self.total_frames == 0:
            return

        self.press_pos = event.position()

        if event.button() == Qt.LeftButton:
            self.is_dragging = True
            self.last_mouse_x = event.position().x()
            self.drag_start_frame = self.current_frame  # Store frame where dragging started

            # Emit signal for drag start
            self.drag_started.emit(self.drag_start_frame)
        elif event.button() == Qt.RightButton:
            segment = self.get_segment_at(event.position().x(), event.position().y())
            if segment:
                behavior, start, end = segment
                clicked_frame = self.x_to_frame(event.position().x())
                self.segment_clicked.emit(behavior, start, end, clicked_frame, self.current_frame, Qt.RightButton)

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
        """Handle mouse release to stop dragging or trigger left-click segment actions"""
        if event.button() == Qt.LeftButton:
            self.is_dragging = False

            # Check if it was a quick click on a segment (minimal movement)
            if self.press_pos and (event.position() - self.press_pos).manhattanLength() < 10:
                segment = self.get_segment_at(event.position().x(), event.position().y())
                if segment:
                    behavior, start, end = segment
                    clicked_frame = self.x_to_frame(event.position().x())
                    self.segment_clicked.emit(behavior, start, end, clicked_frame, self.current_frame, Qt.LeftButton)

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
        painter.fillRect(self.rect(), QColor(26, 26, 26))

        if self.total_frames == 0:
            return

        width = self.width()
        height = self.height()

        # Draw behavior segments
        self.draw_behavior_segments(painter, width, height)

        # Draw range labeling preview if active
        self.draw_range_preview(painter, width, height)

        # Draw timeline axis
        painter.setPen(QPen(QColor(60, 60, 60), 1))
        painter.drawLine(0, height // 2, width, height // 2)

        # Draw frame markers
        self.draw_frame_markers(painter, width, height)

        # Draw current frame indicator
        if self.current_frame >= 0:
            x_pos = self.frame_to_x(self.current_frame)
            if 0 <= x_pos <= width:
                painter.setPen(QPen(QColor(231, 76, 60), 2)) # Red color
                painter.drawLine(int(x_pos), 0, int(x_pos), height)

    def get_sorted_behaviors(self):
        """Get sorted list of all behaviors in annotations and previews"""
        all_present_behaviors = set()
        for behaviors in self.annotations.values():
            if isinstance(behaviors, list):
                all_present_behaviors.update(behaviors)
            elif behaviors:
                all_present_behaviors.add(behaviors)
        all_present_behaviors.update(self.preview_behaviors.keys())
        return sorted(list(all_present_behaviors))

    def draw_behavior_segments(self, painter, width, height):
        """Draw colored segments for behavior annotations, supporting multiple tracks"""
        sorted_behaviors = self.get_sorted_behaviors()
        if not sorted_behaviors:
            return

        # Group consecutive frames for EACH behavior separately
        behavior_segments = {} # behavior -> list of (start, end)
        
        for behavior in sorted_behaviors:
            segments = []
            
            # Find frames that have this behavior, sorted
            behavior_frames = sorted([f for f, behaviors in self.annotations.items() 
                                     if (isinstance(behaviors, list) and behavior in behaviors) 
                                     or behaviors == behavior])
            
            if not behavior_frames:
                continue

            # Group consecutive frames into segments
            current_start = behavior_frames[0]
            for i in range(1, len(behavior_frames)):
                if behavior_frames[i] != behavior_frames[i-1] + 1:
                    segments.append((current_start, behavior_frames[i-1]))
                    current_start = behavior_frames[i]
            segments.append((current_start, behavior_frames[-1]))
            
            behavior_segments[behavior] = segments

        # Draw segments
        num_total_behaviors = len(sorted_behaviors)
        track_height = (height - 10) / num_total_behaviors
        
        for behavior_idx, behavior in enumerate(sorted_behaviors):
            segments = behavior_segments.get(behavior, [])
            if not segments:
                continue
                
            color = self.behavior_colors.get(behavior, "#CCCCCC")
            q_color = QColor(color)
            
            y_pos = 5 + behavior_idx * track_height

            for start, end in segments:
                start_x = self.frame_to_x(start)
                end_x = self.frame_to_x(end + 1)

                if end_x > 0 and start_x < width:
                    visible_start = max(0, start_x)
                    visible_end = min(width, end_x)

                    if visible_start < visible_end:
                        painter.fillRect(int(visible_start), int(y_pos), int(visible_end - visible_start), int(track_height),
                                       QColor(q_color.red(), q_color.green(), q_color.blue(), 150))

                        # Draw behavior label if segment is wide enough
                        if visible_end - visible_start > 50 and track_height > 15:
                            rect = QRect(int(visible_start), int(y_pos), int(visible_end - visible_start), int(track_height))
                            painter.setPen(QPen(Qt.black, 1))
                            painter.drawText(rect, Qt.AlignCenter, behavior[:3])

    def draw_range_preview(self, painter, width, height):
        """Draw a temporary colored segment for range labeling preview"""
        sorted_behaviors = self.get_sorted_behaviors()
        if not sorted_behaviors:
            return

        num_total_behaviors = len(sorted_behaviors)
        track_height = (height - 10) / num_total_behaviors

        for behavior, (start_frame, end_frame) in self.preview_behaviors.items():
            if start_frame == -1 or end_frame == -1:
                continue

            behavior_idx = sorted_behaviors.index(behavior)
            y_pos = 5 + behavior_idx * track_height

            color = self.behavior_colors.get(behavior, "#CCCCCC")
            q_color = QColor(color)

            start = min(start_frame, end_frame)
            end = max(start_frame, end_frame)

            start_x = self.frame_to_x(start)
            end_x = self.frame_to_x(end + 1) # +1 to include the end frame

            if end_x > 0 and start_x < width:
                visible_start = max(0, start_x)
                visible_end = min(width, end_x)

                if visible_start < visible_end:
                    # Draw with a lighter, more transparent color for preview
                    painter.fillRect(int(visible_start), int(y_pos), int(visible_end - visible_start), int(track_height),
                                   QColor(q_color.red(), q_color.green(), q_color.blue(), 80)) # More transparent

                    # Draw a dashed border
                    painter.setPen(QPen(QColor(q_color.red(), q_color.green(), q_color.blue(), 200), 2, Qt.DashLine))
                    painter.drawRect(int(visible_start), int(y_pos), int(visible_end - visible_start), int(track_height))

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

        painter.setPen(QPen(QColor(100, 100, 100), 1))

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
    def __init__(self, parent=None, svg_path=None):
        super().__init__(parent)
        if svg_path is None:
            svg_path = resource_path("assets/mouse-logo.svg")
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
