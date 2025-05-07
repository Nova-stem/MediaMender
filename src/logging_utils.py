# src/logging_utils.py
import logging
import shutil
from datetime import datetime
from pathlib import Path

TIMESTAMP = datetime.now().strftime("%Y%m%d.%H%M")
CURRENT_LOG_FILE = None

def configure_logger(log_dir: Path, reuse_existing: bool = False) -> Path:
    global CURRENT_LOG_FILE

    log_dir.mkdir(parents=True, exist_ok=True)

    if not reuse_existing or CURRENT_LOG_FILE is None:
        CURRENT_LOG_FILE = log_dir / f"media_mender_{TIMESTAMP}.log"
    else:
        # Reuse existing log file name in a new location
        new_path = log_dir / CURRENT_LOG_FILE.name

        # Avoid SameFileError by checking path equality
        if CURRENT_LOG_FILE.resolve() != new_path.resolve():
            if CURRENT_LOG_FILE.exists():
                shutil.copy2(CURRENT_LOG_FILE, new_path)
        CURRENT_LOG_FILE = new_path

        # Remove old handlers before reconfiguring
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
            handler.close()

    # (Re)initialize logging
    logging.basicConfig(
        filename=CURRENT_LOG_FILE,
        filemode="a" if reuse_existing else "w",
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    return CURRENT_LOG_FILE
