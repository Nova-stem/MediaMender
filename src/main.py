# src/main.py

# --- Standard Library ---
import json
import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

# --- Third-Party ---
from PySide6.QtCore import QThread, Signal, Qt, QSize
from PySide6.QtGui import QIcon, QPalette, QStandardItem, QColor
from PySide6.QtWidgets import QApplication, QAbstractItemView, QHeaderView, QMainWindow, QHBoxLayout, QPushButton, \
    QProgressBar, QLabel, QWidget, QVBoxLayout, QToolTip

# --- Local ---
from preferences import load_theme, PreferencesWindow
from src.processing.common_utils import set_tmdb_warning_callback
from src.dialog import ThemedMessage
from src.drag_drop_table import NoFocusDelegate, DragDropSortableTable
from src.preferences import _load_config, get_log_path, get_whisper_model, load_column_widths, save_column_widths
from src.processing.common_utils import ensure_whisper_model_installed, install_ffmpeg_if_needed
from src.processing.media_processor import detect_media_type, process_media
from src.style import get_base_stylesheet
from src.theme_manager import apply_theme
from src.logging_utils import configure_logger, CURRENT_LOG_FILE

gui_lock = threading.Lock()
CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.json"
log_dir = get_log_path()
configure_logger(log_dir)

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
                process_media(Path(file), self.output_dir, self.trash_dir, self.dry_run)
                logging.info(f"{'[DRY RUN] ' if self.dry_run else ''}Processed file: {filename}")
                success = True
            except Exception as e:
                logging.exception(f"Error processing {filename}")
                success = False

            self.file_done.emit(i, success)

    def stop(self):
        self.running = False

