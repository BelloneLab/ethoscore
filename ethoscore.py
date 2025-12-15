import sys
import os
import time
import pandas as pd
import json
import warnings
from PySide6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                              QWidget, QPushButton, QLabel, QFileDialog, QComboBox,
                              QMessageBox, QInputDialog, QDialog,
                              QFormLayout, QKeySequenceEdit, QDialogButtonBox, QSpinBox,
                              QGroupBox, QTabWidget, QCheckBox, QSplitter, QListWidget, QListWidgetItem, QMenu, QScrollArea) # Added QCheckBox, QSplitter, QListWidget, QListWidgetItem, QMenu, QScrollArea
from PySide6.QtCore import Qt, QTimer, QSettings, QCoreApplication, Signal
from PySide6.QtGui import QKeySequence, QFont, QPainter, QColor, QPen, QBrush
from PySide6.QtSvgWidgets import QSvgWidget
# Suppress pygame messages
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
import pygame
from annotator_libs.video_handling import VideoPlayer
from annotator_libs.ui_components import BehaviorButtons, TimelineWidget, LoadingScreen
from annotator_libs.annotation_logic import (
    load_annotations_from_csv,
    save_annotations_to_csv, update_annotations_on_frame_change,
    handle_label_state_change, remove_labels_from_frame,
    check_label_removal_on_backward_navigation, handle_behavior_removal,
    get_default_behaviors
)
from annotator_libs.gamification_logic import GamificationManager, LiveScoreWidget, GamificationSettingsDialog

# Suppress Qt warnings
os.environ['QT_LOGGING_RULES'] = '*.warning=false'
# Suppress warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")
warnings.filterwarnings("ignore")

import pygame


class WelcomeDialog(QDialog):
    """Welcome dialog for selecting video to annotate"""

    controllers_rescanned = Signal()  # Signal emitted when controllers are rescanned

    def __init__(self, last_video_path="", parent=None):
        super().__init__(parent)
        self.last_video_path = last_video_path
        self.selected_video_path = None
        # Initialize pygame for controller detection
        pygame.init()
        pygame.joystick.init()
        self.controller_count = pygame.joystick.get_count()
        self.controller_name = ""
        if self.controller_count > 0:
            try:
                joystick = pygame.joystick.Joystick(0)
                joystick.init()
                self.controller_name = joystick.get_name()
            except:
                self.controller_name = "Controller detected"
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("Ethoscore")
        self.setModal(True)
        self.setFixedSize(600, 400)

        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title_label = QLabel("Ethoscore")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        # Top row: rescan button (left) and logo (right)
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        # Rescan Controllers button (left)
        self.rescan_btn = QPushButton("Rescan Controllers")
        self.rescan_btn.setMinimumWidth(160)
        self.rescan_btn.clicked.connect(self.rescan_controllers)
        top_row.addWidget(self.rescan_btn, alignment=Qt.AlignLeft)

        # Add stretch to push logo to the right
        top_row.addStretch()

        # Logo - conditionally show controller or keyboard logo (right)
        logo_file = "assets/controller-logo.svg" if self.controller_count > 0 else "assets/keyboard-logo.svg"
        self.logo_widget = QSvgWidget(logo_file)
        self.logo_widget.setFixedSize(100, 100)
        top_row.addWidget(self.logo_widget, alignment=Qt.AlignRight)

        layout.addLayout(top_row)

        # Show last video name if available
        if self.last_video_path and os.path.exists(self.last_video_path):
            last_video_name = os.path.basename(self.last_video_path)
            last_video_label = QLabel(f"Last video: {last_video_name}")
            last_video_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(last_video_label)

        # Bottom row: 3 buttons side by side
        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        # Open Last Video button
        self.open_last_btn = QPushButton("Open Last Video")
        self.open_last_btn.setMinimumWidth(120)
        self.open_last_btn.clicked.connect(self.open_last_video)
        button_row.addWidget(self.open_last_btn)

        # Open Next Video button
        self.open_next_btn = QPushButton("Open Next Video")
        self.open_next_btn.setMinimumWidth(120)
        self.open_next_btn.clicked.connect(self.open_next_video)
        button_row.addWidget(self.open_next_btn)

        # Select In Files button
        self.select_new_btn = QPushButton("Select In Files")
        self.select_new_btn.setMinimumWidth(120)
        self.select_new_btn.clicked.connect(self.select_new_video)
        button_row.addWidget(self.select_new_btn)

        layout.addLayout(button_row)

        # Update button visibility based on last video availability
        self.update_button_visibility()

    def update_button_visibility(self):
        """Update button visibility based on whether last video exists"""
        has_last_video = self.last_video_path and os.path.exists(self.last_video_path)

        # Show/hide buttons based on last video availability
        self.open_last_btn.setVisible(has_last_video)
        self.open_next_btn.setVisible(has_last_video)

    def open_last_video(self):
        self.selected_video_path = self.last_video_path
        self.accept()

    def open_next_video(self):
        """Open the next alphabetical video in the same folder as the last opened video."""
        if not self.last_video_path or not os.path.exists(self.last_video_path):
            QMessageBox.warning(self, "Error", "No last video path found or path does not exist.")
            return

        current_dir = os.path.dirname(self.last_video_path)
        video_files = []
        for f in os.listdir(current_dir):
            if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.wmv')):
                video_files.append(os.path.join(current_dir, f))
        
        video_files.sort() # Sort alphabetically

        if not video_files:
            QMessageBox.warning(self, "Error", "No video files found in the current directory.")
            return

        try:
            current_video_index = video_files.index(self.last_video_path)
            next_video_index = (current_video_index + 1) % len(video_files)
            self.selected_video_path = video_files[next_video_index]
            self.accept()
        except ValueError:
            QMessageBox.warning(self, "Error", "Last opened video not found in its directory. Please select a new video.")
            return

    def select_new_video(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "",
            "Video Files (*.mp4 *.avi *.mov *.mkv *.wmv)"
        )
        if file_path:
            self.selected_video_path = file_path
            self.accept()

    def rescan_controllers(self):
        """Rescan for controllers and update the logo and UI"""
        # Reinitialize pygame joystick
        pygame.joystick.quit()
        pygame.joystick.init()
        self.controller_count = pygame.joystick.get_count()
        self.controller_name = ""
        if self.controller_count > 0:
            try:
                joystick = pygame.joystick.Joystick(0)
                joystick.init()
                self.controller_name = joystick.get_name()
            except:
                self.controller_name = "Controller detected"

        # Update logo based on new controller count
        logo_file = "assets/controller-logo.svg" if self.controller_count > 0 else "assets/keyboard-logo.svg"
        self.logo_widget.load(logo_file)

        # Emit signal to notify main application that controllers were rescanned
        self.controllers_rescanned.emit()

        # Note: UI update would require recreating the dialog, which is complex
        # For now, just update the internal state. The dialog would need to be closed and reopened to see changes.


