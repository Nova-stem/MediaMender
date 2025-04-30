MediaMender v0.1
================

MediaMender is a Python-based media processing app with a GUI.
It allows you to load media files, reorder them, process them with background threading, and manage preferences.

---

SETUP
-----

1. Make sure you have Python 3.9+ installed.
2. Install dependencies:
   pip install -r requirements.txt

3. Run the app:
   python src/main.py

---

FOLDER STRUCTURE
----------------

MediaMender_v0.1/
├── config/
│   └── config.json         <-- Preferences saved here
├── resources/              <-- Placeholder for icons or assets
├── src/
│   ├── main.py             <-- GUI Entry Point
│   ├── preferences.py      <-- Preferences window
│   └── media_processor.py  <-- Processing logic (simulated for now)
├── requirements.txt
└── README.txt

---

FEATURES
--------

- Load media files from folder
- Drag-and-drop reorder
- Simulated processing with threading
- Progress bar + current filename
- Preferences popup (input/output/trash paths + flags)
- Error handling (per-file)
- Color-coded file statuses (Green = Success, Red = Error)
- Extensible architecture (ready for backend integration)

---

NEXT STEPS
----------

- Plug in your real processing logic into media_processor.py
- Add pause/resume (optional)
- Add logs to file
- Compile to .exe using PyInstaller or Nuitka
