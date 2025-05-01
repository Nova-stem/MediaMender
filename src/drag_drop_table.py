from PySide6.QtWidgets import QTableWidget, QAbstractItemView, QTableWidgetItem
from PySide6.QtCore import Qt, QMimeData, QDataStream, QByteArray, QModelIndex

class DragDropTableWidget(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropOverwriteMode(False)
        self.setDropIndicatorShown(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)

    def dropEvent(self, event):
        source_row = self.currentRow()
        drop_pos = self.indexAt(event.position().toPoint())

        if not drop_pos.isValid():
            dest_row = self.rowCount()
        else:
            drop_y = event.position().toPoint().y()
            mid_y = self.visualItemRect(self.item(drop_pos.row(), 0)).center().y()
            dest_row = drop_pos.row() + 1 if drop_y > mid_y else drop_pos.row()

        if dest_row == source_row or dest_row == source_row + 1:
            return  # No move needed

        self.insertRow(dest_row)
        for col in range(self.columnCount()):
            new_item = self.item(source_row, col).clone()
            self.setItem(dest_row, col, new_item)
        self.removeRow(source_row if dest_row > source_row else source_row + 1)

        self.renumber_index_column()

    def renumber_index_column(self):
        for i in range(self.rowCount()):
            index_item = QTableWidgetItem(str(i + 1))
            self.setItem(i, 0, index_item)