class MediaMender(QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("MediaMender v0.1")
        self.setGeometry(100, 100, 800, 500)
        self.worker = None

        self.files = []
        self.config = self.load_config()

        self.setup_ui()

    def setup_ui(self):
        palette = self.palette()
        bg_idle = palette.color(QPalette.Button).name()
        bg_hover = palette.color(QPalette.Highlight).name()
        fg_color = palette.color(QPalette.ButtonText).name()
        text_color = palette.color(QPalette.ButtonText).name()

        palette = app.palette()
        tooltip_bg = palette.color(QPalette.ToolTipBase).name()
        tooltip_fg = palette.color(QPalette.ToolTipText).name()
        tooltip_border = palette.color(QPalette.Mid).name()  # subtle border
        app.setStyleSheet(app.styleSheet() + f"""
            QToolTip {{
                background-color: {tooltip_bg};
                color: {tooltip_fg};
                border: 1px solid {tooltip_border};
                padding: 5px;
                border-radius: 4px;
            }}
        """)


        self.preferences_button = QPushButton()
        icon_path = Path(__file__).parent.parent / "resources" / "gear.png"
        self.preferences_button.setIcon(QIcon(str(icon_path)))
        self.preferences_button.setToolTip("Preferences")
        self.preferences_button.setFixedSize(40, 40)
        self.preferences_button.setIconSize(QSize(24, 24))
        self.preferences_button.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {bg_idle};
                        color: {text_color};
                        border-radius: 6px;
                    }}
                    QPushButton:hover {{
                        background-color: {bg_hover};
                    }}
                """)
        self.preferences_button.clicked.connect(self.open_preferences)

        self.play_button = QPushButton()
        icon_path = Path(__file__).parent.parent / "resources" / "start.png"
        self.play_button.setIcon(QIcon(str(icon_path)))
        self.play_button.setToolTip("Start Processing")
        self.play_button.setFixedSize(40, 40)
        self.play_button.setIconSize(QSize(24, 24))
        self.play_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_idle};
                color: {text_color};
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {bg_hover};
            }}
        """)
        self.play_button.clicked.connect(self.start_processing)

        self.stop_button = QPushButton()
        icon_path = Path(__file__).parent.parent / "resources" / "stop.png"
        self.stop_button.setIcon(QIcon(str(icon_path)))
        self.stop_button.setToolTip("Stop Processing")
        self.stop_button.setFixedSize(40, 40)
        self.stop_button.setIconSize(QSize(24, 24))
        self.stop_button.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {bg_idle};
                        color: {text_color};
                        border-radius: 6px;
                    }}
                    QPushButton:hover {{
                        background-color: {bg_hover};
                    }}
                """)
        self.stop_button.clicked.connect(self.stop_processing)

        self.load_button = QPushButton("Load")
        self.load_button.setToolTip("Load Files")
        self.load_button.setFixedSize(60, 40)
        self.load_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_idle};
                color: {text_color};
                border-radius: 6px;
                font-size: 17px;
            }}
            QPushButton:hover {{
                background-color: {bg_hover};
            }}
        """)
        self.load_button.clicked.connect(self.load_files)

        self.unload_button = QPushButton("Unload")
        self.unload_button.setToolTip("Unload All Files")
        self.unload_button.setFixedSize(80, 40)
        self.unload_button.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {bg_idle};
                        color: {text_color};
                        border-radius: 6px;
                        font-size: 17px;
                    }}
                    QPushButton:hover {{
                        background-color: {bg_hover};
                    }}
                """)
        self.unload_button.clicked.connect(self.unload_files)

        self.progress = QProgressBar()
        self.status_label = QLabel("Idle")

        top_bar = QHBoxLayout()
        top_bar.addWidget(self.preferences_button)
        top_bar.addWidget(self.play_button)
        top_bar.addWidget(self.stop_button)
        top_bar.addWidget(self.load_button)
        top_bar.addWidget(self.unload_button)
        top_bar.addStretch()
        top_bar.addWidget(self.status_label)

        central = QWidget()
        central.setAcceptDrops(True)
        layout = QVBoxLayout()

        self.table = DragDropSortableTable()
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setItemDelegate(NoFocusDelegate())

        border_color = palette.color(QPalette.Light).name()

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

        layout.addLayout(top_bar)
        layout.addWidget(self.table)
        layout.addWidget(self.progress)

        central.setLayout(layout)
        self.setCentralWidget(central)

        self.table.row_remove_requested.connect(self.remove_file_at_row)
        self.table.files_dropped.connect(self.add_files_from_drop)

    def add_files_from_drop(self, data):
        file_paths, target_row = data
        existing_filenames = {Path(f).name.lower() for f in self.files}

        for path in file_paths:
            filename = Path(path).name
            if filename.lower() in existing_filenames:
                logging.info(f"Skipped duplicate file: {filename}")
                ThemedMessage.critical(self, "Duplicate File", f"The file '{filename}' is already in the queue.")
                continue

            self.files.insert(target_row, path)
            media_type = detect_media_type(Path(path))

            row_items = [
                QStandardItem(""),  # will be renumbered
                QStandardItem(filename),
                QStandardItem(media_type),
                QStandardItem("Pending")
            ]
            self.table.model.insertRow(target_row, row_items)
            target_row += 1
            logging.info(f"File added via external drop: {filename}")

        self.renumber_table()

    def open_preferences(self):
        pref = PreferencesWindow(self)
        pref.exec()

    def load_config(self):
        if not os.path.exists(CONFIG_PATH):
            return {}
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)

    def unload_files(self):
        if not self.files:
            return

        response = ThemedMessage.question(self,"Unload All Files","Are you sure you want to remove all loaded files?",["Yes", "Cancel"] )

        if response == "Yes":
            self.files.clear()
            self.table.model.removeRows(0, self.table.model.rowCount())
            self.renumber_table()
            logging.info("All files have been unloaded.")

    def load_files(self):
        config = _load_config()
        input_dir = Path(config.get("input_dir", ""))
        if not input_dir.exists():
            dialog = ThemedMessage("Invalid Directory", "The input directory does not exist.", self)
            dialog.setPalette(self.palette())
            dialog.setStyle(self.style())
            dialog.exec()
            return

        # List and sort files
        all_files = [f for f in input_dir.glob("*") if f.is_file()]
        all_files.sort(key=lambda f: f.name.lower())

        seen_filenames = set()
        unique_files = []
        duplicate_count = 0

        for f in all_files:
            name = f.name.lower()
            if name in seen_filenames:
                duplicate_count += 1
                continue
            seen_filenames.add(name)
            unique_files.append(str(f))

        self.files = unique_files

        # Reset table and load only unique files
        self.table.model.removeRows(0, self.table.model.rowCount())
        for file_path in self.files:
            file_name = Path(file_path).name
            media_type = detect_media_type(Path(file_path))
            self.table.add_row([file_name, media_type, "Pending"])

        self.renumber_table()

        if duplicate_count > 0:
            ThemedMessage.critical(self, "Duplicate Files Skipped",
                     f"{duplicate_count} duplicate file(s) were skipped based on filename.")

    def remove_file_at_row(self, row):
        if 0 <= row < len(self.files):
            removed_path = self.files.pop(row)
            filename = Path(removed_path).name
            logging.info(f"Removed file from queue: {filename}")
        else:
            logging.warning(f"Tried to remove invalid row: {row}")

        self.table.model.removeRow(row)

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
        with gui_lock:
            self.progress.setValue(value)
            self.status_label.setText(f"Processing: {filename}")

    def mark_file(self, row, success):
        with gui_lock:
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
    window = MediaMender(app)
    window.show()
    sys.exit(app.exec())

"""
import sys
import threading
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QProgressBar, QPushButton, QVBoxLayout, QWidget, QTableView
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtCore import Qt