class VideoAnnotator(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.video_path = ""
        self.annotations = {}  # frame_number -> behavior (single)
        self.current_behavior = None
        self.view_only_mode = False  # Flag to track if in view-only mode
        # Initialize shortcuts first
        self.shortcuts = {}
        self.settings = QSettings('VideoAnnotator', 'Settings') # Initialize general settings here
        self.input_settings = QSettings('VideoAnnotator', 'InputSettings') # Initialize input settings here
        self.gamification_settings = QSettings('VideoAnnotator', 'GamificationSettings') # Initialize gamification settings
        self.behavior_settings = QSettings('VideoAnnotator', 'BehaviorSettings') # Initialize behavior settings
        self.load_settings() # Load general settings including auto-save
        self.load_shortcuts()
        self.load_behavior_settings() # Load behavior settings

        # Initialize GamificationManager
        self.gamification_manager = GamificationManager(self)
        self.gamification_manager.load_settings(self.gamification_settings)

        # Initialize LiveScoreWidget BEFORE setup_ui
        self.live_score_widget = LiveScoreWidget(self.gamification_manager, self) # Pass gamification_manager
        self.live_score_widget.update_score_display(self.gamification_manager.total_score, 0)
        self.gamification_manager.score_updated.connect(self.live_score_widget.update_score_display)
        self.gamification_manager.combo_timer_progress.connect(self.live_score_widget.update_combo_progress)

        self.setup_ui()
        self.load_input_settings_on_startup() # Load input settings at startup
        # Apply loaded settings to video player
        self.video_player.update_label_key_mode(self.label_key_mode)
        self.video_player.set_show_overlay_bars(self.show_frame_preview_bars)
        self.video_player.update_input_settings(self.get_current_input_settings_for_startup()) # Apply input settings to video player

    def setup_ui(self):
        self.setWindowTitle("Ethoscore")
        self.setGeometry(100, 100, 1200, 800)

        # Status bar for messages
        self.statusBar().showMessage("Loading video and labels...") # Initial message

        # Create menu bar
        self.create_menu_bar()

        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)

        # Create splitter for resizable panels
        splitter = QSplitter(Qt.Horizontal)

        # Left panel - video and timeline
        left_widget = QWidget()
        from PySide6.QtWidgets import QSizePolicy
        left_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_panel = QVBoxLayout(left_widget)



        # Video player
        # Pass the timeline widget to the VideoPlayer so it can update the preview
        self.timeline = TimelineWidget()
        self.video_player = VideoPlayer(self.timeline)
        self.video_player.frame_changed.connect(self.on_frame_changed)
        self.video_player.label_toggled.connect(self.on_label_state_changed)
        self.video_player.remove_labels.connect(self.remove_labels_from_current_frame)
        self.video_player.check_label_removal.connect(self.on_check_label_removal)

        # Add view-only mode flag to video player
        self.video_player.view_only_mode = False

        # Override video player's keyPressEvent to check view-only mode
        original_keyPressEvent = self.video_player.keyPressEvent
        def video_player_keyPressEvent(event):
            """Override video player's keyPressEvent to check view-only mode"""
            key = event.key()

            # Check if it's a behavior key (1-9, 0)
            if key in [Qt.Key_1, Qt.Key_2, Qt.Key_3, Qt.Key_4, Qt.Key_5, Qt.Key_6, Qt.Key_7, Qt.Key_8, Qt.Key_9, Qt.Key_0]:
                if self.view_only_mode:
                    QMessageBox.information(self, "Preview Only Mode", "Cannot modify annotations in view-only mode.")
                    return

            # Call original keyPressEvent
            original_keyPressEvent(event)

        self.video_player.keyPressEvent = video_player_keyPressEvent
        left_panel.addWidget(self.video_player, stretch=1)  # Give video player priority

        # Add LiveScoreWidget as an overlay to the video player
        self.live_score_widget.setParent(self.video_player) # Make it a child of video_player
        self.live_score_widget.show() # Make sure it's visible
        # Initial positioning will be handled by resizeEvent

        # Timeline
        left_panel.addWidget(self.timeline, stretch=0)  # Timeline takes minimum space

        # Connect timeline signals to video player
        self.timeline.frame_clicked.connect(self.video_player.goto_frame)
        self.timeline.drag_started.connect(self.video_player._start_timeline_drag)
        self.timeline.drag_ended.connect(self.video_player._end_timeline_drag)

        # Timer for gamepad polling
        self.gamepad_timer = QTimer(self)
        self.gamepad_timer.timeout.connect(self.video_player.process_gamepad_input)
        self.gamepad_timer.start(50) # Poll every 50ms (20 FPS)

        # Right panel - behavior buttons
        right_widget = QWidget()
        from PySide6.QtWidgets import QSizePolicy
        right_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        right_panel = QVBoxLayout(right_widget)

        # Video file selection
        file_layout = QHBoxLayout()
        self.video_path_label = QLabel("No video selected")
        load_video_btn = QPushButton("Load")
        load_video_btn.clicked.connect(self.load_video_dialog)
        file_layout.addWidget(QLabel("Video:"))
        file_layout.addWidget(self.video_path_label)
        file_layout.addWidget(load_video_btn)
        
        self.load_next_video_btn = QPushButton("Load Next")
        self.load_next_video_btn.clicked.connect(self.load_next_video_in_main_ui)
        file_layout.addWidget(self.load_next_video_btn)
        
        right_panel.addLayout(file_layout)

        self.behavior_buttons = BehaviorButtons()
        self.behavior_buttons.behavior_toggled.connect(self.on_behavior_toggled)
        self.behavior_buttons.behavior_added.connect(self.on_behavior_added)
        self.behavior_buttons.behavior_removed.connect(self.on_behavior_removed)
        right_panel.addWidget(self.behavior_buttons)

        # Save button
        self.save_btn = QPushButton("Save Annotations") # Make save_btn an instance variable
        self.save_btn.clicked.connect(self.save_annotations)
        right_panel.addWidget(self.save_btn)

        # Set minimum widths for panels
        left_widget.setMinimumWidth(400)
        right_widget.setMinimumWidth(200)

        # Add widgets to splitter
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)

        # Set stretch factors (left panel gets priority when resizing)
        splitter.setStretchFactor(0, 1)  # Left panel stretches
        splitter.setStretchFactor(1, 0)  # Right panel doesn't stretch

        # Set initial sizes (3:1 ratio)
        splitter.setSizes([900, 300])  # Approximate 3:1 ratio for 1200px width

        main_layout.addWidget(splitter)

        self.setCentralWidget(central_widget)
        
        # Load default behaviors
        self.load_default_behaviors()

        # Connect caching_complete signal from video_player and disable controls after all components are initialized
        self.video_player.caching_complete.connect(self.on_caching_complete)
        self.set_controls_enabled(False) # Disable controls initially

        # Loading screen
        self.loading_screen = LoadingScreen(self)
        self.loading_screen.hide() # Hide initially
        self.video_player.preload_progress.connect(self.update_loading_progress)
        self.video_player.preload_finished.connect(self.on_caching_complete) # Connect to preload_finished
        
        # Connect combo timer visibility signal
        self.gamification_manager.combo_timer_visible.connect(self.live_score_widget.update_combo_visibility)

        # Connect label toggled signal to gamification manager
        self.video_player.label_toggled.connect(self.on_label_toggled_for_gamification)

    def on_label_toggled_for_gamification(self, behavior, is_active, start_frame, end_frame):
        """Handle label toggled events for gamification"""
        if is_active:
            self.gamification_manager.behavior_activated()
        else:
            self.gamification_manager.behavior_deactivated()



    def create_menu_bar(self):
        """Create the menu bar with File and Settings menus"""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu('File')
        load_video_action = file_menu.addAction('Load Video')
        load_video_action.triggered.connect(self.load_video_dialog)
        load_next_video_action = file_menu.addAction('Load Next Video')
        load_next_video_action.triggered.connect(self.load_next_video_in_main_ui)
        load_behavior_action = file_menu.addAction('Load Behaviors')
        load_behavior_action.triggered.connect(self.load_behavior_dialog)
        file_menu.addSeparator()
        save_action = file_menu.addAction('Save Annotations')
        save_action.setShortcut(QKeySequence(self.shortcuts.get('save', 'Ctrl+S')))
        save_action.triggered.connect(self.save_annotations)

        # Settings menu
        settings_menu = menubar.addMenu('Settings')
        general_settings_action = settings_menu.addAction('General Settings')
        general_settings_action.triggered.connect(self.show_general_settings_dialog)
        input_settings_action = settings_menu.addAction('Input Settings')
        input_settings_action.triggered.connect(self.show_input_settings_dialog)
        gamification_settings_action = settings_menu.addAction('Gamification Settings')
        gamification_settings_action.triggered.connect(self.show_gamification_settings_dialog)


    def load_settings(self):
        """Load general application settings"""
        # self.settings is already initialized in __init__
        self.auto_save_enabled = self.settings.value('auto_save_enabled', False, bool)
        self.auto_save_interval = self.settings.value('auto_save_interval', 3, int) # Default 3 minutes
        self.hold_time = self.settings.value('hold_time', 100, int) # Default 100 ms
        self.label_key_mode = self.settings.value('label_key_mode', 'both', str) # Default both modes
        self.show_frame_preview_bars = self.settings.value('show_frame_preview_bars', True, bool) # Default enabled
        self.include_last_frame_in_range = self.settings.value('include_last_frame_in_range', True, bool) # Default include last frame
        self.show_statistics_popup = self.settings.value('show_statistics_popup', True, bool) # Default enabled
        self.last_video_path = self.settings.value('last_video_path', '', str)
        # Load frame positions as JSON string and parse to dict
        frame_positions_json = self.settings.value('last_frame_positions', '{}', str)
        try:
            self.last_frame_positions = json.loads(frame_positions_json)
        except (json.JSONDecodeError, TypeError):
            self.last_frame_positions = {}

        # Load video scores as JSON string and parse to dict
        video_scores_json = self.settings.value('last_video_scores', '{}', str)
        try:
            self.last_video_scores = json.loads(video_scores_json)
        except (json.JSONDecodeError, TypeError):
            self.last_video_scores = {}

        # Setup auto-save timer
        self.auto_save_timer = QTimer(self)
        self.auto_save_timer.timeout.connect(self.auto_save_annotations)
        if self.auto_save_enabled:
            self.auto_save_timer.start(self.auto_save_interval * 60 * 1000) # Convert minutes to ms

    def save_settings(self):
        """Save general application settings"""
        self.settings.setValue('auto_save_enabled', self.auto_save_enabled)
        self.settings.setValue('auto_save_interval', self.auto_save_interval)
        self.settings.setValue('hold_time', self.hold_time)
        self.settings.setValue('label_key_mode', self.label_key_mode)
        self.settings.setValue('show_frame_preview_bars', self.show_frame_preview_bars)
        self.settings.setValue('include_last_frame_in_range', self.include_last_frame_in_range)
        self.settings.setValue('show_statistics_popup', self.show_statistics_popup)
        self.settings.setValue('last_video_path', self.last_video_path)
        # Save frame positions as JSON string
        self.settings.setValue('last_frame_positions', json.dumps(self.last_frame_positions))
        # Save video scores as JSON string
        self.settings.setValue('last_video_scores', json.dumps(self.last_video_scores))

    def load_behavior_settings(self):
        """Load behavior settings from QSettings"""
        # Load saved behaviors list
        saved_behaviors_json = self.behavior_settings.value('behaviors', '[]', str)
        try:
            self.saved_behaviors = json.loads(saved_behaviors_json)
        except (json.JSONDecodeError, TypeError):
            self.saved_behaviors = []

        # Load behavior colors
        saved_colors_json = self.behavior_settings.value('behavior_colors', '{}', str)
        try:
            self.saved_behavior_colors = json.loads(saved_colors_json)
        except (json.JSONDecodeError, TypeError):
            self.saved_behavior_colors = {}

    def save_behavior_settings(self):
        """Save behavior settings to QSettings"""
        # Save behaviors list
        self.behavior_settings.setValue('behaviors', json.dumps(self.behavior_buttons.behaviors))
        # Save behavior colors
        self.behavior_settings.setValue('behavior_colors', json.dumps(self.behavior_buttons.behavior_colors))
        self.behavior_settings.sync()

    def load_shortcuts(self):
        """Load keyboard shortcuts from settings"""
        # Use a separate QSettings for shortcuts to avoid conflicts
        self.shortcut_settings = QSettings('VideoAnnotator', 'Shortcuts')
        # Default shortcuts
        self.shortcuts = {
            'save': self.shortcut_settings.value('save', 'Ctrl+S'),
            'load_video': self.shortcut_settings.value('load_video', 'Ctrl+O'),
            'load_next_video': self.shortcut_settings.value('load_next_video', 'Ctrl+N'), # New shortcut
            'next_frame': self.shortcut_settings.value('next_frame', 'Right'),
            'prev_frame': self.shortcut_settings.value('prev_frame', 'Left'),
            'delete': self.shortcut_settings.value('delete', 'Escape'),
        }
        # Add behavior shortcuts 1-10
        for i in range(1, 11):
            key = f'toggle_behavior_{i}'
            default_key = str(i) if i <= 9 else '0'
            self.shortcuts[key] = self.shortcut_settings.value(key, default_key)

    def save_shortcuts(self):
        """Save keyboard shortcuts to settings"""
        for key, value in self.shortcuts.items():
            self.shortcut_settings.setValue(key, value)

    def update_menu_shortcuts(self):
        """Update menu shortcuts based on settings"""
        menubar = self.menuBar()
        file_menu = menubar.findChild(QMenu, 'File')
        if file_menu:
            for action in file_menu.actions():
                if action.text() == 'Save Annotations':
                    action.setShortcut(QKeySequence(self.shortcuts['save']))
                elif action.text() == 'Load Next Video': # Update shortcut for new action
                    action.setShortcut(QKeySequence(self.shortcuts['load_next_video']))



    def show_input_settings_dialog(self):
        """Show the input settings configuration dialog with tabs"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Input Settings")
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)

        # Create tab widget
        tab_widget = QTabWidget()

        # Keyboard settings tab
        keyboard_tab = QWidget()
        keyboard_layout = QVBoxLayout(keyboard_tab)

        keyboard_group = QGroupBox("Keyboard Arrow Key Settings")
        keyboard_form = QFormLayout(keyboard_group)

        # Frame step size
        self.frame_step_spin = QSpinBox()
        self.frame_step_spin.setRange(1, 100)
        self.frame_step_spin.setValue(1)
        keyboard_form.addRow("Frame step size:", self.frame_step_spin)

        # Shift frame skip
        self.shift_skip_spin = QSpinBox()
        self.shift_skip_spin.setRange(1, 1000)
        self.shift_skip_spin.setValue(10)
        keyboard_form.addRow("Shift frame skip:", self.shift_skip_spin)


        keyboard_layout.addWidget(keyboard_group)

        # Keyboard shortcuts group
        shortcuts_group = QGroupBox("Keyboard Shortcuts")
        shortcuts_form = QFormLayout(shortcuts_group)

        self.shortcut_edits = {}
        shortcut_labels = {
            'save': 'Save Annotations',
            'load_video': 'Load Video',
            'load_next_video': 'Load Next Video',
            'next_frame': 'Next Frame',
            'prev_frame': 'Previous Frame',
            'delete': 'Delete Labels',
        }

        # Add behavior shortcuts up to the number of behaviors
        num_behaviors = len(self.behavior_buttons.behaviors)
        for i in range(1, num_behaviors + 1):
            shortcut_labels[f'toggle_behavior_{i}'] = f'Toggle Behavior {i}'

        for key, label in shortcut_labels.items():
            edit = QKeySequenceEdit(QKeySequence(self.shortcuts[key]))
            self.shortcut_edits[key] = edit
            shortcuts_form.addRow(label, edit)

        keyboard_layout.addWidget(shortcuts_group)
        keyboard_layout.addStretch()

        # Controller settings tab
        controller_tab = QWidget()
        controller_layout = QVBoxLayout(controller_tab)

        controller_group = QGroupBox("Gamepad/Controller Settings")
        controller_form = QFormLayout(controller_group)

        # Joystick deadzone
        self.deadzone_spin = QSpinBox()
        self.deadzone_spin.setRange(0, 50)
        self.deadzone_spin.setValue(10)
        self.deadzone_spin.setSuffix(" %")
        controller_form.addRow("Joystick deadzone:", self.deadzone_spin)

        # Joystick sensitivity
        self.joystick_sensitivity_spin = QSpinBox()
        self.joystick_sensitivity_spin.setRange(1, 10)
        self.joystick_sensitivity_spin.setValue(5)
        controller_form.addRow("Joystick sensitivity:", self.joystick_sensitivity_spin)

        # Joystick mode
        self.joystick_mode_combo = QComboBox()
        self.joystick_mode_combo.addItem("Linear", "linear")
        self.joystick_mode_combo.addItem("Quadratic", "quadratic")
        controller_form.addRow("Joystick mode:", self.joystick_mode_combo)

        # Frame skip rate
        self.frame_skip_spin = QSpinBox()
        self.frame_skip_spin.setRange(1, 10)
        self.frame_skip_spin.setValue(1)
        controller_form.addRow("Frame skip rate:", self.frame_skip_spin)

        # Fast forward multiplier
        self.fast_forward_multiplier_spin = QSpinBox()
        self.fast_forward_multiplier_spin.setRange(1, 100)
        self.fast_forward_multiplier_spin.setValue(10)
        controller_form.addRow("Fast forward multiplier:", self.fast_forward_multiplier_spin)

        # Automapped behaviors
        automap_group = QGroupBox("Controller Button Mappings")
        automap_layout = QVBoxLayout(automap_group)

        # Info label
        automap_info = QLabel("Configure which controller buttons map to behaviors and navigation actions:")
        automap_layout.addWidget(automap_info)

        # List widget to display current mappings
        self.automap_list = QListWidget()
        self.automap_list.setMaximumHeight(150)
        automap_layout.addWidget(self.automap_list)

        # Buttons for automapping
        automap_buttons_layout = QHBoxLayout()
        automap_btn = QPushButton("Configure Mappings")
        automap_btn.clicked.connect(self.show_controller_automap_dialog)
        automap_buttons_layout.addWidget(automap_btn)

        clear_automap_btn = QPushButton("Clear All")
        clear_automap_btn.clicked.connect(self.clear_all_automappings)
        automap_buttons_layout.addWidget(clear_automap_btn)

        automap_layout.addLayout(automap_buttons_layout)

        controller_layout.addWidget(controller_group)
        controller_layout.addWidget(automap_group)
        controller_layout.addStretch()

        # Add tabs
        tab_widget.addTab(keyboard_tab, "Keyboard")
        tab_widget.addTab(controller_tab, "Controller")

        layout.addWidget(tab_widget)

        # Load current settings into the dialog widgets
        self.load_input_settings_into_dialog()

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults,
            Qt.Horizontal, dialog
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_default_input_settings)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.Accepted:
            # Save shortcuts
            if hasattr(self, 'shortcut_edits'):
                for key, edit in self.shortcut_edits.items():
                    self.shortcuts[key] = edit.keySequence().toString()
                self.save_shortcuts()
                self.update_menu_shortcuts()
            self.save_input_settings()

    def show_controller_automap_dialog(self):
        """Show the controller automapping dialog"""
        dialog = ControllerAutomapDialog(self.behavior_buttons.behaviors + ["fast_forward", "erase"], self.video_player.controller_mappings, self)
        if dialog.exec() == QDialog.Accepted:
            self.video_player.controller_mappings = dialog.get_mappings()
            # Removed immediate save_controller_mappings() call here.
            # Mappings will be saved when the main Input Settings dialog is accepted.
            # Update video player with new mappings
            self.video_player.update_input_settings(self.get_current_input_settings())
            # Update the display in input settings if it's open
            if hasattr(self, 'automap_list'):
                self.update_automap_display()


    def show_general_settings_dialog(self):
        """Show the general settings configuration dialog"""
        dialog = QDialog(self)
        dialog.setWindowTitle("General Settings")
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        form_layout = QFormLayout()

        # Hold detection time
        self.hold_time_spin = QSpinBox()
        self.hold_time_spin.setRange(10, 2000) # Adjusted range
        self.hold_time_spin.setValue(self.hold_time) # Use loaded value
        self.hold_time_spin.setSuffix(" ms")
        form_layout.addRow("Hold detection time:", self.hold_time_spin)

        # Auto-save enabled checkbox
        self.auto_save_checkbox = QCheckBox("Enable Auto-Save")
        self.auto_save_checkbox.setChecked(self.auto_save_enabled)
        form_layout.addRow("Auto-Save:", self.auto_save_checkbox)

        # Auto-save interval spin box
        self.auto_save_interval_spin = QSpinBox()
        self.auto_save_interval_spin.setRange(1, 60) # 1 to 60 minutes
        self.auto_save_interval_spin.setSuffix(" minutes")
        self.auto_save_interval_spin.setValue(self.auto_save_interval)
        form_layout.addRow("Auto-Save Interval:", self.auto_save_interval_spin)

        # Label key mode combo box
        self.label_key_mode_combo = QComboBox()
        self.label_key_mode_combo.addItem("Both (tap to toggle, hold to activate)", "both")
        self.label_key_mode_combo.addItem("Toggle only", "toggle")
        self.label_key_mode_combo.addItem("Hold only", "hold")
        # Set current selection based on saved mode
        mode_index = self.label_key_mode_combo.findData(self.label_key_mode)
        if mode_index >= 0:
            self.label_key_mode_combo.setCurrentIndex(mode_index)
        form_layout.addRow("Label Keys:", self.label_key_mode_combo)

        # Show frame preview bars checkbox
        self.show_frame_preview_bars_checkbox = QCheckBox("Show frame preview bars")
        self.show_frame_preview_bars_checkbox.setChecked(self.show_frame_preview_bars)
        form_layout.addRow("UI:", self.show_frame_preview_bars_checkbox)

        # Include last frame in range checkbox
        self.include_last_frame_checkbox = QCheckBox("Include last selected frame in range")
        self.include_last_frame_checkbox.setChecked(self.include_last_frame_in_range)
        form_layout.addRow("Labeling:", self.include_last_frame_checkbox)

        # Show statistics popup checkbox
        self.show_statistics_popup_checkbox = QCheckBox("Show statistics popup when loading next video")
        self.show_statistics_popup_checkbox.setChecked(self.show_statistics_popup)
        form_layout.addRow("UI:", self.show_statistics_popup_checkbox)

        layout.addLayout(form_layout)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults,
            Qt.Horizontal, dialog
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_default_general_settings)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.Accepted:
            self.hold_time = self.hold_time_spin.value()
            self.auto_save_enabled = self.auto_save_checkbox.isChecked()
            self.auto_save_interval = self.auto_save_interval_spin.value()
            self.label_key_mode = self.label_key_mode_combo.currentData()
            self.show_frame_preview_bars = self.show_frame_preview_bars_checkbox.isChecked()
            self.include_last_frame_in_range = self.include_last_frame_checkbox.isChecked()
            self.show_statistics_popup = self.show_statistics_popup_checkbox.isChecked()
            self.save_settings() # Save general settings

            # Restart auto-save timer with new settings
            self.auto_save_timer.stop()
            if self.auto_save_enabled:
                self.auto_save_timer.start(self.auto_save_interval * 60 * 1000)

            # Update VideoPlayer with new label key mode setting
            self.video_player.update_label_key_mode(self.label_key_mode)

            # Update VideoPlayer with new frame preview bars setting
            self.video_player.set_show_overlay_bars(self.show_frame_preview_bars)

            # Update VideoPlayer with new include last frame setting
            self.video_player.set_include_last_frame_in_range(self.include_last_frame_in_range)

            # Update VideoPlayer with the new hold time
            self.video_player.update_input_settings({'hold_time': self.hold_time})

    def show_gamification_settings_dialog(self):
        """Show the gamification settings configuration dialog."""
        dialog = GamificationSettingsDialog(self.gamification_manager, self)
        if dialog.exec() == QDialog.Accepted:
            self.gamification_manager.save_settings(self.gamification_settings)

    def restore_default_general_settings(self):
        """Restore default general settings"""
        self.hold_time_spin.setValue(100) # Default 100 ms
        self.auto_save_checkbox.setChecked(False)
        self.auto_save_interval_spin.setValue(3) # Default 3 minutes
        # Set combo box to "both" mode
        both_index = self.label_key_mode_combo.findData('both')
        if both_index >= 0:
            self.label_key_mode_combo.setCurrentIndex(both_index)
        self.show_frame_preview_bars_checkbox.setChecked(True) # Default enabled

    def load_input_settings_on_startup(self):
        """Load input settings from QSettings at application startup."""
        settings = self.input_settings

        # Load keyboard settings into instance variables
        self._frame_step = settings.value('frame_step', 1, int)
        self._shift_skip = settings.value('shift_skip', 10, int)

        # Load controller settings into instance variables
        self._deadzone = settings.value('deadzone', 10, int)
        self._joystick_sensitivity = settings.value('joystick_sensitivity', 5, int)
        self._frame_skip = settings.value('frame_skip', 1, int)
        self._fast_forward_multiplier = settings.value('fast_forward_multiplier', 10, int)
        self._joystick_mode = settings.value('joystick_mode', 'quadratic', str)

        # Load controller automappings
        automap_json = settings.value('controller_automappings', '{}', str)
        try:
            self.video_player.controller_mappings = json.loads(automap_json)
        except (json.JSONDecodeError, TypeError):
            self.video_player.controller_mappings = {}

    def get_current_input_settings_for_startup(self):
        """Helper to get current input settings for updating VideoPlayer at startup."""
        return {
            'frame_step': getattr(self, '_frame_step', 1),
            'shift_skip': getattr(self, '_shift_skip', 10),
            'hold_time': self.hold_time, # Add hold_time here
            'deadzone': getattr(self, '_deadzone', 10),
            'joystick_sensitivity': getattr(self, '_joystick_sensitivity', 5),
            'frame_skip': getattr(self, '_frame_skip', 1),
            'fast_forward_multiplier': getattr(self, '_fast_forward_multiplier', 10),
            'joystick_mode': getattr(self, '_joystick_mode', 'quadratic'),
            'button_a': 'None',  # Legacy, not used anymore
            'button_b': 'None',
            'button_x': 'None',
            'button_y': 'None',
            'controller_automappings': self.video_player.controller_mappings
        }

    def load_input_settings_into_dialog(self):
        """Load input settings from QSettings into the input settings dialog widgets."""
        settings = self.input_settings

        # Keyboard settings
        self.frame_step_spin.setValue(settings.value('frame_step', 1, int))
        self.shift_skip_spin.setValue(settings.value('shift_skip', 10, int))

        # Controller settings
        self.deadzone_spin.setValue(settings.value('deadzone', 10, int))
        self.joystick_sensitivity_spin.setValue(settings.value('joystick_sensitivity', 5, int))
        self.frame_skip_spin.setValue(settings.value('frame_skip', 1, int))
        self.fast_forward_multiplier_spin.setValue(settings.value('fast_forward_multiplier', 10, int))
        mode_index = self.joystick_mode_combo.findData(settings.value('joystick_mode', 'quadratic', str))
        if mode_index >= 0:
            self.joystick_mode_combo.setCurrentIndex(mode_index)

        # Load controller automappings
        automap_json = settings.value('controller_automappings', '{}', str)
        try:
            self.video_player.controller_mappings = json.loads(automap_json)
        except (json.JSONDecodeError, TypeError):
            self.video_player.controller_mappings = {}
        self.update_automap_display() # Display current mappings

    def save_input_settings(self):
        """Save input settings from the dialog widgets to QSettings."""
        settings = self.input_settings

        # Keyboard settings
        settings.setValue('frame_step', self.frame_step_spin.value())
        settings.setValue('shift_skip', self.shift_skip_spin.value())

        # Controller settings
        settings.setValue('deadzone', self.deadzone_spin.value())
        settings.setValue('joystick_sensitivity', self.joystick_sensitivity_spin.value())
        settings.setValue('frame_skip', self.frame_skip_spin.value())
        settings.setValue('fast_forward_multiplier', self.fast_forward_multiplier_spin.value())
        settings.setValue('joystick_mode', self.joystick_mode_combo.currentData())

        settings.sync()  # Ensure the settings are written to disk

        # Update VideoPlayer with new settings
        input_settings = {
            'frame_step': self.frame_step_spin.value(),
            'shift_skip': self.shift_skip_spin.value(),
            'deadzone': self.deadzone_spin.value(),
            'joystick_sensitivity': self.joystick_sensitivity_spin.value(),
            'frame_skip': self.frame_skip_spin.value(),
            'fast_forward_multiplier': self.fast_forward_multiplier_spin.value(),
            'joystick_mode': self.joystick_mode_combo.currentData(),
            'button_a': 'None',  # Legacy, not used anymore
            'button_b': 'None',
            'button_x': 'None',
            'button_y': 'None',
            'controller_automappings': self.video_player.controller_mappings # Include automappings
        }
        self.video_player.update_input_settings(input_settings)
        self.save_controller_mappings() # Save automappings as well

    def save_controller_mappings(self):
        """Save controller automappings to QSettings"""
        settings = self.input_settings
        json_mappings = json.dumps(self.video_player.controller_mappings)
        settings.setValue('controller_automappings', json_mappings)
        settings.sync()  # Ensure the settings are written to disk

    def get_current_input_settings(self):
        """Helper to get current input settings from dialog widgets for updating VideoPlayer."""
        # This function is called when the dialog is open, so widgets should exist.
        return {
            'frame_step': self.frame_step_spin.value(),
            'shift_skip': self.shift_skip_spin.value(),
            'deadzone': self.deadzone_spin.value(),
            'joystick_sensitivity': self.joystick_sensitivity_spin.value(),
            'frame_skip': self.frame_skip_spin.value(),
            'fast_forward_multiplier': self.fast_forward_multiplier_spin.value(),
            'joystick_mode': self.joystick_mode_combo.currentData(),
            'button_a': 'None',  # Legacy, not used anymore
            'button_b': 'None',
            'button_x': 'None',
            'button_y': 'None',
            'controller_automappings': self.video_player.controller_mappings # Include automappings
        }

    def update_automap_display(self):
        """Update the automapping display in the input settings dialog"""
        if hasattr(self, 'automap_list'):
            self.automap_list.clear()
            if self.video_player.controller_mappings:
                for button_name, behavior in self.video_player.controller_mappings.items():
                    item = QListWidgetItem(f"{button_name} → {behavior}")
                    self.automap_list.addItem(item)
            else:
                item = QListWidgetItem("No mappings configured")
                item.setFlags(item.flags() & ~Qt.ItemIsSelectable)  # Make it non-selectable
                self.automap_list.addItem(item)

    def clear_all_automappings(self):
        """Clear all controller automappings"""
        self.video_player.controller_mappings = {}
        self.save_controller_mappings()
        if hasattr(self, 'automap_list'):
            self.update_automap_display()
        # Update video player with cleared mappings
        self.video_player.update_input_settings(self.get_current_input_settings())

    def restore_default_input_settings(self):
        """Restore default input settings"""
        # Keyboard defaults
        self.frame_step_spin.setValue(1)
        self.shift_skip_spin.setValue(10)
        self.hold_time_spin.setValue(500)

        # Controller defaults
        self.deadzone_spin.setValue(10)
        self.joystick_sensitivity_spin.setValue(5)
        self.frame_skip_spin.setValue(1)
        self.fast_forward_multiplier_spin.setValue(10)

        # Restore default shortcuts
        if hasattr(self, 'shortcut_edits'):
            default_shortcuts = {
                'save': 'Ctrl+S',
                'load_video': 'Ctrl+O',
                'load_next_video': 'Ctrl+N',
                'next_frame': 'Right',
                'prev_frame': 'Left',
                'delete': 'Escape',
            }
            # Add behavior shortcuts up to the number of behaviors
            num_behaviors = len(self.behavior_buttons.behaviors)
            for i in range(1, num_behaviors + 1):
                default_shortcuts[f'toggle_behavior_{i}'] = str(i) if i <= 9 else '0'

            for key, shortcut in default_shortcuts.items():
                if key in self.shortcut_edits:
                    self.shortcut_edits[key].setKeySequence(QKeySequence(shortcut))

        self.video_player.controller_mappings = {} # Clear automappings
        self.save_controller_mappings() # Save cleared automappings

    def load_default_behaviors(self):
        """Load default behaviors from settings or use hardcoded defaults"""
        # First try to load from saved settings
        if self.saved_behaviors:
            behaviors = self.saved_behaviors
            # Also load saved colors if available
            if self.saved_behavior_colors:
                self.behavior_buttons.behavior_colors = self.saved_behavior_colors
        else:
            # Fall back to hardcoded defaults
            behaviors = get_default_behaviors()
            # Set default colors
            self.behavior_buttons.behavior_colors = {
                "nose-to-nose": "#FF6B6B",  # Red
                "nose-to-body": "#A7DB50",  # Lime
                "anogenital": "#45B7D1",    # Blue
                "passive": "#BD23FF",       # Violet
                "rearing": "#ECFF1C",       # Yellow
                "fighting": "#00FFC8",     # Turquoise
                "mounting": "#FF8C00"      # Orange
            }

        self.behavior_buttons.load_behaviors(behaviors)
        # Connect video player to behavior buttons
        self.video_player.available_behaviors = behaviors
        self.video_player.get_behavior_color = self.behavior_buttons.get_behavior_color

        # Update input settings with current settings (to refresh button mappings with new behaviors)
        try:
            input_settings = {
                'frame_step': self.frame_step_spin.value() if hasattr(self, 'frame_step_spin') else 1,
                'shift_skip': self.shift_skip_spin.value() if hasattr(self, 'shift_skip_spin') else 10,
                'hold_time': self.hold_time_spin.value() if hasattr(self, 'hold_time_spin') else 500,
                'deadzone': self.deadzone_spin.value() if hasattr(self, 'deadzone_spin') else 10,
                'joystick_sensitivity': self.joystick_sensitivity_spin.value() if hasattr(self, 'joystick_sensitivity_spin') else 5,
                'frame_skip': self.frame_skip_spin.value() if hasattr(self, 'frame_skip_spin') else 1,
                'button_a': 'None',  # Legacy, not used anymore
                'button_b': 'None',
                'button_x': 'None',
                'button_y': 'None',
                'controller_automappings': self.video_player.controller_mappings if hasattr(self.video_player, 'controller_mappings') else {}
            }
            self.video_player.update_input_settings(input_settings)
        except AttributeError:
            # Input settings widgets may not be initialized yet
            pass

    def load_annotations_with_behavior_handling(self, video_path):
        """Load annotations with flexible behavior handling based on CSV content"""
        csv_path = os.path.splitext(video_path)[0] + '.csv'

        # If no CSV exists, use last saved behavior list
        if not os.path.exists(csv_path):
            return {}  # Return empty annotations

        try:
            df = pd.read_csv(csv_path)
            csv_behaviors = df.columns.tolist()[1:]  # Skip 'Frames' column
            saved_behaviors = self.saved_behaviors if self.saved_behaviors else get_default_behaviors()

            # Check if CSV headers match saved behaviors exactly
            if set(csv_behaviors) == set(saved_behaviors):
                # Headers match exactly - use the CSV as-is
                return load_annotations_from_csv(video_path, saved_behaviors, parent=self)

            # Headers don't match - ask user what to do
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Behavior Mismatch")
            msg_box.setText("The CSV file has different behaviors than your saved behavior list.\n\n"
                          f"CSV behaviors: {', '.join(sorted(csv_behaviors))}\n"
                          f"Saved behaviors: {', '.join(sorted(saved_behaviors))}\n\n"
                          "Choose how to proceed:")

            # Add detailed explanations for each option
            msg_box.setInformativeText(
                "<b>Fix CSV:</b> This will modify the CSV file to match your saved behavior list.<br>"
                "• New behaviors from your saved list will be added with 0 values<br>"
                "• Behaviors in the CSV that are not in your saved list will be removed<br>"
                "• <b>WARNING:</b> This permanently modifies your CSV file!<br><br>"

                "<b>Use CSV as Reference:</b> This will update your behavior list to match the CSV file.<br>"
                "• Your saved behavior list will be replaced with the behaviors from the CSV<br>"
                "• You can annotate normally using the behaviors from the CSV<br>"

                "<b>Preview Only:</b> This loads the CSV for viewing only.<br>"
                "• The CSV data will be displayed but you cannot modify annotations<br>"
                "• Your saved behavior list and csv remain unchanged<br>"
                "• Safe option if you're unsure which behaviors to use"
            )

            fix_csv_btn = msg_box.addButton("Fix CSV", QMessageBox.ActionRole)
            use_csv_btn = msg_box.addButton("Use CSV as Reference", QMessageBox.ActionRole)
            view_only_btn = msg_box.addButton("Preview Only", QMessageBox.ActionRole)
            cancel_btn = msg_box.addButton(QMessageBox.Cancel)

            msg_box.exec()

            if msg_box.clickedButton() == fix_csv_btn:
                # Fix CSV: add new behaviors from saved list with 0s, remove behaviors not in saved list
                synced_df = self.sync_csv_with_saved_behaviors(df, saved_behaviors)
                if synced_df is not None:
                    synced_df.to_csv(csv_path, index=False)
                    return load_annotations_from_csv(video_path, saved_behaviors, parent=self)

            elif msg_box.clickedButton() == use_csv_btn:
                # Use CSV as reference: update saved behaviors to match CSV
                self.behavior_buttons.load_behaviors(csv_behaviors)
                # Set default colors for new behaviors
                for behavior in csv_behaviors:
                    if behavior not in self.behavior_buttons.behavior_colors:
                        import random
                        self.behavior_buttons.behavior_colors[behavior] = f"#{random.randint(0, 255):02x}{random.randint(0, 255):02x}{random.randint(0, 255):02x}"
                self.save_behavior_settings()
                # Update video player
                self.video_player.available_behaviors = csv_behaviors
                self.video_player.get_behavior_color = self.behavior_buttons.get_behavior_color
                return load_annotations_from_csv(video_path, csv_behaviors, parent=self)

            elif msg_box.clickedButton() == view_only_btn:
                # Preview only: load CSV but disable editing
                self.view_only_mode = True  # Set view-only flag
                self.behavior_buttons.load_behaviors(csv_behaviors)
                # Set default colors for new behaviors
                for behavior in csv_behaviors:
                    if behavior not in self.behavior_buttons.behavior_colors:
                        import random
                        self.behavior_buttons.behavior_colors[behavior] = f"#{random.randint(0, 255):02x}{random.randint(0, 255):02x}{random.randint(0, 255):02x}"
                # Update video player but disable controls
                self.video_player.available_behaviors = csv_behaviors
                self.video_player.get_behavior_color = self.behavior_buttons.get_behavior_color
                self.set_controls_enabled(False)  # Disable editing controls
                QMessageBox.information(self, "Preview Only Mode",
                                      "CSV loaded in view-only mode. Editing is disabled.")
                return load_annotations_from_csv(video_path, csv_behaviors, parent=self)

            # Cancel or other - return empty annotations
            return {}

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not load annotations: {str(e)}")
            return {}

    def sync_csv_with_saved_behaviors(self, df, saved_behaviors):
        """Sync CSV dataframe with saved behaviors"""
        csv_behaviors = df.columns.tolist()[1:]  # Skip 'Frames' column
        saved_behaviors_set = set(saved_behaviors)
        csv_behaviors_set = set(csv_behaviors)

        # Create new dataframe with saved behaviors
        synced_data = {'Frames': df['Frames'].copy()}

        # Add existing behaviors that are in saved list
        for behavior in saved_behaviors:
            if behavior in df.columns:
                synced_data[behavior] = df[behavior].copy()
            else:
                # New behavior, add column with 0s
                synced_data[behavior] = [0] * len(df)

        synced_df = pd.DataFrame(synced_data)
        return synced_df

    def update_timeline_annotations(self):
        """Update timeline with current annotations and behavior colors"""
        behavior_colors = {}
        for behavior in self.behavior_buttons.behaviors:
            behavior_colors[behavior] = self.behavior_buttons.get_behavior_color(behavior)

        self.timeline.set_annotations(self.annotations, behavior_colors)
        self.timeline.update()

    def load_video_by_path(self, file_path):
        """Load video by path"""
        # Save current frame position and score for the previous video
        if self.video_path:
            self.last_frame_positions[self.video_path] = self.video_player.current_frame
            self.last_video_scores[self.video_path] = self.gamification_manager.total_score

        # Reset view-only mode for new video
        self.view_only_mode = False

        # Record video load time for statistics
        self.video_load_time = time.time()

        if self.video_player.load_video(file_path):
            self.video_path = file_path
            self.video_path_label.setText(os.path.basename(file_path))
            self.annotations = {}  # Reset annotations for new video

            # Load score for the new video, or initialize to 0
            initial_score = self.last_video_scores.get(file_path, 0)
            self.gamification_manager.set_total_score(initial_score) # Set the score in the manager

            # Try to autoload CSV if exists with flexible behavior handling
            self.annotations = self.load_annotations_with_behavior_handling(file_path)

            # Update VideoPlayer with current annotations for overlay preview bars
            self.video_player.annotations = self.annotations

            # Determine starting frame: last saved position, or last annotated frame, or frame 0
            start_frame = 0

            # First priority: saved frame position for this video
            if file_path in self.last_frame_positions:
                start_frame = self.last_frame_positions[file_path]

            # Second priority: last annotated frame (if annotations exist)
            elif self.annotations:
                start_frame = max(self.annotations.keys())

            # Go to the determined starting frame
            self.video_player.goto_frame(start_frame)
            # Force UI update to reflect the new frame
            self.video_player.update()
            QCoreApplication.processEvents()  # Process any pending UI events
            self.on_frame_changed(start_frame)

            # Update timeline
            self.timeline.total_frames = self.video_player.total_frames
            self.timeline.current_frame = start_frame # Ensure timeline current frame is set to start_frame
            self.timeline.update()
            self.timeline.ensure_marker_visible() # Ensure marker is visible after update

            # Update timeline with annotations
            self.update_timeline_annotations()

            # Save as last video
            self.last_video_path = file_path
            self.save_settings()

    def load_video_dialog(self):
        """Open dialog to load video file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "",
            "Video Files (*.mp4 *.avi *.mov *.mkv *.wmv)"
        )

        if file_path:
            self.load_video_by_path(file_path)
            self.loading_screen.show() # Show loading screen when video starts loading
            
    def load_next_video_in_main_ui(self):
        """Load the next alphabetical video in the same folder as the currently opened video."""
        if not self.video_path or not os.path.exists(self.video_path):
            QMessageBox.warning(self, "Error", "No video currently loaded or path does not exist.")
            return

        # Show statistics popup if enabled
        if self.show_statistics_popup:
            statistics = self.calculate_statistics()
            dialog = StatisticsDialog(statistics, self)
            dialog.exec()

        current_dir = os.path.dirname(self.video_path)
        video_files = []
        for f in os.listdir(current_dir):
            if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.wmv')):
                video_files.append(os.path.join(current_dir, f))

        video_files.sort() # Sort alphabetically

        if not video_files:
            QMessageBox.warning(self, "Error", "No video files found in the current directory.")
            return

        try:
            current_video_index = video_files.index(self.video_path)
            next_video_index = (current_video_index + 1) % len(video_files)
            next_video_path = video_files[next_video_index]
            self.save_annotations() # Save current video annotations before loading the next
            self.load_video_by_path(next_video_path)
            self.loading_screen.show() # Show loading screen when video starts loading
            self.loading_screen.set_loading_text("Loading next video...")
            self.loading_screen.raise_() # Bring to front
            QCoreApplication.processEvents() # Process events to ensure loading screen is shown
        except ValueError:
            QMessageBox.warning(self, "Error", "Current video not found in its directory. Please select a new video.")
            return

            self.loading_screen.set_loading_text("Loading video...")
            self.loading_screen.raise_() # Bring to front
            QCoreApplication.processEvents() # Process events to ensure loading screen is shown
                
    def load_behavior_dialog(self):
        """Open dialog to load behavior file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Behavior CSV File", "", 
            "CSV Files (*.csv)"
        )
        
        if file_path:
            try:
                df = pd.read_csv(file_path)
                # Get behavior names (skip first column which is 'Frames')
                behaviors = df.columns.tolist()[1:]
                self.behavior_buttons.load_behaviors(behaviors)
                # Update video player with new behaviors
                self.video_player.available_behaviors = behaviors
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not load behavior file: {str(e)}")
                
    def on_frame_changed(self, frame_number):
        """Handle frame change events"""
        self.timeline.current_frame = frame_number
        self.timeline.ensure_marker_visible()
        self.timeline.update()

        # The video_player.current_behavior updates directly within VideoPlayer.goto_frame but video_player.annotations should be up-to-date for other logic/timeline.
        # The update_annotations_on_frame_change function is still useful for its side effects but its return value for current_behavior is no longer directly assigned here.
        update_annotations_on_frame_change(
            self.annotations, frame_number, self.video_player, self.video_player.available_behaviors
        )

        # Ensure VideoPlayer's annotations are always in sync with the main annotations
        self.video_player.annotations = self.annotations



    def on_label_state_changed(self, behavior, is_active, start_frame, end_frame): # Updated signature
        if self.view_only_mode:
            QMessageBox.information(self, "Preview Only Mode", "Cannot modify annotations in view-only mode.")
            return

        current_frame = self.video_player.current_frame # This is still the current frame of the video player

        # For deactivation, calculate duration before removing the label
        duration_frames = 0
        frame_for_gamification = current_frame # Default to current_frame

        if not is_active:
            # Use the provided start_frame and end_frame for duration calculation
            duration_frames = end_frame - start_frame + 1
            frame_for_gamification = end_frame # Use the actual end frame of the segment for gamification

        # handle_label_state_change now updates video_player.current_behavior internally
        # This function still operates on the current_frame of the video player,
        # which is fine for updating the UI, but not for gamification scoring.
        handle_label_state_change(
            self.annotations, behavior, is_active, current_frame, self.video_player
        )

        # Call gamification manager when a label is applied or deactivated
        if is_active:
            self.gamification_manager.label_applied(current_frame, behavior)
        else:
            self.gamification_manager.label_completed(frame_for_gamification, behavior, duration_frames)

        # Ensure VideoPlayer's annotations are always in sync with the main annotations
        self.video_player.annotations = self.annotations

        # Deselect behavior buttons if no behaviors active
        if not any(self.video_player.active_labels.values()):
            for btn in self.behavior_buttons.buttons:
                btn.button.setChecked(False)

        # Update timeline with new annotations
        self.update_timeline_annotations()

    def _calculate_behavior_segment_duration(self, current_frame, behavior):
        """Calculate the duration (in frames) of the behavior segment that ends at current_frame"""
        # Find the start of the current behavior segment by going backwards from current_frame
        start_frame = current_frame
        while start_frame > 0 and self.annotations.get(start_frame - 1) == behavior:
            start_frame -= 1

        # Calculate duration (inclusive of start and end frames)
        duration_frames = current_frame - start_frame + 1
        return duration_frames

    def on_behavior_toggled(self, behavior):
        """Handle behavior toggle from button"""
        if self.view_only_mode:
            QMessageBox.information(self, "Preview Only Mode", "Cannot modify annotations in view-only mode.")
            return
        self.video_player.toggle_label(behavior)
        self.video_player.setFocus()
        
    def on_behavior_added(self, behavior):
        """Handle behavior added"""
        # Save behavior settings
        self.save_behavior_settings()
        # Update video player with new behaviors
        self.video_player.available_behaviors = self.behavior_buttons.behaviors
        # Update timeline colors
        self.update_timeline_annotations()

    def on_behavior_removed(self, behavior):
        """Handle behavior removed"""
        # Save behavior settings
        self.save_behavior_settings()
        # Update video player with new behaviors
        self.video_player.available_behaviors = self.behavior_buttons.behaviors
        # Remove from annotations if present
        handle_behavior_removal(self.annotations, behavior, self.behavior_buttons.behaviors)
        # Update timeline
        self.update_timeline_annotations()

    def on_check_label_removal(self, target_frame):
        """Check if labels should be removed from subsequent frames when moving backwards with key held or behavior active"""
        if self.view_only_mode:
            return  # Don't modify annotations in view-only mode

        # check_label_removal_on_backward_navigation now updates video_player.current_behavior internally
        removed_labels = check_label_removal_on_backward_navigation(
            self.annotations, target_frame, self.video_player, self.video_player.available_behaviors
        )

        # Call gamification manager for each removed label
        for frame, behavior in removed_labels:
            self.gamification_manager.label_removed(frame, behavior)

        # Ensure VideoPlayer's annotations are always in sync with the main annotations
        self.video_player.annotations = self.annotations

        # Update timeline
        self.update_timeline_annotations()

    def remove_labels_from_current_frame(self):
        """Remove all labels from the current frame"""
        if self.view_only_mode:
            QMessageBox.information(self, "Preview Only Mode", "Cannot modify annotations in view-only mode.")
            return

        current_frame = self.video_player.current_frame
        # Get the behavior that was removed before calling remove_labels_from_frame
        removed_behavior = self.annotations.get(current_frame)
        # remove_labels_from_frame now updates video_player.current_behavior internally
        remove_labels_from_frame(
            self.annotations, current_frame, self.video_player
        )

        # Call gamification manager if a label was removed
        if removed_behavior:
            self.gamification_manager.label_removed(current_frame, removed_behavior)

        # Ensure VideoPlayer's annotations are always in sync with the main annotations
        self.video_player.annotations = self.annotations

        # Update timeline
        self.update_timeline_annotations()

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts"""
        # Build key sequence string from modifiers and key
        modifier_str = ""
        if event.modifiers() & Qt.ControlModifier:
            modifier_str += "Ctrl+"
        if event.modifiers() & Qt.ShiftModifier:
            modifier_str += "Shift+"
        if event.modifiers() & Qt.AltModifier:
            modifier_str += "Alt+"
        if event.modifiers() & Qt.MetaModifier:
            modifier_str += "Meta+"
        key_str = QKeySequence(event.key()).toString()
        key_sequence = modifier_str + key_str

        # Check custom shortcuts
        if key_sequence == self.shortcuts['save']:
            self.save_annotations()
            return
        elif key_sequence == self.shortcuts['load_video']:
            self.load_video_dialog()
            return
        elif key_sequence == self.shortcuts['load_next_video']: # Handle new shortcut
            self.load_next_video_in_main_ui()
            return
        elif key_sequence == self.shortcuts['next_frame']:
            if self.video_player.total_frames > 0:
                next_frame = min(self.video_player.current_frame + 1, self.video_player.total_frames - 1)
                self.video_player.goto_frame(next_frame)
            return
        elif key_sequence == self.shortcuts['prev_frame']:
            if self.video_player.total_frames > 0:
                prev_frame = max(self.video_player.current_frame - 1, 0)
                self.video_player.goto_frame(prev_frame)
            return
        elif key_sequence == self.shortcuts['delete']:
            if self.view_only_mode:
                QMessageBox.information(self, "Preview Only Mode", "Cannot modify annotations in view-only mode.")
                return
            self.remove_labels_from_current_frame()
            return
        # Check behavior shortcuts 1-10
        for i in range(1, 11):
            if key_sequence == self.shortcuts[f'toggle_behavior_{i}'] and len(self.behavior_buttons.behaviors) >= i:
                if self.view_only_mode:
                    QMessageBox.information(self, "Preview Only Mode", "Cannot modify annotations in view-only mode.")
                    return
                self.behavior_buttons.toggle_behavior(self.behavior_buttons.behaviors[i-1])
                return

        super().keyPressEvent(event)

    def save_annotations(self):
        """Save annotations to CSV file in video2_2.csv format"""
        if self.view_only_mode:
            QMessageBox.information(self, "Preview Only Mode", "Cannot save annotations in view-only mode.")
            return
        save_annotations_to_csv(self.video_path, self.annotations, self.behavior_buttons.behaviors, self.statusBar())

    def auto_save_annotations(self):
        """Automatically save annotations"""
        if self.view_only_mode:
            return  # Don't auto-save in view-only mode
        if self.video_path: # Only auto-save if a video is loaded
            self.statusBar().showMessage("Auto-saving annotations...", 2000) # Show message for 2 seconds
            self.save_annotations()

    def set_controls_enabled(self, enabled):
        """Enable or disable interactive controls"""
        self.behavior_buttons.setEnabled(enabled)
        self.timeline.setEnabled(enabled)
        self.save_btn.setEnabled(enabled)
        # Disable menu actions that interact with video/annotations
        for action in self.menuBar().actions():
            if action.text() == 'File':
                for sub_action in action.menu().actions():
                    if sub_action.text() in ['Save Annotations']:
                        sub_action.setEnabled(enabled)
            # Also disable input settings if no video is loaded, as they affect video player
            if action.text() == 'Settings':
                for sub_action in action.menu().actions():
                    if sub_action.text() in ['Input Settings']:
                        sub_action.setEnabled(enabled)

    def update_loading_progress(self, current, total):
        """Update the loading screen progress"""
        if self.loading_screen.isVisible():
            progress = 0.0
            if total > 0:
                progress = current / total
            self.loading_screen.set_animation_progress(progress)
            self.loading_screen.set_loading_text(f"Caching frames: {current}/{total}")
            QCoreApplication.processEvents() # Ensure UI updates

    def on_caching_complete(self):
        """Handle caching complete event from VideoPlayer"""
        self.statusBar().showMessage("Cached & ready", 500)
        self.set_controls_enabled(True)
        self.video_player.setFocus() # Ensure video player has focus for immediate key input
        self.loading_screen.hide() # Hide loading screen

    def closeEvent(self, event):
        """Handle application close event to save settings."""
        if self.video_path: # Only save score if a video was loaded
            self.last_video_scores[self.video_path] = self.gamification_manager.total_score
        self.save_settings() # Save general settings
        self.gamification_manager.save_settings(self.gamification_settings) # Save gamification settings
        super().closeEvent(event)

    def resizeEvent(self, event):
        """Handle resize event to reposition overlay widgets."""
        super().resizeEvent(event)
        # Position LiveScoreWidget at the bottom-left of the video player
        if self.video_player and self.live_score_widget:
            # Define padding from bottom and left edges
            padding = 40 # Increased padding to move it up
            # Calculate position for bottom-left
            x = padding
            y = self.video_player.height() - self.live_score_widget.height() - padding
            self.live_score_widget.setGeometry(x, y, self.live_score_widget.width(), self.live_score_widget.height())

    def calculate_statistics(self):
        """Calculate annotation statistics for the current video"""
        statistics = {}

        # Calculate video duration
        if hasattr(self.video_player, 'frame_rate') and self.video_player.frame_rate > 0:
            video_duration = self.video_player.total_frames / self.video_player.frame_rate
            statistics['video_duration'] = video_duration
        else:
            statistics['video_duration'] = 0

        # Calculate annotation time (time since video was loaded)
        if hasattr(self, 'video_load_time') and self.video_load_time:
            annotation_time = time.time() - self.video_load_time
            statistics['annotation_time'] = annotation_time
        else:
            statistics['annotation_time'] = 0

        # Calculate annotation speed (video duration / annotation time)
        if statistics['annotation_time'] > 0:
            statistics['annotation_speed'] = statistics['video_duration'] / statistics['annotation_time']
        else:
            statistics['annotation_speed'] = 0

        # Calculate behavior statistics
        behavior_stats = {}
        for behavior in self.behavior_buttons.behaviors:
            # Count occurrences (blocks) and find max duration
            block_count = 0
            total_frames = 0
            max_duration = 0
            current_start = None

            for frame in range(self.video_player.total_frames):
                if self.annotations.get(frame) == behavior:
                    if current_start is None:
                        current_start = frame
                        block_count += 1
                    total_frames += 1
                else:
                    if current_start is not None:
                        # Calculate duration of this segment
                        duration = (frame - current_start) / self.video_player.frame_rate
                        max_duration = max(max_duration, duration)
                        current_start = None

            # Check if behavior continues to end of video
            if current_start is not None:
                duration = (self.video_player.total_frames - current_start) / self.video_player.frame_rate
                max_duration = max(max_duration, duration)

            behavior_stats[behavior] = {
                'block_count': block_count,
                'total_frames': total_frames,
                'max_duration': max_duration
            }

        # Calculate overall labeling statistics
        total_labeled_frames = sum(stats['total_frames'] for stats in behavior_stats.values())
        total_frames = self.video_player.total_frames
        labeled_percentage = (total_labeled_frames / total_frames) * 100 if total_frames > 0 else 0
        unlabeled_percentage = 100 - labeled_percentage

        statistics['labeling_stats'] = {
            'total_labeled_frames': total_labeled_frames,
            'total_frames': total_frames,
            'labeled_percentage': labeled_percentage,
            'unlabeled_percentage': unlabeled_percentage
        }

        statistics['behaviors'] = behavior_stats
        return statistics

    def show_startup_dialog(self):
        """Show welcome dialog to choose video"""
        dialog = WelcomeDialog(self.last_video_path, self)
        if dialog.exec() == QDialog.Accepted and dialog.selected_video_path:
            self.load_video_by_path(dialog.selected_video_path)
            
