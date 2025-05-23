# src/processing/tv_processor.py
#23 May 2025

from pathlib import Path
import asyncio
import logging
#import subprocess

from src.system.async_utils import stream_subprocess
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
from src.system.safety import require_safe_path

def process_tv(file_path: Path, base_output_dir: Path, trash_dir: Path, dry_run: bool, logger=None):
    logger = logger or logging.getLogger(__name__)
    logger.info(f"[TV] Starting: {file_path.name}")

    try:
        require_safe_path(file_path, "TV Input File", logger)
        require_safe_path(base_output_dir, "TV Output Root", logger)
        require_safe_path(trash_dir, "Trash Directory", logger)
    except RuntimeError:
        logger.error("TV processing aborted due to unsafe paths.")
        return

    # 1. Metadata from filename
    metadata = extract_metadata_from_filename(file_path.name)
    show_title = metadata.get("title", file_path.stem)
    season = metadata.get("season")
    episode = metadata.get("episode")

    if season is None or episode is None:
        logger.warning(f"Could not extract season/episode from filename: {file_path.name}")
        return

    # 2. Enrich with TMDb
    enriched = validate_with_tmdb(metadata, media_type="tv", logger=logger)
    episode_title = enriched.get("episode_title", "")
    tmdb_show_title = enriched.get("title", show_title) #TODO: Is this used?

    # 3. Build output filename
    aspect = detect_aspect_ratio(file_path)
    source = detect_source_format(file_path.name)

    output_dir = get_output_path_for_media("show", {
        "show_title": show_title,
        "season_number": season
    }, base_output_dir, dry_run=dry_run, logger=logger)

    if output_dir is None:
        logger.error("Could not resolve safe output directory. Aborting.")
        return

    safe_title = sanitize_filename(show_title)
    safe_ep_title = sanitize_filename(episode_title)
    output_name = f"{safe_title} - S{int(season):02d}E{int(episode):02d} - {safe_ep_title} [{source} {aspect}].mkv"
    output_path = output_dir / output_name

    if output_path.exists():
        logger.info(f"Skipping: output already exists at {output_path}")
        return

    # 4. Subtitles: convert, clean, tag
    subtitle_tracks = prepare_subtitles_for_muxing(file_path, trash_dir, dry_run, logger=logger)

    # 5. Build mkvmerge command
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
        asyncio.run(mux_tv_episode(cmd, logger))

    # 6. Trash source video
    move_to_trash(file_path, trash_dir, dry_run, logger=logger)

    # 7. Trash cleaned subtitle files
    for track in subtitle_tracks:
        sub_path = track["path"]
        if sub_path.exists():
            move_to_trash(sub_path, trash_dir, dry_run, logger=logger)
    logger.info(f"[TV] Finished: {output_path.name}")

async def mux_tv_episode(cmd, logger):
    def handle_line(line):
        logger.info(f"[MKVMERGE TV] {line}")

    await stream_subprocess(
        cmd,
        on_output=handle_line,
        logger=logger,
        progress_range=(80, 100)
    )