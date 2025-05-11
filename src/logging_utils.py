# src/logging_utils.py

import logging
import shutil
from datetime import datetime
from pathlib import Path
from src.system.safety import require_safe_path

TIMESTAMP = datetime.now().strftime("%Y%m%d.%H%M")
CURRENT_LOG_FILE = None

def configure_logger(log_dir: Path, reuse_existing: bool = False, level=logging.INFO) -> Path:
    """
    Configures the global logger.
    - log_dir: target log directory (must be safe)
    - reuse_existing: whether to reuse CURRENT_LOG_FILE if it exists
    - level: logging level (default is logging.INFO)
    Returns: Path to CURRENT_LOG_FILE
    """
    global CURRENT_LOG_FILE

    require_safe_path(log_dir, "Logging Directory")
    log_dir.mkdir(parents=True, exist_ok=True)

    if not reuse_existing or CURRENT_LOG_FILE is None:
        CURRENT_LOG_FILE = log_dir / f"media_mender_{TIMESTAMP}.log"
    else:
        new_path = log_dir / CURRENT_LOG_FILE.name
        if CURRENT_LOG_FILE.resolve() != new_path.resolve():
            if CURRENT_LOG_FILE.exists():
                shutil.copy2(CURRENT_LOG_FILE, new_path)
        CURRENT_LOG_FILE = new_path

        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
            handler.close()

    logging.basicConfig(
        filename=CURRENT_LOG_FILE,
        filemode="a" if reuse_existing else "w",
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    return CURRENT_LOG_FILE