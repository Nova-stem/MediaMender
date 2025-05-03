# /src/dialog.py
#from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
#from PySide6.QtCore import Qt

#class ThemedMessage(QDialog):
#    def __init__(self, title: str, message: str, parent=None):
#        super().__init__(parent)
#        self.setWindowTitle(title)
#        self.setMinimumWidth(300)
#        self.setWindowModality(Qt.ApplicationModal)

#        layout = QVBoxLayout()
#        layout.addWidget(QLabel(message))

#        ok_button = QPushButton("OK")
#        ok_button.clicked.connect(self.accept)
#        layout.addWidget(ok_button)

#        self.setLayout(layout)


from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt

class ThemedMessage(QDialog):
    def __init__(self, title: str, message: str, parent=None, buttons=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(300)
        self.setWindowModality(Qt.ApplicationModal)

        layout = QVBoxLayout()
        layout.addWidget(QLabel(message))

        # Default button if none provided
        if buttons is None:
            buttons = ["OK"]

        for text in buttons:
            btn = QPushButton(text)
            btn.clicked.connect(lambda _, t=text: self._handle_click(t))
            layout.addWidget(btn)

        self.setLayout(layout)

    def _handle_click(self, text):
        self.result = text
        self.accept()

    @staticmethod
    def question(parent, title, message, buttons=["Yes", "Cancel"]) -> str:
        dialog = ThemedMessage(title, message, parent, buttons)  # ✅ fixed order
        dialog.exec()
        return dialog.result if hasattr(dialog, "result") else buttons[1]

    @staticmethod
    def critical(parent, title, message):
        dialog = ThemedMessage(title, message, parent, ["OK"])  # ✅ fixed order
        dialog.exec()
