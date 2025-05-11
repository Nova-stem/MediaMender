#src/processing/movie_processor.py

import asyncio
from pathlib import Path
import logging

from src.processing.common_utils import (
    extract_metadata_from_filename,
    validate_with_tmdb,
    detect_aspect_ratio,
    detect_source_format,
    sanitize_filename,
    prepare_subtitles_for_muxing,
    move_to_trash,
    get_output_path_for_media
)
from src.system.async_utils import stream_subprocess

from src.system.safety import require_safe_path

def process_movie(file_path: Path, base_output_dir: Path, trash_dir: Path, dry_run: bool, logger=None):
    logger = logger or logging.getLogger(__name__)
    logger.info(f"[Movie] Starting: {file_path.name}")

    try:
        require_safe_path(file_path, "Movie Input", logger)
        require_safe_path(base_output_dir, "Movie Output Root", logger)
        require_safe_path(trash_dir, "Trash Directory", logger)
    except RuntimeError:
        logger.error("Movie processing aborted due to unsafe paths.")
        return

    # 1. Metadata
    metadata = extract_metadata_from_filename(file_path.name)
    metadata = validate_with_tmdb(metadata, media_type="movie", logger=logger)

    title = metadata.get("title", file_path.stem)
    year = metadata.get("year", "unknown")
    aspect = detect_aspect_ratio(file_path)
    source = detect_source_format(file_path.name)

    # 2. Output path
    output_dir = get_output_path_for_media("movie", metadata, base_output_dir, dry_run, logger=logger)
    if output_dir is None:
        logger.error("Could not resolve a safe output directory. Aborting.")
        return

    safe_title = sanitize_filename(title)
    output_name = f"{safe_title} ({year}) [{source} {aspect}].mkv"
    output_path = output_dir / output_name

    if output_path.exists():
        logger.info(f"Skipping: output already exists at {output_path}")
        return

    # 3. Subtitles
    subtitle_tracks = prepare_subtitles_for_muxing(file_path, trash_dir, dry_run, logger=logger)

    # 4. Build mkvmerge command
    cmd = ["mkvmerge", "-o", str(output_path), str(file_path)]

    for track in subtitle_tracks:
        sub_path = track["path"]
        sub_type = track["type"]

        cmd += [
            "--language", "0:eng",
            "--track-name", f"0:{sub_type.upper()}" if sub_type != "normal" else "0:"
        ]
        if sub_type == "forced":
            cmd += ["--forced-track", "0"]
        cmd.append(str(sub_path))

    logger.info(f"Re-multiplexing: {' '.join(cmd)}")
    if not dry_run:
        asyncio.run(mux_with_mkvmerge(cmd, logger))

    # 5. Trash original video
    move_to_trash(file_path, trash_dir, dry_run, logger=logger)

    # 6. Trash used subtitle files
    for track in subtitle_tracks:
        orig_path = track.get("original_path")
        if orig_path and orig_path.exists():
            move_to_trash(orig_path, trash_dir, dry_run, logger=logger)

    logger.info(f"[Movie] Finished: {output_path.name}")

async def mux_with_mkvmerge(cmd, logger):
    def handle_line(line):
        logger.info(f"[MKVMERGE Movie] {line}")

    await stream_subprocess(
        cmd,
        on_output=handle_line,
        logger=logger,
        progress_range=(80, 100)  # optional range
    )