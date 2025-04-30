# src/processing/tv_processor.py

from pathlib import Path
import logging

def process_tv(file_path: Path, output_dir: Path):
    logging.info(f"📺 [TV] Starting: {file_path.name}")

    # TODO 1: Extract show title, season, episode from filename
    # TODO 2: Look up episode title via TMDb
    # TODO 3: Collect + convert subtitles
    # TODO 4: Clean subtitles (branding, typos)
    # TODO 5: Detect aspect ratio from video
    # TODO 6: Detect source type (DVD/Bluray/Temp)
    # TODO 7: Format filename: Show SxxEyy - Title [Source Aspect].mkv
    # TODO 8: Package with MKVToolNix or FFmpeg
    # TODO 9: Log subtitle corrections

    logging.info(f"✅ [TV] Finished: {file_path.name}")