from src.drag_drop_table import DragDropSortableTable
from src.preferences import PreferencesWindow, load_theme
from src.theme_manager import apply_theme
from src.style import get_base_stylesheet
from src.processing.media_processor import process_media
from pathlib import Path
from PySide6.QtCore import QThread, Signal, QObject

import logging

# Global thread lock
gui_lock = threading.Lock()

class Worker(QObject):
    progress = Signal(int, str)
    finished = Signal(int, bool)

    def __init__(self, files, output_dir, trash_dir, dry_run):
        super().__init__()
        self.files = files
        self.output_dir = output_dir
        self.trash_dir = trash_dir
        self.dry_run = dry_run

    def run(self):
        for index, path in enumerate(self.files):
            try:
                process_media(path, self.output_dir, self.trash_dir, self.dry_run)
                self.finished.emit(index, True)
            except Exception:
                self.finished.emit(index, False)

class MediaMender(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MediaMender")
        self.setMinimumSize(800, 600)

        theme = load_theme()
        apply_theme(QApplication.instance(), theme)

        layout = QVBoxLayout()

        self.status_label = QLabel("Ready")
        self.progress = QProgressBar()
        self.progress.setValue(0)

        self.table = DragDropSortableTable()

        self.process_button = QPushButton("Start Processing")
        self.process_button.clicked.connect(self.start_processing)

        self.preferences_button = QPushButton("Preferences")
        self.preferences_button.clicked.connect(self.open_preferences)

        layout.addWidget(self.status_label)
        layout.addWidget(self.progress)
        layout.addWidget(self.table)
        layout.addWidget(self.process_button)
        layout.addWidget(self.preferences_button)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.thread = None
        self.worker = None

    def start_processing(self):
        files = self.table.get_paths()
        if not files:
            return

        self.progress.setMaximum(len(files))
        self.progress.setValue(0)

        self.thread = QThread()
        self.worker = Worker(
            files,
            self.table.output_dir,
            self.table.trash_dir,
            self.table.dry_run
        )
        self.worker.moveToThread(self.thread)

        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.mark_file)
        self.thread.started.connect(self.worker.run)
        self.thread.start()

    def update_progress(self, value, filename):
        with gui_lock:
            self.progress.setValue(value)
            self.status_label.setText(f"Processing: {filename}")

    def mark_file(self, row, success):
        with gui_lock:
            for col in range(3):
                item = self.table.model.item(row, col)
                if item:
                    item.setBackground(Qt.GlobalColor.green if success else Qt.GlobalColor.red)
            self.table.model.setItem(row, 3, QStandardItem("Done" if success else "Errored"))

    def reset_table_colors(self):
        with gui_lock:
            for row in range(self.table.model.rowCount()):
                for col in range(self.table.model.columnCount()):
                    item = self.table.model.item(row, col)
                    if item:
                        item.setBackground(Qt.GlobalColor.transparent)

    def append_to_table(self, items):
        with gui_lock:
            for item in items:
                self.table.model.appendRow(item)

    def load_files(self, files):
        with gui_lock:
            self.table.model.clear()
            for path in files:
                self.table.model.appendRow([QStandardItem(str(path))])

    def open_preferences(self):
        dlg = PreferencesWindow(self)
        dlg.exec()

def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(get_base_stylesheet())
    window = MediaMender()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
"""