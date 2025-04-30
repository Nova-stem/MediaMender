# src/preferences.py

import os
import json
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QCheckBox, QMessageBox
)

CONFIG_PATH = "config/config.json"

class PreferencesWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(400)
        self.load_config()

        layout = QVBoxLayout()

        # Folder selectors
        self.input_field = self.create_path_field("Input Folder", self.config.get("input_dir", ""))
        self.output_field = self.create_path_field("Output Folder", self.config.get("output_dir", ""))
        self.trash_field = self.create_path_field("Trash Folder", self.config.get("trash_dir", ""))

        layout.addLayout(self.input_field["layout"])
        layout.addLayout(self.output_field["layout"])
        layout.addLayout(self.trash_field["layout"])

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
        if not os.path.exists(CONFIG_PATH):
            self.config = {}
        else:
            with open(CONFIG_PATH, "r") as f:
                self.config = json.load(f)

    def save_preferences(self):
        self.config["input_dir"] = self.input_field["field"].text()
        self.config["output_dir"] = self.output_field["field"].text()
        self.config["trash_dir"] = self.trash_field["field"].text()
        self.config["prohibit_extraction"] = self.prohibit_extraction.isChecked()
        self.config["prohibit_downloads"] = self.prohibit_downloads.isChecked()
        self.config["prohibit_encoding"] = self.prohibit_encoding.isChecked()
        self.config["allow_generation"] = self.allow_generation.isChecked()

        os.makedirs("config", exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(self.config, f, indent=2)

        QMessageBox.information(self, "Saved", "Preferences saved successfully.")
        self.accept()
