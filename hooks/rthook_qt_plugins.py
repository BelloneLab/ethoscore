import os
import sys


def _setup_qt_plugins():
    """Ensure Qt can find its platform plugins at runtime."""
    if hasattr(sys, '_MEIPASS'):
        # PySide6 plugins are usually under sys._MEIPASS/PySide6/plugins/
        plugin_path = os.path.join(sys._MEIPASS, 'PySide6', 'plugins')
        if os.path.isdir(plugin_path):
            os.environ['QT_PLUGIN_PATH'] = plugin_path


_setup_qt_plugins()
