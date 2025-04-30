from pathlib import Path
from src.processing.movie_processor import process_movie
from src.processing.tv_processor import process_tv
from src.processing.audiobook_processor import process_audiobook
from src.processing.common_utils import extract_metadata_from_filename
import logging

def process_media(file_path: Path, output_dir: Path):
    ext = file_path.suffix.lower()
    metadata = extract_metadata_from_filename(file_path)

    try:
        # Route based on file type and metadata
        if ext in [".mp4", ".mkv", ".avi", ".mov"]:
            if metadata.get("season") and metadata.get("episode"):
                logging.info(f"🎬 Detected TV episode: {file_path.name}")
                process_tv(file_path, output_dir)
            else:
                logging.info(f"🎬 Detected movie: {file_path.name}")
                process_movie(file_path, output_dir)

        elif ext in [".mp3", ".m4a", ".aac", ".flac", ".wav"]:
            logging.info(f"📘 Detected audiobook: {file_path.name}")
            process_audiobook(file_path, output_dir)

        else:
            logging.warning(f"⚠️ Unsupported file type: {file_path.name}")

    except Exception as e:
        logging.exception(f"❌ Failed to process file: {file_path.name}")

def detect_media_type(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    metadata = extract_metadata_from_filename(file_path)

    if ext in [".mp4", ".mkv", ".avi", ".mov"]:
        if metadata.get("season") is not None:
            return "TV"
        return "Movie"
    elif ext in [".mp3", ".m4a", ".flac", ".wav", ".aac"]:
        return "Audiobook"
    return "Unsupported"