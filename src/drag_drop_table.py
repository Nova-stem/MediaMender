#src/drag_drop_table.py
#23 May 2025

from PySide6.QtWidgets import (
    QTreeView, QHeaderView, QMenu, QAbstractItemView, QStyledItemDelegate, QStyle, QLabel
)
from PySide6.QtGui import (
    QDrag, QPainter, QPen, QColor, QAction, QStandardItemModel, QStandardItem
)
from PySide6.QtCore import Qt, QModelIndex, Signal, QMimeData, QTimer, QPoint
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
        self.drop_target_index = QModelIndex()  # actual resolved drop index
        self.drag_position_y = -1  # track last drag position to control redraw

        self.up_arrow = QLabel("⬆", self.viewport())
        self.up_arrow.setStyleSheet("color: red; font-size: 20px; background-color: rgba(255, 255, 255, 200);")
        self.up_arrow.setVisible(False)

        self.down_arrow = QLabel("⬇", self.viewport())
        self.down_arrow.setStyleSheet("color: red; font-size: 20px; background-color: rgba(255, 255, 255, 200);")
        self.down_arrow.setVisible(False)

        self.auto_scroll_timer = QTimer(self)
        self.auto_scroll_timer.timeout.connect(self._check_drag_scroll)
        self.scroll_edge_margin = 40  # px near edge to trigger scrolling
        self.scroll_max_speed = 20  # max scroll step
        self.scroll_sticky_zone = 10  # Dead zone inside edge
        self.drop_below = True  # NEW: track drag-bar position

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

    def dropEvent_OLD1(self, event):
        # ✅ NEW: Always re-resolve drop location to ensure correctness
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        self.drop_target_index, self.drop_below = self.resolve_valid_drop_target(pos)
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

            insert_row = self.drop_target_index.row()
            if self.drop_below:
                insert_row += 1

            self.files_dropped.emit((safe_paths, insert_row))
            event.acceptProposedAction()
            return

        indexes = self.selectedIndexes()
        if not indexes:
            return

        source_index = indexes[0]
        source_item = self.model.itemFromIndex(source_index)
        is_folder_drag = source_item.data(Qt.UserRole).is_folder
        if not source_item:
            return

        source_parent = source_item.parent()
        source_row = source_index.row()

        self.logger.debug(f"[DROP] Source row: {source_row}, Source parent: {source_parent}")
        self.logger.debug(f"[DROP] Drop target index: {self.drop_target_index}, Drop below: {self.drop_below}")

        target_item = self.model.itemFromIndex(self.drop_target_index)
        target_parent = target_item.parent() if target_item else None
        target_model = target_parent if target_parent else self.model

        insert_row = self.drop_target_index.row()
        if self.drop_below:
            insert_row += 1

        self.logger.debug(f"[DROP] Target parent: {target_parent}, Insert row: {insert_row}, Target model rowCount: {target_model.rowCount()}")

        if is_folder_drag:
            block_rows = self.extract_folder_block(source_index)

            if source_parent:
                source_parent.removeRow(source_row)
            else:
                self.model.removeRow(source_row)

            for offset, row in enumerate(block_rows):
                target_model.insertRow(insert_row + offset, row)

            insert_index = self.model.indexFromItem(block_rows[0][1])
        else:
            row_items = [
                source_parent.child(source_row, c) if source_parent else self.model.item(source_row, c)
                for c in range(self.model.columnCount())
            ]
            cloned_items = [item.clone() for item in row_items]

            if source_parent:
                source_parent.removeRow(source_row)
            else:
                self.model.removeRow(source_row)

            success = target_model.insertRow(insert_row, cloned_items)
            if not success:
                self.logger.error("[DROP] insertRow returned False!")

            insert_index = self.model.indexFromItem(cloned_items[1])

        self.setCurrentIndex(insert_index)
        self.expand(self.model.indexFromItem(block_rows[0][1]))
        self.scrollTo(insert_index, QAbstractItemView.PositionAtCenter)

        self.renumber_visible_rows()
        self.drop_target_index = QModelIndex()
        self.auto_scroll_timer.stop()
        self.drag_position_y = -1
        self.viewport().update()
        event.acceptProposedAction()
        self.up_arrow.setVisible(False)
        self.down_arrow.setVisible(False)

    def dropEvent(self, event):
        #pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        #self.drop_target_index, self.drop_below = self.resolve_valid_drop_target(pos)

        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        source_index = self.currentIndex()

        result = self.resolve_final_drop_target(source_index, pos)
        if result is None:
            self.logger.warning("Drop location invalid — ignoring drop")
            return

        self.drop_target_index, self.drop_below = result

        # External file drop
        if event.mimeData().hasUrls():
            raw_paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            safe_paths = [p for p in raw_paths if is_safe_path(Path(p), logger=self.logger)]
            if not safe_paths:
                self.logger.warning("All dropped files were unsafe. Ignoring drop event.")
                return

            insert_row = self.drop_target_index.row()
            if self.drop_below:
                insert_row += 1

            self.files_dropped.emit((safe_paths, insert_row))
            event.acceptProposedAction()
            return

        # Internal drag
        indexes = self.selectedIndexes()
        if not indexes:
            return

        source_index = indexes[0]
        source_item = self.model.itemFromIndex(source_index)
        if not source_item:
            return

        is_folder_drag = source_item.data(Qt.UserRole).is_folder
        source_parent = source_item.parent()
        source_row = source_index.row()

        target_item = self.model.itemFromIndex(self.drop_target_index)
        target_parent = target_item.parent() if target_item else None
        target_model = target_parent if target_parent else self.model

        insert_row = self.drop_target_index.row()
        if self.drop_below:
            insert_row += 1

        # Prevent invalid nesting (block all cross-folder for files)
        if not is_folder_drag and source_parent != target_parent:
            self.logger.info("Redirected illegal file move to valid source folder boundary")
            insert_row = source_row + 1 if self.drop_below else source_row

        # --- FOLDER MOVE BLOCK ---
        if is_folder_drag:
            block_rows = self.extract_folder_block(source_index)

            if source_parent:
                source_parent.removeRows(source_row, len(block_rows))
            else:
                self.model.removeRows(source_row, len(block_rows))

            for i, row_items in enumerate(block_rows):
                target_model.insertRow(insert_row + i, row_items)

            insert_index = self.model.indexFromItem(block_rows[0][1])
            self.setExpanded(insert_index, True)
        else:
            # --- SINGLE FILE MOVE ---
            row_items = [
                source_parent.child(source_row, c) if source_parent else self.model.item(source_row, c)
                for c in range(self.model.columnCount())
            ]
            cloned_items = [item.clone() for item in row_items]

            if source_parent:
                source_parent.removeRow(source_row)
            else:
                self.model.removeRow(source_row)

            target_model.insertRow(insert_row, cloned_items)
            insert_index = self.model.indexFromItem(cloned_items[1])

        self.setCurrentIndex(insert_index)
        self.scrollTo(insert_index, QAbstractItemView.PositionAtCenter)
        self.renumber_visible_rows()
        self.drop_target_index = QModelIndex()
        self.auto_scroll_timer.stop()
        self.drag_position_y = -1
        self.viewport().update()
        event.acceptProposedAction()
        self.up_arrow.setVisible(False)
        self.down_arrow.setVisible(False)

    def leaveEvent(self, event):
        self._drag_hover_pos = None
        self.viewport().update()
        super().leaveEvent(event)

    def startDrag(self, supportedActions):
        index = self.currentIndex()
        if not index.isValid():
            return

        # Always drag from column 1 (Filename)
        if index.column() != 1:
            index = index.siblingAtColumn(1)

        item = self.model.itemFromIndex(index)
        if not item:
            return

        media = item.data(Qt.UserRole)
        if not media:
            return

        # ❌ Disallow dragging nested children of folders (e.g. sub-sub-items)
        # ✅ Allow root files, folder items, and folder children (now safe)
        # We only block if it's deeply nested
        if item.parent() and item.parent().data(Qt.UserRole).is_folder and not media.is_folder:
            # This is a child of a folder (like A1, A2) — now allowed!
            pass

        mime = self.model.mimeData([index])
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)

    def startDrag_OLD2(self, supportedActions):
        index = self.currentIndex()
        print(f"START DRAG called for index: {index.row()}, col: {index.column()}, valid: {index.isValid()}")
        if not index.isValid() or index.column() != 1:
            return

        item = self.model.itemFromIndex(index)
        media = item.data(Qt.UserRole)
        if not media:
            return

        if item.parent() and not media.is_folder:
            self.logger.warning("Dragging child items is disabled to prevent folder corruption")
            return

        mime = self.model.mimeData([index])
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)

    def startDrag_OLD(self, supportedActions):
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
        self.auto_scroll_timer.start(30)
        event.acceptProposedAction()

    def dragMoveEvent_OLD(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        #index, below = self.resolve_valid_drop_target(pos)

        #self.drop_target_index = index
        #self.drop_below = below
        #self.drag_position_y = pos.y()
        #self.viewport().update()
        #event.accept()

        index = self.indexAt(pos)
        self.drop_target_index, self.drop_below = self.resolve_valid_drop_target(pos)

        # If dragging a folder, prevent bar from showing inside another folder
        if index.isValid():
            target_item = self.model.itemFromIndex(index)
            target_media = target_item.data(Qt.UserRole)
            if target_media and target_media.is_folder:
                # Force drop to valid outer edge
                rect = self.visualRect(index)
                self.drop_below = pos.y() >= rect.center().y()

    def dragMoveEvent_OLD2(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        self.drop_target_index, self.drop_below = self.resolve_valid_drop_target(pos)

        # Hide bar if this would cause invalid nesting
        index = self.currentIndex()
        source_item = self.model.itemFromIndex(index)
        is_folder_drag = source_item and source_item.data(Qt.UserRole).is_folder

        if is_folder_drag:
            hover_item = self.model.itemFromIndex(self.drop_target_index)
            hover_media = hover_item.data(Qt.UserRole) if hover_item else None
            if hover_media and hover_media.is_folder:
                rect = self.visualRect(self.drop_target_index)
                self.drop_below = pos.y() >= rect.center().y()

        self.drag_position_y = pos.y()
        self.viewport().update()
        event.accept()

    def dragMoveEvent_OLD3(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        source_index = self.currentIndex()

        result = self.resolve_final_drop_target(source_index, pos)
        if result is None:
            self.drop_target_index = QModelIndex()
            self.viewport().update()
            return

        self.drop_target_index, self.drop_below = result
        self.drag_position_y = pos.y()
        view_rect = self.viewport().rect()
        if self.drop_target_index.isValid():
            drop_rect = self.visualRect(self.drop_target_index)

            if drop_rect.bottom() < view_rect.top():
                self.up_arrow.move(view_rect.width() // 2 - 10, 5)
                self.up_arrow.setVisible(True)
                self.down_arrow.setVisible(False)
            elif drop_rect.top() > view_rect.bottom():
                self.down_arrow.move(view_rect.width() // 2 - 10, view_rect.height() - 25)
                self.down_arrow.setVisible(True)
                self.up_arrow.setVisible(False)
            else:
                self.up_arrow.setVisible(False)
                self.down_arrow.setVisible(False)
        else:
            self.up_arrow.setVisible(False)
            self.down_arrow.setVisible(False)
        self.viewport().update()
        event.accept()

    def dragMoveEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        source_index = self.currentIndex()
        result = self.resolve_final_drop_target(source_index, pos)

        if result is None:
            self.drop_target_index = QModelIndex()
            self.up_arrow.setVisible(False)
            self.down_arrow.setVisible(False)
            self.viewport().update()
            return

        self.drop_target_index, self.drop_below = result
        self.drag_position_y = pos.y()
        self.viewport().update()
        event.accept()

        # 🔻 Show arrows if bar is offscreen
        view_rect = self.viewport().rect()
        drop_rect = self.visualRect(self.drop_target_index)

        if drop_rect.bottom() < view_rect.top():
            self.up_arrow.move(view_rect.width() // 2 - 10, 5)
            self.up_arrow.setVisible(True)
            self.down_arrow.setVisible(False)
        elif drop_rect.top() > view_rect.bottom():
            self.down_arrow.move(view_rect.width() // 2 - 10, view_rect.height() - 25)
            self.down_arrow.setVisible(True)
            self.up_arrow.setVisible(False)
        else:
            self.up_arrow.setVisible(False)
            self.down_arrow.setVisible(False)

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

        if not self.drop_target_index or not self.drop_target_index.isValid():
            return

        rect = self.visualRect(self.drop_target_index)
        y = rect.top() if self.drop_below is False else rect.bottom()

        painter = QPainter(self.viewport())
        pen = QPen(Qt.red, 2, Qt.SolidLine)
        painter.setPen(pen)
        painter.drawLine(0, y, self.viewport().width(), y)
        painter.end()

    def _check_drag_scroll(self):
        if self.drag_position_y < 0:
            return  # Not actively dragging

        margin = self.scroll_edge_margin
        sticky_zone = self.scroll_sticky_zone
        max_speed = self.scroll_max_speed

        view_rect = self.viewport().rect()
        y = self.drag_position_y

        bar = self.verticalScrollBar()
        direction = 0

        # Top edge
        if y < view_rect.top() + margin:
            distance = (margin - (y - view_rect.top()))
            if distance > sticky_zone:
                # Speed ramps up smoothly after sticky_zone
                direction = -min(max_speed, max(1, (distance - sticky_zone) // 4))

        # Bottom edge
        elif y > view_rect.bottom() - margin:
            distance = (y - (view_rect.bottom() - margin))
            if distance > sticky_zone:
                direction = min(max_speed, max(1, (distance - sticky_zone) // 4))

        if direction != 0:
            bar.setValue(bar.value() + direction)
            self.viewport().update()

    def resolve_valid_drop_target(self, pos: QPoint) -> tuple[QModelIndex, bool]:
        index = self.indexAt(pos)
        model = self.model

        if not index.isValid():
            return model.index(model.rowCount() - 1, 0), True

        item = model.itemFromIndex(index)
        media = item.data(Qt.UserRole) if item else None
        rect = self.visualRect(index)

        if media and media.is_folder:
            # For folder dragging, snap to top or bottom of folder only
            return index, pos.y() >= rect.center().y()

        # Snap above row 0 only if cursor is above midpoint
        if index.row() == 0 and pos.y() < rect.center().y():
            return index, False

        return index, pos.y() > rect.center().y()

    def extract_folder_block(self, index: QModelIndex) -> list[list[QStandardItem]]:
        item = self.model.itemFromIndex(index)
        if not item or not item.data(Qt.UserRole).is_folder:
            return []

        block = []
        folder_row = item.row()
        row_items = [item.model().item(folder_row, col) for col in range(self.model.columnCount())]
        block.append([i.clone() for i in row_items])

        for r in range(item.rowCount()):
            child_items = [item.child(r, col) for col in range(self.model.columnCount())]
            block.append([i.clone() for i in child_items])

        return block

    def remove_folder_block(self, index: QModelIndex):
        item = self.model.itemFromIndex(index)
        if not item or not item.data(Qt.UserRole).is_folder:
            return

        total_rows = item.rowCount() + 1
        model = item.parent() if item.parent() else self.model
        model.removeRows(item.row(), total_rows)

    def resolve_final_drop_target_OLD(self, source_index: QModelIndex, pos: QPoint) -> tuple[QModelIndex, bool] | None:
        model = self.model
        hover_index = self.indexAt(pos)
        if not hover_index.isValid():
            # If hovering empty space, treat as drop at end of root
            if not source_index.isValid():
                return None
            source_item = model.itemFromIndex(source_index)
            if source_item.data(Qt.UserRole).is_folder:
                return model.index(model.rowCount() - 1, 0), True  # drop folder at end
            else:
                # files must stay inside their folder — can't drop outside
                return None

        source_item = model.itemFromIndex(source_index)
        hover_item = model.itemFromIndex(hover_index)

        if not source_item or not hover_item:
            return None

        source_is_folder = source_item.data(Qt.UserRole).is_folder
        hover_is_folder = hover_item.data(Qt.UserRole).is_folder
        source_parent = source_item.parent()
        hover_parent = hover_item.parent()

        hover_rect = self.visualRect(hover_index)
        hover_row = hover_index.row()
        drop_below = pos.y() >= hover_rect.center().y()

        # ✅ Folder being dragged — allow between top-level folder rows
        if source_is_folder:
            if hover_parent:
                # Cannot drop folder into another folder
                return None
            return hover_index, drop_below

        # ✅ File being dragged
        if source_parent == hover_parent:
            return hover_index, drop_below  # same folder = valid move

        # ❌ Invalid cross-folder file drag
        if not source_parent:
            return None  # root-level file cannot move into a folder

        # Snap file to nearest edge of its own folder
        siblings = source_parent.rowCount()
        source_row = source_index.row()

        if pos.y() < hover_rect.center().y():
            target_row = 0
        else:
            target_row = siblings

        #return source_parent.child(target_row, 0).index(), False if target_row == 0 else True
        if target_row >= source_parent.rowCount():
            # Make a safe index for "after last child"
            #return source_parent.index().child(source_parent.rowCount() - 1, 0), True
            last_valid = source_parent.child(source_parent.rowCount() - 1, 0)
            if last_valid:
                return last_valid.index(), True
            else:
                return None
        else:
            return source_parent.child(target_row, 0).index(), target_row != 0

    def resolve_final_drop_target(self, source_index: QModelIndex, pos: QPoint) -> tuple[QModelIndex, bool] | None:
        model = self.model
        hover_index = self.indexAt(pos)
        source_item = model.itemFromIndex(source_index)
        if not source_item:
            return None

        source_is_folder = source_item.data(Qt.UserRole).is_folder
        source_parent = source_item.parent()
        source_row = source_index.row()

        # If hovering empty space
        if not hover_index.isValid():
            if source_is_folder:
                return model.index(model.rowCount() - 1, 0), True
            else:
                return None  # files can't leave their folder

        hover_item = model.itemFromIndex(hover_index)
        if not hover_item:
            return None

        hover_is_folder = hover_item.data(Qt.UserRole).is_folder
        hover_parent = hover_item.parent()
        hover_rect = self.visualRect(hover_index)
        drop_below = pos.y() >= hover_rect.center().y()

        # 🧱 Folder drag: allow at root only
        if source_is_folder:
            if hover_parent:
                return None  # disallow drop into another folder
            return hover_index, drop_below

        # 📁 File drag
        if source_parent == hover_parent:
            return hover_index, drop_below  # intra-folder reorder allowed

        if not source_parent:
            return None  # root file can't leave root

        # Snap back to top or bottom of source folder
        count = source_parent.rowCount()
        if count == 0:
            return None

        if pos.y() < hover_rect.center().y():
            # Snap to top
            top = source_parent.child(0, 0)
            return (top.index(), False) if top else None
        else:
            # Snap to bottom
            bottom = source_parent.child(count - 1, 0)
            return (bottom.index(), True) if bottom else None

    #----------------------------------------



    def resolve_valid_drop_target_Old(self, pos: QPoint) -> tuple[QModelIndex, bool]:
        """
        Resolves a valid drop location based on the mouse position.
        Ensures that the drop does not land inside folders or outside its current parent.
        Returns: (target_index, drop_below)
        """
        index = self.indexAt(pos)
        if not index.isValid():
            # Snap to bottom of root
            return self.model.index(self.model.rowCount() - 1, 0), True

        item = self.model.itemFromIndex(index)
        media = item.data(Qt.UserRole) if item else None
        rect = self.visualRect(index)

        if media and media.is_folder:
            # Cannot drop INTO folder — snap below it
            return index, True

        if index.row() == 0 and pos.y() < rect.center().y():
            return index, False  # Above first row
        else:
            return index, True   # Below any other row

    def dropEvent_OLD(self, event):
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
            #index = self.indexAt(pos)
            #target_row = index.row() if index.isValid() else -1
            #self.files_dropped.emit((safe_paths, target_row))
            insert_row = self.drop_target_index.row()
            if self.drop_below:
                insert_row += 1

            self.files_dropped.emit((safe_paths, insert_row))
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

        #pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        #hover_index = self.drop_target_index if self.drop_target_index.isValid() else self.indexAt(pos)
        #hover_item = self.model.itemFromIndex(hover_index)
        #hover_parent = hover_item.parent() if hover_item else None
        #hover_row = hover_index.row() if hover_index.isValid() else -1

        row_items = [
            source_parent.child(source_row, c) if source_parent else self.model.item(source_row, c)
            for c in range(self.model.columnCount())
        ]
        cloned_items = [item.clone() for item in row_items]

        if source_parent:
            source_parent.removeRow(source_row)
        else:
            self.model.removeRow(source_row)

        target_parent = (
            self.model.itemFromIndex(self.drop_target_index).parent()
            if self.drop_target_index.isValid()
            else None
        )
        target_model = target_parent if target_parent else self.model

        insert_row = self.drop_target_index.row()
        if self.drop_below:
            insert_row += 1

        target_model.insertRow(insert_row, cloned_items)

        #if hover_item:
        #    rect = self.visualRect(hover_index)
        #    insert_above = pos.y() < rect.center().y()

        #    if hover_parent == source_parent:
        #        insert_row = hover_row if insert_above else hover_row + 1
        #        (hover_parent or self.model).insertRow(insert_row, cloned_items)
        #    else:
        #        insert_row = 0 if pos.y() < rect.center().y() else (
        #            source_parent.rowCount() if source_parent else self.model.rowCount()
        #        )
        #        (source_parent or self.model).insertRow(insert_row, cloned_items)
        #else:
        #    insert_row = 0 if pos.y() < 0 else (
        #        source_parent.rowCount() if source_parent else self.model.rowCount()
        #    )
        #    (source_parent or self.model).insertRow(insert_row, cloned_items)

        self.renumber_visible_rows()
        self.drop_target_index = QModelIndex()
        self.auto_scroll_timer.stop()
        self.drag_position_y = -1
        self.viewport().update()
        event.acceptProposedAction()
        self.up_arrow.setVisible(False)
        self.down_arrow.setVisible(False)

    def paintEvent_OLD2(self, event):
        super().paintEvent(event)

        if not self.drop_target_index or not self.drop_target_index.isValid():
            return

        rect = self.visualRect(self.drop_target_index)
        y = rect.bottom()

        if self.drop_target_index.row() == 0 and self.drag_position_y < rect.center().y():
            y = rect.top()

        painter = QPainter(self.viewport())
        pen = QPen(Qt.red, 2, Qt.SolidLine)
        painter.setPen(pen)
        painter.drawLine(0, y, self.viewport().width(), y)
        painter.end()

    def paintEvent_OLD3(self, event):
        super().paintEvent(event)

        if not self.drop_target_index or not self.drop_target_index.isValid():
            return

        rect = self.visualRect(self.drop_target_index)
        y = rect.bottom() if self.drop_below else rect.top()

        painter = QPainter(self.viewport())
        pen = QPen(Qt.red, 2, Qt.SolidLine)
        painter.setPen(pen)
        painter.drawLine(0, y, self.viewport().width(), y)
        painter.end()

    def dragMoveEvent_OLD2(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        index = self.indexAt(pos)

        # Determine where the file would land
        if index.isValid():
            rect = self.visualRect(index)
            self.drop_target_index = index
            self.drop_below = pos.y() > rect.center().y()
        else:
            # Drop is below all items
            self.drop_target_index = self.model.index(self.model.rowCount() - 1, 0)
            self.drop_below = True

        self.drag_position_y = pos.y()
        self.viewport().update()
        event.accept()

    def dragMoveEvent_OLD(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        index = self.indexAt(pos)

        # Compute visual drop row
        row_count = self.model.rowCount()
        hover_row = index.row()
        first_rect = self.visualRect(self.model.index(0, 0))
        is_above_first_row = pos.y() < first_rect.center().y()

        # Determine legal drop target row
        if not index.isValid():
            target_row = row_count
        elif hover_row == 0 and is_above_first_row:
            target_row = 0  # insert above first row
        else:
            target_row = hover_row + 1  # insert *after* current row

        # Store resolved drop index (used in paint)
        model = self.model
        self.drop_target_index = model.index(min(target_row, row_count - 1), 0)


        self.drag_position_y = pos.y()
        self.viewport().update()  # trigger paint
        event.accept()

        # Position of drop rect
        if self.drop_target_index.isValid():
            drop_rect = self.visualRect(self.drop_target_index)
            view_rect = self.viewport().rect()

            # Check offscreen state
            if drop_rect.bottom() < view_rect.top():
                # Target is above
                self.up_arrow.move(view_rect.width() // 2 - 10, 5)
                self.up_arrow.setVisible(True)
                self.down_arrow.setVisible(False)

            elif drop_rect.top() > view_rect.bottom():
                # Target is below
                self.down_arrow.move(view_rect.width() // 2 - 10, view_rect.height() - 25)
                self.down_arrow.setVisible(True)
                self.up_arrow.setVisible(False)

            else:
                self.up_arrow.setVisible(False)
                self.down_arrow.setVisible(False)

    def dragMoveEvent_OLD(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        index = self.indexAt(pos)

        if not index.isValid():
            self.drop_target_index = self.model.index(self.model.rowCount() - 1, 0)
            self.drop_below = True
        else:
            rect = self.visualRect(index)
            row = index.row()
            if row == 0 and pos.y() < rect.center().y():
                self.drop_target_index = index
                self.drop_below = False  # special case: above top row
            else:
                self.drop_target_index = index
                self.drop_below = True

        self.drag_position_y = pos.y()
        self.viewport().update()
        event.accept()

    def resolve_valid_drop_target_Old2(self, pos: QPoint) -> tuple[QModelIndex, bool]:
        index = self.indexAt(pos)
        model = self.model

        if not index.isValid():
            return model.index(model.rowCount() - 1, 0), True  # Drop at very bottom

        item = model.itemFromIndex(index)
        media = item.data(Qt.UserRole) if item else None
        rect = self.visualRect(index)

        if media and media.is_folder:
            return index, True  # Force snap BELOW folder

        # Snap above row 0 only if cursor is above midpoint
        if index.row() == 0 and pos.y() < rect.center().y():
            return index, False

        # All other rows: standard midpoint logic
        return index, pos.y() > rect.center().y()

    def extract_folder_block_Old(self, index: QModelIndex) -> list[list[QStandardItem]]:
        item = self.model.itemFromIndex(index)
        if not item or not item.data(Qt.UserRole).is_folder:
            return []

        block = []

        row_items = [item.model().item(item.row(), col) for col in range(self.model.columnCount())]
        block.append([i.clone() for i in row_items])

        for row in range(item.rowCount()):
            child_row = [item.child(row, col) for col in range(self.model.columnCount())]
            block.append([i.clone() for i in child_row])

        return block