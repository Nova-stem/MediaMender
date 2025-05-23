#src/theme_manage.py
#23 May 2025

from enum import Enum
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt

class ThemeMode(Enum):
    SYSTEM = "system"
    DARK = "dark"
    LIGHT = "light"

def apply_theme(app: QApplication, mode: ThemeMode):
    if mode == ThemeMode.DARK:
        palette = _dark_palette()
    elif mode == ThemeMode.LIGHT:
        palette = _light_palette()
    else:
        if app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
            palette = _dark_palette()
        else:
            palette = _light_palette()
    app.setPalette(palette)

def _light_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#f0f0f0"))
    palette.setColor(QPalette.WindowText, Qt.black)
    palette.setColor(QPalette.Base, QColor("#ffffff"))               # input fields
    palette.setColor(QPalette.AlternateBase, QColor("#e8e8e8"))
    palette.setColor(QPalette.ToolTipBase, Qt.black)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.black)
    palette.setColor(QPalette.Button, QColor("#e0e0e0"))
    palette.setColor(QPalette.ButtonText, Qt.black)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(0, 122, 204))
    palette.setColor(QPalette.Highlight, QColor(0, 122, 204))        # selected item background
    palette.setColor(QPalette.HighlightedText, Qt.white)             # selected item text
    return palette

def _dark_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(45, 45, 45))               # e.g. input fields
    palette.setColor(QPalette.AlternateBase, QColor(35, 35, 35))
    palette.setColor(QPalette.ToolTipBase, QColor(50, 50, 50))
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(50, 50, 50))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))       # selected item background
    palette.setColor(QPalette.HighlightedText, Qt.black)             # selected item text
    return palette