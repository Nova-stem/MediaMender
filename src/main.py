# src/main.py

import sys, os, json
from PySide6.QtWidgets import QApplication, QMainWindow, QTableWidgetItem, QVBoxLayout, QPushButton, QWidget, QProgressBar, QLabel, QComboBox, QAbstractItemView, QHeaderView
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QPalette, QIcon, QStandardItem
from src.theme_manager import apply_theme
#from src.theme import apply_system_theme
from src.style import get_base_stylesheet
from preferences import PreferencesWindow, load_theme
from src.processing.media_processor import process_media
#import configparser
from src.preferences import load_column_widths, save_column_widths, get_whisper_model
from pathlib import Path
import logging
from datetime import datetime
from src.preferences import get_log_path, _load_config
from src.dialog import ThemedMessage
from src.processing.media_processor import detect_media_type
from src.drag_drop_table import DragDropSortableTable, NoFocusDelegate
from src.processing.common_utils import ensure_whisper_model_installed, install_ffmpeg_if_needed

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

    def __init__(self, files, output_dir, trash_dir, log_dir, dry_run=False):
        super().__init__()
        self.files = files
        self.output_dir = output_dir
        self.trash_dir = trash_dir
        self.log_dir = log_dir
        self.dry_run = dry_run
        self.running = True

    def run(self):
        for i, file in enumerate(self.files):
            if not self.running:
                break

            filename = os.path.basename(file)
            self.update_progress.emit(int((i + 1) / len(self.files) * 100), filename)

            try:
                if self.dry_run:
                    logging.info(f"[DRY RUN] Would process: {filename}")
                    success = True
                else:
                    process_media(Path(file), self.output_dir)
                    logging.info(f"Processed file: {filename}")
                    success = True
            except Exception as e:
                logging.exception(f"Error processing {filename}")
                success = False

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
        central.setAcceptDrops(True)
        layout = QVBoxLayout()

        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "Movie", "TV Show", "Audiobook"])
        layout.addWidget(self.filter_combo)

        self.table = DragDropSortableTable()
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setItemDelegate(NoFocusDelegate())

        border_color = self.palette().color(QPalette.Light).name()

        header = self.table.horizontalHeader()
        header.sectionClicked.connect(self.renumber_table)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)  # Allow manual resizing
        header.setSectionsClickable(True)
        header.setStretchLastSection(False)  # Keep fixed widths
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Column 0 (the "#" column)
        header.setStyleSheet(
            f"""
            QHeaderView::section {{
                border: 1px solid {border_color};
                padding: 4px;
                text-align: left;
                font-weight: normal;
            }}
            """
        )



        # Left-align headers
        for i in range(self.table.model.columnCount()):
            header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Restore saved column widths
        saved_widths = load_column_widths()
        if saved_widths:
            for i, width in enumerate(saved_widths, start=1):  # start at 1 to skip column 0
                if i < self.table.model.columnCount():
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

        self.files.sort(key=lambda path: Path(path).name.lower())  # Case-insensitive sort by filename

        self.table.model.removeRows(0, self.table.model.rowCount())
        for file_path in self.files:
            file_name = Path(file_path).name
            media_type = detect_media_type(Path(file_path))
            self.table.add_row([file_name, media_type, "Pending"])

    def renumber_table(self):
        #for row in range(self.table.rowCount()):
        for row in range(self.table.model.rowCount()):
            item = QStandardItem(str(row + 1))
            item.setEditable(False)
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.model.setItem(row, 0, item)
        self.table.resizeColumnToContents(0)

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
        model = get_whisper_model()
        if not ensure_whisper_model_installed(model, self.update_progress, dry_run=self.dry_run):
            dialog = ThemedMessage("Model Error", "Whisper model installation failed. Cannot continue.", self)
            dialog.exec()
            return
        if not install_ffmpeg_if_needed(self.update_progress, dry_run=self.dry_run):
            dialog = ThemedMessage("Missing FFmpeg", "FFmpeg could not be installed. Processing cannot continue.", self)
            dialog.exec()
            return

        self.lock_table()

        self.update_file_order()
        self.worker = WorkerThread(self.files, self.output_dir, self.trash_dir, self.log_dir, self.dry_run)
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
            self.unlock_table()

    def lock_table(self):
        self.table.setSortingEnabled(False)
        self.table.setDragEnabled(False)
        self.table.setAcceptDrops(False)
        self.table.setDropIndicatorShown(False)
        #self.table.model.setSupportedDragActions(Qt.NoAction)

    def unlock_table(self):
        self.table.setSortingEnabled(True)
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.setDropIndicatorShown(True)
        #self.table.model.setSupportedDragActions(Qt.MoveAction)

    def update_progress(self, value, filename):
        self.progress.setValue(value)
        self.status_label.setText(f"Processing: {filename}")

    def mark_file(self, row, success):
        color = "#98FB98" if success else "#FF7F7F"
        for col in range(3):
            item = self.table.model.item(row, col)
            if item:
                item.setBackground(Qt.GlobalColor.green if success else Qt.GlobalColor.red)
        self.table.model.setItem(row, 3, QStandardItem("Done" if success else "Errored"))

    def check_required_paths(self) -> bool:
        config = _load_config()
        required_keys = ["input_dir", "output_dir", "trash_dir", "log_dir"]
        missing = [key for key in required_keys if not config.get(key) or not Path(config[key]).exists()]
        if missing:
            return False
        self.output_dir = Path(config.get("output_dir", "output"))
        self.trash_dir = Path(config.get("trash_dir", "trash"))
        self.log_dir = Path(config.get("log_dir", "logs"))
        self.dry_run = config.get("dry_run", True)
        return True

    def update_file_order(self):
        new_order = []
        seen = set()
        for row in range(self.table.model.rowCount()):
            filename = self.table.model.item(row, 1).text()
            for f in self.files:
                if Path(f).name == filename and f not in seen:
                    new_order.append(f)
                    seen.add(f)
                    break
        self.files = new_order
        self.renumber_table()

    def dropEvent(self, event):
        if not self.table.selectedIndexes():
            return

        global_pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        if self.table.is_cursor_within_viewport(global_pos):
            return  # Let the table handle it normally

        cursor_pos = self.table.mapFromGlobal(global_pos)
        if cursor_pos.y() < 0:
            target_row = 0
        elif cursor_pos.y() > self.table.viewport().height():
            target_row = self.table.model.rowCount()
        else:
            return

        source_row = self.table.selectedIndexes()[0].row()
        if target_row > source_row:
            target_row -= 1

        items = [self.table.model.item(source_row, col).clone() for col in range(self.table.model.columnCount())]
        self.table.model.removeRow(source_row)
        self.table.model.insertRow(target_row, items)
        self.table.renumber_rows()

        self.table._drag_hover_pos = None
        self.table.viewport().update()
        event.acceptProposedAction()

    def dragEnterEvent(self, event):
        event.acceptProposedAction()

    def closeEvent(self, event):
        widths = [self.table.columnWidth(i) for i in range(1, self.table.model.columnCount())]
        save_column_widths(widths)
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    apply_theme(app, load_theme())
    app.setStyleSheet(get_base_stylesheet())
    icon_path = Path(__file__).parent.parent / "resources" / "Icon.JPG"
    app.setWindowIcon(QIcon(str(icon_path)))
    window = MediaMender()
    window.show()
    sys.exit(app.exec())
