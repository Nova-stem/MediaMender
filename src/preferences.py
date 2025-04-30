import os
import json
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QCheckBox, QMessageBox, QComboBox
)
from src.theme_manager import ThemeMode
from src.dialog import ThemedMessage

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.json"

class PreferencesWindow(QDialog):
    def __init__(self, parent=None, on_theme_changed=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(400)
        self.on_theme_changed = on_theme_changed
        self.load_config()

        layout = QVBoxLayout()

        # Folder selectors
        self.input_field = self.create_path_field("Input Folder", self.config.get("input_dir", ""))
        self.output_field = self.create_path_field("Output Folder", self.config.get("output_dir", ""))
        self.trash_field = self.create_path_field("Trash Folder", self.config.get("trash_dir", ""))
        self.tmdb_api_field = self.create_path_field("TMDb API Key", self.config.get("tmdb_api_key", ""))
        self.log_path_field = self.create_path_field("Log Folder", self.config.get("log_dir", "logs"))

        layout.addLayout(self.input_field["layout"])
        layout.addLayout(self.output_field["layout"])
        layout.addLayout(self.trash_field["layout"])
        layout.addLayout(self.tmdb_api_field["layout"])
        layout.addLayout(self.log_path_field["layout"])

        # Theme selector
        layout.addWidget(QLabel("Theme:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["System", "Dark", "Light"])
        layout.addWidget(self.theme_combo)

        current_theme = self.config.get("theme", "system").capitalize()
        index = self.theme_combo.findText(current_theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)

        # Processing flags
        self.prohibit_extraction = QCheckBox("Prohibit Extraction")
        self.prohibit_downloads = QCheckBox("Prohibit Downloads")
        self.prohibit_encoding = QCheckBox("Prohibit Encoding")
        self.allow_generation = QCheckBox("Allow Generation")

        self.prohibit_extraction.setChecked(self.config.get("prohibit_extraction", False))
        self.prohibit_downloads.setChecked(self.config.get("prohibit_downloads", False))
        self.prohibit_encoding.setChecked(self.config.get("prohibit_encoding", False))
        self.allow_generation.setChecked(self.config.get("allow_generation", True))

        layout.addWidget(self.prohibit_extraction)
        layout.addWidget(self.prohibit_downloads)
        layout.addWidget(self.prohibit_encoding)
        layout.addWidget(self.allow_generation)

        # Buttons
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_preferences)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def create_path_field(self, label_text, value):
        layout = QHBoxLayout()
        label = QLabel(label_text)
        field = QLineEdit()
        field.setText(value)
        browse_btn = QPushButton("Browse")
        layout.addWidget(label)
        layout.addWidget(field)
        layout.addWidget(browse_btn)
        browse_btn.clicked.connect(lambda: self.select_folder(field))
        return {"layout": layout, "field": field}

    def select_folder(self, field):
        path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if path:
            field.setText(path)

    def load_config(self):
        if not CONFIG_PATH.exists():
            self.config = {}
        else:
            with open(CONFIG_PATH, "r") as f:
                self.config = json.load(f)

    def save_preferences(self):
        self.config["input_dir"] = self.input_field["field"].text()
        self.config["output_dir"] = self.output_field["field"].text()
        self.config["trash_dir"] = self.trash_field["field"].text()
        self.config["tmdb_api_key"] = self.tmdb_api_field["field"].text()
        self.config["log_dir"] = self.log_path_field["field"].text()
        self.config["prohibit_extraction"] = self.prohibit_extraction.isChecked()
        self.config["prohibit_downloads"] = self.prohibit_downloads.isChecked()
        self.config["prohibit_encoding"] = self.prohibit_encoding.isChecked()
        self.config["allow_generation"] = self.allow_generation.isChecked()
        self.config["theme"] = self.theme_combo.currentText().lower()

        os.makedirs(CONFIG_PATH.parent, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(self.config, f, indent=2)

        dialog = ThemedMessage("Saved", "Preferences saved successfully.", self)
        dialog.setPalette(self.palette())  # Apply current theme
        dialog.setStyle(self.style())  # Ensure style inheritance
        dialog.exec()

        if self.on_theme_changed:
            self.on_theme_changed()

# Utility functions for use in main.py
def load_theme() -> ThemeMode:
    try:
        with open(CONFIG_PATH, "r") as f:
            data = json.load(f)
            return ThemeMode(data.get("theme", "system"))
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return ThemeMode.SYSTEM

#
def save_column_widths(widths: list[int]):
    config = _load_config()
    config["column_widths"] = widths
    _write_config(config)

def load_column_widths() -> list[int] | None:
    config = _load_config()
    return config.get("column_widths")

def _load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}

def _write_config(config: dict):
    os.makedirs(CONFIG_PATH.parent, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)

def get_tmdb_api_key() -> str | None:
    config = _load_config()
    return config.get("tmdb_api_key")

def get_log_path() -> Path:
    config = _load_config()
    raw = config.get("log_dir", "logs")
    path = Path(raw)
    path.mkdir(exist_ok=True, parents=True)
    return path