def main():
    # Record program start time
    program_start_time = time.time()

    app = QApplication(sys.argv)
    window = VideoAnnotator()
    window.program_start_time = program_start_time
    window.video_player.program_start_time = program_start_time

    # Show welcome dialog first (don't show main window yet)
    dialog = WelcomeDialog(window.last_video_path)
    # Connect controller rescan signal to reinitialize VideoPlayer gamepad
    dialog.controllers_rescanned.connect(window.video_player.init_gamepad)
    if dialog.exec() == QDialog.Accepted and dialog.selected_video_path:
        # Load the selected video
        window.load_video_by_path(dialog.selected_video_path)
        # Now show the main window
        window.show()
        sys.exit(app.exec())
    else:
        # No video selected, exit
        sys.exit(0)


class ControllerAutomapDialog(QDialog):
    """Dialog for controller automapping"""
    def __init__(self, behaviors, current_mappings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Controller Automapping")
        self.setModal(True)
        # Filter out fast_backward if it exists, fast_forward is used for both directions
        self.behaviors = [b for b in behaviors if b != "fast_backward"]
        self.current_mappings = current_mappings.copy() # Make a mutable copy
        self.listening_for_input = False
        self.target_behavior = None
        self.joystick = None
        self.baseline_axis_values = {} # Store initial axis values when listening starts

        self.setup_ui()
        self.init_pygame_joystick()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        info_label = QLabel("Click 'Listen' next to a behavior or action, then press a button on your controller to map it.")
        layout.addWidget(info_label)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        self.populate_behavior_list()

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults,
            Qt.Horizontal, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_default_mappings)
        layout.addWidget(buttons)

        self.gamepad_timer = QTimer(self)
        self.gamepad_timer.timeout.connect(self.poll_gamepad_for_mapping)
        self.listen_delay_timer = None # Initialize delay timer

    def populate_behavior_list(self):
        self.list_widget.clear()
        for behavior in self.behaviors:
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(0, 0, 0, 0)

            behavior_label = QLabel(behavior)
            item_layout.addWidget(behavior_label)

            mapped_button_label = QLabel(self.get_mapped_button_name(behavior))
            mapped_button_label.setObjectName(f"mapped_label_{behavior}") # Unique object name for easy access
            item_layout.addWidget(mapped_button_label)

            listen_button = QPushButton("Listen")
            listen_button.clicked.connect(lambda checked, b=behavior: self.start_listening(b))
            item_layout.addWidget(listen_button)

            clear_button = QPushButton("Clear")
            clear_button.clicked.connect(lambda checked, b=behavior: self.clear_mapping(b))
            item_layout.addWidget(clear_button)

            self.list_widget.addItem(QListWidgetItem())
            self.list_widget.setItemWidget(self.list_widget.item(self.list_widget.count() - 1), item_widget)

    def get_mapped_button_name(self, behavior):
        """Returns the human-readable name of the button mapped to a behavior."""
        for button_name, mapped_behavior in self.current_mappings.items():
            if mapped_behavior == behavior:
                return f"Mapped to: {button_name}"
        return "Not mapped"

    def init_pygame_joystick(self):
        pygame.init()
        pygame.joystick.init()
        if pygame.joystick.get_count() > 0:
            try:
                self.joystick = pygame.joystick.Joystick(0)
                self.joystick.init()
            except pygame.error as e:
                QMessageBox.warning(self, "Controller Error", f"Could not initialize joystick: {e}")
                self.joystick = None
        else:
            QMessageBox.information(self, "No Controller", "No game controller detected.")
            self.joystick = None

    def start_listening(self, behavior):
        if not self.joystick:
            QMessageBox.warning(self, "No Controller", "No game controller detected or initialized.")
            return

        self.listening_for_input = True
        self.target_behavior = behavior
        self.list_widget.setEnabled(False) # Disable list while listening

        # Record baseline axis values
        self.baseline_axis_values = {}
        for i in range(self.joystick.get_numaxes()):
            try:
                self.baseline_axis_values[i] = self.joystick.get_axis(i)
            except pygame.error:
                self.baseline_axis_values[i] = 0.0

        # Start a short delay timer before actually polling for input
        self.listen_delay_timer = QTimer(self)
        self.listen_delay_timer.setSingleShot(True)
        self.listen_delay_timer.timeout.connect(self._start_polling_after_delay)
        self.listen_delay_timer.start(500) # 500ms delay before polling starts

    def poll_gamepad_for_mapping(self):
        if not self.listening_for_input or not self.joystick:
            return

        pygame.event.pump() # Process pygame events

        # Check for button presses
        for i in range(self.joystick.get_numbuttons()):
            button_state = self.joystick.get_button(i)
            if button_state:
                button_name = f"Button {i}"
                self.map_button_to_behavior(button_name, self.target_behavior)
                self.stop_listening()
                return

        # Check for hat presses (D-pad)
        for i in range(self.joystick.get_numhats()):
            hat_x, hat_y = self.joystick.get_hat(i)
            if hat_x != 0 or hat_y != 0:
                hat_direction = ""
                if hat_x == 1: hat_direction = "Right"
                elif hat_x == -1: hat_direction = "Left"
                elif hat_y == 1: hat_direction = "Up"
                elif hat_y == -1: hat_direction = "Down"
                button_name = f"Hat {i} {hat_direction}"
                self.map_button_to_behavior(button_name, self.target_behavior)
                self.stop_listening()
                return

        # Check for axis movement (joysticks/triggers)
        for i in range(self.joystick.get_numaxes()):
            axis_value = self.joystick.get_axis(i)
            baseline_value = self.baseline_axis_values.get(i, 0.0)
            
            # Threshold for detecting significant movement
            activation_threshold = 0.5 

            # Case 1: Axis is a "trigger-like" axis that rests at -1.0 and moves to 1.0
            # If baseline is near -1.0 -> positive movement
            if baseline_value < -0.9 and axis_value > activation_threshold:
                button_name = f"Axis {i} Positive"
                self.map_button_to_behavior(button_name, self.target_behavior)
                self.stop_listening()
                return
            # Case 2: Axis is a "trigger-like" axis that rests at 1.0 and moves to -1.0 (inverted)
            # If baseline is near 1.0 -> negative movement
            elif baseline_value > 0.9 and axis_value < -activation_threshold:
                button_name = f"Axis {i} Negative"
                self.map_button_to_behavior(button_name, self.target_behavior)
                self.stop_listening()
                return
            # Case 3: General axis movement (joysticks, or other axes not at extremes)
            # Detect if the axis value has changed significantly from its baseline
            elif abs(axis_value - baseline_value) > activation_threshold:
                axis_direction = "Positive" if axis_value > baseline_value else "Negative"
                button_name = f"Axis {i} {axis_direction}"
                self.map_button_to_behavior(button_name, self.target_behavior)
                self.stop_listening()
                return

    def map_button_to_behavior(self, button_name, behavior):
        # Remove existing mapping for this behavior if it exists
        for key, value in list(self.current_mappings.items()):
            if value == behavior:
                del self.current_mappings[key]
        # Remove existing mapping for this button if it exists
        if button_name in self.current_mappings:
            del self.current_mappings[button_name]

        self.current_mappings[button_name] = behavior
        self.populate_behavior_list() # Refresh the list to show new mapping
        QMessageBox.information(self, "Mapped", f"'{behavior}' mapped to '{button_name}'.")

    def clear_mapping(self, behavior):
        """Clears the mapping for a specific behavior."""
        for button_name, mapped_behavior in list(self.current_mappings.items()):
            if mapped_behavior == behavior:
                del self.current_mappings[button_name]
                break
        self.populate_behavior_list() # Refresh the list

    def stop_listening(self):
        self.listening_for_input = False
        self.target_behavior = None
        self.gamepad_timer.stop()
        self.list_widget.setEnabled(True) # Re-enable list
        if self.listen_delay_timer and self.listen_delay_timer.isActive():
            self.listen_delay_timer.stop()

    def restore_default_mappings(self):
        self.current_mappings = {} # Clear all mappings
        self.populate_behavior_list()
        QMessageBox.information(self, "Defaults Restored", "All controller mappings have been cleared.")

    def get_mappings(self):
        return self.current_mappings

    def reject(self):
        self.stop_listening()
        super().reject()

    def accept(self):
        self.stop_listening()
        super().accept()

    def closeEvent(self, event):
        self.stop_listening()
        pygame.joystick.quit()
        pygame.quit()
        if self.listen_delay_timer and self.listen_delay_timer.isActive():
            self.listen_delay_timer.stop()
        super().closeEvent(event)

    def _start_polling_after_delay(self):
        """Starts the gamepad polling after the initial delay."""
        self.gamepad_timer.start(50) # Start polling


