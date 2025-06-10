#src/drag_drop_table.py
#23 May 2025

from PySide6.QtWidgets import (
    QTreeView, QHeaderView, QMenu, QAbstractItemView, QStyledItemDelegate, QStyle, QLabel
)
from PySide6.QtGui import (
    QDrag, QPainter, QPen, QColor, QAction, QStandardItemModel, QStandardItem, QPixmap
)
from PySide6.QtCore import Qt, QModelIndex, Signal, QMimeData, QTimer, QPoint
from pathlib import Path
from models.media_item import MediaItem
from processing.media_processor import detect_media_type
import logging
import inspect

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
        self._drop_pos = 0
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
        self._drag_source_index = None
        #print(f"[DEBUG DROP TARGET SET (INIT)] drop_target_index={self.drop_target_index.row()}, drop_below={self.drop_below}")
        self._row_height = self.rowHeight(self.model.index(0, 0))
        #print(f"[DEBUG] (init) Row height: {self._row_height}px")

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
        self._row_height = self.rowHeight(self.model.index(0, 0))
        #print(f"[DEBUG] (renumber_visible_rows) Row height: {self._row_height}px")
        row_number = 1

        def walk(item: QStandardItem):
            nonlocal row_number
            if not item:
                return

            index = self.model.indexFromItem(item)
            if self.isExpanded(index) or not item.hasChildren():
                item.setText(str(row_number))
                row_number += 1

            # Walk children
            for i in range(item.rowCount()):
                child = item.child(i, 0)
                walk(child)

        # Start walking top-level items
        for i in range(self.model.rowCount()):
            parent_item = self.model.item(i, 0)
            walk(parent_item)

    def get_item_at_row(self, row: int) -> MediaItem:
        top = self.model.item(row, 0)
        return top.data(Qt.UserRole)

    def dropEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        source_index = self.currentIndex()
        print(f"[DEBUG DROP EVENT START] pos={pos}, source_index={source_index.row() if source_index.isValid() else 'INVALID'}")
        self._drag_source_index = None

        hover_index = self.indexAt(pos)
        target_parent = None
        result = self.determine_drop_location(hover_index, source_index, pos)
        if result is None:
            self.logger.warning("Drop location invalid — ignoring drop")
            #print("[DEBUG] dropEvent: No valid target — rejecting drop")
            #print(f"[DEBUG DROP EVENT CLEAR] Invalid drop — clearing drop_target_index")
            self._drop_pos = None  # <- 🔥 Clear drop state on rejected drop
            self.viewport().update()  # <- 🔥 Force repaint to clear the line
            event.ignore()
            return

        self.drop_target_index, self.drop_below = result
        #print(f"[DEBUG DROP TARGET SET (dropEvent)] drop_target_index={self.drop_target_index.row()}, drop_below={self.drop_below}")
        target_row = self.drop_target_index.row()

        # FORBID reparenting into folders
        target_item = self.model.itemFromIndex(self.drop_target_index)
        media_item = target_item.data(Qt.UserRole) if target_item else None
        is_target_folder = media_item and getattr(media_item, "is_folder", False)

        if is_target_folder:
            # When dropping ONTO a folder, forbid drop *into* folder; Force parent to stay same as source
            self.setDropIndicatorShown(False)  # Hide the built-in drop indicator
            self.model.blockSignals(True)  # Temporarily block signals
            event.ignore()  # Forbid the event
            self.model.blockSignals(False)
            self._drop_pos = None
            self.viewport().update()
            #print(f"[DEBUG] Drop ignored — not allowed to drop inside folder")
            return

        # External file drop
        if event.mimeData().hasUrls():
            raw_paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            safe_paths = [p for p in raw_paths if is_safe_path(Path(p), logger=self.logger)]
            if not safe_paths:
                self.logger.warning("All dropped files were unsafe. Ignoring drop event.")
                return

            insert_row = target_row + 1 if self.drop_below else target_row
            self.logger.debug(f"[DropEvent] External drop: row={insert_row}, below={self.drop_below}")
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

        # Determine target model and parent
        target_item = self.model.itemFromIndex(self.drop_target_index)
        target_parent = target_item.parent() if target_item else None
        target_model = target_parent if target_parent else self.model

        # Determine insert row
        insert_row = target_item.row() if target_item else target_row
        if self.drop_below:
            insert_row += 1

        if target_model == (source_parent if source_parent else self.model) and insert_row > source_row:
            insert_row -= 1

        # Restrict files to original folder (prevent dragging into or out of folders)
        if not is_folder_drag and source_parent != target_parent:
            self.logger.info("Redirected illegal file move to valid source folder boundary")
            insert_row = source_row + 1 if self.drop_below else source_row

        if is_folder_drag:
            # Move entire folder block
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
            # Move single file
            row_items = [
                source_parent.child(source_row, c) if source_parent else self.model.item(source_row, c)
                for c in range(self.model.columnCount())
            ]
            cloned_items = [item.clone() for item in row_items]

            try:
                if source_parent:
                    source_parent.removeRow(source_row)
                else:
                    self.model.removeRow(source_row)

                target_model.insertRow(insert_row, cloned_items)
                insert_index = self.model.indexFromItem(cloned_items[1])
            except Exception as e:
                self.logger.exception("Failed to insert dropped file, restoring original row")
                if source_parent:
                    source_parent.insertRow(source_row, cloned_items)
                else:
                    self.model.insertRow(source_row, cloned_items)
                return

        self.setCurrentIndex(insert_index)
        self.scrollTo(insert_index, QAbstractItemView.PositionAtCenter)
        self.renumber_visible_rows()
        self.drop_target_index = QModelIndex()
        #print(f"[DEBUG DROP TARGET SET (also dropEvent)] drop_target_index={self.drop_target_index.row()}, drop_below={self.drop_below}")
        self._drop_pos = None
        self.auto_scroll_timer.stop()
        self.drag_position_y = -1
        self.viewport().update()
        event.acceptProposedAction()
        self.up_arrow.setVisible(False)
        self.down_arrow.setVisible(False)
        #print(f"[DEBUG DROP EVENT ACCEPTED] drop_target_index={self.drop_target_index.row()}, drop_below={self.drop_below}")

    def leaveEvent(self, event):
        self._drag_hover_pos = None
        self.viewport().update()
        super().leaveEvent(event)

    def startDrag(self, supportedActions):
        self._drag_source_index = self.currentIndex()
        index = self._drag_source_index
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

    def dragMoveEvent(self, event):
        def describe_index_brief(index: QModelIndex) -> str:
            if not index.isValid():
                return "ROOT"
            item = self.model.itemFromIndex(index)
            if not item:
                return f"Row {index.row()}: Unknown"
            text = item.text() or "Unnamed"
            return f"Row {index.row()}: {text}"

        # -- DEBUG: Event start
        #print(f"[DEBUG DRAG MOVE EVENT] pos={event.pos()}, current drop_target_index={self.drop_target_index.row() if self.drop_target_index and self.drop_target_index.isValid() else 'None'}")

        # (1) Get the raw mouse position
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()

        # (2) Save viewport-relative position for painting
        self._drop_pos = pos

        # (3) Save ABSOLUTE y-coordinate for calculations (helper will translate it)
        self.drag_position_y = pos.y() + self.get_scroll_position()

        # (4) Resolve hovered index and determine drop target
        source_index = self.currentIndex()
        hover_index = self.indexAt(pos)
        result = self.determine_drop_location(hover_index, source_index, pos)

        # -- DEBUG: Hovered row description
        #print(f"[DEBUG] (dragMoveEvent) Hovered index: {describe_index_brief(hover_index)}")

        if result is None:
            self.drop_target_index = QModelIndex()
            #print(f"[DEBUG DROP TARGET SET (dragMoveEvent)] drop_target_index={self.drop_target_index.row()}, drop_below={self.drop_below}")
            self.viewport().update()
            return

        # (5) Save result from determine_drop_location (index and drop_below)
        self.drop_target_index, self.drop_below = result
        #print(f"[DEBUG DROP TARGET SET (also dragMoveEvent)] drop_target_index={self.drop_target_index.row()}, drop_below={self.drop_below}")

        # (6) Request a repaint
        self.viewport().update()

        # (7) Accept the event so Qt knows we handled it
        event.accept()

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

        if not hasattr(self, 'drop_target_index') or self.drop_target_index is None:
            return

        index = self.drop_target_index
        drop_below = self.drop_below

        if not index or not index.isValid():
            return

        rect = self.visualRect(index)
        # Calculate the absolute Y position
        scroll_offset = self.get_scroll_position()
        row_top_abs = rect.top() + scroll_offset
        row_bottom_abs = rect.bottom() + scroll_offset
        y_absolute = row_bottom_abs if drop_below else row_top_abs

        #print(f"[DEBUG PAINT EVENT] drop_target_index={index.row()}, drop_below={drop_below}")

        painter = QPainter(self.viewport())
        pen = QPen(Qt.red, 2, Qt.SolidLine)
        painter.setPen(pen)
        # Draw the line relative to the viewport
        painter.drawLine(0, y_absolute - scroll_offset, self.viewport().width(), y_absolute - scroll_offset)
        painter.end()

        # --- ARROW HANDLING BELOW ---

        viewport_top = scroll_offset
        viewport_bottom = viewport_top + self.get_viewport_height()

        if y_absolute < viewport_top:
            #print("[DEBUG] paintEvent: Showing UP arrow (drop ABOVE visible area)")
            self.up_arrow.move(self.viewport().width() // 2 - 10, 5)
            self.up_arrow.setVisible(True)
            self.down_arrow.setVisible(False)
        elif y_absolute > viewport_bottom:
            #print("[DEBUG] paintEvent: Showing DOWN arrow (drop BELOW visible area)")
            self.down_arrow.move(self.viewport().width() // 2 - 10, self.viewport().height() - 25)
            self.down_arrow.setVisible(True)
            self.up_arrow.setVisible(False)
        else:
            #print("[DEBUG] paintEvent: No arrows needed — drop inside viewport")
            self.up_arrow.setVisible(False)
            self.down_arrow.setVisible(False)

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

    def extract_folder_block(self, index: QModelIndex) -> list[list[QStandardItem]]:
        item = self.model.itemFromIndex(index)
        if not item or not item.data(Qt.UserRole).is_folder:
            return []

        block = []

        # Clone the folder itself (no row math)
        row_items = [item.child(0, col).parent() if col == 0 else item.siblingAtColumn(col) for col in
                     range(self.model.columnCount())]
        block.append([i.clone() for i in row_items])

        # Now clone all its children properly
        for r in range(item.rowCount()):
            child_row = []
            for c in range(self.model.columnCount()):
                child_item = item.child(r, c)
                if child_item:
                    child_row.append(child_item.clone())
            if child_row:
                block.append(child_row)

        return block

    def remove_folder_block(self, index: QModelIndex):
        item = self.model.itemFromIndex(index)
        if not item or not item.data(Qt.UserRole).is_folder:
            return

        parent = item.parent() if item.parent() else self.model

        if parent:
            parent.removeRow(item.row())

    def is_folder(self, index: QModelIndex) -> bool:
        if not index.isValid():
            return False
        item = self.model.itemFromIndex(index)
        if not item:
            return False
        data = item.data(Qt.UserRole)
        return getattr(data, "is_folder", False)

    def find_ancestor_folder(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()  # ROOT
        item = self.model.itemFromIndex(index)
        media_item = item.data(Qt.UserRole) if item else None
        if media_item and getattr(media_item, "is_folder", False):
            return index
        return self.find_ancestor_folder(index.parent())

    def describe_index(self, index: QModelIndex) -> str:
        if not index.isValid():
            return "ROOT"
        item = self.model.itemFromIndex(index)
        if not item:
            return "Unknown"
        text = item.text()
        if text:
            return text
        return "Unknown"

    def determine_drop_location(self, hover_index: QModelIndex, source_index: QModelIndex | None, pos: QPoint) -> tuple[QModelIndex, bool] | None:
        caller = inspect.stack()[1].function
        #print(f"[DEBUG] Called from {caller}")
        model = self.model
        scroll_offset = self.get_scroll_position()
        cursor_y = pos.y() + scroll_offset

        def absolute_top(index: QModelIndex) -> int: return self.get_row_bounds(index.row())[0]

        def absolute_bottom(index: QModelIndex) -> int: return self.get_row_bounds(index.row())[1]

        if not hover_index.isValid():
            if source_index is None:
                return None

            # Drop-to-end
            root_parent = source_index.parent() if source_index.isValid() else QModelIndex()
            row_count = model.rowCount(root_parent)

            if row_count == 0:
                return None

            last_index = model.index(row_count - 1, 0, parent=root_parent)
            last_bottom = absolute_bottom(last_index)

            #print(f"[DEBUG] Cursor Y={cursor_y}, Last item bottom Y={last_bottom}")

            if cursor_y > last_bottom:
                #print(f"[DEBUG] Cursor past last item — snapping below last item")
                return last_index, True
            else:
                #print(f"[DEBUG] Cursor not past last item — no valid drop target")
                return None

        # Normalize to column 0
        hover_index = hover_index.siblingAtColumn(0)
        item = model.itemFromIndex(hover_index)
        media_item = item.data(Qt.UserRole) if item else None
        is_folder = media_item and getattr(media_item, "is_folder", False)
        hover_indent = getattr(media_item, "indent_level", 0)

        if source_index is None:
            source_indent = hover_indent
        else:
            source_index = source_index.siblingAtColumn(0)
            source_item = model.itemFromIndex(source_index)
            source_media = source_item.data(Qt.UserRole)
            source_indent = getattr(source_media, "indent_level", 0)

        #print(f"[DEBUG] hover_row={hover_index.row()}, drop_below={self.drop_below}, source_indent={source_indent}, hover_indent={hover_indent}")

        hover_top = absolute_top(hover_index)
        hover_bottom = absolute_bottom(hover_index)
        hover_mid_y = (hover_top + hover_bottom) // 2

        drop_below = cursor_y > hover_mid_y

        #print(f"[DEBUG] Hover visual absolute top={hover_top}, bottom={hover_bottom}, mid_y={hover_mid_y}, cursor_y={cursor_y}")
        #print(f"[DEBUG] Hover item: {'folder' if is_folder else 'file'}, drop_below={drop_below}")

        if source_index is None:
            print(f"[DEBUG] Painting — no parent check")
            return hover_index, drop_below

        source_ancestor = self.find_ancestor_folder(source_index)
        hover_ancestor = self.find_ancestor_folder(hover_index)

        #print(f"[DEBUG] Source Ancestor: {self.describe_index(source_ancestor)} | Hover Ancestor: {self.describe_index(hover_ancestor)}")

        if source_ancestor != hover_ancestor:
            print(f"[DEBUG] Ancestor mismatch — snapping to group boundary of hovered folder")
            group_top_row, group_bottom_row = self.get_group_bounds(hover_index)

            # 🚨 NEW SAFETY: Validate row bounds
            group_top_row = max(0, min(group_top_row[0], model.rowCount() - 1))
            group_bottom_row = max(0, min(group_bottom_row[0], model.rowCount() - 1))

            #print(f"[DEBUG] Group bounds: top_row={group_top_row}, bottom_row={group_bottom_row}")

            top_index = model.index(group_top_row, 0)
            bottom_index = model.index(group_bottom_row, 0)

            group_top_y = absolute_top(top_index)
            group_bottom_y = absolute_bottom(bottom_index)
            group_mid_y = (group_top_y + group_bottom_y) // 2

            #print(f"[DEBUG] Group Y bounds: top={group_top_y}, bottom={group_bottom_y}, mid={group_mid_y}")

            if cursor_y < group_mid_y:
                print(f"[DEBUG] Cursor above mid — snapping ABOVE group at row {group_top_row}")
                return top_index, False
            else:
                print(f"[DEBUG] Cursor below mid — snapping BELOW group at row {group_bottom_row}")
                return bottom_index, True

        if is_folder:
            print(f"[DEBUG] Hover target is a folder — snapping OUTSIDE folder group")
            group_top_row, group_bottom_row = self.get_group_bounds(hover_index)

            group_top_row = max(0, min(group_top_row[0], model.rowCount() - 1))
            group_bottom_row = max(0, min(group_bottom_row[0], model.rowCount() - 1))

            top_index = model.index(group_top_row, 0)
            bottom_index = model.index(group_bottom_row, 0)

            folder_rect = self.visualRect(hover_index)

            if folder_rect.top() <= cursor_y <= folder_rect.bottom():
                print(f"[DEBUG] Cursor is inside folder header — snapping ABOVE group at row {group_top_row}")
                return top_index, False

            group_top_y = absolute_top(top_index)
            group_bottom_y = absolute_bottom(bottom_index)
            group_mid_y = (group_top_y + group_bottom_y) // 2

            if cursor_y < group_mid_y:
                print(f"[DEBUG] Cursor above mid — snapping ABOVE folder group at row {group_top_row}")
                return top_index, False
            else:
                print(f"[DEBUG] Cursor below mid — snapping BELOW folder group at row {group_bottom_row}")
                return bottom_index, True

        print(f"[DEBUG] Normal drop — same parent, not a folder")
        return hover_index, drop_below

    def get_group_bounds(self, hover_index: QModelIndex) -> tuple[tuple[int, int], tuple[int, int]]:
        if not hover_index.isValid():
            raise ValueError("Invalid hover_index provided to get_group_bounds()")

        model = self.model

        hover_index = hover_index.siblingAtColumn(0)  # 🛡️ Normalize to column 0

        hover_parent = hover_index.parent()
        hover_row = hover_index.row()
        row_count = model.rowCount(hover_parent)

        top_row = hover_row
        bottom_row = hover_row

        # 🔼 Walk UP
        for r in range(hover_row - 1, -1, -1):
            sibling = model.index(r, 0, parent=hover_parent)
            if not sibling.isValid():
                break
            if self.find_ancestor_folder(sibling) != self.find_ancestor_folder(hover_index):
                break
            top_row = r

        # 🔽 Walk DOWN
        for r in range(hover_row + 1, row_count):
            sibling = model.index(r, 0, parent=hover_parent)
            if not sibling.isValid():
                break
            if self.find_ancestor_folder(sibling) != self.find_ancestor_folder(hover_index):
                break
            bottom_row = r

        # 🛡️ Clamp to safe bounds
        top_row = max(0, min(top_row, row_count - 1))
        bottom_row = max(0, min(bottom_row, row_count - 1))

        return (top_row, top_row), (bottom_row, bottom_row)

    def get_total_table_height(self) -> int:
        """Returns total pixel height of all rows combined."""
        if not self.model:
            return 0
        return self._row_height * self.model.rowCount()

    def get_viewport_height(self) -> int:
        """Returns the pixel height of the visible viewport area."""
        return self.viewport().height()

    def get_scroll_position(self) -> int:
        """Returns the current vertical scroll position (in pixels)."""
        return self.verticalScrollBar().value()

    def get_scroll_range(self) -> int:
        """Returns the maximum scroll range (in pixels)."""
        return self.verticalScrollBar().maximum()

    def is_row_visible(self, row: int) -> bool:
        """Returns True if the given row index is at least partially visible in the viewport."""
        if not self.model():
            return False

        row_top = row * self._row_height
        row_bottom = row_top + self._row_height

        viewport_top = self.get_scroll_position()
        viewport_bottom = viewport_top + self.get_viewport_height()

        # Check if any part of the row overlaps the visible area
        return not (row_bottom < viewport_top or row_top > viewport_bottom)

    def get_row_bounds(self, row: int) -> tuple[int, int]:
        """Returns (top_y, bottom_y) pixel coordinates for a given row relative to the full table."""
        if not self.model:
            return 0, 0
        row_top = row * self._row_height
        row_bottom = row_top + self._row_height
        return row_top, row_bottom

    def normalize_hover_index(self, index: QModelIndex) -> QModelIndex:
        """Walks up to find the top-most parent of the given index."""
        while index.parent().isValid():
            index = index.parent()
        return index


# ----------------------------------------












class oldThings():
    def get_group_bounds_NOTUSED(self, index: QModelIndex) -> tuple[int, int, int]:
        model = self.model
        row = index.row()

        # Walk backwards to find the start of the group (a top-level parent)
        group_start = row
        while group_start > 0:
            idx = model.index(group_start, 0)
            if not model.parent(idx).isValid():
                break
            group_start -= 1

        top_index = model.index(group_start, 0)
        if not self.isExpanded(top_index) and model.hasChildren(top_index):
            self.expand(top_index)
        top_rect = self.visualRect(top_index)
        top_y = top_rect.top() if top_rect.isValid() else 0

        # Walk forward to find the end of this group
        group_end = group_start
        while True:
            next_index = model.index(group_end + 1, 0)
            if not next_index.isValid() or not model.parent(next_index).isValid():
                break
            group_end += 1

        bottom_index = model.index(group_end, 0)
        if not self.isExpanded(bottom_index) and model.hasChildren(bottom_index):
            self.expand(bottom_index)
        bottom_rect = self.visualRect(bottom_index)
        bottom_y = bottom_rect.bottom() if bottom_rect.isValid() else self.viewport().height()

        #print(f"[DEBUG] get_group_bounds(index.row={row}, column=1)")
        #print(f"[DEBUG] Returning group bounds: group_row={group_start}, top_y={top_y}, bottom_y={bottom_y}")
        return group_start, top_y, bottom_y

    def determine_drop_location_OLD2(self, hover_index: QModelIndex, source_index: QModelIndex | None, pos: QPoint) -> tuple[QModelIndex, bool] | None:
        model = self.model

        if not hover_index.isValid():
            if source_index is not None:
                # Dragging but no valid hover — fallback to top/bottom snap
                group_row, group_top, group_bottom = self.get_group_bounds(source_index)
                mid_y = (group_top + group_bottom) // 2
                fallback = model.index(group_row, 1)
                return (fallback, False) if pos.y() < mid_y else (fallback, True)
            else:
                # Painting — no valid hover — no drop line
                return None

        item = model.itemFromIndex(hover_index)
        media_item = item.data(Qt.UserRole) if item else None
        is_folder = media_item and getattr(media_item, "is_folder", False)

        cursor_y = pos.y()
        _, group_top, group_bottom = self.get_group_bounds(hover_index)
        drop_below = cursor_y > (group_top + group_bottom) // 2

        if source_index is None:
            # Painting mode — no parent checking
            return hover_index, drop_below

        # Source and hover parents
        source_parent = source_index.parent()
        hover_parent = hover_index.parent()

        if source_parent != hover_parent:
            # Not same parent — invalid move — snap to source group
            group_row, group_top, group_bottom = self.get_group_bounds(source_index)
            mid_y = (group_top + group_bottom) // 2
            fallback = model.index(group_row, 1)
            return (fallback, False) if pos.y() < mid_y else (fallback, True)

        # Same parent — check if we're dropping on a folder
        if is_folder:
            # Dropping on a folder — insert as first child
            if model.hasChildren(hover_index):
                first_child_index = model.index(0, 0, parent=hover_index)
                return first_child_index, False
            else:
                # Folder has no children — drop below folder
                return hover_index, True

        # Dropping on a file inside same folder — normal behavior
        return hover_index, drop_below

    def determine_drop_location_OLD(self, hover_index: QModelIndex, source_index: QModelIndex | None, pos: QPoint) -> tuple[QModelIndex, bool] | None:
        model = self.model

        if not hover_index.isValid():
            if source_index is not None:
                # Dragging but no valid hover — fallback to top/bottom snap
                group_row, group_top, group_bottom = self.get_group_bounds(source_index)
                mid_y = (group_top + group_bottom) // 2
                if pos.y() < mid_y:
                    fallback = model.index(group_row, 1)  # Column 1 = filename column
                    return fallback, False
                else:
                    fallback = model.index(group_row, 1)
                    return fallback, True
            else:
                # Painting — no valid hover — no drop line
                return None

        # Determine if the drop should happen above or below
        cursor_y = pos.y()
        _, group_top, group_bottom = self.get_group_bounds(hover_index)
        drop_below = cursor_y > (group_top + group_bottom) // 2

        # Special logic: if dropping on folder, and cursor is in upper half, insert above
        item = model.itemFromIndex(hover_index)
        media_item = item.data(Qt.UserRole) if item else None
        if media_item and getattr(media_item, "is_folder", False) and not drop_below:
            return hover_index, False

        if source_index is None:
            # Paint case — no parent enforcement
            return hover_index, True if drop_below else False

        # Dragging — enforce parent boundaries
        source_parent = source_index.parent()
        hover_parent = hover_index.parent()

        if source_parent == hover_parent:
            # Valid drop within same parent
            return hover_index, True if drop_below else False
        else:
            # Invalid move — snap back to original folder
            group_row, group_top, group_bottom = self.get_group_bounds(source_index)
            mid_y = (group_top + group_bottom) // 2
            if pos.y() < mid_y:
                fallback = model.index(group_row, 1)
                return fallback, False
            else:
                fallback = model.index(group_row, 1)
                return fallback, True

    def resolve_final_drop_target_OLD(self, source_index: QModelIndex, pos: QPoint) -> tuple[QModelIndex, bool] | None:
        index = self.indexAt(pos)
        #if not index.isValid():
        #    row = self.model.rowCount() - 1
        #    fallback = self.model.index(row, 1)
        #    return (fallback, True) if fallback.isValid() else None

        #row = index.row()
        #_, group_top, group_bottom = self.get_group_bounds(index)

        model = self.model
        if source_index is not None:
            source_parent = source_index.parent()
        else:
            source_parent = None

        if not index.isValid():
            if source_index is not None:
                # No hover target — fallback to snapping to top/bottom of source group
                group_row, group_top, group_bottom = self.get_group_bounds(source_index)
                mid_y = (group_top + group_bottom) // 2
                if pos.y() < mid_y:
                    fallback = model.index(group_row, 1)  # Top row of the group
                    return fallback, False
                else:
                    fallback = model.index(group_row, 1)  # Bottom of the group
                    return fallback, True
            else:
                return None

        hover_parent = index.parent()

        if source_parent == hover_parent:
            # Same parent — normal drop behavior
            _, group_top, group_bottom = self.get_group_bounds(index)

            cursor_y = pos.y()
            drop_below = cursor_y > (group_top + group_bottom) // 2

            item = model.itemFromIndex(index)
            media_item = item.data(Qt.UserRole) if item else None
            if media_item and getattr(media_item, "is_folder", False) and not drop_below:
                return index, False

            return index, True
        else:
            # Different parent — snap to top/bottom of original folder group
            group_row, group_top, group_bottom = self.get_group_bounds(source_index)
            mid_y = (group_top + group_bottom) // 2
            if pos.y() < mid_y:
                fallback = model.index(group_row, 1)
                return fallback, False
            else:
                fallback = model.index(group_row, 1)
                return fallback, True

        cursor_y = pos.y()
        drop_below = cursor_y > (group_top + group_bottom) // 2

        item = self.model.itemFromIndex(index)
        media_item = item.data(Qt.UserRole) if item else None
        if media_item and getattr(media_item, "is_folder", False) and not drop_below:
            return index, False

        return index, True

    def resolve_final_drop_target_NOTUSED(self, source_index: QModelIndex, pos: QPoint) -> tuple[QModelIndex, bool] | None:
        hover_index = self.indexAt(pos)
        return self.determine_drop_location(hover_index, source_index, pos)

    def remove_folder_block_OLD(self, index: QModelIndex):
        item = self.model.itemFromIndex(index)
        if not item or not item.data(Qt.UserRole).is_folder:
            return

        total_rows = item.rowCount() + 1
        model = item.parent() if item.parent() else self.model
        model.removeRows(item.row(), total_rows)

    def extract_folder_block_OLD(self, index: QModelIndex) -> list[list[QStandardItem]]:
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


    def determine_drop_location_old3(self, hover_index: QModelIndex, source_index: QModelIndex | None, pos: QPoint) -> tuple[QModelIndex, bool] | None:
        caller = inspect.stack()[1].function
        print(f"[DEBUG] Called from {caller}")

        model = self.model

        # 🚨 INSTEAD of recomputing scroll offset + pos.y(), use precomputed ABSOLUTE Y:
        cursor_y = self.drag_position_y  # <- 🛠️ Correct: Already includes scrollbar offset

        def absolute_top(index: QModelIndex) -> int:
            return self.visualRect(index).top() + self.get_scroll_position()

        def absolute_bottom(index: QModelIndex) -> int:
            return self.visualRect(index).bottom() + self.get_scroll_position()

        print(f"[DEBUG] Original Hover Index: {hover_index}")
        hover_index = self.normalize_hover_index(hover_index)
        print(f"[DEBUG] Normalized Hover Index: {hover_index}")

        if not hover_index.isValid():
            print(f"[DEBUG] No valid hover index")
            if source_index is None:
                print(f"[DEBUG] No source index: PaintEvent, no drop line")
                return None

            # Handle drop-to-end (past last item)
            root_parent = source_index.parent() if source_index.isValid() else QModelIndex()
            row_count = model.rowCount(root_parent)

            if row_count == 0:
                print(f"[DEBUG] Empty parent — nothing to snap to")
                return None

            last_index = model.index(row_count - 1, 0, parent=root_parent)
            last_bottom = absolute_bottom(last_index)

            print(f"[DEBUG] Cursor Y={cursor_y}, Last item bottom Y={last_bottom}")

            if cursor_y > last_bottom:
                print(f"[DEBUG] Cursor past last item — snapping below last item")
                return last_index, True
            else:
                print(f"[DEBUG] Cursor not past last item — no valid drop target")
                return None

        item = model.itemFromIndex(hover_index)
        media_item = item.data(Qt.UserRole) if item else None
        is_folder = media_item and getattr(media_item, "is_folder", False)

        hover_top = absolute_top(hover_index)
        hover_bottom = absolute_bottom(hover_index)
        hover_mid_y = (hover_top + hover_bottom) // 2

        drop_below = cursor_y > hover_mid_y

        print(
            f"[DEBUG] Hover visual absolute top={hover_top}, bottom={hover_bottom}, mid_y={hover_mid_y}, cursor_y={cursor_y}")
        print(f"[DEBUG] Hover item: {'folder' if is_folder else 'file'}, drop_below={drop_below}")

        if source_index is None:
            print(f"[DEBUG] Painting — no parent check")
            return hover_index, drop_below

        source_ancestor = self.find_ancestor_folder(source_index)
        hover_ancestor = self.find_ancestor_folder(hover_index)

        print(
            f"[DEBUG] Source Ancestor: {self.describe_index(source_ancestor)} | Hover Ancestor: {self.describe_index(hover_ancestor)}")

        if source_ancestor != hover_ancestor:
            print(f"[DEBUG] Ancestor mismatch — snapping to group boundary of hovered folder")
            group_top_row, group_bottom_row = self.get_group_bounds(hover_index)
            print(f"[DEBUG] Group bounds: top_row={group_top_row}, bottom_row={group_bottom_row}")
            top_index = model.index(group_top_row[0], 0)
            bottom_index = model.index(group_bottom_row[0], 0)

            group_top_y = absolute_top(top_index)
            group_bottom_y = absolute_bottom(bottom_index)
            group_mid_y = (group_top_y + group_bottom_y) // 2

            print(f"[DEBUG] Group Y bounds: top={group_top_y}, bottom={group_bottom_y}, mid={group_mid_y}")

            if cursor_y < group_mid_y:
                print(f"[DEBUG] Cursor above mid — snapping ABOVE group at row {group_top_row}")
                return top_index, False
            else:
                print(f"[DEBUG] Cursor below mid — snapping BELOW group at row {group_bottom_row}")
                return bottom_index, True

        if is_folder:
            print(f"[DEBUG] Hover target is a folder — snapping OUTSIDE folder group")
            group_top_row, group_bottom_row = self.get_group_bounds(hover_index)
            top_index = model.index(group_top_row[0], 0)
            bottom_index = model.index(group_bottom_row[0], 0)

            folder_rect = self.visualRect(hover_index)

            folder_top_y = folder_rect.top() + self.get_scroll_position()
            folder_bottom_y = folder_rect.bottom() + self.get_scroll_position()

            if folder_top_y <= cursor_y <= folder_bottom_y:
                print(f"[DEBUG] Cursor is inside folder header — snapping ABOVE group at row {group_top_row}")
                return top_index, False

            group_top_y = absolute_top(top_index)
            group_bottom_y = absolute_bottom(bottom_index)
            group_mid_y = (group_top_y + group_bottom_y) // 2

            if cursor_y < group_mid_y:
                print(f"[DEBUG] Cursor above mid — snapping ABOVE folder group at row {group_top_row}")
                return top_index, False
            else:
                print(f"[DEBUG] Cursor below mid — snapping BELOW folder group at row {group_bottom_row}")
                return bottom_index, True

        print(f"[DEBUG] Normal drop — same parent, not a folder")
        return hover_index, drop_below

    def determine_drop_location_old2(self, hover_index: QModelIndex, source_index: QModelIndex | None, pos: QPoint) -> tuple[QModelIndex, bool] | None:
        caller = inspect.stack()[1].function
        print(f"[DEBUG] Called from {caller}")

        model = self.model

        scroll_offset = self.verticalScrollBar().value()
        cursor_y = pos.y()

        def absolute_top(index: QModelIndex) -> int:
            return self.visualRect(index).top() + scroll_offset

        def absolute_bottom(index: QModelIndex) -> int:
            return self.visualRect(index).bottom() + scroll_offset

        if not hover_index.isValid():
            print(f"[DEBUG] No valid hover index")
            # Special case: if source_index is None (paintEvent) allow painting nothing
            if source_index is None:
                print(f"[DEBUG] No source index: PaintEvent, no drop line")
                return None

            # Handle drop-to-end (past last item)
            root_parent = source_index.parent() if source_index.isValid() else QModelIndex()
            row_count = model.rowCount(root_parent)

            if row_count == 0:
                print(f"[DEBUG] Empty parent — nothing to snap to")
                return None  # No items at all

            last_index = model.index(row_count - 1, 0, parent=root_parent)
            last_bottom = absolute_bottom(last_index)

            print(f"[DEBUG] Cursor Y={cursor_y}, Last item bottom Y={last_bottom}")

            if cursor_y > last_bottom:
                print(f"[DEBUG] Cursor past last item — snapping below last item")
                return last_index, True  # Insert below last item
            else:
                print(f"[DEBUG] Cursor not past last item — no valid drop target")
                return None  # No good target

        item = model.itemFromIndex(hover_index)
        media_item = item.data(Qt.UserRole) if item else None
        is_folder = media_item and getattr(media_item, "is_folder", False)

        hover_top = absolute_top(hover_index)
        hover_bottom = absolute_bottom(hover_index)
        hover_mid_y = (hover_top + hover_bottom) // 2

        drop_below = cursor_y > hover_mid_y

        print(
            f"[DEBUG] Hover visual absolute top={hover_top}, bottom={hover_bottom}, mid_y={hover_mid_y}, cursor_y={cursor_y}")
        print(f"[DEBUG] Hover item: {'folder' if is_folder else 'file'}, drop_below={drop_below}")

        if source_index is None:
            print(f"[DEBUG] Painting — no parent check")
            return hover_index, drop_below

        source_ancestor = self.find_ancestor_folder(source_index)
        hover_ancestor = self.find_ancestor_folder(hover_index)

        print(f"[DEBUG] Source Ancestor: {self.describe_index(source_ancestor)} | Hover Ancestor: {self.describe_index(hover_ancestor)}")

        if source_ancestor != hover_ancestor:
            print(f"[DEBUG] Ancestor mismatch — snapping to group boundary of hovered folder")
            group_top_row, group_bottom_row = self.get_group_bounds(hover_index)
            print(f"[DEBUG] Group bounds: top_row={group_top_row}, bottom_row={group_bottom_row}")
            top_index = self.model.index(group_top_row[0], 0)
            bottom_index = self.model.index(group_bottom_row[0], 0)

            group_top_y = absolute_top(top_index)
            group_bottom_y = absolute_bottom(bottom_index)
            group_mid_y = (group_top_y + group_bottom_y) // 2

            print(f"[DEBUG] Group Y bounds: top={group_top_y}, bottom={group_bottom_y}, mid={group_mid_y}")

            if cursor_y < group_mid_y:
                print(f"[DEBUG] Cursor above mid — snapping ABOVE group at row {group_top_row}")
                return top_index, False  # Drop ABOVE the group
            else:
                print(f"[DEBUG] Cursor below mid — snapping BELOW group at row {group_bottom_row}")
                return bottom_index, True  # Drop BELOW the group

        if is_folder:
            print(f"[DEBUG] Hover target is a folder — snapping OUTSIDE folder group")
            group_top_row, group_bottom_row = self.get_group_bounds(hover_index)
            top_index = self.model.index(group_top_row[0], 0)
            bottom_index = self.model.index(group_bottom_row[0], 0)

            folder_rect = self.visualRect(hover_index)

            # Force snap ABOVE if hovering inside the folder header
            if folder_rect.top() <= cursor_y <= folder_rect.bottom():
                print(f"[DEBUG] Cursor is inside folder header — snapping ABOVE group at row {group_top_row}")
                return top_index, False

            # Otherwise, normal above/below snapping
            group_top_y = absolute_top(top_index)
            group_bottom_y = absolute_bottom(bottom_index)
            group_mid_y = (group_top_y + group_bottom_y) // 2

            if cursor_y < group_mid_y:
                print(f"[DEBUG] Cursor above mid — snapping ABOVE folder group at row {group_top_row}")
                return top_index, False
            else:
                print(f"[DEBUG] Cursor below mid — snapping BELOW folder group at row {group_bottom_row}")
                return bottom_index, True

        print(f"[DEBUG] Normal drop — same parent, not a folder")
        return hover_index, drop_below

    def determine_drop_location_OLD(self, hover_index: QModelIndex, source_index: QModelIndex | None, pos: QPoint) -> tuple[QModelIndex, bool] | None:
        caller = inspect.stack()[1].function
        print(f"[DEBUG] Called from {caller}")
        model = self.model
        if not hover_index.isValid():
            print(f"[DEBUG] No valid hover index")
            if source_index is not None:
                print(f"[DEBUG] Dragging fallback: snapping to source parent or folder")
                fallback_folder = source_index.parent()

                if not fallback_folder.isValid():
                    fallback_folder = source_index

                model = self.model
                row_count = model.rowCount(fallback_folder)

                if row_count > 0:
                    first_child_index = model.index(0, 0, parent=fallback_folder)
                    last_child_index = model.index(row_count - 1, 0, parent=fallback_folder)

                    first_child_rect = self.visualRect(first_child_index)
                    last_child_rect = self.visualRect(last_child_index)

                    group_top = first_child_rect.top()
                    group_bottom = last_child_rect.bottom()
                    drop_below = pos.y() > (group_top + group_bottom) // 2

                    if drop_below:
                        print(f"[DEBUG] Snapping fallback below last child of folder")
                        return last_child_index, True
                    else:
                        print(f"[DEBUG] Snapping fallback to first child of folder")
                        return first_child_index, False
                else:
                    print(f"[DEBUG] Snapping fallback directly below folder (no children)")
                    return fallback_folder, True
            else:
                print(f"[DEBUG] No source index: PaintEvent, no drop line")
                return None

        item = model.itemFromIndex(hover_index)
        media_item = item.data(Qt.UserRole) if item else None
        is_folder = media_item and getattr(media_item, "is_folder", False)

        rect = self.visualRect(hover_index)
        mid_y = rect.top() + rect.height() // 2
        drop_below = pos.y() > mid_y

        print(f"[DEBUG] visualRect top={rect.top()}, bottom={rect.bottom()}, mid_y={mid_y}, cursor_y={pos.y()}")
        print(f"[DEBUG] Hover item: {'folder' if is_folder else 'file'}, drop_below={drop_below}")

        if source_index is None:
            print(f"[DEBUG] Painting — no parent check")
            return hover_index, drop_below

        source_parent = source_index.parent()
        hover_parent = hover_index.parent()

        print(f"[DEBUG] source_parent.row(): {source_parent.row() if source_parent.isValid() else 'INVALID'}, "
              f"hover_parent.row(): {hover_parent.row() if hover_parent.isValid() else 'INVALID'}")

        if source_parent != hover_parent:
            print(f"[DEBUG] Parent mismatch — snapping to group boundary of hovered folder")
            group_top_row, group_bottom_row = self.get_group_bounds(hover_index)
            print(f"[DEBUG] Group bounds: top_row={group_top_row}, bottom_row={group_bottom_row}")
            top_index = self.model.index(group_top_row[0], 0)
            bottom_index = self.model.index(group_bottom_row[0], 0)

            top_rect = self.visualRect(top_index)
            bottom_rect = self.visualRect(bottom_index)

            group_top_y = top_rect.top()
            group_bottom_y = bottom_rect.bottom()
            group_mid_y = (group_top_y + group_bottom_y) // 2

            print(f"[DEBUG] Group Y bounds: top={group_top_y}, bottom={group_bottom_y}, mid={group_mid_y}")

            # Compare cursor Y position to midpoint
            if pos.y() < group_mid_y:
                print(f"[DEBUG] Cursor above mid — snapping ABOVE group at row {group_top_row}")
                return top_index, False  # Drop ABOVE the top of the group
            else:
                print(f"[DEBUG] Cursor below mid — snapping BELOW group at row {group_bottom_row}")
                return bottom_index, True  # Drop BELOW the bottom of the group

        if is_folder:
            print(f"[DEBUG] Hover target is a folder — inserting relative to folder, not inside")
            folder_rect = self.visualRect(hover_index)
            mid_y = folder_rect.top() + folder_rect.height() // 2
            drop_below = pos.y() > mid_y
            print(
                f"[DEBUG] Folder rect top={folder_rect.top()}, bottom={folder_rect.bottom()}, mid_y={mid_y}, cursor_y={pos.y()}, drop_below={drop_below}")
            return hover_index, drop_below

        print(f"[DEBUG] Normal drop — same parent, not a folder")
        return hover_index, drop_below

    def get_group_bounds_old(self, item):
        """Finds the top and bottom row indexes of the item's parent group."""
        parent = item.parent()
        if parent is None:
            parent = self.model.invisibleRootItem()

        if item.hasChildren():
            row = item.row()
            return row, row

        row = item.row()

        # Walk up
        top = row
        while top > 0:
            sibling = parent.child(top - 1)
            if sibling is None or sibling.hasChildren():
                break
            top -= 1

        # Walk down
        bottom = row
        while bottom + 1 < parent.rowCount():
            sibling = parent.child(bottom + 1)
            if sibling is None or sibling.hasChildren():
                break
            bottom += 1

        return top, bottom

    def get_group_bounds_old2(self, item: QModelIndex) -> tuple[int, int]:
        """Finds the top and bottom row indexes of the item's parent group (folder children block)."""
        model = self.model
        parent_index = item.parent()
        if not parent_index.isValid():
            parent_item = model.invisibleRootItem()
        else:
            parent_item = model.itemFromIndex(parent_index)

        # If the current item is a folder, the group is just itself
        item_obj = model.itemFromIndex(item)
        if item_obj.hasChildren():
            row = item.row()
            return row, row

        row = item.row()

        # Walk up to find top boundary
        top = row
        while top > 0:
            sibling_item = parent_item.child(top - 1)
            if sibling_item is None or sibling_item.hasChildren():
                break
            top -= 1

        # Walk down to find bottom boundary
        bottom = row
        while bottom + 1 < parent_item.rowCount():
            sibling_item = parent_item.child(bottom + 1)
            if sibling_item is None or sibling_item.hasChildren():
                break
            bottom += 1

        return top, bottom

    def get_group_bounds_old3(self, index):
        # Move upward to find the folder (header)
        current = index
        while current.isValid():
            if self.is_folder(current):
                break
            current = current.parent()
        top_row = current.row()

        # Move downward to find last child
        bottom_row = top_row
        next_row = top_row + 1
        while next_row < self.model.rowCount():
            next_index = self.model.index(next_row, 0)
            if self.is_folder(next_index):
                break  # Stop when next folder is found
            bottom_row = next_row
            next_row += 1

        return top_row, bottom_row

    def get_group_bounds_old4(self, folder_index):
        folder_row = folder_index.row()

        # Find last child row
        last_row = folder_row
        for r in range(folder_row + 1, self.model.rowCount()):
            idx = self.model.index(r, 0)
            if self.find_ancestor_folder(idx) != self.find_ancestor_folder(folder_index):
                break
            last_row = r

        folder_top = self.viewport().mapToGlobal(self.visualRect(self.model.index(folder_row, 0)).topLeft()).y()
        last_bottom = self.viewport().mapToGlobal(self.visualRect(self.model.index(last_row, 0)).bottomLeft()).y()

        return (folder_row, last_row), (folder_top, last_bottom)

    def describe_index_OLD(self, index: QModelIndex) -> str:
        if not index.isValid():
            return "ROOT"
        item = self.model.itemFromIndex(index)
        return item.text() if item else "Unknown"

    def find_ancestor_folder_OLD(self, index: QModelIndex) -> QModelIndex:
        while index.isValid():
            item = self.model.itemFromIndex(index)
            media_item = item.data(Qt.UserRole) if item else None
            if media_item and getattr(media_item, "is_folder", False):
                return index
            index = index.parent()
        return QModelIndex()

    def paintEvent_OLD(self, event):
        super().paintEvent(event)

        if not hasattr(self, '_drop_pos') or self._drop_pos is None:
            return

        hover_index = self.indexAt(self._drop_pos)
        result = self.determine_drop_location(hover_index, self._drag_source_index, self._drop_pos)
        if result is None:
            print("[DEBUG] paintEvent: No valid drop target")
            self.up_arrow.setVisible(False)
            self.down_arrow.setVisible(False)
            return

        index, drop_below = result
        if not index or not index.isValid():
            return

        rect = self.visualRect(index)
        y = rect.bottom() if drop_below else rect.top()

        print(f"[DEBUG PAINT EVENT] drop_target_index={self.drop_target_index.row() if self.drop_target_index and self.drop_target_index.isValid() else 'None'}, drop_below={self.drop_below}")

        painter = QPainter(self.viewport())
        pen = QPen(Qt.red, 2, Qt.SolidLine)
        painter.setPen(pen)
        painter.drawLine(0, y, self.viewport().width(), y)
        painter.end()

        # New arrow visibility control
        view_rect = self.viewport().rect()
        drop_rect = self.visualRect(index)

        if drop_rect.bottom() < view_rect.top():
            print("[DEBUG] paintEvent: Showing UP arrow")
            self.up_arrow.move(view_rect.width() // 2 - 10, 5)
            self.up_arrow.setVisible(True)
            self.down_arrow.setVisible(False)
        elif drop_rect.top() > view_rect.bottom():
            print("[DEBUG] paintEvent: Showing DOWN arrow")
            self.down_arrow.move(view_rect.width() // 2 - 10, view_rect.height() - 25)
            self.down_arrow.setVisible(True)
            self.up_arrow.setVisible(False)
        else:
            print("[DEBUG] paintEvent: No arrows needed — drop inside viewport")
            self.up_arrow.setVisible(False)
            self.down_arrow.setVisible(False)

    def paintEvent_odl2(self, event):
        super().paintEvent(event)

        if not hasattr(self, '_drop_pos') or self._drop_pos is None:
            return

        hover_index = self.indexAt(self._drop_pos)
        result = self.determine_drop_location(hover_index, self._drag_source_index, self._drop_pos)
        if result is None:
            print("[DEBUG] paintEvent: No valid drop target")
            self.up_arrow.setVisible(False)
            self.down_arrow.setVisible(False)
            return

        index, drop_below = result
        if not index or not index.isValid():
            return

        # 🔥🔥🔥 REPLACEMENT: Instead of visualRect(index) — absolute math using row
        row = index.row()
        row_top, row_bottom = self.get_row_bounds(row)
        y = row_bottom if drop_below else row_top
        # 🔥🔥🔥 END REPLACEMENT

        print(
            f"[DEBUG PAINT EVENT] drop_target_index={self.drop_target_index.row() if self.drop_target_index and self.drop_target_index.isValid() else 'None'}, drop_below={self.drop_below}")

        painter = QPainter(self.viewport())
        pen = QPen(Qt.red, 2, Qt.SolidLine)
        painter.setPen(pen)
        painter.drawLine(0, y - self.get_scroll_position(), self.viewport().width(), y - self.get_scroll_position())
        painter.end()

        # --- ARROW HANDLING BELOW ---

        # 🧠 Get viewport boundaries in absolute coords
        viewport_top = self.get_scroll_position()
        viewport_bottom = viewport_top + self.get_viewport_height()

        # Get the y coordinate of the drop line in absolute terms
        drop_line_y = y

        # 🔥 Hardened: Now check if the drop line is above or below the viewport
        if drop_line_y < viewport_top:
            print("[DEBUG] paintEvent: Showing UP arrow (drop ABOVE visible area)")
            self.up_arrow.move(self.viewport().width() // 2 - 10, 5)
            self.up_arrow.setVisible(True)
            self.down_arrow.setVisible(False)
        elif drop_line_y > viewport_bottom:
            print("[DEBUG] paintEvent: Showing DOWN arrow (drop BELOW visible area)")
            self.down_arrow.move(self.viewport().width() // 2 - 10, self.viewport().height() - 25)
            self.down_arrow.setVisible(True)
            self.up_arrow.setVisible(False)
        else:
            print("[DEBUG] paintEvent: No arrows needed — drop inside viewport")
            self.up_arrow.setVisible(False)
            self.down_arrow.setVisible(False)

    def paintEvent_old3(self, event):
        super().paintEvent(event)

        if not hasattr(self, 'drop_target_index') or self.drop_target_index is None:
            return

        index = self.drop_target_index
        drop_below = self.drop_below

        if not index or not index.isValid():
            return

        # 🔥 Replacement: Calculate absolute Y position based on target index
        row = index.row()
        row_top, row_bottom = self.get_row_bounds(row)
        y = row_bottom if drop_below else row_top

        print(f"[DEBUG PAINT EVENT] drop_target_index={row}, drop_below={drop_below}")

        painter = QPainter(self.viewport())
        pen = QPen(Qt.red, 2, Qt.SolidLine)
        painter.setPen(pen)
        painter.drawLine(0, y - self.get_scroll_position(), self.viewport().width(), y - self.get_scroll_position())
        painter.end()

        # --- ARROW HANDLING BELOW ---

        viewport_top = self.get_scroll_position()
        viewport_bottom = viewport_top + self.get_viewport_height()

        drop_line_y = y

        if drop_line_y < viewport_top:
            print("[DEBUG] paintEvent: Showing UP arrow (drop ABOVE visible area)")
            self.up_arrow.move(self.viewport().width() // 2 - 10, 5)
            self.up_arrow.setVisible(True)
            self.down_arrow.setVisible(False)
        elif drop_line_y > viewport_bottom:
            print("[DEBUG] paintEvent: Showing DOWN arrow (drop BELOW visible area)")
            self.down_arrow.move(self.viewport().width() // 2 - 10, self.viewport().height() - 25)
            self.down_arrow.setVisible(True)
            self.up_arrow.setVisible(False)
        else:
            print("[DEBUG] paintEvent: No arrows needed — drop inside viewport")
            self.up_arrow.setVisible(False)
            self.down_arrow.setVisible(False)

    def renumber_visible_rows_OLD(self):
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

    def dragMoveEventOLD(self, event):
        def describe_index_brief(index: QModelIndex) -> str:
            if not index.isValid():
                return "ROOT"
            item = self.model.itemFromIndex(index)
            if not item:
                return f"Row {index.row()}: Unknown"
            text = item.text() or "Unnamed"
            return f"Row {index.row()}: {text}"

        print(f"[DEBUG DRAG MOVE EVENT] pos={event.pos()}, current drop_target_index={self.drop_target_index.row() if self.drop_target_index and self.drop_target_index.isValid() else 'None'}")
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        self._drop_pos = pos

        source_index = self.currentIndex()
        hover_index = self.indexAt(pos)
        result = self.determine_drop_location(hover_index, source_index, pos)
        print(f"[DEBUG] (dragMoveEvent) Hovered index: {describe_index_brief(hover_index)}")

        if result is None:
            self.drop_target_index = QModelIndex()
            print(f"[DEBUG DROP TARGET SET (dragMoveEvent)] drop_target_index={self.drop_target_index.row()}, drop_below={self.drop_below}")
            self.viewport().update()
            return

        self.drop_target_index, self.drop_below = result
        print(f"[DEBUG DROP TARGET SET (also dragMoveEvent)] drop_target_index={self.drop_target_index.row()}, drop_below={self.drop_below}")
        self.drag_position_y = pos.y()
        self.viewport().update()
        event.accept()



    # target_item = self.model.itemFromIndex(self.drop_target_index)
    # media_item = target_item.data(Qt.UserRole) if target_item else None
    # target_is_folder = media_item.is_folder if media_item else False

    # if target_is_folder:
    #    # Drop into the folder
    #    target_model = target_item
    #    insert_row = 0  # insert at top of folder (could customize later)
    # else:
    #    # Normal file drop
    #    target_parent = target_item.parent() if target_item else None
    #    target_model = target_parent if target_parent else self.model

    #    insert_row = target_item.row() if target_item else target_row
    #    if self.drop_below:
    #        insert_row += 1
class DragDropItemModel_Defunct(QStandardItemModel):
    """Simple wrapper to avoid cyclic imports if you have any customizations."""
    pass
class DragDropSortableTable_Defunct(QTreeView):
    row_remove_requested = Signal(int)
    files_dropped = Signal(tuple)

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        #self._model = QStandardItemModel()
        #self.setModel(self._model)
        self.logger = logger or logging.getLogger(__name__)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.drop_target_index = None
        self.drop_below = True
        self.setUniformRowHeights(True)
        self.setAnimated(False)

        self.model = DragDropItemModel()
        self.model.setHorizontalHeaderLabels(["#", "Filename", "Type", "Status"])
        self.setModel(self.model)

        self.up_arrow = QLabel(self)
        self.up_arrow.setPixmap(QPixmap(":/icons/up-arrow.png").scaled(20, 20, Qt.KeepAspectRatio))
        self.up_arrow.setVisible(False)

        self.down_arrow = QLabel(self)
        self.down_arrow.setPixmap(QPixmap(":/icons/down-arrow.png").scaled(20, 20, Qt.KeepAspectRatio))
        self.down_arrow.setVisible(False)

    def get_row_bounds(self, row):
        index = self.model.index(row, 0)
        rect = self.visualRect(index)
        return rect.top(), rect.bottom()

    def get_scroll_position(self):
        return self.verticalScrollBar().value()

    def get_viewport_height(self):
        return self.viewport().height()

    def convert_absolute_to_viewport(self, y):
        return y - self.get_scroll_position()

    def get_indent(self, index):
        item = self.model.itemFromIndex(index)
        media = item.data(Qt.UserRole)
        return getattr(media, "indent_level", 0)

    def find_ancestor_folder(self, index):
        item = self.model.itemFromIndex(index)
        media = item.data(Qt.UserRole)
        if media and media.indent_level == 0:
            return index
        current_row = index.row()
        while current_row >= 0:
            parent_index = self.model.index(current_row, 0)
            media = self.model.itemFromIndex(parent_index).data(Qt.UserRole)
            if media and media.indent_level == 0:
                return parent_index
            current_row -= 1
        return QModelIndex()

    def get_group_bounds(self, index):
        top = index.row()
        while top > 0 and self.get_indent(self.model.index(top - 1, 0)) > 0:
            top -= 1
        bottom = index.row()
        max_row = self.model.rowCount() - 1
        while bottom < max_row and self.get_indent(self.model.index(bottom + 1, 0)) > 0:
            bottom += 1
        return top, bottom

    def dragMoveEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        self.cursor_absolute_y = pos.y() + self.get_scroll_position()
        source_index = self.currentIndex()
        result = self.determine_drop_location(self.indexAt(pos), source_index, pos)
        if result:
            self.drop_target_index, self.drop_below = result
        else:
            self.drop_target_index = None
        self.viewport().update()

    def dropEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        print(f"[DEBUG] dropEvent: cursor_absolute_y={pos.y() + self.get_scroll_position()}")
        source_index = self.currentIndex()
        result = self.determine_drop_location(self.indexAt(pos), source_index, pos)
        if result is None:
            print("[DEBUG DROP] Drop invalid — no action taken.")
            return
        self.drop_target_index, self.drop_below = result
        print(f"[DEBUG DROP] drop_target_index={self.drop_target_index.row()}, drop_below={self.drop_below}")
        # Handle actual move here
        self.viewport().update()

    def determine_drop_location(self, hover_index, source_index, pos):
        print(f"[DEBUG] Called from {inspect.stack()[1].function}")
        scroll_offset = self.get_scroll_position()
        cursor_y = pos.y() + scroll_offset

        if not hover_index.isValid():
            if self.model.rowCount() == 0:
                return None
            last_index = self.model.index(self.model.rowCount() - 1, 0)
            last_top, last_bot = self.get_row_bounds(last_index.row())
            return (last_index, True) if cursor_y > last_bot else None

        hover_index = hover_index.siblingAtColumn(0)
        hover_row = hover_index.row()
        hover_item = self.model.itemFromIndex(hover_index)
        hover_media = hover_item.data(Qt.UserRole)
        hover_indent = getattr(hover_media, "indent_level", 0)

        if source_index is not None:
            source_index = source_index.siblingAtColumn(0)
            source_item = self.model.itemFromIndex(source_index)
            source_media = source_item.data(Qt.UserRole)
            source_indent = getattr(source_media, "indent_level", 0)
        else:
            source_indent = hover_indent

        row_top, row_bottom = self.get_row_bounds(hover_row)
        y_mid = (row_top + row_bottom) // 2
        drop_below = cursor_y > y_mid

        print(f"[DEBUG] Hover Index Row: {hover_row}")
        print(f"[DEBUG] Hover Row Bounds: top={row_top}, bottom={row_bottom}")
        print(f"[DEBUG] hover_row={hover_row}, drop_below={drop_below}, source_indent={source_indent}, hover_indent={hover_indent}")

        if source_index and self.find_ancestor_folder(source_index) != self.find_ancestor_folder(hover_index):
            top, bot = self.get_group_bounds(hover_index)
            top_index = self.model.index(top, 0)
            bot_index = self.model.index(bot, 0)
            y_top, y_bot = self.get_row_bounds(top)
            y_mid = (y_top + y_bot) // 2
            return (top_index, False) if cursor_y < y_mid else (bot_index, True)

        if hover_media and hover_media.is_folder:
            top, bot = self.get_group_bounds(hover_index)
            top_index = self.model.index(top, 0)
            bot_index = self.model.index(bot, 0)
            y_top, y_bot = self.get_row_bounds(bot)
            y_mid = (y_top + y_bot) // 2
            return (top_index, False) if cursor_y < y_mid else (bot_index, True)

        print(f"[DEBUG] Returning drop_target_index={hover_row}, drop_below={drop_below}")
        return hover_index, drop_below

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.drop_target_index or not self.drop_target_index.isValid():
            return

        row = self.drop_target_index.row()
        row_top, row_bottom = self.get_row_bounds(row)
        y_absolute = row_bottom if self.drop_below else row_top
        y_viewport = self.convert_absolute_to_viewport(y_absolute)

        print(f"[DEBUG PAINT] row={row}, drop_below={self.drop_below}")
        print(f"[DEBUG PAINT] row_top={row_top}, row_bottom={row_bottom}, scroll_offset={self.get_scroll_position()}")
        print(f"[DEBUG PAINT] y_absolute={y_absolute}, y_viewport={y_viewport}")

        painter = QPainter(self.viewport())
        painter.setPen(QPen(Qt.red, 2))
        painter.drawLine(0, y_viewport, self.viewport().width(), y_viewport)
        painter.end()

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
        self._row_height = self.rowHeight(self.model.index(0, 0))
        print(f"[DEBUG] (renumber_visible_rows) Row height: {self._row_height}px")
        row_number = 1

        def walk(item: QStandardItem):
            nonlocal row_number
            if not item:
                return

            index = self.model.indexFromItem(item)
            if self.isExpanded(index) or not item.hasChildren():
                item.setText(str(row_number))
                row_number += 1

            # Walk children
            for i in range(item.rowCount()):
                child = item.child(i, 0)
                walk(child)

        # Start walking top-level items
        for i in range(self.model.rowCount()):
            parent_item = self.model.item(i, 0)
            walk(parent_item)
class DragDropSortableTable_old3(QTreeView):
    row_remove_requested = Signal(int)
    files_dropped = Signal(tuple)

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        self.logger = logger or logging.getLogger(__name__)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

        self.model = DragDropItemModel()
        self.model.setHorizontalHeaderLabels(["#", "Filename", "Type", "Status"])
        self.setModel(self.model)

        self.setRootIsDecorated(True)
        self.setItemsExpandable(True)
        self.setTreePosition(1)
        self.setIndentation(20)

        header = self.header()
        header.setSectionResizeMode(QHeaderView.Stretch)

        self._drop_pos = None
        self.drop_target_index = QModelIndex()
        self.drop_below = True
        self._drag_source_index = None

        self._row_height = 19  # default; will auto-refresh

        self.up_arrow = QLabel("⬆", self.viewport())
        self.down_arrow = QLabel("⬇", self.viewport())
        for arrow in [self.up_arrow, self.down_arrow]:
            arrow.setStyleSheet("color: red; font-size: 20px; background-color: rgba(255,255,255,200);")
            arrow.setVisible(False)

    # --- Position + Bounds Helpers ---

    def get_scroll_position(self) -> int:
        return self.verticalScrollBar().value()

    def get_viewport_height(self) -> int:
        return self.viewport().height()

    def get_row_bounds(self, row: int) -> tuple[int, int]:
        top = row * self._row_height
        return top, top + self._row_height

    def is_row_visible(self, row: int) -> bool:
        top, bottom = self.get_row_bounds(row)
        scroll_top = self.get_scroll_position()
        scroll_bottom = scroll_top + self.get_viewport_height()
        return not (bottom < scroll_top or top > scroll_bottom)

    def find_ancestor_folder(self, index: QModelIndex) -> QModelIndex:
        while index.isValid():
            item = self.model.itemFromIndex(index)
            media = item.data(Qt.UserRole)
            if media and media.is_folder:
                return index
            index = index.parent()
        return QModelIndex()

    def get_group_bounds(self, hover_index: QModelIndex) -> tuple[tuple[int, int], tuple[int, int]]:
        row = hover_index.row()
        model = self.model
        parent = hover_index.parent()
        top = bottom = row

        for r in range(row - 1, -1, -1):
            sibling = model.index(r, 0, parent)
            if self.find_ancestor_folder(sibling) != self.find_ancestor_folder(hover_index):
                break
            top = r

        for r in range(row + 1, model.rowCount(parent)):
            sibling = model.index(r, 0, parent)
            if self.find_ancestor_folder(sibling) != self.find_ancestor_folder(hover_index):
                break
            bottom = r

        return (top, top), (bottom, bottom)

    def convert_absolute_to_viewport(self, y_absolute: int) -> int:
        """Converts an absolute Y coordinate (from top of model) to viewport-relative."""
        return y_absolute - self.get_scroll_position()

    # --- Drop Logic ---

    def determine_drop_location_old(self, hover_index: QModelIndex, source_index: QModelIndex | None, pos: QPoint) -> tuple[QModelIndex, bool] | None:
        print(f"[DEBUG] Called from {inspect.stack()[1].function}")

        scroll_offset = self.get_scroll_position()
        cursor_y = pos.y() + scroll_offset

        def top(index): return self.get_row_bounds(index.row())[0]
        def bottom(index): return self.get_row_bounds(index.row())[1]

        if not hover_index.isValid():
            if self.model.rowCount() == 0:
                return None
            last_index = self.model.index(self.model.rowCount() - 1, 0)
            if cursor_y > bottom(last_index):
                return last_index, True
            return None

        hover_index = hover_index.siblingAtColumn(0)
        hover_item = self.model.itemFromIndex(hover_index)
        hover_media = hover_item.data(Qt.UserRole)
        hover_indent = getattr(hover_media, "indent_level", 0)

        if source_index is None:
            source_indent = hover_indent
        else:
            source_index = source_index.siblingAtColumn(0)
            source_item = self.model.itemFromIndex(source_index)
            source_media = source_item.data(Qt.UserRole)
            source_indent = getattr(source_media, "indent_level", 0)

        y_mid = (top(hover_index) + bottom(hover_index)) // 2
        drop_below = cursor_y > y_mid

        print(f"[DEBUG] hover_row={hover_index.row()}, drop_below={drop_below}, source_indent={source_indent}, hover_indent={hover_indent}")

        #if source_index and self.find_ancestor_folder(source_index) != self.find_ancestor_folder(hover_index):
        if source_index and (
                self.find_ancestor_folder(source_index) != self.find_ancestor_folder(hover_index)
                and self.get_indent(source_index) == self.get_indent(hover_index)
        ):
            # Only treat as cross-group if ancestor is different AND we're at the same depth
            print("[DEBUG] Dropping outside original group — snapping to boundary")
            group_top_row, group_bottom_row = self.get_group_bounds(hover_index)
            top_index = self.model.index(group_top_row[0], 0)
            bottom_index = self.model.index(group_bottom_row[0], 0)
            y_mid = (top(top_index) + bottom(bottom_index)) // 2
            result = (top_index, False) if cursor_y < y_mid else (bottom_index, True)
            print(f"[DEBUG] Adjusted drop target row={result[0].row()}, drop_below={result[1]}")
            return result

        if hover_media and hover_media.is_folder:
            top_row, bot_row = self.get_group_bounds(hover_index)
            top_index = self.model.index(top_row[0], 0)
            bot_index = self.model.index(bot_row[0], 0)
            y_mid = (top(top_index) + bottom(bot_index)) // 2
            return (top_index, False) if cursor_y < y_mid else (bot_index, True)

        return hover_index, drop_below

    def determine_drop_location_old2(self, hover_index: QModelIndex, source_index: QModelIndex | None, pos: QPoint) -> tuple[QModelIndex, bool] | None:
        print(f"[DEBUG] Called from {inspect.stack()[1].function}")

        scroll_offset = self.get_scroll_position()
        cursor_y = pos.y() + scroll_offset

        def top(index):
            return self.get_row_bounds(index.row())[0]

        def bottom(index):
            return self.get_row_bounds(index.row())[1]

        if not hover_index.isValid():
            if self.model.rowCount() == 0:
                return None
            last_index = self.model.index(self.model.rowCount() - 1, 0)
            if cursor_y > bottom(last_index):
                return last_index, True
            return None

        hover_index = hover_index.siblingAtColumn(0)
        hover_item = self.model.itemFromIndex(hover_index)
        hover_media = hover_item.data(Qt.UserRole)
        hover_indent = getattr(hover_media, "indent_level", 0)

        if source_index is None:
            source_indent = hover_indent
        else:
            source_index = source_index.siblingAtColumn(0)
            source_item = self.model.itemFromIndex(source_index)
            source_media = source_item.data(Qt.UserRole)
            source_indent = getattr(source_media, "indent_level", 0)

        y_mid = (top(hover_index) + bottom(hover_index)) // 2
        drop_below = cursor_y > y_mid

        print(
            f"[DEBUG] hover_row={hover_index.row()}, drop_below={drop_below}, source_indent={source_indent}, hover_indent={hover_indent}")

        # Handle cross-folder drops
        source_folder = self.find_ancestor_folder(source_index) if source_index else None
        hover_folder = self.find_ancestor_folder(hover_index)

        if source_folder != hover_folder:
            print("[DEBUG] Dropping outside original group — snapping to boundary")
            top_row, bot_row = self.get_group_bounds(hover_index)
            top_index = self.model.index(top_row[0], 0)
            bot_index = self.model.index(bot_row[0], 0)
            y_mid = (top(top_index) + bottom(bot_index)) // 2
            return (top_index, False) if cursor_y < y_mid else (bot_index, True)

        # Snapping above/below folder block when hovering on a folder
        if hover_media and hover_media.is_folder:
            print("[DEBUG] Hovering over folder — aligning drop to outer edge of group")
            top_row, bot_row = self.get_group_bounds(hover_index)
            top_index = self.model.index(top_row[0], 0)
            bot_index = self.model.index(bot_row[0], 0)
            y_mid = (top(top_index) + bottom(bot_index)) // 2
            return (top_index, False) if cursor_y < y_mid else (bot_index, True)

        # Normal case — same group, not on folder
        return hover_index, drop_below

    def determine_drop_location(self, hover_index: QModelIndex, source_index: QModelIndex | None, cursor_y_absolute: int) -> tuple[QModelIndex, bool] | None:
        print(f"[DEBUG] Called from {inspect.stack()[1].function}")

        model = self.model

        def top(index):
            return self.get_row_bounds(index.row())[0]

        def bottom(index):
            return self.get_row_bounds(index.row())[1]

        # Drop-to-end behavior
        if not hover_index.isValid():
            if model.rowCount() == 0:
                print(f"[DEBUG] Returning Other 01")
                return None
            last_index = model.index(model.rowCount() - 1, 0)
            if cursor_y_absolute > bottom(last_index):
                print(f"[DEBUG] Returning Other 02")
                return last_index, True
            print(f"[DEBUG] Returning Other 03")
            return None

        hover_index = hover_index.siblingAtColumn(0)
        print(f"[DEBUG] Hover Index Row: {hover_index.row()}")
        print(f"[DEBUG] Hover Row Bounds: top={top(hover_index)}, bottom={bottom(hover_index)}")
        hover_item = model.itemFromIndex(hover_index)
        hover_media = hover_item.data(Qt.UserRole)
        hover_indent = getattr(hover_media, "indent_level", 0)

        if source_index is None:
            source_indent = hover_indent
        else:
            source_index = source_index.siblingAtColumn(0)
            source_item = model.itemFromIndex(source_index)
            source_media = source_item.data(Qt.UserRole)
            source_indent = getattr(source_media, "indent_level", 0)

        y_mid = (top(hover_index) + bottom(hover_index)) // 2
        drop_below = cursor_y_absolute > y_mid

        print(f"[DEBUG] hover_row={hover_index.row()}, drop_below={drop_below}, source_indent={source_indent}, hover_indent={hover_indent}")

        # Cross-group snapping (between folders)
        if source_index and (
                self.find_ancestor_folder(source_index) != self.find_ancestor_folder(hover_index)
                and source_indent == hover_indent
        ):
            print("[DEBUG] Dropping outside original group — snapping to boundary")
            group_top_row, group_bottom_row = self.get_group_bounds(hover_index)
            top_index = model.index(group_top_row[0], 0)
            bottom_index = model.index(group_bottom_row[0], 0)
            group_mid = (top(top_index) + bottom(bottom_index)) // 2
            print(f"[DEBUG] Returning Other 04")
            return (top_index, False) if cursor_y_absolute < group_mid else (bottom_index, True)

        # Prevent dropping inside a folder
        if hover_media and hover_media.is_folder:
            group_top_row, group_bottom_row = self.get_group_bounds(hover_index)
            top_index = model.index(group_top_row[0], 0)
            bottom_index = model.index(group_bottom_row[0], 0)
            group_mid = (top(top_index) + bottom(bottom_index)) // 2
            print(f"[DEBUG] Returning Other 05")
            return (top_index, False) if cursor_y_absolute < group_mid else (bottom_index, True)

        print(f"[DEBUG] Returning drop_target_index={hover_index.row()}, drop_below={drop_below}")
        return hover_index, drop_below

    # --- Paint Drag Line + Arrows ---

    def paintEvent_old(self, event):
        super().paintEvent(event)

        if not self.drop_target_index or not self.drop_target_index.isValid():
            return

        row = self.drop_target_index.row()
        row_top, row_bottom = self.get_row_bounds(row)
        y = row_bottom if self.drop_below else row_top
        y -= self.get_scroll_position()

        painter = QPainter(self.viewport())
        painter.setPen(QPen(Qt.red, 2))
        y_viewport = self.convert_absolute_to_viewport(y)

        painter.drawLine(0, y_viewport, self.viewport().width(), y_viewport)

        #painter.drawLine(0, y, self.viewport().width(), y)
        painter.end()

        viewport_top = self.get_scroll_position()
        viewport_bottom = viewport_top + self.get_viewport_height()
        if y + self.get_scroll_position() < viewport_top:
            self.up_arrow.move(self.viewport().width() // 2 - 10, 5)
            self.up_arrow.setVisible(True)
            self.down_arrow.setVisible(False)
        elif y + self.get_scroll_position() > viewport_bottom:
            self.down_arrow.move(self.viewport().width() // 2 - 10, self.viewport().height() - 25)
            self.down_arrow.setVisible(True)
            self.up_arrow.setVisible(False)
        else:
            self.up_arrow.setVisible(False)
            self.down_arrow.setVisible(False)

    def paintEvent(self, event):
        super().paintEvent(event)

        if not self.drop_target_index or not self.drop_target_index.isValid():
            return

        row = self.drop_target_index.row()
        row_top, row_bottom = self.get_row_bounds(row)
        y_absolute = row_bottom if self.drop_below else row_top

        # 🔧 Convert to viewport-relative once (no double offset!)
        y_viewport = y_absolute - self.get_scroll_position()

        print(f"[DEBUG PAINT] row={row}, drop_below={self.drop_below}")
        print(f"[DEBUG PAINT] row_top={row_top}, row_bottom={row_bottom}, scroll_offset={self.get_scroll_position()}")
        print(f"[DEBUG PAINT] y_absolute={y_absolute}, y_viewport={y_viewport}")

        painter = QPainter(self.viewport())
        painter.setPen(QPen(Qt.red, 2))
        painter.drawLine(0, y_viewport, self.viewport().width(), y_viewport)
        painter.end()

        # --- Arrows
        viewport_top = self.get_scroll_position()
        viewport_bottom = viewport_top + self.get_viewport_height()
        if y_absolute < viewport_top:
            self.up_arrow.move(self.viewport().width() // 2 - 10, 5)
            self.up_arrow.setVisible(True)
            self.down_arrow.setVisible(False)
        elif y_absolute > viewport_bottom:
            self.down_arrow.move(self.viewport().width() // 2 - 10, self.viewport().height() - 25)
            self.down_arrow.setVisible(True)
            self.up_arrow.setVisible(False)
        else:
            self.up_arrow.setVisible(False)
            self.down_arrow.setVisible(False)

    def indexAt_absolute_y(self, absolute_y: int) -> QModelIndex:
        scroll_offset = self.get_scroll_position()
        viewport_y = absolute_y - scroll_offset
        return self.indexAt(QPoint(0, viewport_y))

    def dragMoveEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        self._drop_pos = pos
        self._drag_source_index = self.currentIndex()

        hover_index = self.indexAt(pos)
        #pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        cursor_y_absolute = pos.y() + self.get_scroll_position()
        print(f"[DEBUG] dragMoveEvent: cursor_absolute_y={cursor_y_absolute}")
        result = self.determine_drop_location(hover_index, self._drag_source_index, cursor_y_absolute)
        #result = self.determine_drop_location(hover_index, self._drag_source_index, pos)

        if result:
            self.drop_target_index, self.drop_below = result
        else:
            self.drop_target_index = QModelIndex()

        self.viewport().update()
        event.accept()

    def dragEnterEvent(self, event):
        self._drag_source_index = self.currentIndex()
        event.acceptProposedAction()

    def dropEvent(self, event):
        self.up_arrow.setVisible(False)
        self.down_arrow.setVisible(False)

        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        hover_index = self.indexAt(pos)
        #pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        cursor_y_absolute = pos.y() + self.get_scroll_position()
        print(f"[DEBUG] dropEvent: cursor_absolute_y={cursor_y_absolute}")
        result = self.determine_drop_location(hover_index, self._drag_source_index, cursor_y_absolute)
        #result = self.determine_drop_location(hover_index, self._drag_source_index, pos)

        if not result:
            print("[DEBUG] dropEvent: No valid drop target — ignoring")
            self.drop_target_index = QModelIndex()
            self.viewport().update()
            return

        self.drop_target_index, self.drop_below = result
        print(f"[DEBUG DROP] drop_target_index={self.drop_target_index.row()}, drop_below={self.drop_below}")
        # ➕ You’ll insert drop handling logic here (already exists in your codebase)

        self.viewport().update()

    def load_items(self, media_items: list[MediaItem]):
        self.model.removeRows(0, self.model.rowCount())
        folder_items = {}

        sorted_items = sorted(media_items, key=lambda i: (i.depth, i.is_folder))

        for item in sorted_items:
            row_items = [
                QStandardItem(""),  # Column 0: Row number
                QStandardItem(f"📁 {item.basename}" if item.is_folder else item.basename),
                QStandardItem("Folder" if item.is_folder else detect_media_type(item.path, logger=self.logger)),
                QStandardItem(item.status)
            ]
            for q in row_items:
                q.setEditable(False)
                q.setData(item, Qt.UserRole)
                #q.setData(item.indent_level, Qt.UserRole + 1)  # 🔥 Store indent level explicitly
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
        self._row_height = self.rowHeight(self.model.index(0, 0))
        print(f"[DEBUG] (renumber_visible_rows) Row height: {self._row_height}px")
        row_number = 1

        def walk(item: QStandardItem):
            nonlocal row_number
            if not item:
                return

            index = self.model.indexFromItem(item)
            if self.isExpanded(index) or not item.hasChildren():
                item.setText(str(row_number))
                row_number += 1

            for i in range(item.rowCount()):
                child = item.child(i, 0)
                walk(child)

        for i in range(self.model.rowCount()):
            parent_item = self.model.item(i, 0)
            walk(parent_item)
class DragDropSortableTable_OLD2(QTreeView):
    row_remove_requested = Signal(int)
    files_dropped = Signal(tuple)  # (file_paths, target_row)

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        self.logger = logger or logging.getLogger(__name__)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(False)
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

        self.up_arrow = QLabel("⬆", self.viewport())
        self.up_arrow.setStyleSheet("color: red; font-size: 20px; background-color: rgba(255, 255, 255, 200);")
        self.up_arrow.setVisible(False)

        self.down_arrow = QLabel("⬇", self.viewport())
        self.down_arrow.setStyleSheet("color: red; font-size: 20px; background-color: rgba(255, 255, 255, 200);")
        self.down_arrow.setVisible(False)

        self.auto_scroll_timer = QTimer(self)
        self.auto_scroll_timer.timeout.connect(self._check_drag_scroll)
        self.scroll_edge_margin = 40
        self.scroll_max_speed = 20
        self.scroll_sticky_zone = 10
        self.drop_target_index = QModelIndex()
        self.drop_below = True
        self._drag_source_index = None
        self.drag_position_y = -1
        self._drop_pos = None

        self._row_height = self.rowHeight(self.model.index(0, 0))
        print(f"[DEBUG] (init) Row height: {self._row_height}px")

    def load_items(self, media_items: list[MediaItem]):
        self.model.removeRows(0, self.model.rowCount())
        folder_items = {}

        sorted_items = sorted(media_items, key=lambda i: (i.depth, i.is_folder))

        for item in sorted_items:
            row_items = [
                QStandardItem(""),
                QStandardItem(f"📁 {item.basename}" if item.is_folder else item.basename),
                QStandardItem("Folder" if item.is_folder else item.extension.strip(".")),
                QStandardItem(item.status)
            ]
            for q in row_items:
                q.setEditable(False)
                q.setData(item, Qt.UserRole)
                q.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)

            indent_level = item.depth
            item.indent_level = indent_level

            if item.parent_folder in folder_items:
                folder_items[item.parent_folder][0].appendRow(row_items)
            else:
                self.model.appendRow(row_items)

            if item.is_folder:
                folder_items[item.path] = row_items

        self.expandAll()
        self.renumber_visible_rows()

    def renumber_visible_rows(self):
        self._row_height = self.rowHeight(self.model.index(0, 0))
        print(f"[DEBUG] (renumber_visible_rows) Row height: {self._row_height}px")
        row_number = 1

        def walk(item: QStandardItem):
            nonlocal row_number
            if not item:
                return
            index = self.model.indexFromItem(item)
            if self.isExpanded(index) or not item.hasChildren():
                item.setText(str(row_number))
                row_number += 1
            for i in range(item.rowCount()):
                child = item.child(i, 0)
                walk(child)

        for i in range(self.model.rowCount()):
            parent_item = self.model.item(i, 0)
            walk(parent_item)

    def dragEnterEvent(self, event):
        self.auto_scroll_timer.start(30)
        event.acceptProposedAction()

    def dragMoveEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        self._drop_pos = pos
        self.drag_position_y = pos.y() + self.get_scroll_position()

        source_index = self.currentIndex()
        hover_index = self.indexAt(pos)
        result = self.determine_drop_location(hover_index, source_index, pos)

        print(f"[DEBUG] (dragMoveEvent) Hovered index: {self.describe_index(hover_index)}")

        if result is None:
            self.drop_target_index = QModelIndex()
            self.viewport().update()
            return

        self.drop_target_index, self.drop_below = result
        print(f"[DEBUG DROP TARGET SET (dragMoveEvent)] drop_target_index={self.drop_target_index.row()}, drop_below={self.drop_below}")
        self.viewport().update()
        event.accept()

    def dropEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        source_index = self.currentIndex()
        print(f"[DEBUG DROP EVENT START] pos={pos}, source_index={source_index.row() if source_index.isValid() else 'INVALID'}")
        self._drag_source_index = None

        hover_index = self.indexAt(pos)
        result = self.determine_drop_location(hover_index, source_index, pos)
        if result is None:
            print("[DEBUG] dropEvent: No valid target — rejecting drop")
            self._drop_pos = None
            self.viewport().update()
            event.ignore()
            return

        self.drop_target_index, self.drop_below = result
        print(f"[DEBUG DROP TARGET SET (dropEvent)] drop_target_index={self.drop_target_index.row()}, drop_below={self.drop_below}")

        # TODO: Implementation of the move logic will go here.
        # Moving folders as a block or moving individual files correctly.

        self._drop_pos = None
        self.auto_scroll_timer.stop()
        self.drag_position_y = -1
        self.viewport().update()
        event.acceptProposedAction()
        self.up_arrow.setVisible(False)
        self.down_arrow.setVisible(False)
        print(f"[DEBUG DROP EVENT ACCEPTED] drop_target_index={self.drop_target_index.row()}, drop_below={self.drop_below}")

    def paintEvent(self, event):
        super().paintEvent(event)

        if not hasattr(self, 'drop_target_index') or not self.drop_target_index.isValid():
            return

        # Recalculate based on current mouse pos and drag source
        if hasattr(self, '_drop_pos') and self._drop_pos is not None and self._drag_source_index:
            result = self.determine_drop_location(
                self.indexAt(self._drop_pos), self._drag_source_index, self._drop_pos
            )
            if result is None:
                print("[DEBUG PAINT EVENT] No legal drop — skipping paint")
                return
            index, drop_below = result
        else:
            print("[DEBUG PAINT EVENT] Missing drag context")
            return

        rect = self.visualRect(index)
        scroll_offset = self.get_scroll_position()
        row_top_abs = rect.top() + scroll_offset
        row_bottom_abs = rect.bottom() + scroll_offset
        y_absolute = row_bottom_abs if drop_below else row_top_abs

        print(f"[DEBUG PAINT EVENT] drop_target_index={index.row()}, drop_below={drop_below}")

        painter = QPainter(self.viewport())
        pen = QPen(Qt.red, 2, Qt.SolidLine)
        painter.setPen(pen)
        painter.drawLine(0, y_absolute - scroll_offset, self.viewport().width(), y_absolute - scroll_offset)
        painter.end()

        viewport_top = scroll_offset
        viewport_bottom = viewport_top + self.get_viewport_height()

        if y_absolute < viewport_top:
            print("[DEBUG] paintEvent: Showing UP arrow (drop ABOVE visible area)")
            self.up_arrow.move(self.viewport().width() // 2 - 10, 5)
            self.up_arrow.setVisible(True)
            self.down_arrow.setVisible(False)
        elif y_absolute > viewport_bottom:
            print("[DEBUG] paintEvent: Showing DOWN arrow (drop BELOW visible area)")
            self.down_arrow.move(self.viewport().width() // 2 - 10, self.viewport().height() - 25)
            self.down_arrow.setVisible(True)
            self.up_arrow.setVisible(False)
        else:
            print("[DEBUG] paintEvent: No arrows needed — drop inside viewport")
            self.up_arrow.setVisible(False)
            self.down_arrow.setVisible(False)

    # Additional methods:
    # determine_drop_location
    # get_scroll_position
    # get_viewport_height
    # describe_index
    # _check_drag_scroll
    # _show_context_menu
    # etc.

    def determine_drop_location(self, hover_index: QModelIndex, source_index: QModelIndex | None, pos: QPoint) -> tuple[QModelIndex, bool] | None:
        caller = inspect.stack()[1].function
        print(f"[DEBUG] Called from {caller}")

        model = self.model
        scroll_offset = self.get_scroll_position()
        cursor_y = pos.y() + scroll_offset

        # Normalize hover_index to column 0
        hover_index = hover_index.siblingAtColumn(0)

        if not hover_index.isValid():
            print(f"[DEBUG] No valid hover index — outside items")
            if source_index is None:
                return None  # No drop line during paint
            # Handle dropping past last item
            last_row = model.rowCount() - 1
            if last_row < 0:
                return None
            last_index = model.index(last_row, 0)
            return last_index, True

        item = model.itemFromIndex(hover_index)
        media_item = item.data(Qt.UserRole) if item else None
        is_folder = media_item.is_folder if media_item else False

        hover_top = hover_index.row() * self._row_height
        hover_bottom = hover_top + self._row_height
        hover_mid_y = (hover_top + hover_bottom) // 2

        drop_below = cursor_y > hover_mid_y

        print(f"[DEBUG] Hover row={hover_index.row()}, top={hover_top}, bottom={hover_bottom}, mid={hover_mid_y}, cursor_y={cursor_y}")
        print(f"[DEBUG] Hover item: {'folder' if is_folder else 'file'}, drop_below={drop_below}")

        if source_index is None:
            return hover_index, drop_below

        source_index = source_index.siblingAtColumn(0)
        source_item = model.itemFromIndex(source_index)
        source_media = source_item.data(Qt.UserRole) if source_item else None
        if not source_media:
            return None

        source_indent = source_media.indent_level
        hover_indent = media_item.indent_level if media_item else 0

        print(f"[DEBUG] Source indent={source_indent}, Hover indent={hover_indent}")

        if source_media.is_folder:
            # Folders can only move at top-level (no indent)
            if hover_indent != 0:
                print("[DEBUG] Folder drag — snapping to top-level")
                hover_index = self.find_top_level_parent(hover_index)
            return hover_index, drop_below
        else:
            # Files can only move within their indent group
            if source_indent != hover_indent:
                print("[DEBUG] File drag — snapping to top-level folder boundary")
                hover_index = self.find_top_level_parent(hover_index)
                return hover_index, drop_below
            return hover_index, drop_below

    def find_top_level_parent(self, index: QModelIndex) -> QModelIndex:
        while index.parent().isValid():
            index = index.parent()
        return index.siblingAtColumn(0)

    def get_scroll_position(self) -> int:
        return self.verticalScrollBar().value()

    def get_viewport_height(self) -> int:
        return self.viewport().height()

    def describe_index(self, index: QModelIndex) -> str:
        if not index.isValid():
            return "ROOT"
        item = self.model.itemFromIndex(index)
        if not item:
            return "Unknown"
        text = item.text()
        return f"Row {index.row()}: {text or 'Unnamed'}"

    def _check_drag_scroll(self):
        if self.drag_position_y < 0:
            return

        margin = self.scroll_edge_margin
        sticky_zone = self.scroll_sticky_zone
        max_speed = self.scroll_max_speed
        y = self.drag_position_y
        bar = self.verticalScrollBar()
        view_rect = self.viewport().rect()
        direction = 0

        if y < view_rect.top() + margin:
            distance = (margin - (y - view_rect.top()))
            if distance > sticky_zone:
                direction = -min(max_speed, max(1, (distance - sticky_zone) // 4))
        elif y > view_rect.bottom() - margin:
            distance = (y - (view_rect.bottom() - margin))
            if distance > sticky_zone:
                direction = min(max_speed, max(1, (distance - sticky_zone) // 4))

        if direction != 0:
            bar.setValue(bar.value() + direction)
            self.viewport().update()

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
