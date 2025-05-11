# src/system/safety.py

from pathlib import Path
import logging

def get_safe_root_folders() -> list[Path]:
    """
    Returns the hardcoded list of safe user directories if they exist.
    """
    user_home = Path.home()
    folder_names = ["Documents", "Desktop", "Downloads", "Pictures", "Music", "Videos"]
    return [user_home / name for name in folder_names if (user_home / name).exists()]

def is_safe_path(path: Path, logger=None) -> bool:
    """
    Checks if a path is within allowed safe zones.
    """
    logger = logger or logging.getLogger(__name__)

    try:
        path = path.resolve()

        if path == Path(path.anchor):  # Root of drive (e.g., C:\)
            return False

        for base in get_safe_root_folders():
            if path.is_relative_to(base):
                return True

        for parent in path.parents:
            if "mediamender" in parent.name.lower():
                return True

        return False

    except Exception as e:
        logger.warning(f"[safety] Path resolution failed for {path}: {e}")
        return False

def is_safe_to_trash(path: Path, logger=None) -> bool:
    """
    Applies is_safe_path() to trash-related operations.
    """
    return is_safe_path(path, logger=logger)

def require_safe_path(path: Path, purpose: str = "unspecified", logger=None) -> None:
    """
    Raises RuntimeError if the given path is unsafe. Logs with dry-run-compatible logger if available.
    """
    logger = logger or logging.getLogger(__name__)
    if not is_safe_path(path, logger=logger):
        msg = f"[SECURITY BLOCK] Unsafe path for {purpose}: {path}"
        logger.error(msg)
        raise RuntimeError(msg)

def log_if_unsafe(path: Path, context: str = "operation", logger=None) -> None:
    """
    Logs a warning if the path is unsafe, useful during dry run or soft gating.
    """
    logger = logger or logging.getLogger(__name__)
    if not is_safe_path(path, logger=logger):
        logger.warning(f"Refusing {context}: {path} (not within safe zones)")

def explain_path_rejection(path: Path, logger=None) -> str:
    """
    Returns a diagnostic explanation of why a path is considered unsafe.
    """
    logger = logger or logging.getLogger(__name__)
    try:
        path = path.resolve()
    except Exception as e:
        logger.warning(f"Path resolution failed for {path}: {e}")
        return f"Rejected path '{path}': could not resolve."

    reasons = []
    if path == Path(path.anchor):
        reasons.append("it is the root of the drive.")
    if not any(path.is_relative_to(base) for base in get_safe_root_folders()):
        reasons.append("it is not inside Documents, Desktop, Downloads, Pictures, Music, or Videos.")
    if not any("mediamender" in parent.name.lower() for parent in path.parents):
        reasons.append("it is not part of a MediaMender folder.")

    return f"Rejected path '{path}': " + " ".join(reasons) if reasons else f"Path '{path}' is safe."
