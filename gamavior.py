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
                              QGroupBox, QTabWidget, QCheckBox, QSplitter, QListWidget, QListWidgetItem, QMenu) # Added QCheckBox, QSplitter, QListWidget, QListWidgetItem, QMenu
from PySide6.QtCore import Qt, QTimer, QSettings, QCoreApplication, Signal
from PySide6.QtGui import QKeySequence, QFont
from PySide6.QtSvgWidgets import QSvgWidget

# Suppress pygame messages
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
# Suppress Qt warnings
os.environ['QT_LOGGING_RULES'] = '*.warning=false'
# Suppress warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")
warnings.filterwarnings("ignore")

import pygame

from annotator_libs.video_handling import VideoPlayer
from annotator_libs.ui_components import BehaviorButtons, TimelineWidget, LoadingScreen
from annotator_libs.annotation_logic import (
    load_behaviors_from_csv, save_behaviors_to_csv, load_annotations_from_csv,
    save_annotations_to_csv, update_annotations_on_frame_change,
    handle_label_state_change, remove_labels_from_frame,
    check_label_removal_on_backward_navigation, handle_behavior_removal
)


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
        self.setWindowTitle("Gamavior")
        self.setModal(True)
        self.setFixedSize(500, 400)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(20)

        # Title
        title_label = QLabel("Gamavior")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        # Logo - conditionally show controller or mouse logo
        logo_file = "controller-logo.svg" if self.controller_count > 0 else "mouse-logo.svg"
        self.logo_widget = QSvgWidget(logo_file)
        self.logo_widget.setFixedSize(100, 100)
        layout.addWidget(self.logo_widget, alignment=Qt.AlignCenter)

        # Controller info or rescan button
        if self.controller_count > 0:
            controller_label = QLabel(f"Controller: {self.controller_name}")
            controller_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(controller_label, alignment=Qt.AlignCenter)
        else:
            # Rescan Controllers button
            rescan_btn = QPushButton("Rescan Controllers")
            rescan_btn.setFixedWidth(180)
            rescan_btn.clicked.connect(self.rescan_controllers)
            layout.addWidget(rescan_btn, alignment=Qt.AlignCenter)

        # Spacer
        layout.addStretch()

        # Options
        if self.last_video_path and os.path.exists(self.last_video_path):
            # Show last video option
            last_video_name = os.path.basename(self.last_video_path)
            last_video_label = QLabel(f"Last opened video: {last_video_name}")
            last_video_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(last_video_label)

            open_last_btn = QPushButton("Open Last Video")
            open_last_btn.setFixedWidth(200)
            open_last_btn.clicked.connect(self.open_last_video)
            layout.addWidget(open_last_btn, alignment=Qt.AlignCenter)

            # Separator
            separator = QLabel("or")
            separator.setAlignment(Qt.AlignCenter)
            layout.addWidget(separator)

            # Open next video button
            open_next_btn = QPushButton("Open Next Video")
            open_next_btn.setFixedWidth(200)
            open_next_btn.clicked.connect(self.open_next_video)
            layout.addWidget(open_next_btn, alignment=Qt.AlignCenter)

            # Separator
            separator2 = QLabel("or")
            separator2.setAlignment(Qt.AlignCenter)
            layout.addWidget(separator2)

        # New video button
        select_new_btn = QPushButton("Select New Video")
        select_new_btn.setFixedWidth(200)
        select_new_btn.clicked.connect(self.select_new_video)
        layout.addWidget(select_new_btn, alignment=Qt.AlignCenter)

        # Spacer
        layout.addStretch()

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
        logo_file = "controller-logo.svg" if self.controller_count > 0 else "mouse-logo.svg"
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
        self.behaviors_file = ""
        self.current_behavior = None
        # Initialize shortcuts first
        self.shortcuts = {}
        self.settings = QSettings('VideoAnnotator', 'Settings') # Initialize general settings here
        self.input_settings = QSettings('VideoAnnotator', 'InputSettings') # Initialize input settings here
        self.load_settings() # Load general settings including auto-save
        self.load_shortcuts()
        self.setup_ui()
        self.load_input_settings_on_startup() # Load input settings at startup
        # Apply loaded settings to video player
        self.video_player.update_label_key_mode(self.label_key_mode)
        self.video_player.set_show_overlay_bars(self.show_frame_preview_bars)
        self.video_player.update_input_settings(self.get_current_input_settings_for_startup()) # Apply input settings to video player

    def setup_ui(self):
        self.setWindowTitle("Gamavior")
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
        self.video_player = VideoPlayer()
        self.video_player.frame_changed.connect(self.on_frame_changed)
        self.video_player.label_toggled.connect(self.on_label_state_changed)
        self.video_player.remove_labels.connect(self.remove_labels_from_current_frame) # Re-enabled for debugging
        self.video_player.check_label_removal.connect(self.on_check_label_removal)
        left_panel.addWidget(self.video_player, stretch=1)  # Give video player priority

        # Timer for gamepad polling
        self.gamepad_timer = QTimer(self)
        self.gamepad_timer.timeout.connect(self.video_player.process_gamepad_input)
        self.gamepad_timer.start(50) # Poll every 50ms (20 FPS)

        # Timeline
        self.timeline = TimelineWidget()
        self.timeline.frame_clicked.connect(self.video_player.goto_frame)
        left_panel.addWidget(self.timeline, stretch=0)  # Timeline takes minimum space

        # Right panel - behavior buttons
        right_widget = QWidget()
        from PySide6.QtWidgets import QSizePolicy
        right_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        right_panel = QVBoxLayout(right_widget)

        # Video file selection
        file_layout = QHBoxLayout()
        self.video_path_label = QLabel("No video selected")
        load_video_btn = QPushButton("Load Video")
        load_video_btn.clicked.connect(self.load_video_dialog)
        file_layout.addWidget(QLabel("Video:"))
        file_layout.addWidget(self.video_path_label)
        file_layout.addWidget(load_video_btn)
        
        self.load_next_video_btn = QPushButton("Load Next Video")
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
        input_settings_action = settings_menu.addAction('Input Settings')
        input_settings_action.triggered.connect(self.show_input_settings_dialog)
        general_settings_action = settings_menu.addAction('General Settings')
        general_settings_action.triggered.connect(self.show_general_settings_dialog)


    def load_settings(self):
        """Load general application settings"""
        # self.settings is already initialized in __init__
        self.auto_save_enabled = self.settings.value('auto_save_enabled', False, bool)
        self.auto_save_interval = self.settings.value('auto_save_interval', 3, int) # Default 3 minutes
        self.hold_time = self.settings.value('hold_time', 50, int) # Default 50 ms
        self.label_key_mode = self.settings.value('label_key_mode', 'both', str) # Default both modes
        self.show_frame_preview_bars = self.settings.value('show_frame_preview_bars', True, bool) # Default enabled
        self.last_video_path = self.settings.value('last_video_path', '', str)
        # Load frame positions as JSON string and parse to dict
        frame_positions_json = self.settings.value('last_frame_positions', '{}', str)
        try:
            self.last_frame_positions = json.loads(frame_positions_json)
        except (json.JSONDecodeError, TypeError):
            self.last_frame_positions = {}

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
        self.settings.setValue('last_video_path', self.last_video_path)
        # Save frame positions as JSON string
        self.settings.setValue('last_frame_positions', json.dumps(self.last_frame_positions))

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
            self.auto_save_enabled = self.auto_save_checkbox.isChecked()
            self.auto_save_interval = self.auto_save_interval_spin.value()
            self.label_key_mode = self.label_key_mode_combo.currentData()
            self.show_frame_preview_bars = self.show_frame_preview_bars_checkbox.isChecked()
            self.save_settings() # Save general settings

            # Restart auto-save timer with new settings
            self.auto_save_timer.stop()
            if self.auto_save_enabled:
                self.auto_save_timer.start(self.auto_save_interval * 60 * 1000)

            # Update VideoPlayer with new label key mode setting
            self.video_player.update_label_key_mode(self.label_key_mode)

            # Update VideoPlayer with new frame preview bars setting
            self.video_player.set_show_overlay_bars(self.show_frame_preview_bars)

    def restore_default_general_settings(self):
        """Restore default general settings"""
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
        """Load default behaviors from behaviors.csv if available"""
        behaviors = load_behaviors_from_csv(parent=self)
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

    def update_timeline_annotations(self):
        """Update timeline with current annotations and behavior colors"""
        behavior_colors = {}
        for behavior in self.behavior_buttons.behaviors:
            behavior_colors[behavior] = self.behavior_buttons.get_behavior_color(behavior)

        self.timeline.set_annotations(self.annotations, behavior_colors)
        self.timeline.update()

    def load_video_by_path(self, file_path):
        """Load video by path"""
        # Save current frame position for the previous video
        if self.video_path:
            self.last_frame_positions[self.video_path] = self.video_player.current_frame

        if self.video_player.load_video(file_path):
            self.video_path = file_path
            self.video_path_label.setText(os.path.basename(file_path))
            self.annotations = {}  # Reset annotations for new video

            # Try to autoload CSV if exists
            self.annotations = load_annotations_from_csv(file_path, self.behavior_buttons.behaviors, parent=self)

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
                self.behaviors_file = file_path
                # Update video player with new behaviors
                self.video_player.available_behaviors = behaviors
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not load behavior file: {str(e)}")
                
    def on_frame_changed(self, frame_number):
        """Handle frame change events"""
        self.timeline.current_frame = frame_number
        self.timeline.ensure_marker_visible()
        self.timeline.update()

        # The video_player.current_behavior is now updated directly within VideoPlayer.goto_frame
        # However, we still need to ensure video_player.annotations is up-to-date for other logic
        # and the timeline needs to be updated.
        # The update_annotations_on_frame_change function is still useful for its side effects
        # (e.g., removing labels in removing_mode), but its return value for current_behavior
        # is no longer directly assigned here.
        update_annotations_on_frame_change(
            self.annotations, frame_number, self.video_player, self.video_player.available_behaviors
        )

        # Ensure VideoPlayer's annotations are always in sync with the main annotations
        self.video_player.annotations = self.annotations



    def on_label_state_changed(self, behavior, is_active):
        current_frame = self.video_player.current_frame
        # handle_label_state_change now updates video_player.current_behavior internally
        handle_label_state_change(
            self.annotations, behavior, is_active, current_frame, self.video_player
        )

        # Ensure VideoPlayer's annotations are always in sync with the main annotations
        self.video_player.annotations = self.annotations

        # Deselect behavior buttons if no behaviors active
        if not any(self.video_player.active_labels.values()):
            for btn in self.behavior_buttons.buttons:
                btn.setChecked(False)

        # Update timeline with new annotations
        self.update_timeline_annotations()

    def on_behavior_toggled(self, behavior):
        """Handle behavior toggle from button"""
        self.video_player.toggle_label(behavior)
        self.video_player.setFocus()
        
    def on_behavior_added(self, behavior):
        """Handle behavior added"""
        save_behaviors_to_csv(self.behavior_buttons.behaviors)
        # Update video player with new behaviors
        self.video_player.available_behaviors = self.behavior_buttons.behaviors
        # Update timeline colors
        self.update_timeline_annotations()

    def on_behavior_removed(self, behavior):
        """Handle behavior removed"""
        save_behaviors_to_csv(self.behavior_buttons.behaviors)
        # Update video player with new behaviors
        self.video_player.available_behaviors = self.behavior_buttons.behaviors
        # Remove from annotations if present
        handle_behavior_removal(self.annotations, behavior, self.behavior_buttons.behaviors)
        # Update timeline
        self.update_timeline_annotations()

    def on_check_label_removal(self, target_frame):
        """Check if labels should be removed from subsequent frames when moving backwards with key held or behavior active"""
        # check_label_removal_on_backward_navigation now updates video_player.current_behavior internally
        check_label_removal_on_backward_navigation(
            self.annotations, target_frame, self.video_player, self.video_player.available_behaviors
        )

        # Ensure VideoPlayer's annotations are always in sync with the main annotations
        self.video_player.annotations = self.annotations

        # Update timeline
        self.update_timeline_annotations()

    def remove_labels_from_current_frame(self):
        """Remove all labels from the current frame"""
        current_frame = self.video_player.current_frame
        # remove_labels_from_frame now updates video_player.current_behavior internally
        remove_labels_from_frame(
            self.annotations, current_frame, self.video_player
        )

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
            self.remove_labels_from_current_frame()
            return
        # Check behavior shortcuts 1-10
        for i in range(1, 11):
            if key_sequence == self.shortcuts[f'toggle_behavior_{i}'] and len(self.behavior_buttons.behaviors) >= i:
                self.behavior_buttons.toggle_behavior(self.behavior_buttons.behaviors[i-1])
                return

        super().keyPressEvent(event)

    def save_annotations(self):
        """Save annotations to CSV file in video2_2.csv format"""
        save_annotations_to_csv(self.video_path, self.annotations, self.behavior_buttons.behaviors, self.statusBar())

    def auto_save_annotations(self):
        """Automatically save annotations"""
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
        # Filter out fast_backward if it exists, since we now use fast_forward for both directions
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
        # print(f"DEBUG: poll_gamepad_for_mapping called. Listening: {self.listening_for_input}, Target: {self.target_behavior}") # Removed debug print

        # Check for button presses
        for i in range(self.joystick.get_numbuttons()):
            button_state = self.joystick.get_button(i)
            # print(f"DEBUG: Button {i} state: {button_state}") # Removed debug print
            if button_state:
                button_name = f"Button {i}"
                self.map_button_to_behavior(button_name, self.target_behavior)
                self.stop_listening()
                return

        # Check for hat presses (D-pad)
        for i in range(self.joystick.get_numhats()):
            hat_x, hat_y = self.joystick.get_hat(i)
            # print(f"DEBUG: Hat {i} state: ({hat_x}, {hat_y})") # Removed debug print
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
            # print(f"DEBUG: Axis {i} value: {axis_value}, baseline: {baseline_value}") # Removed debug print
            
            # Threshold for detecting significant movement
            activation_threshold = 0.5 

            # Case 1: Axis is a "trigger-like" axis that rests at -1.0 and moves to 1.0
            # If baseline is near -1.0, we detect positive movement
            if baseline_value < -0.9 and axis_value > activation_threshold:
                button_name = f"Axis {i} Positive"
                self.map_button_to_behavior(button_name, self.target_behavior)
                self.stop_listening()
                return
            # Case 2: Axis is a "trigger-like" axis that rests at 1.0 and moves to -1.0 (inverted)
            # If baseline is near 1.0, we detect negative movement
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


if __name__ == "__main__":
    main()
