from PySide6.QtWidgets import (
    QTreeView, QHeaderView, QMenu, QAbstractItemView, QStyledItemDelegate, QStyle
)
from PySide6.QtGui import (
    QDrag, QPainter, QPen, QColor, QAction, QStandardItemModel, QStandardItem
)
from PySide6.QtCore import Qt, QModelIndex, Signal, QMimeData
from pathlib import Path
from models.media_item import MediaItem
from processing.media_processor import detect_media_type
import logging

from src.system.safety import is_safe_path


class DragDropItemModel(QStandardItemModel):
    def supportedDragActions(self):
        return Qt.MoveAction

    def flags(self, index):
        default_flags = super().flags(index)
        if not index.isValid():
            return Qt.ItemIsDropEnabled
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled

    def dropMimeData(self, data, action, row, column, parent):
        if column == 0:
            self.logger.warning("Attempted drop into column 0 (row numbers)")
            return False  # prevent corruption
        return super().dropMimeData(data, action, row, column, parent)


class NoFocusDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index: QModelIndex):
        option.state &= ~QStyle.State_HasFocus
        super().paint(painter, option, index)

class DragDropSortableTable(QTreeView):
    row_remove_requested = Signal(int)
    files_dropped = Signal(tuple)  # (file_paths, target_row)

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)

        self.logger = logger or logging.getLogger(__name__)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

        self.model = DragDropItemModel()
        self.model.setHorizontalHeaderLabels(["#", "Filename", "Type", "Status"])
        self.setModel(self.model)

        header = self.header()
        header.setSectionResizeMode(QHeaderView.Stretch)
        self.setSortingEnabled(False)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.setRootIsDecorated(True)
        self.setItemsExpandable(True)
        self.setTreePosition(1)
        self.setIndentation(20)
        self._drag_hover_pos = None
        self._drop_y = None

    def load_items(self, media_items: list[MediaItem]):
        self.model.removeRows(0, self.model.rowCount())
        folder_items = {}

        sorted_items = sorted(media_items, key=lambda i: (i.depth, i.is_folder))

        for item in sorted_items:
            row_items = [
                QStandardItem(""),  # Column 0: Row number
                QStandardItem(f"📁 {item.basename}" if item.is_folder else item.basename),  # Column 1: Tree
                QStandardItem("Folder" if item.is_folder else detect_media_type(item.path, logger=self.logger)),
                QStandardItem(item.status)
            ]
            for q in row_items:
                q.setEditable(False)
                q.setData(item, Qt.UserRole)
                q.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)

            if item.parent_folder in folder_items:
                folder_items[item.parent_folder][0].appendRow(row_items)
            else:
                self.model.appendRow(row_items)

            if item.is_folder:
                folder_items[item.path] = row_items

        self.expandAll()
        self.renumber_visible_rows()

    def renumber_visible_rows(self):
        row_number = 1

        def walk(parent: QStandardItem):
            nonlocal row_number
            for i in range(parent.rowCount()):
                child = parent.child(i)
                if not child:
                    continue
                index = self.model.indexFromItem(child)
                if self.isExpanded(index) or not child.hasChildren():
                    child.setText(str(row_number))
                    row_number += 1
                    if child.hasChildren():
                        walk(child)

        for i in range(self.model.rowCount()):
            top = self.model.item(i, 0)
            top.setText(str(row_number))
            row_number += 1
            if top.hasChildren() and self.isExpanded(self.model.index(i, 0)):
                walk(top)

    def get_item_at_row(self, row: int) -> MediaItem:
        top = self.model.item(row, 0)
        return top.data(Qt.UserRole)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            raw_paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            safe_paths = []
            for path_str in raw_paths:
                path = Path(path_str)
                if is_safe_path(path, logger=self.logger):
                    safe_paths.append(path_str)
                else:
                    self.logger.warning(f"Refused to accept unsafe dropped path: {path}")

            if not safe_paths:
                self.logger.warning("All dropped files were unsafe. Ignoring drop event.")
                return

            pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
            index = self.indexAt(pos)
            target_row = index.row() if index.isValid() else -1
            self.files_dropped.emit((safe_paths, target_row))
            event.acceptProposedAction()
            return

        indexes = self.selectedIndexes()
        if not indexes:
            return

        source_index = indexes[0]
        source_item = self.model.itemFromIndex(source_index)
        if not source_item:
            return

        source_parent = source_item.parent()
        source_row = source_index.row()

        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        hover_index = self.indexAt(pos)
        hover_item = self.model.itemFromIndex(hover_index)
        hover_parent = hover_item.parent() if hover_item else None
        hover_row = hover_index.row() if hover_index.isValid() else -1

        row_items = [
            source_parent.child(source_row, c) if source_parent else self.model.item(source_row, c)
            for c in range(self.model.columnCount())
        ]
        cloned_items = [item.clone() for item in row_items]

        if source_parent:
            source_parent.removeRow(source_row)
        else:
            self.model.removeRow(source_row)

        if hover_item:
            rect = self.visualRect(hover_index)
            insert_above = pos.y() < rect.center().y()

            if hover_parent == source_parent:
                insert_row = hover_row if insert_above else hover_row + 1
                (hover_parent or self.model).insertRow(insert_row, cloned_items)
            else:
                insert_row = 0 if pos.y() < rect.center().y() else (
                    source_parent.rowCount() if source_parent else self.model.rowCount()
                )
                (source_parent or self.model).insertRow(insert_row, cloned_items)
        else:
            insert_row = 0 if pos.y() < 0 else (
                source_parent.rowCount() if source_parent else self.model.rowCount()
            )
            (source_parent or self.model).insertRow(insert_row, cloned_items)

        self.renumber_visible_rows()
        self._drop_y = None
        self.viewport().update()
        event.acceptProposedAction()

    def leaveEvent(self, event):
        self._drag_hover_pos = None
        self.viewport().update()
        super().leaveEvent(event)

    def startDrag(self, supportedActions):
        index = self.currentIndex()
        if not index.isValid() or index.column() != 1:
            return

        mime = self.model.mimeData([index])
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)

    def sort_within_groups(self, column: int, ascending: bool = True):
        for i in range(self.model.rowCount()):
            parent = self.model.item(i, 0)
            children = []
            for r in range(parent.rowCount()):
                row_data = [parent.child(r, c) for c in range(self.model.columnCount())]
                children.append(row_data)

            children.sort(key=lambda row: row[column].text().lower(), reverse=not ascending)
            parent.removeRows(0, parent.rowCount())
            for row_data in children:
                parent.appendRow(row_data)

        self.renumber_visible_rows()

    def _show_context_menu(self, pos):
        index = self.indexAt(pos)
        if not index.isValid():
            return

        item = self.model.itemFromIndex(index)
        media_item = item.data(Qt.UserRole)
        if not media_item:
            return

        parent = item.parent()
        menu = QMenu(self)
        remove_action = QAction("Remove", self)

        def do_remove():
            if parent:
                parent.removeRow(item.row())
            else:
                self.model.removeRow(item.row())
            self.renumber_visible_rows()

        remove_action.triggered.connect(do_remove)
        menu.addAction(remove_action)
        menu.exec(self.viewport().mapToGlobal(pos))

    def is_cursor_within_viewport(self, global_pos):
        local_pos = self.mapFromGlobal(global_pos)
        return self.viewport().rect().contains(local_pos)

    def on_header_clicked(self, col):
        if col == 0:
            return

        ascending = not self.sort_ascending if self.last_sorted_column == col else True
        self.last_sorted_column = col
        self.sort_ascending = ascending

        expanded_paths = set()
        for i in range(self.model.rowCount()):
            index = self.model.index(i, 1)
            if self.isExpanded(index):
                item = self.model.itemFromIndex(index)
                media_item = item.data(Qt.UserRole)
                if media_item:
                    expanded_paths.add(str(media_item.path))

        self.model.blockSignals(True)  # Prevent unnecessary UI redraws

        for i in range(self.model.rowCount()):
            parent = self.model.item(i, 1)
            if parent:
                self._deep_folder_sort(parent, col, ascending)

        self.model.blockSignals(False)

        for i in range(self.model.rowCount()):
            index = self.model.index(i, 1)
            item = self.model.itemFromIndex(index)
            media_item = item.data(Qt.UserRole)
            if media_item and str(media_item.path) in expanded_paths:
                self.setExpanded(index, True)

        self.renumber_visible_rows()

    def dragEnterEvent(self, event):
        event.acceptProposedAction()

    def dragMoveEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        index = self.indexAt(pos)

        if index.isValid():
            rect = self.visualRect(index)
            self._drop_y = rect.top() if pos.y() < rect.center().y() else rect.bottom()
        else:
            if pos.y() < 0:
                self._drop_y = 0
            else:
                last_row = self.model.rowCount() - 1
                last_index = self.model.index(last_row, 1)
                self._drop_y = self.visualRect(last_index).bottom()

        event.acceptProposedAction()
        self.viewport().update()

    def _deep_folder_sort(self, parent_item: QStandardItem, col: int, ascending: bool):
        children = []
        for r in range(parent_item.rowCount()):
            row_data = [parent_item.child(r, c) for c in range(self.model.columnCount())]
            children.append(row_data)

        children.sort(key=lambda row: row[col].text().lower(), reverse=not ascending)

        parent_item.removeRows(0, parent_item.rowCount())
        for row_data in children:
            parent_item.appendRow(row_data)
            if row_data[1].hasChildren():
                self._deep_folder_sort(row_data[1], col, ascending)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.clearSelection()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        index = self.indexAt(event.pos())
        if not index.isValid():
            self.clearSelection()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drop_y is None:
            return

        painter = QPainter(self.viewport())
        pen = QPen(QColor(self.palette().highlight().color()))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(0, self._drop_y, self.viewport().width(), self._drop_y)