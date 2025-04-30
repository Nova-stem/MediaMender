# src/main.py

import sys
import os
import json
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QTableWidgetItem, QTableWidget, QVBoxLayout,
    QPushButton, QWidget, QProgressBar, QLabel, QComboBox, QMessageBox, QMenuBar
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction
from preferences import PreferencesWindow
from media_processor import MediaProcessor, simulate_processing
import configparser

CONFIG_PATH = "config/config.json"

class WorkerThread(QThread):
    update_progress = Signal(int, str)
    file_done = Signal(int, bool)

    def __init__(self, files):
        super().__init__()
        self.files = files
        self.running = True

    def run(self):
        for i, file in enumerate(self.files):
            if not self.running:
                break
            filename = os.path.basename(file)
            self.update_progress.emit(int((i+1)/len(self.files)*100), filename)
            success = simulate_processing(file)
            self.file_done.emit(i, success)

    def stop(self):
        self.running = False

class MediaMender(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MediaMender v0.1")
        self.setGeometry(100, 100, 800, 500)
        self.worker = None

        self.files = []
        self.config = self.load_config()

        self.setup_ui()

    def setup_ui(self):
        menu = self.menuBar()
        settings_menu = menu.addMenu("Settings")
        preferences_action = QAction("Preferences", self)
        preferences_action.triggered.connect(self.open_preferences)
        settings_menu.addAction(preferences_action)

        central = QWidget()
        layout = QVBoxLayout()

        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "Movie", "TV Show", "Audiobook"])
        layout.addWidget(self.filter_combo)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Filename", "Type", "Status"])
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        btn_layout = QVBoxLayout()
        self.load_btn = QPushButton("Load Files")
        self.load_btn.clicked.connect(self.load_files)
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.start_processing)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_processing)
        btn_layout.addWidget(self.load_btn)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)

        self.progress = QProgressBar()
        self.status_label = QLabel("Idle")
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress)

        layout.addLayout(btn_layout)
        central.setLayout(layout)
        self.setCentralWidget(central)

    def open_preferences(self):
        pref = PreferencesWindow(self)
        pref.exec()

    def load_config(self):
        if not os.path.exists(CONFIG_PATH):
            return {}
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)

    def load_files(self):
        folder = self.config.get("input_dir", "")
        if not folder or not os.path.exists(folder):
            folder = QFileDialog.getExistingDirectory(self, "Select Input Folder")
            if not folder:
                return
            self.config["input_dir"] = folder
            os.makedirs("config", exist_ok=True)
            with open(CONFIG_PATH, "w") as f:
                json.dump(self.config, f, indent=2)

        self.files = [
            os.path.join(folder, f) for f in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, f))
        ]
        self.table.setRowCount(0)
        for i, file in enumerate(self.files):
            self.table.insertRow(i)
            self.table.setItem(i, 0, QTableWidgetItem(os.path.basename(file)))
            self.table.setItem(i, 1, QTableWidgetItem("Unknown"))
            self.table.setItem(i, 2, QTableWidgetItem("Pending"))

    def start_processing(self):
        if not self.files:
            QMessageBox.warning(self, "No files", "Please load files first.")
            return
        self.worker = WorkerThread(self.files)
        self.worker.update_progress.connect(self.update_progress)
        self.worker.file_done.connect(self.mark_file)
        self.worker.start()

    def stop_processing(self):
        if self.worker:
            self.worker.stop()
            self.worker.quit()
            self.worker.wait()
            self.status_label.setText("Stopped")
            self.progress.setValue(0)

    def update_progress(self, value, filename):
        self.progress.setValue(value)
        self.status_label.setText(f"Processing: {filename}")

    def mark_file(self, row, success):
        color = "#98FB98" if success else "#FF7F7F"
        for col in range(3):
            item = self.table.item(row, col)
            if item:
                item.setBackground(Qt.GlobalColor.green if success else Qt.GlobalColor.red)
        self.table.setItem(row, 2, QTableWidgetItem("Done" if success else "Errored"))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MediaMender()
    window.show()
    sys.exit(app.exec())
