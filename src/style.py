#src/style.py
#23 May 2025

def get_base_stylesheet() -> str:
    return """
    QWidget {
        font-family: 'Segoe UI', sans-serif;
        font-size: 13px;
    }

    QPushButton {
        padding: 6px 12px;
        border-radius: 6px;
        background-color: palette(button);
        color: palette(button-text);
        border: 1px solid palette(mid);
    }

    QPushButton:hover {
        background-color: palette(highlight);
        color: palette(highlighted-text);
    }

    QPushButton:pressed {
        background-color: palette(dark);
    }

    QPushButton:disabled {
        background-color: palette(midlight);
        color: palette(mid);
    }

    QComboBox {
        padding: 4px;
        border-radius: 4px;
    }

    QMenuBar {
        background-color: palette(window);
        color: palette(window-text);
    }

    QMenuBar::item {
        background-color: transparent;
        color: palette(window-text);
        padding: 4px 10px;
    }

    QMenuBar::item:selected {
        background-color: palette(highlight);
        color: palette(highlighted-text);
    }

    QMenu {
        background-color: palette(base);
        color: palette(text);
    }

    QMenu::item:selected {
        background-color: palette(highlight);
        color: palette(highlighted-text);
    }

    QHeaderView {
        border: none;
        background-color: palette(button);
    }

    QHeaderView::section {
        background-color: palette(button);
        color: palette(button-text);
        padding: 4px;
        border: 1px solid palette(mid);  /* unified from conflicting definitions */
        text-align: left;
    }

    QTableCornerButton::section {
        background-color: palette(button);
        border: 1px solid palette(mid);
    }

    QProgressBar {
        border: 1px solid palette(mid);
        border-radius: 4px;
        text-align: center;
    }

    QProgressBar::chunk {
        width: 10px;
        margin: 1px;
    }

    QScrollBar:vertical, QScrollBar:horizontal {
        background: palette(base);
        border: none;
        margin: 0px;
    }

    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
        background: palette(mid);
        border-radius: 4px;
        min-height: 20px;
        min-width: 20px;
    }

    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
        background: palette(highlight);
    }

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        background: none;
        height: 0px;
        width: 0px;
    }

    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
        background: none;
    }
    QLineEdit {
    background-color: palette(base);
    color: palette(text);
    border: 1px solid palette(mid);
    border-radius: 4px;
    padding: 4px;
    }
    QTableWidget::item:focus {
        outline: none;
    }
    """