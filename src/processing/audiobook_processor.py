#src/processing/audiobook_processor.py
import asyncio
from pathlib import Path
import logging
#import subprocess
#import urllib.request
#import shutil

from src.dialog import ThemedMessage
from src.preferences import _load_config
from src.processing.common_utils import (
    sanitize_filename, move_to_trash, generate_normal_subtitles_from_audio,
    parse_chapters_from_srt, get_expected_chapter_count,
    fetch_openlibrary_metadata, build_audiobook_filename, get_output_path_for_media
)
from src.system.async_utils import stream_download, stream_subprocess
from src.system.safety import require_safe_path

def process_audiobook(file_path: Path, base_output_dir: Path, dry_run: bool = False, logger=None):
    logger = logger or logging.getLogger(__name__)
    logger.info(f"[Audiobook] Starting: {file_path.name}")

    try:
        require_safe_path(file_path, "Audiobook Input", logger)
        require_safe_path(base_output_dir, "Audiobook Output Root", logger)
    except RuntimeError:
        logger.error("Aborting audiobook processing due to unsafe paths.")
        return

    output_dir = get_output_path_for_media("audiobook", {}, base_output_dir, dry_run, logger)
    if output_dir is None:
        logger.error("Could not resolve safe output directory. Aborting.")
        return

    config = _load_config()
    allow_generation = config.get("allow_generation", False)
    whisper_model = config.get("whisper_model", "base") #TODO: Is this being used? I think all the audio processing is handled by common utils

    # Step 3: Fetch metadata
    title = sanitize_filename(file_path.stem)
    try:
        metadata = fetch_openlibrary_metadata(title, logger=logger)
    except Exception as e:
        logger.error(f"Metadata lookup failed: {e}")
        ThemedMessage.critical(None, "Metadata Error", f"Failed to fetch metadata for this audiobook: {title}.")
        return
    book_title = metadata.get("title", title)
    author = metadata.get("author", "Unknown")
    series = metadata.get("series")
    cover_url = metadata.get("cover_url")
    cover_path = None

    metadata.update({
        "title": book_title,
        "author": author,
        "series_name": series or "",
        "series_number": metadata.get("series_number", "")
    })

    filename = sanitize_filename(build_audiobook_filename(metadata))
    m4b_path = output_dir / filename

    logger.info(f"Output filename: {m4b_path.name}")

    if m4b_path.exists():
        logger.info(f"Skipping audiobook (already exists): {m4b_path.name}")
        return

    if cover_url:
        logger.info(f"Downloading Cover Image for {book_title} from {cover_url}")
        if not dry_run:
            cover_path = output_dir / "cover.jpg"
            success = stream_download(cover_url, cover_path, logger=logger)
            if not success:
                logger.warning(f"Cover image download failed: {cover_url}")
                cover_path = None

    # Step 1: Detect single vs multipart
    #parts = []
    if file_path.is_dir():
        parts = sorted(file_path.glob("*.mp3")) + sorted(file_path.glob("*.m4a"))
        if not parts:
            logger.warning(f"No audio parts found in {file_path}")
            return
    else:
        parts = [file_path]

    # Step 2: Merge if needed
    merged_path = output_dir / (file_path.stem + ".merged.m4a")
    if len(parts) > 1:
        list_path = output_dir / "parts.txt"
        logger.info(f"Merging audio parts into {merged_path} using {list_path}")
        if not dry_run:
            with list_path.open("w", encoding="utf-8") as f:
                for p in parts:
                    f.write(f"file '{p.as_posix()}'\n")
            asyncio.run(merge_audio_parts(list_path, merged_path, logger))
            list_path.unlink()
    else:
        merged_path = parts[0]

    # Step 4: Generate SRT + parse chapters
    srt_path = output_dir / f"{file_path.stem}.srt"
    chapters = []
    if allow_generation and not dry_run:
        try:
            srt_path = generate_normal_subtitles_from_audio(merged_path, srt_path, dry_run=dry_run, logger=logger) #TODO: Why is this returning a bool
            chapters = parse_chapters_from_srt(srt_path) #TODO: Why is this expecting a Path
        except Exception as e:
            logger.warning(f"Whisper transcription failed: {e}")
    elif not allow_generation:
        logger.info("Subtitle generation disabled. Enable it in Preferences for better chapter detection.")

    # Step 5: Expected chapter sanity check
    #expected_count = get_expected_chapter_count(book_title, logger=logger)##
    try:
        expected_count = get_expected_chapter_count(book_title, logger=logger)
    except Exception as e:
        logger.error(f"Chapter Count lookup failed: {e}")
        expected_count = None
    if expected_count and (len(chapters) < 0.5 * expected_count or len(chapters) > 2.5 * expected_count):
        logger.warning(f"Chapter mismatch. Expected ~{expected_count}, detected {len(chapters)}. Skipping chapters.")
        chapters = [] #clear chapters? #TODO: Is this being used?

    # Step 6: M4B encoding
    cmd = [
        "ffmpeg", "-i", str(merged_path),
        "-vn", "-c:a", "aac", "-b:a", "64k",
        "-metadata", f"title={book_title}",
        "-metadata", f"author={author}",
        "-metadata", f"album={series or ''}",
        "-metadata", f"genre=Audiobook",
        "-metadata", f"comment=Generated by MediaMender"
    ]

    if cover_path and cover_path.exists():
        cmd += ["-i", str(cover_path), "-map", "0:a", "-map", "1", "-c:v", "jpeg", "-disposition:v", "attached_pic"]
    cmd.append(str(m4b_path))
    logger.info(f"Creating M4B: {m4b_path}")
    logger.debug(" ".join(cmd))
    if not dry_run:
        asyncio.create_task(encode_m4b(cmd, logger))

    # Step 7: Cleanup
    if cover_path and cover_path.exists():
        cover_path.unlink()

    if merged_path != parts[0] and merged_path.exists():
        move_to_trash(merged_path, output_dir, dry_run, logger=logger)

    if srt_path.exists():
        move_to_trash(srt_path, output_dir, dry_run, logger=logger)

    logger.info(f"[Audiobook] Finished: {m4b_path.name}")

async def merge_audio_parts(list_path, merged_path, logger):
    cmd = [
        "ffmpeg", "-f", "concat", "-safe", "0",
        "-i", str(list_path), "-c", "copy", str(merged_path)
    ]
    def handle_line(line): logger.info(f"[FFMPEG MERGE] {line}")
    await stream_subprocess(cmd, on_output=handle_line, logger=logger, progress_range=(0, 10))

async def encode_m4b(cmd, logger):
    def handle_line(line):
        logger.info(f"[FFMPEG M4B] {line}")

    await stream_subprocess(
        cmd,
        on_output=handle_line,
        logger=logger,
        progress_range=(50, 100)  # Adjust based on observed performance
    )