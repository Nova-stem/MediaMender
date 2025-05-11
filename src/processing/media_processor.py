from pathlib import Path

from src.dialog import ThemedMessage
from src.processing.movie_processor import process_movie
from src.processing.tv_processor import process_tv
from src.processing.audiobook_processor import process_audiobook
from src.processing.common_utils import extract_metadata_from_filename, move_to_trash, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS, SUBTITLE_EXTENSIONS
from src.system.safety import require_safe_path, is_safe_path, log_if_unsafe
import logging

def process_media(file_path: Path, output_dir: Path, trash_dir: Path, dry_run: bool, logger=None):
    logger = logger or logging.getLogger(__name__)
    ext = file_path.suffix.lower()
    metadata = extract_metadata_from_filename(str(file_path), logger=logger)

    # Safety enforcement
    try:
        require_safe_path(file_path, "Input File", logger)
        require_safe_path(output_dir, "Output Directory", logger)
        require_safe_path(trash_dir, "Trash Directory", logger)
    except RuntimeError:
        logger.error(f"Processing aborted due to unsafe paths.")
        return

    try:
        # --- VIDEO ---
        if is_likely_sample(file_path, logger=logger):
            logger.info(f"Trashing sample file: {file_path.name}")
            move_to_trash(file_path, trash_dir, dry_run, logger=logger)
            return
        elif ext in VIDEO_EXTENSIONS:
            if metadata.get("season") and metadata.get("episode"):
                logger.info(f"Detected TV episode: {file_path.name}")
                process_tv(file_path, output_dir, trash_dir, dry_run, logger=logger)
            else:
                logger.info(f"Detected movie: {file_path.name}")
                process_movie(file_path, output_dir, trash_dir, dry_run, logger=logger)

        # --- AUDIO ---
        elif ext in AUDIO_EXTENSIONS:
            logger.info(f"Detected audiobook: {file_path.name}")
            process_audiobook(file_path, output_dir, trash_dir, dry_run, logger=logger)

        # --- SUBTITLES ---
        elif ext in SUBTITLE_EXTENSIONS:
            logger.info(f"Detected subtitle, skipping: {file_path.name}")

        # --- UNSUPPORTED ---
        else:
            logger.warning(f"Unsupported file type: {file_path.name}")
            move_to_trash(file_path, trash_dir, dry_run, logger=logger)

    except Exception as e:
        logger.exception(f"Failed to process file: {file_path.name}")
        ThemedMessage.critical(None, "Processing Error", f"Failed to process:\n{file_path.name}") #TODO: Should populate 'Failed' In UI instead.

def detect_media_type(file_path: Path, logger=None) -> str:
    ext = file_path.suffix.lower()
    logger = logger or logging.getLogger(__name__)
    metadata = extract_metadata_from_filename(str(file_path), logger=logger)

    if ext in VIDEO_EXTENSIONS:
        if metadata.get("season") is not None:
            return "TV"
        return "Movie"
    elif ext in AUDIO_EXTENSIONS:
        return "Audiobook"
    elif ext in SUBTITLE_EXTENSIONS:
        return "Subtitle"
    return "Unsupported"

def is_likely_sample(file_path: Path, logger=None) -> bool:
    """
    Determines whether a file is a 'sample' based on:
    - Name patterns
    - Size threshold (<100 MB)
    - Sibling comparison (same extension, significantly larger)
    """
    logger = logger or logging.getLogger(__name__)
    name = file_path.stem.lower()

    is_named_sample = (
        name == "sample" or
        name.startswith("sample_") or
        name.endswith("_sample") or
        name.endswith("-sample")
    )

    try:
        size_mb = file_path.stat().st_size / (1024 * 1024)
    except Exception as e:
        logger.warning(f"Could not stat file {file_path}: {e}")
        return False

    is_small = size_mb < 100
    if not is_named_sample or not is_small:
        return False

    try:
        for sibling in file_path.parent.iterdir():
            if sibling == file_path or not sibling.is_file():
                continue
            if sibling.suffix.lower() != file_path.suffix.lower():
                continue
            if sibling.stat().st_size > file_path.stat().st_size * 3:
                logger.info(f"Sample file confirmed by sibling comparison: {file_path.name}")
                return True
    except Exception as e:
        logger.warning(f"Could not compare sample to siblings: {e}")

    return False
