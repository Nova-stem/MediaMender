# MediaMender

**MediaMender** is a desktop tool for processing, organizing, and tagging Movies, TV Shows, and Audiobooks. It remuxes media, cleans and converts subtitles, adds metadata, and supports Whisper-based transcription — all from a drag-and-drop GUI.

---

## ✨ Features

- 🎬 Auto-detects and separates Movies, TV Shows, and Audiobooks
- 📚 Metadata lookup via TMDb (video) and OpenLibrary (audio)
- 🧠 Subtitle generation with Whisper — supports GPU acceleration
- 💬 Subtitle correction, conversion, and tagging
- 📦 MKV remuxing with embedded tracks and forced flags
- 🔄 Dry-run mode for safe preview of actions
- 🧹 Automatically trashes processed and intermediate files

---

## 🖥 Requirements

- Python 3.10+
- FFmpeg (must be available on system PATH or installed by app)
- MKVToolNix (`mkvmerge`)
- Whisper model files (downloaded on first use)
- NVIDIA GPU (optional, for acceleration)

---

## 📦 Installation

Clone the repo and install dependencies:

```bash
git clone https://github.com/Nova-stem/MediaMender.git
cd MediaMender
pip install -r requirements.txt
```

---

## 🚀 Usage

```bash
python main.py
```

The GUI allows drag-and-drop media files, setting preferences, and running background processing with progress tracking.

---

## 🔧 Configuration

Preferences are stored in a `config/` folder (excluded for security).

First-time use will:
- Prompt for missing Whisper models and download them
- Check for FFmpeg and MKVToolNix
- Configure GPU acceleration if available

---

## 🛠 Developer Notes

- Thread-safe GUI built with PySide6
- Uses `faster-whisper` for GPU support
- Subtitle pipeline includes: detection → cleaning → tagging → muxing
- Structured for future `.exe` packaging

---

## 📄 License

This project is licensed under the MIT License.

```
MIT License

Copyright (c) 2025 Nova-Stem (Novastem was taken)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the “Software”), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Disclaimer: I am not responsible for exploding robots or missing limbs. If the
robot gains sentience, it would be in your best interest to run.
