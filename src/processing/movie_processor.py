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

def process_movie(file_path: Path, output_dir: Path, trash_dir: Path, dry_run: bool):
    logging.info(f"🎬 [Movie] Starting: {file_path.name}")

    # 1. Metadata
    metadata = extract_metadata_from_filename(file_path.name)
    metadata = validate_with_tmdb(metadata, media_type="movie")

    title = metadata.get("title", file_path.stem)
    year = metadata.get("year", "unknown")
    aspect = detect_aspect_ratio(file_path)
    source = detect_source_format(file_path.name)

    # 2. Output path
    safe_title = sanitize_filename(title)
    output_name = f"{safe_title} ({year}) [{source}][{aspect}].mkv"
    output_path = output_dir / output_name

    # 3. Subtitles
    subtitle_tracks = prepare_subtitles_for_muxing(file_path, trash_dir, dry_run)

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

    logging.info(f"📦 Remuxing: {' '.join(cmd)}")
    if not dry_run:
        subprocess.run(cmd, check=True)

    # 5. Trash original video
    move_to_trash(file_path, trash_dir, dry_run)

    # 6. Trash used subtitle files
    for track in subtitle_tracks:
        orig_path = track.get("original_path")
        if orig_path and orig_path.exists():
            move_to_trash(orig_path, trash_dir, dry_run)

    logging.info(f"✅ [Movie] Finished: {output_path.name}")
