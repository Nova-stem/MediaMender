# src/processing/movie_processor.py

from pathlib import Path
import logging

def process_movie(file_path: Path, output_dir: Path):
    logging.info(f"🎬 [Movie] Starting: {file_path.name}")

    # TODO 1: Extract metadata from filename
    # TODO 2: Validate title/year with TMDb
    # TODO 3: Collect + convert subtitles to .srt
    # TODO 4: Clean subtitles (branding, typos)
    # TODO 5: Detect aspect ratio from file
    # TODO 6: Detect source format (DVD/Bluray/Temp)
    # TODO 7: Build final metadata & output filename
    # TODO 8: Package with MKVToolNix or FFmpeg
    # TODO 9: Save logs for subtitle cleanup / corrections

    logging.info(f"✅ [Movie] Finished: {file_path.name}")
