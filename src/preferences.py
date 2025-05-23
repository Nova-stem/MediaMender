#src/preferences.py
#23 May 2025

import logging
import os
import json
#import shutil
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QCheckBox, QComboBox
)

from src.logging_utils import configure_logger
from src.system.safety import is_safe_path, require_safe_path
from src.theme_manager import ThemeMode
from src.dialog import ThemedMessage
from src.system.gpu_utils import (
    is_nvidia_gpu_present,
    is_cuda_runtime_available,
    is_torch_cuda_available,
    install_cuda_enabled_torch,
    get_cuda_installer_url,
    download_cuda_installer,
    run_cuda_installer
)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.json"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = {
    "input_dir": str(PROJECT_ROOT / "Input"),
    "output_dir": str(PROJECT_ROOT / "Output"),
    "trash_dir": str(PROJECT_ROOT / "Trash"),
    "tmdb_api_key": "",
    "log_dir": str(PROJECT_ROOT / "logs"),
    "dry_run": True,
    "allow_generation": False,
    "gpu_enabled": False,
    "theme": "system",
    "whisper_model": "base"
}

class PreferencesWindow(QDialog):
    def __init__(self, parent=None, on_theme_changed=None, logger=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(400)
        self.on_theme_changed = on_theme_changed
        self.load_config()
        self.logger = logger or logging.getLogger(__name__)

        layout = QVBoxLayout()

        # Folder selectors
        self.input_field = self.create_path_field("Input Folder", self.config.get("input_dir", ""))
        self.output_field = self.create_path_field("Output Folder", self.config.get("output_dir", ""))
        self.trash_field = self.create_path_field("Trash Folder", self.config.get("trash_dir", ""))
        self.tmdb_api_field = self.create_path_field("TMDb API Key", self.config.get("tmdb_api_key", ""))
        self.log_path_field = self.create_path_field("Log Folder", self.config.get("log_dir", ""))

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

        layout.addWidget(QLabel("Whisper Model:"))
        self.whisper_model_combo = QComboBox()
        self.whisper_model_combo.addItem("Tiny (fastest, lowest accuracy)", "tiny")
        self.whisper_model_combo.addItem("Base (fast, good accuracy)", "base")
        self.whisper_model_combo.addItem("Small (balanced)", "small")
        self.whisper_model_combo.addItem("Medium (slow, high accuracy)", "medium")
        self.whisper_model_combo.addItem("Large (slowest, best accuracy)", "large")
        selected_model = self.config.get("whisper_model", "base")
        index = self.whisper_model_combo.findText(selected_model)
        self.whisper_model_combo.setCurrentIndex(index if index >= 0 else 1)

        layout.addWidget(self.whisper_model_combo)
        # Processing flags
        #self.prohibit_extraction = QCheckBox("Prohibit Extraction")
        #self.prohibit_downloads = QCheckBox("Prohibit Downloads")
        #self.prohibit_encoding = QCheckBox("Prohibit Encoding")
        self.allow_generation = QCheckBox("Enable Whisper (Subtitle Generation)")
        self.dry_run_checkbox = QCheckBox("Enable Dry Run (no file changes)")
        self.gpu_checkbox = QCheckBox("Enable GPU Acceleration (NVIDIA only)")

        #self.prohibit_extraction.setChecked(self.config.get("prohibit_extraction", False))
        #self.prohibit_downloads.setChecked(self.config.get("prohibit_downloads", False))
        #self.prohibit_encoding.setChecked(self.config.get("prohibit_encoding", False))
        self.allow_generation.setChecked(self.config.get("allow_generation", True))
        self.dry_run_checkbox.setChecked(self.config.get("dry_run", False))
        self.gpu_checkbox.setChecked(self.config.get("gpu_enabled", False))


        #layout.addWidget(self.prohibit_extraction)
        #layout.addWidget(self.prohibit_downloads)
        #layout.addWidget(self.prohibit_encoding)
        layout.addWidget(self.allow_generation)
        layout.addWidget(self.dry_run_checkbox)

        if not is_nvidia_gpu_present():
            self.gpu_checkbox.setEnabled(False)
            self.gpu_checkbox.setToolTip("No NVIDIA GPU detected on this system.")
        else:
            self.gpu_checkbox.setToolTip("Uses CUDA for Whisper transcription if supported.")

        layout.addWidget(self.gpu_checkbox)

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

    def load_config(self, logger=None):
        logger = logger or logging.getLogger(__name__)
        if not CONFIG_PATH.exists():
            logger.warning("Config file missing. Using default settings.")
            self.config = DEFAULT_CONFIG.copy()
            return

        try:
            with open(CONFIG_PATH, "r") as f:
                loaded = json.load(f)
        except json.JSONDecodeError:
            logger.error("Config file is corrupted. Using default settings.")
            self.config = DEFAULT_CONFIG.copy()
            return

        # Merge loaded config with defaults (fill missing or blank values)
        self.config = {}
        for key, default in DEFAULT_CONFIG.items():
            value = loaded.get(key, default)
            if isinstance(value, str):
                value = value.strip()
            self.config[key] = value if value != "" else default

    def save_preferences(self):
        self.config["input_dir"] = self.input_field["field"].text()
        self.config["output_dir"] = self.output_field["field"].text()
        self.config["trash_dir"] = self.trash_field["field"].text()
        self.config["tmdb_api_key"] = self.tmdb_api_field["field"].text()
        self.config["log_dir"] = self.log_path_field["field"].text()
        self.config["whisper_model"] = self.whisper_model_combo.currentText()
        self.config["allow_generation"] = self.allow_generation.isChecked()
        self.config["dry_run"] = self.dry_run_checkbox.isChecked()
        self.config["gpu_enabled"] = self.gpu_checkbox.isChecked()
        self.config["theme"] = self.theme_combo.currentText().lower()

        invalid = []

        paths_to_check = [
            ("Input Directory", self.input_field["field"].text()),
            ("Output Directory", self.output_field["field"].text()),
            ("Trash Directory", self.trash_field["field"].text()),
            ("Log Directory", self.log_path_field["field"].text()),
        ]

        for label, path_str in paths_to_check:
            path = Path(path_str.strip())
            if not is_safe_path(path, logger=self.logger):
                invalid.append(f"{label}: {path}")

        if invalid:
            ThemedMessage.critical(self, "Invalid Paths", "The following paths are unsafe:\n\n" + "\n".join(invalid))
            return  # Abort save

        os.makedirs(CONFIG_PATH.parent, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(self.config, f, indent=2)

        dialog = ThemedMessage("Saved", "Preferences saved successfully.", self)
        dialog.setPalette(self.palette())  # Apply current theme
        dialog.setStyle(self.style())  # Ensure style inheritance
        dialog.exec()

        new_log_path = Path(self.log_path_field["field"].text().strip())
        configure_logger(new_log_path, reuse_existing=True)

        after_preferences_saved(self.config, dry_run=self.config.get("dry_run", False))

        if self.on_theme_changed:
            self.on_theme_changed()
        self.accept()

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

def _write_config(new_data: dict):
    config = _load_config()
    config.update(new_data)  # merge instead of overwrite
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
    require_safe_path(path, "Log Directory")
    path.mkdir(exist_ok=True, parents=True)
    return path

def get_whisper_model() -> str:
    config = _load_config()
    return config.get("whisper_model", "base")

def is_generation_allowed() -> bool:
    config = _load_config()
    return config.get("allow_generation", False)

def after_preferences_saved(config, dry_run=False):
    if not config.get("gpu_enabled", False):
        return

    if not is_nvidia_gpu_present():
        ThemedMessage.critical(
            None,
            "No NVIDIA GPU",
            "GPU acceleration was enabled but no NVIDIA GPU was found.\n\n"
            "GPU acceleration has been disabled."
        )
        config["gpu_enabled"] = False
        _write_config(config)
        return

    if is_cuda_runtime_available() and is_torch_cuda_available():
        return

    result = ThemedMessage.question(
        None,
        "Install CUDA Toolkit",
        "CUDA support is missing. This requires both the CUDA Toolkit and a GPU-enabled PyTorch install.\n\n"
        "Would you like to automatically install the required components?",
        buttons=["Install", "Disable"]
    )

    if result == "Install":
        installer_url = get_cuda_installer_url()
        installer_path = Path.cwd() / "cuda_installer.exe"

        if not download_cuda_installer(installer_url, installer_path, dry_run=dry_run):
            ThemedMessage.critical(
                None,
                "Download Failed",
                "Failed to download the CUDA Toolkit installer. GPU acceleration has been disabled."
            )
            config["gpu_enabled"] = False
            _write_config(config)
            return

        if not run_cuda_installer(installer_path, dry_run=dry_run):
            ThemedMessage.critical(
                None,
                "Install Failed",
                "CUDA Toolkit installation could not be started. GPU acceleration has been disabled."
            )
            config["gpu_enabled"] = False
            _write_config(config)
            return

        if not install_cuda_enabled_torch():
            ThemedMessage.critical(
                None,
                "PyTorch GPU Install Failed",
                "Failed to install PyTorch with CUDA support. GPU acceleration has been disabled."
            )
            config["gpu_enabled"] = False
            _write_config(config)
            return

        if not (is_cuda_runtime_available() and is_torch_cuda_available()):
            ThemedMessage.critical(
                None,
                "CUDA Still Missing",
                "CUDA runtime or PyTorch with GPU support is still not available after installation.\n\n"
                "GPU acceleration has been disabled."
            )
            config["gpu_enabled"] = False
            _write_config(config)
    else:
        config["gpu_enabled"] = False
        _write_config(config)
