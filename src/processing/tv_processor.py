# src/processing/tv_processor.py

from pathlib import Path
import logging
import subprocess

from src.processing.common_utils import (
    extract_metadata_from_filename,
    validate_with_tmdb,
    detect_aspect_ratio,
    detect_source_format,
    sanitize_filename,
    prepare_subtitles_for_muxing,
    move_to_trash
)

def process_tv(file_path: Path, output_dir: Path, trash_dir: Path, dry_run: bool):
    logging.info(f"📺 [TV] Starting: {file_path.name}")

    # 1. Metadata from filename
    metadata = extract_metadata_from_filename(file_path.name)
    show_title = metadata.get("title", file_path.stem)
    season = metadata.get("season")
    episode = metadata.get("episode")

    if season is None or episode is None:
        logging.warning(f"⚠️ Could not extract season/episode from filename: {file_path.name}")
        return

    # 2. Enrich with TMDb
    enriched = validate_with_tmdb(metadata, media_type="tv")
    episode_title = enriched.get("episode_title", "")
    tmdb_show_title = enriched.get("title", show_title)

    # 3. Build output filename
    safe_title = sanitize_filename(tmdb_show_title)
    safe_ep_title = sanitize_filename(episode_title)
    ep_code = f"S{season:02d}E{episode:02d}"
    aspect = detect_aspect_ratio(file_path)
    source = detect_source_format(file_path.name)

    final_name = f"{safe_title} {ep_code}"
    if safe_ep_title:
        final_name += f" - {safe_ep_title}"
    final_name += f" [{source}][{aspect}].mkv"

    output_path = output_dir / final_name

    # 4. Subtitles: convert, clean, tag
    subtitle_tracks = prepare_subtitles_for_muxing(file_path, trash_dir, dry_run)

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

    logging.info(f"📦 Remuxing: {' '.join(cmd)}")
    if not dry_run:
        subprocess.run(cmd, check=True)

    # 6. Trash source video
    move_to_trash(file_path, trash_dir, dry_run)

    # 7. Trash cleaned subtitle files
    for track in subtitle_tracks:
        sub_path = track["path"]
        if sub_path.exists():
            move_to_trash(sub_path, trash_dir, dry_run)

    logging.info(f"✅ [TV] Finished: {output_path.name}")