class BehaviorChart(QWidget):
    """Custom widget to display a bar chart of behavior frame counts"""

    def __init__(self, behavior_data, behavior_colors, parent=None):
        super().__init__(parent)
        self.behavior_data = behavior_data
        self.behavior_colors = behavior_colors
        self.setMinimumHeight(200)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Get dimensions
        width = self.width()
        height = self.height()

        if not self.behavior_data:
            return

        # Find max frames for scaling
        max_frames = max(stats['total_frames'] for stats in self.behavior_data.values()) if self.behavior_data else 1

        # Chart margins
        margin_left = 60
        margin_right = 20
        margin_top = 60
        margin_bottom = 40

        chart_width = width - margin_left - margin_right
        chart_height = height - margin_top - margin_bottom

        # Draw title
        title_font = QFont()
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(0, 15, width, 20, Qt.AlignCenter, "Behavior Frame Counts")

        # Draw bars
        bar_width = chart_width / len(self.behavior_data) if self.behavior_data else 0
        x = margin_left

        for behavior, stats in self.behavior_data.items():
            frames = stats['total_frames']
            if max_frames > 0:
                bar_height = (frames / max_frames) * chart_height
            else:
                bar_height = 0

            # Get color for behavior
            color = self.behavior_colors.get(behavior, QColor(100, 100, 100))
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(color.darker(), 1))

            # Draw bar
            bar_x = x
            bar_y = height - margin_bottom - bar_height
            painter.drawRect(int(bar_x), int(bar_y), int(bar_width - 5), int(bar_height))

            # Draw label
            label_font = QFont()
            label_font.setPointSize(8)
            painter.setFont(label_font)
            painter.setPen(QPen(Qt.black))

            # Rotate and draw behavior name
            painter.save()
            painter.translate(bar_x + bar_width/2, height - margin_bottom + 15)
            painter.rotate(-45)
            painter.drawText(-30, 0, 60, 20, Qt.AlignCenter, behavior[:10])  # Truncate long names
            painter.restore()

            # Draw frame count above bar
            painter.setPen(QPen(Qt.black))
            painter.drawText(int(bar_x), int(bar_y - 5), int(bar_width), 20, Qt.AlignCenter, str(frames))

            x += bar_width

        # Draw axes
        painter.setPen(QPen(Qt.black, 2))
        # Y-axis
        painter.drawLine(margin_left, margin_top, margin_left, height - margin_bottom)
        # X-axis
        painter.drawLine(margin_left, height - margin_bottom, width - margin_right, height - margin_bottom)

        # Draw Y-axis labels
        painter.setFont(QFont())
        for i in range(0, max_frames + 1, max(1, max_frames // 5)):
            y_pos = height - margin_bottom - (i / max_frames) * chart_height if max_frames > 0 else height - margin_bottom
            painter.drawText(5, int(y_pos - 5), margin_left - 10, 20, Qt.AlignRight, str(i))


class PieChart(QWidget):
    """Custom widget to display a pie chart of labeling statistics"""

    def __init__(self, labeling_stats, parent=None):
        super().__init__(parent)
        self.labeling_stats = labeling_stats
        self.setMinimumHeight(250)
        self.setMinimumWidth(250)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Get dimensions
        width = self.width()
        height = self.height()

        if not self.labeling_stats or self.labeling_stats['total_frames'] == 0:
            return

        # Chart dimensions
        center_x = width // 2
        center_y = height // 2
        radius = min(width, height) // 2 - 40

        # Data
        labeled_percentage = self.labeling_stats['labeled_percentage']
        unlabeled_percentage = self.labeling_stats['unlabeled_percentage']

        # Colors
        labeled_color = QColor(100, 200, 100)  # Green for labeled
        unlabeled_color = QColor(200, 100, 100)  # Red for unlabeled

        # Draw title
        title_font = QFont()
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(0, 15, width, 20, Qt.AlignCenter, "Frame Labeling Overview")

        # Draw pie chart
        start_angle = 0

        # Labeled portion
        if labeled_percentage > 0:
            labeled_angle = int(labeled_percentage * 16 * 3.6)  # Convert to 16ths of degree
            painter.setBrush(QBrush(labeled_color))
            painter.setPen(QPen(labeled_color.darker(), 2))
            painter.drawPie(center_x - radius, center_y - radius, radius * 2, radius * 2, start_angle, labeled_angle)
            start_angle += labeled_angle

        # Unlabeled portion
        if unlabeled_percentage > 0:
            unlabeled_angle = int(unlabeled_percentage * 16 * 3.6)  # Convert to 16ths of degree
            painter.setBrush(QBrush(unlabeled_color))
            painter.setPen(QPen(unlabeled_color.darker(), 2))
            painter.drawPie(center_x - radius, center_y - radius, radius * 2, radius * 2, start_angle, unlabeled_angle)

        # Draw legend
        legend_x = 20
        legend_y = height - 60

        # Labeled legend
        painter.setBrush(QBrush(labeled_color))
        painter.setPen(QPen(Qt.black, 1))
        painter.drawRect(legend_x, legend_y, 15, 15)
        painter.setPen(QPen(Qt.black))
        painter.setFont(QFont())
        painter.drawText(legend_x + 20, legend_y + 12, f"Labeled: {labeled_percentage:.1f}%")

        # Unlabeled legend
        painter.setBrush(QBrush(unlabeled_color))
        painter.setPen(QPen(Qt.black, 1))
        painter.drawRect(legend_x, legend_y + 20, 15, 15)
        painter.setPen(QPen(Qt.black))
        painter.drawText(legend_x + 20, legend_y + 32, f"Unlabeled: {unlabeled_percentage:.1f}%")


class StatisticsDialog(QDialog):
    """Dialog to display annotation statistics"""

    def __init__(self, statistics, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Annotation Statistics")
        self.setModal(True)
        self.statistics = statistics
        # Get behavior colors from parent and convert to QColor
        self.behavior_colors = {}
        if parent and hasattr(parent, 'behavior_buttons'):
            for behavior in parent.behavior_buttons.behaviors:
                color_str = parent.behavior_buttons.get_behavior_color(behavior)
                if isinstance(color_str, str):
                    # Convert hex string to QColor
                    if color_str.startswith('#'):
                        self.behavior_colors[behavior] = QColor(color_str)
                    else:
                        self.behavior_colors[behavior] = QColor(100, 100, 100)  # Default gray
                else:
                    self.behavior_colors[behavior] = color_str
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Title
        # Create scroll area for statistics
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        # Pie chart for labeling overview
        if 'labeling_stats' in self.statistics and self.statistics['labeling_stats']['total_frames'] > 0:
            pie_group = QGroupBox("Labeling Overview")
            pie_layout = QVBoxLayout(pie_group)
            pie_chart = PieChart(self.statistics['labeling_stats'])
            pie_layout.addWidget(pie_chart)
            scroll_layout.addWidget(pie_group)

        # Behavior chart
        if 'behaviors' in self.statistics and self.statistics['behaviors']:
            chart_group = QGroupBox("Behavior Frame Distribution")
            chart_layout = QVBoxLayout(chart_group)
            chart = BehaviorChart(self.statistics['behaviors'], self.behavior_colors)
            chart_layout.addWidget(chart)
            scroll_layout.addWidget(chart_group)

        # Behavior statistics
        if 'behaviors' in self.statistics and self.statistics['behaviors']:
            behavior_group = QGroupBox("Behavior Statistics")
            behavior_layout = QVBoxLayout(behavior_group)

            for behavior, stats in self.statistics['behaviors'].items():
                behavior_label = QLabel(f"{behavior}: {stats['block_count']} blocks, max duration: {stats['max_duration']:.2f}s")
                behavior_layout.addWidget(behavior_label)

            scroll_layout.addWidget(behavior_group)

        # Timing statistics
        timing_group = QGroupBox("Timing Statistics")
        timing_layout = QVBoxLayout(timing_group)

        if 'annotation_time' in self.statistics:
            time_label = QLabel(f"Annotation time: {self.statistics['annotation_time']:.2f} seconds")
            timing_layout.addWidget(time_label)

        if 'video_duration' in self.statistics:
            duration_label = QLabel(f"Video duration: {self.statistics['video_duration']:.2f} seconds")
            timing_layout.addWidget(duration_label)

        if 'annotation_speed' in self.statistics:
            speed_label = QLabel(f"Annotation speed: {self.statistics['annotation_speed']:.2f}x real-time")
            timing_layout.addWidget(speed_label)

        scroll_layout.addWidget(timing_group)

        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        layout.addWidget(scroll_area)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok, Qt.Horizontal, self)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self.setMinimumWidth(600)
        self.setMinimumHeight(500)


if __name__ == "__main__":
    main()
