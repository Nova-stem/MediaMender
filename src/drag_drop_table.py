from PySide6.QtWidgets import QTableView, QAbstractItemView, QHeaderView, QStyledItemDelegate, QStyleOptionViewItem, QStyle
from PySide6.QtGui import QStandardItemModel, QStandardItem, QDrag, QPainter, QPen, QColor
from PySide6.QtCore import Qt, QModelIndex, QMimeData

class DragDropSortableTable(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setDragDropOverwriteMode(False)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["#", "Filename", "Type", "Status"])
        self.setModel(self.model)
        self.setSortingEnabled(False)

        self.last_sorted_column = None
        self.sort_ascending = True
        self._drag_hover_pos = None

        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.sectionClicked.connect(self.on_header_clicked)

    def add_row(self, row_data):
        row_index = self.model.rowCount()
        items = [QStandardItem(str(row_index + 1))] + [QStandardItem(x) for x in row_data]
        for item in items:
            item.setEditable(False)
        self.model.appendRow(items)

    def _get_drop_target_row(self, pos):
        if pos.y() < 0:
            return 0  # Drop above the table → top
        elif pos.y() > self.viewport().height():
            return self.model.rowCount()  # Drop below the table → bottom

        index = self.indexAt(pos)
        if index.isValid():
            rect = self.visualRect(index)
            mid_y = rect.top() + rect.height() // 2
            return index.row() if pos.y() < mid_y else index.row() + 1

        return self.model.rowCount()  # Default: drop at end

    def dropEvent(self, event):
        if self.model.rowCount() == 0:
            return

        indexes = self.selectedIndexes()
        if not indexes:
            return

        source_row = indexes[0].row()
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        target_row = self._get_drop_target_row(pos)

        if target_row > source_row:
            target_row -= 1
        if target_row == source_row:
            return

        items = [self.model.item(source_row, col).clone() for col in range(self.model.columnCount())]
        self.model.removeRow(source_row)
        self.model.insertRow(target_row, items)
        self.renumber_rows()

        self._drag_hover_pos = None
        self.viewport().update()
        event.acceptProposedAction()

    def renumber_rows(self):
        for row in range(self.model.rowCount()):
            item = self.model.item(row, 0)
            if item:
                item.setText(str(row + 1))

    def on_header_clicked(self, col):
        if col == 0:
            return
        rows = [
            [self.model.item(row, c).text() for c in range(self.model.columnCount())]
            for row in range(self.model.rowCount())
        ]
        if self.last_sorted_column == col:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_ascending = True
        self.last_sorted_column = col
        rows.sort(key=lambda x: x[col].lower(), reverse=not self.sort_ascending)
        self.model.removeRows(0, self.model.rowCount())
        for row_data in rows:
            items = [QStandardItem(text) for text in row_data]
            for item in items:
                item.setEditable(False)
            self.model.appendRow(items)
        self.renumber_rows()

    #def startDrag(self, supportedActions):
    #    indexes = self.selectedIndexes()
    #    if not indexes:
    #        return
    #    mime_data = self.model.mimeData(indexes)
    #    drag = QDrag(self)
    #    drag.setMimeData(mime_data)
    #    drag.exec(Qt.MoveAction)
    def startDrag(self, supportedActions):
        indexes = self.selectedIndexes()
        if not indexes:
            return

        text = indexes[0].data()  # get the display text of the first selected cell

        mime_data = QMimeData()
        mime_data.setText(text)

        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(Qt.MoveAction)

    def dragEnterEvent(self, event):
        event.setDropAction(Qt.MoveAction)
        event.accept()

    def dragMoveEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        self._drag_hover_pos = pos

        # Force-accept if dragging above or below the viewport
        if pos.y() < 0 or pos.y() > self.viewport().height():
            event.setDropAction(Qt.MoveAction)
            event.accept()
        elif event.mimeData():
            event.setDropAction(Qt.MoveAction)
            event.accept()

        self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._drag_hover_pos:
            return

        row = self._get_drop_target_row(self._drag_hover_pos)
        if self.model.rowCount() == 0:
            return

        col = 1  # Use filename column for indicator width
        if row == self.model.rowCount():
            rect = self.visualRect(self.model.index(row - 1, col))
            y = rect.bottom()
        else:
            rect = self.visualRect(self.model.index(row, col))
            y = rect.top()

        painter = QPainter(self.viewport())
        pen = QPen(QColor(self.palette().highlight().color()))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(rect.left(), y, rect.right(), y)

    def is_cursor_within_viewport(self, global_pos):
        local_pos = self.mapFromGlobal(global_pos)
        return self.viewport().rect().contains(local_pos)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.clearSelection()
        else:
            super().keyPressEvent(event)

class NoFocusDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index: QModelIndex):
        option.state &= ~QStyle.State_HasFocus
        super().paint(painter, option, index)