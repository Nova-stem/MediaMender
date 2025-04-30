# src/main.py

import sys, os, json
from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QTableWidgetItem, QTableWidget, QVBoxLayout, QPushButton, QWidget, QProgressBar, QLabel, QComboBox, QMessageBox
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QPalette, QIcon
from src.theme_manager import apply_theme
#from src.theme import apply_system_theme
from src.style import get_base_stylesheet
from preferences import PreferencesWindow, load_theme
from src.processing.media_processor import process_media
#import configparser
from src.preferences import load_column_widths, save_column_widths
from pathlib import Path
import logging
from datetime import datetime
from src.preferences import get_log_path, _load_config, _write_config
from src.dialog import ThemedMessage
from src.processing.media_processor import detect_media_type

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.json"

log_path = get_log_path()
timestamp = datetime.now().strftime("%Y%m%d.%H%M")
log_filename = log_path / f"media_mender_{timestamp}.log"
CURRENT_LOG_FILE = log_filename

logging.basicConfig(
    filename=log_filename,
    filemode="w",  # use "w" to start a fresh file each run
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

class WorkerThread(QThread):
    update_progress = Signal(int, str)
    file_done = Signal(int, bool)

    def __init__(self, files, output_dir, trash_dir, log_dir):
        super().__init__()
        self.files = files
        self.output_dir = output_dir
        self.trash_dir = trash_dir
        self.log_dir = log_dir
        self.running = True

    def run(self):
        for i, file in enumerate(self.files):
            if not self.running:
                break

            filename = os.path.basename(file)
            self.update_progress.emit(int((i + 1) / len(self.files) * 100), filename)

            try:
                process_media(Path(file), self.output_dir)
                logging.info(f"Processed file: {filename}")
                success = True
            except Exception as e:
                logging.exception(f"Error processing {filename}")
                success = False
            #try:
            #    media_type = detect_media_type(Path(file))
            #    self.table.item(i, 1).setText(media_type.capitalize())  # ← set type in table

            #    process_media(Path(file), self.output_dir)
            #    success = True
            #except Exception as e:
            #    logging.exception(f"❌ Error processing {filename}")
            #    self.table.item(i, 2).setText("Errored")
            #    success = False

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

        # Get theme-aware border color (higher contrast than Mid)
        border_color = self.palette().color(QPalette.Light).name()

        header = self.table.horizontalHeader()
        header.setStyleSheet(
            f"""
            QHeaderView::section {{
                border: 1px solid {border_color};
                padding: 4px;
                text-align: left;
            }}
            """
        )

        # Left-align headers
        for i in range(self.table.columnCount()):
            item = self.table.horizontalHeaderItem(i)
            if item:
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Restore saved column widths
        saved_widths = load_column_widths()
        if saved_widths:
            for i, width in enumerate(saved_widths):
                if i < self.table.columnCount():
                    self.table.setColumnWidth(i, width)

        # Stretch last column
        header.setStretchLastSection(True)
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
        config = _load_config()
        input_dir = Path(config.get("input_dir", ""))
        if not input_dir.exists():
            dialog = ThemedMessage("Invalid Directory", "The input directory does not exist.", self)
            dialog.setPalette(self.palette())  # Apply current theme
            dialog.setStyle(self.style())  # Ensure style inheritance
            dialog.exec()
            return

        self.files = [
            str(f) for f in input_dir.glob("*") if f.is_file()
        ]

        self.table.setRowCount(len(self.files))
        #for i, file in enumerate(self.files):
        #    name_item = QTableWidgetItem(Path(file).name)
        #    type_item = QTableWidgetItem("Unknown")
        #    status_item = QTableWidgetItem("Pending")
        for i, file_path in enumerate(self.files):
            file_name = Path(file_path).name
            media_type = detect_media_type(Path(file_path))
            name_item = QTableWidgetItem(file_name)
            type_item = QTableWidgetItem(media_type)
            status_item = QTableWidgetItem("Pending")

            self.table.setItem(i, 0, name_item)
            self.table.setItem(i, 1, type_item)
            self.table.setItem(i, 2, status_item)

    def start_processing(self):
        if not self.files:
            dialog = ThemedMessage("No Files", "There are no files to process.", self)
            dialog.setPalette(self.palette())  # Apply current theme
            dialog.setStyle(self.style())  # Ensure style inheritance
            dialog.exec()
            return
        if not self.check_required_paths():
            dialog = ThemedMessage("Missing File Paths", "There are file paths missing from your preferences.", self)
            dialog.setPalette(self.palette())  # Apply current theme
            dialog.setStyle(self.style())  # Ensure style inheritance
            dialog.exec()
            return
        self.worker = WorkerThread(self.files, self.output_dir, self.trash_dir, self.log_dir)
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

    def check_required_paths(self) -> bool:
        config = _load_config()
        required_keys = ["input_dir", "output_dir", "trash_dir", "log_dir"]
        missing = [key for key in required_keys if not config.get(key) or not Path(config[key]).exists()]
        if missing:
            return False
        self.output_dir = Path(config["output_dir"])
        self.trash_dir = Path(config["trash_dir"])
        self.log_dir = Path(config["log_dir"])
        return True

    def closeEvent(self, event):
        widths = [self.table.columnWidth(i) for i in range(self.table.columnCount())]
        save_column_widths(widths)
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    apply_theme(app, load_theme())
    app.setStyleSheet(get_base_stylesheet())
    icon_path = Path(__file__).parent.parent / "resources" / "Icon.JPG"
    app.setWindowIcon(QIcon(str(icon_path)))
    window = MediaMender()
    window.show()
    sys.exit(app.exec())
