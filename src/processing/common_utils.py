# src/processing/common_utils.py

#Standard
import datetime
import difflib
import json
import logging
import os
import platform
import re
import shutil
import string
import subprocess
import zipfile
from datetime import time
from pathlib import Path
from typing import Any, Optional
from urllib import parse, request

#Third Party
from faster_whisper import WhisperModel
from spellchecker import SpellChecker
from srt import Subtitle, compose
from tmdbv3api import Movie, Search, TMDb, TV

#Local
from src.dialog import ThemedMessage
from src.preferences import get_tmdb_api_key, get_whisper_model, is_generation_allowed

FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FFMPEG_TARGET = Path("resources/ffmpeg/ffmpeg.exe")
_ignored_names_cache = None
spellchecker = SpellChecker(distance=1)
tmdb = TMDb()
tmdb.api_key = get_tmdb_api_key() or ""
tmdb.language = 'en'
movie_search = Movie()
tv_search = TV()
_tmdb_warning_shown = False

BRANDING_PATTERNS = [
    ["sync", "by"], ["addic7ed"], ["subscene"], ["corrected", "by"],
    ["corrections", "by"], ["downloaded", "from"], ["yts"], ["yifi"],
    ["opensubtitle"], ["english", "us "], ["english", " us"],
    ["ripped", "by"], ["encoded", "by"], ["provided", "by"],
    ["captioned", "by"], ["www.", ".net"], ["www.", ".org"],
    ["www.", ".app"], ["www.", ".com"], ["timecodes"], ["[nef]"],
    ["caption", "possible"], ["caption", "made"], [".org"], [".com"],
    [".net"], [".bb"], [".io"], ["www."], ["sub", "download"],
    ["subtitle", "rate"], ["clearway"], ["season", "episode"],
    ["improved", "by"], ["winxbloom1980"], ["editing", "timing"],
    ["4kvod"], [".tv"], ["p@rm!nder"], ["parminder"], ["p@"],
    ["©"], ["subtitle", "by"], ["explosiveskull"], [".app"],
    [".admit"], ["subtitled", "by"], ["muntasir"], [".co"]
]

def load_ignored_names() -> set[str]:
    global _ignored_names_cache
    if _ignored_names_cache is not None:
        return _ignored_names_cache

    path = Path(__file__).parent.parent / "resources" / "ignored_names.txt"
    if not path.exists():
        _ignored_names_cache = set()
        return _ignored_names_cache

    with open(path, "r", encoding="utf-8") as f:
        _ignored_names_cache = set(line.strip().lower() for line in f if line.strip())
    return _ignored_names_cache
ignored_names = load_ignored_names()

def detect_aspect_ratio(file_path: Path) -> str:
    """Detects aspect ratio using ffprobe and returns label."""
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        width, height = map(int, result.stdout.strip().split('\n'))
        ratio = width / height

        if ratio < 1.6:
            return "Fullscreen"
        elif ratio < 2.0:
            return "Widescreen"
        else:
            return "Ultrawide"
    except Exception as e:
        print(f"Aspect ratio detection failed: {e}")
        return "Widescreen"

def detect_source_format(file_name: str) -> str:
    """Returns 'DVD', 'Bluray', or 'Temp' based on file name."""
    name = file_name.lower()
    if "[dvd" in name:
        return "DVD"
    elif "[bluray" in name or "[blu-ray" in name:
        return "Bluray"
    else:
        return "Temp"

def clean_subtitle_text(text: str) -> str:
    def is_branding_line(line: str) -> bool:
        normalized = line.lower().translate(str.maketrans('', '', string.punctuation)).strip()
        for pattern in BRANDING_PATTERNS:
            if all(word in normalized for word in pattern):
                return True
        return False

    lines = text.splitlines()
    cleaned = [line for line in lines if not is_branding_line(line)]
    return "\n".join(cleaned)

def sanitize_filename(name: str) -> str:
    """Removes illegal filename characters."""
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()

def extract_year_from_metadata(metadata: dict) -> Optional[int]:
    """Returns the year from metadata, if available."""
    for key in ("year", "release_date", "date"):
        if key in metadata:
            match = re.search(r'\d{4}', str(metadata[key]))
            if match:
                return int(match.group())
    return None

def correct_subtitle_typos(text: str) -> tuple[str, list[dict]]:
    """
    Returns corrected subtitle text and a list of change logs.
    """
    corrected_lines = []
    correction_log = []

    for idx, line in enumerate(text.splitlines(), start=1):
        if line.strip() == "" or re.match(r"^\d+$", line) or "-->" in line:
            corrected_lines.append(line)
            continue

        words = line.split()
        corrected_words = []

        for w_idx, word in enumerate(words, start=1):
            raw = re.sub(r"[^\w']+", '', word)  # stripped of punctuation
            if not raw:
                corrected_words.append(word)
                continue

            # Skip names and proper nouns
            if raw.lower() in ignored_names:
                corrected_words.append(word)
                continue

            # Likely proper name — capitalized and not the first word
            if raw[0].isupper() and w_idx > 1:
                corrected_words.append(word)
                continue

            # Apply correction if needed
            if raw.lower() not in spellchecker:
                suggestion = spellchecker.correction(raw.lower())
                if suggestion and suggestion.lower() != raw.lower():
                    corrected_word = word.replace(raw, suggestion, 1)
                    corrected_words.append(corrected_word)
                    correction_log.append({
                        "original": raw,
                        "corrected": suggestion,
                        "line": idx,
                        "word": w_idx
                    })
                    continue

            corrected_words.append(word)

        corrected_lines.append(" ".join(corrected_words))

    return "\n".join(corrected_lines), correction_log

def extract_metadata_from_filename(file_path: str) -> dict:
    name = Path(file_path).stem
    metadata = {
        "title": None,
        "year": None,
        "season": None,
        "episode": None,
        "original_suffix": None
    }

    # 1. Grab [Bluray Ultrawide] or similar and store it before cleaning
    suffix_match = re.search(r"\[([^\[\]]+)\]$", name)
    if suffix_match:
        metadata["original_suffix"] = suffix_match.group(1)
        name = name[:suffix_match.start()].strip()
        logging.info(f"{suffix_match.group(1)}")

    # Lowercase for normalization
    normalized = name.lower()

    metadata: dict[str, Any] = {}

    # 2. Extract season/episode if present
    match = re.search(r's(\d{1,2})e(\d{1,2})', normalized)
    if match:
        metadata["season"] = int(match.group(1))
        metadata["episode"] = int(match.group(2))

    # 3. Extract year
    match = re.search(r'\b(19|20)\d{2}\b', normalized)
    if match:
        metadata["year"] = int(match.group(0))
        normalized = normalized.replace(match.group(0), '')

    # 4. Remove encoding junk
    junk_patterns = r'(bluray|brrip|webrip|web[-.]dl|hdrip|xvid|x264|x265|10bit|aac|dts|hevc|dvdrip|hdtv|proper|repack|subs|eng|mp3|flac)'
    normalized = re.sub(junk_patterns, '', normalized)
    normalized = re.sub(r'[._\-]', ' ', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()

    # 5. Remove empty brackets, parentheses, and braces
    normalized = re.sub(r'\(\s*\)', '', normalized)
    normalized = re.sub(r'\[\s*\]', '', normalized)
    normalized = re.sub(r'\{\s*\}', '', normalized)

    # 6. Title assembly
    tokens = normalized.split()
    #logging.info(f"Tokens: {tokens}")
    title_tokens = [
        t for t in tokens
        if not re.match(r's\d{1,2}e\d{1,2}', t)
        and not re.match(r'\d{3,4}p', t)
        and not re.match(r'^\d{4}$', t)
    ]

    if title_tokens:
        metadata["title"] = " ".join(word.capitalize() for word in title_tokens)

    return metadata

def set_tmdb_warning_callback(callback: callable):
    global _tmdb_warning_callback
    _tmdb_warning_callback = callback

def validate_with_tmdb(metadata: dict, media_type: str = "movie") -> dict:
    """Validate and enrich metadata using TMDb."""
    global _tmdb_warning_shown

    api_key = get_tmdb_api_key()
    if not api_key:
        if not _tmdb_warning_shown:
            logging.warning("TMDb API key is missing. Metadata lookup skipped.")
            _tmdb_warning_shown = True
        return metadata

    query = metadata["title"]
    year = metadata.get("year")
    logging.info("TBDb metadata enrichment in progress...")

    if media_type == "movie":
        results = Search().movies(query)
        if year:
            results = [r for r in results if str(year) in str(r.get('release_date', ''))]
        if results:
            best = results[0]
            return {
                "title": best.title,
                "year": int(best.release_date.split('-')[0]),
                "tmdb_id": best.id,
            }

    elif media_type == "tv":
        results = Search().movies(query)
        if results:
            best = results[0]
            return {
                "title": best.name,
                "tmdb_id": best.id,
                "year": int(best.first_air_date.split('-')[0]) if best.first_air_date else None
            }

    return metadata  # fallback to original if nothing found

def prepare_subtitles_for_muxing(video_path: Path, trash_dir: Path, dry_run: bool) -> list[dict]:
    subtitle_tracks = find_all_subtitles(video_path)
    prepared = []

    for track in subtitle_tracks:
        original = track["path"]
        sub_path = original
        sub_type = track["type"]

        # Convert to .srt if needed
        if original.suffix.lower() != ".srt":
            converted = original.with_suffix(".converted.srt")
            try:
                if dry_run:
                    logging.info(f"[DRY RUN] Would convert subtitle: {original.name}")
                    sub_path = converted
                else:
                    subprocess.run(["ffmpeg", "-y", "-i", str(original), str(converted)], check=True)
                    sub_path = converted
                    move_to_trash(original, trash_dir, dry_run)
            except Exception as e:
                logging.warning(f"Subtitle conversion failed: {e}")
                continue

        # Clean + correct
        try:
            raw = sub_path.read_text(encoding="utf-8", errors="ignore")
            cleaned = clean_subtitle_text(raw)
            corrected, corrections = correct_subtitle_typos(cleaned)

            cleaned_path = sub_path.with_name(sub_path.stem + ".cleaned.srt")
            if dry_run:
                logging.info(f"[DRY RUN] Would write cleaned subtitle: {cleaned_path.name}")
            else:
                cleaned_path.write_text(corrected, encoding="utf-8")
                if corrections:
                    log_path = cleaned_path.with_suffix(".log")
                    with open(log_path, "w", encoding="utf-8") as f:
                        for entry in corrections:
                            f.write(
                                f"Line {entry['line']}, Word {entry['word']}: "
                                f"{entry['original']} → {entry['corrected']}\n"
                            )
                    logging.info(f"Logged {len(corrections)} subtitle corrections to: {log_path.name}")

            prepared.append({
                "path": cleaned_path,
                "type": sub_type,
                "original_path": sub_path
            })

        except Exception as e:
            logging.warning(f"Subtitle cleanup failed for {original.name}: {e}")

    # Fallback generation if no usable subtitles found
    if not prepared:
        logging.info("No usable subtitles found.")

        if is_generation_allowed():
            logging.info("Generating subtitles from audio...")
            normal_srt = video_path.with_name(video_path.stem + ".normal.srt")
            if generate_normal_subtitles_from_audio(video_path, normal_srt, dry_run):
                prepared.append({"path": normal_srt, "type": "normal"})

            forced_srt = video_path.with_name(video_path.stem + ".forced.srt")
            if generate_forced_subtitles_from_audio(video_path, forced_srt, dry_run):
                prepared.append({"path": forced_srt, "type": "forced"})
        else:
            logging.info("Subtitle generation is disabled. Enable 'Allow Generation' in preferences to use Whisper.")

    return prepared

def find_all_subtitles(file_path: Path, threshold: float = 0.75) -> list[dict]:
    """
    Fuzzy-matches subtitle files to a given video file, classifies them
    as 'normal', 'forced', or 'sdh', and returns usable subtitle tracks.
    """
    folder = file_path.parent
    video_stem = file_path.stem.lower()
    subtitle_exts = {".srt", ".ass", ".vtt", ".sub"}
    candidates = []

    for sub in folder.iterdir():
        if not sub.is_file():
            continue
        if sub.suffix.lower() not in subtitle_exts:
            continue
        name = sub.name.lower()
        if "sample" in name:
            continue

        sub_stem = sub.stem.lower()

        match_score = difflib.SequenceMatcher(None, video_stem, sub_stem).ratio()
        if match_score >= threshold:
            candidates.append(sub)

    if not candidates:
        return []

    # Sort by file size ascending
    candidates.sort(key=lambda p: p.stat().st_size)

    results = []
    seen_types = set()

    for sub in candidates:
        name = sub.name.lower()
        label = "normal"
        if "forced" in name:
            label = "forced"
        elif "sdh" in name or "hi" in name:
            label = "sdh"

        if label not in seen_types:
            seen_types.add(label)
            results.append({"path": sub, "type": label})

    return results

def move_to_trash(file_path: Path, trash_dir: Path, dry_run: bool):
    """
    Moves a file to the specified trash directory. Honors dry run and safety checks.
    """
    if not file_path.exists():
        return

    if dry_run and not is_safe_to_trash(file_path):
        logging.warning(f"[DRY RUN] Refusing to trash file outside of safe zones: {file_path}")
        return

    if not is_safe_to_trash(file_path):
        logging.warning(f"Refusing to trash file outside of safe zones: {file_path}")
        return

    trash_dir.mkdir(parents=True, exist_ok=True)
    dest = trash_dir / file_path.name

    # Handle filename collision in trash
    counter = 1
    while dest.exists():
        dest = trash_dir / f"{file_path.stem}_{counter}{file_path.suffix}"
        counter += 1

    if dry_run:
        logging.info(f"[DRY RUN] Moved to trash: {file_path.name} -> {dest.name}")
        return

    file_path.rename(dest)
    logging.info(f"Moved to trash: {file_path.name} -> {dest.name}")

def generate_forced_subtitles_from_audio(file_path: Path, output_srt: Path, dry_run: bool = False) -> bool:
    logging.info(f"Scanning for non-English (forced) segments in: {file_path.name}")
    if dry_run:
        logging.info(f"[DRY RUN] Would write forced subtitles to: {output_srt}")
        return True

    try:
        model_size = get_whisper_model()
        model = WhisperModel(model_size, compute_type="int8")

        segments, _ = model.transcribe(str(file_path), language=None)

        forced_segments = []
        for i, seg in enumerate(segments):
            lang = seg.language or "en"
            if lang != "en":
                start = datetime.timedelta(seconds=seg.start)
                end = datetime.timedelta(seconds=seg.end)
                text = seg.text.strip()
                forced_segments.append(Subtitle(index=i+1, start=start, end=end, content=text))

        if not forced_segments:
            logging.info("No non-English speech found.")
            return False

        output_srt.write_text(compose(forced_segments), encoding="utf-8")
        logging.info(f"Forced subtitles saved: {output_srt.name}")
        return True

    except Exception as e:
        logging.warning(f"Whisper (forced) generation failed: {e}")
        return False

def generate_normal_subtitles_from_audio(file_path: Path, output_srt: Path, dry_run: bool = False) -> bool:
    logging.info(f"Generating full transcription subtitles for: {file_path.name}")
    if dry_run:
        logging.info(f"[DRY RUN] Would write normal subtitles to: {output_srt}")
        return True

    try:
        model_size = get_whisper_model()
        model = WhisperModel(model_size, compute_type="int8")

        segments, _ = model.transcribe(str(file_path), language="en")

        srt_segments = []
        for i, seg in enumerate(segments):
            start = datetime.timedelta(seconds=seg.start)
            end = datetime.timedelta(seconds=seg.end)
            text = seg.text.strip()
            srt_segments.append(Subtitle(index=i+1, start=start, end=end, content=text))

        if not srt_segments:
            logging.warning("No segments generated.")
            return False

        output_srt.write_text(compose(srt_segments), encoding="utf-8")
        logging.info(f"Normal subtitles saved: {output_srt.name}")
        return True

    except Exception as e:
        logging.warning(f"Whisper (normal) generation failed: {e}")
        return False

def get_whisper_model_dir() -> Path:
    if platform.system() == "Windows":
        return Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "MediaMender" / "models"
    else:
        return Path.home() / ".mediamender" / "models"

def ensure_whisper_model_installed(model: str, progress_callback=None, dry_run: bool = False) -> bool:
    model_dir = get_whisper_model_dir() / model
    if model_dir.exists() and any(model_dir.iterdir()):
        logging.info(f"Whisper model '{model}' already installed.")
        return True

    if dry_run:
        logging.info(f"[DRY RUN] Whisper model '{model}' not found. Would download to: {model_dir}")
        if progress_callback:
            progress_callback(0, f"[DRY RUN] Would install Whisper model '{model}'.")
        return True

    try:
        logging.info(f"Downloading Whisper model: {model} to {model_dir}")
        if progress_callback:
            progress_callback(0, f"Downloading Whisper model '{model}'...")

        # This auto-downloads and caches the model
        WhisperModel(model, download_root=str(model_dir), compute_type="int8")

        if progress_callback:
            progress_callback(100, f"Whisper model '{model}' installed.")
        return True

    except Exception as e:
        logging.error(f"Failed to download Whisper model '{model}': {e}")
        if progress_callback:
            progress_callback(0, f"Failed to install Whisper model: {e}")
        return False

def find_ffmpeg_path() -> str:
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return "ffmpeg"  # found in PATH
    except Exception:
        fallback = Path("resources/ffmpeg/ffmpeg.exe")
        if fallback.exists():
            return str(fallback)

        return None

def install_ffmpeg_if_needed(progress_callback=None, dry_run: bool = False) -> str | None:
    # 1. Check system PATH
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        logging.info("FFmpeg found in system PATH.")
        return "ffmpeg"
    except Exception:
        pass

    # 2. Check local install
    if FFMPEG_TARGET.exists():
        logging.info("FFmpeg found in local resources.")
        return str(FFMPEG_TARGET)

    if dry_run:
        logging.info("[DRY RUN] FFmpeg not found. Would download and install to resources/ffmpeg/")
        if progress_callback:
            progress_callback(0, "[DRY RUN] Would install FFmpeg.")
        return str(FFMPEG_TARGET)

    # 3. Download and install
    try:
        if progress_callback:
            progress_callback(0, "Downloading FFmpeg...")

        zip_path = Path("ffmpeg_tmp.zip")
        request.urlretrieve(FFMPEG_URL, zip_path)

        if progress_callback:
            progress_callback(30, "Extracting FFmpeg...")

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall("ffmpeg_tmp")

        extracted = next(Path("ffmpeg_tmp").rglob("ffmpeg.exe"))
        FFMPEG_TARGET.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(extracted, FFMPEG_TARGET)

        # Clean up
        shutil.rmtree("ffmpeg_tmp")
        zip_path.unlink()

        if progress_callback:
            progress_callback(100, "FFmpeg installed.")
        return str(FFMPEG_TARGET)

    except Exception as e:
        logging.error(f"Failed to install FFmpeg: {e}")
        if progress_callback:
            progress_callback(0, "Failed to install FFmpeg.")
        return None

def parse_chapters_from_srt(srt_path: Path) -> list[tuple[float, float]]:
    """
    Detect chapters from SRT by looking for major time gaps or keyword lines.
    """
    chapters = []
    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

        times = []
        keywords = []

        for i, line in enumerate(lines):
            if "-->" in line:
                start = line.split("-->")[0].strip()
                h, m, s = re.split("[:,]", start)
                start_sec = int(h) * 3600 + int(m) * 60 + int(s)
                times.append(start_sec)
            elif re.match(r"^(chapter|prologue|epilogue|\d+|[IVXLC]+)\b", line.strip(), re.IGNORECASE):
                keywords.append(len(times))

        if keywords:
            # Convert keyword positions to chapters
            for i, idx in enumerate(keywords):
                start = times[idx]
                end = times[keywords[i + 1]] if i + 1 < len(keywords) else None
                chapters.append((start, end))
        else:
            # Use gaps
            last = 0
            for current in times:
                if current - last >= 60:
                    chapters.append((last, current))
                    last = current
            chapters.append((last, None))
    except Exception as e:
        logging.warning(f"Chapter parsing from SRT failed: {e}")
    return chapters

def openlibrary_request(url: str) -> dict:
    for attempt in range(10):
        try:
            with request.urlopen(url) as response:
                return json.loads(response.read().decode())
        except Exception as e:
            logging.warning(f"[Attempt {attempt+1}] OpenLibrary request failed: {e}")
            time.sleep(20)
    raise RuntimeError(f"Failed to fetch OpenLibrary data after 10 attempts: {url}")

def get_expected_chapter_count(title: str) -> int | None:
    """
    Uses OpenLibrary to estimate the expected number of chapters for a given title.
    Returns number of ToC entries if available, otherwise None.
    """
    q = parse.quote(title)
    search_url = f"https://openlibrary.org/search.json?title={q}&has_fulltext=true&language=eng"

    try:
        with request.urlopen(search_url) as response:
            search_data = json.loads(response.read().decode())
            if not search_data.get("docs"):
                return None

            work_key = search_data["docs"][0].get("key")
            if not work_key:
                return None

        toc_url = f"https://openlibrary.org{work_key}.json"
        with request.urlopen(toc_url) as toc_response:
            toc_data = json.loads(toc_response.read().decode())
            toc = toc_data.get("table_of_contents")
            if isinstance(toc, list):
                return len(toc)

    except Exception as e:
        logging.warning(f"OpenLibrary chapter lookup failed: {e}")
        return None

def openlibrary_request(url: str) -> dict:
    for attempt in range(10):
        try:
            with request.urlopen(url) as response:
                return json.loads(response.read().decode())
        except Exception as e:
            logging.warning(f"[Attempt {attempt+1}] OpenLibrary request failed: {e}")
            time.sleep(20)
    raise RuntimeError(f"Failed to fetch OpenLibrary data after 10 attempts: {url}")

def fetch_openlibrary_metadata(title: str) -> dict:
    """
    Fetch book metadata (title, author, series, cover URL) using OpenLibrary API.
    """
    q = parse.quote(title)
    search_url = f"https://openlibrary.org/search.json?title={q}&has_fulltext=true&language=eng"
    data = openlibrary_request(search_url)

    if not data.get("docs"):
        return {}

    doc = data["docs"][0]
    result = {
        "title": doc.get("title"),
        "author": doc.get("author_name", ["Unknown"])[0],
        "series": doc.get("series", [None])[0],
        "cover_url": f"https://covers.openlibrary.org/b/id/{doc['cover_i']}-L.jpg" if "cover_i" in doc else None
    }
    return result

def build_audiobook_filename(metadata: dict) -> str:
    """
    Constructs a filename like:
    'Series Name Book 2, Title - Author.m4b'
    """
    series = metadata.get("series_name", "").strip()
    number = metadata.get("series_number", "").strip()
    title = metadata.get("title", "").strip()
    author = metadata.get("author", "").strip()

    parts = []
    if series and number:
        parts.append(f"{series} Book {number}")
    if title:
        parts.append(title)
    if author:
        parts.append(f"- {author}")

    if not parts:
        return "Unknown_Audiobook.m4b"

    return ", ".join(parts[:-1]) + f" {parts[-1]}.m4b"

def get_output_path_for_media(media_type: str, metadata: dict, base_output_dir: Path, dry_run: bool = False) -> Path | None:
    """
    Returns and (optionally) creates the output directory path based on media type.
    Logs the resolved path and respects dry run. If media_type is unsupported, logs and returns None.
    """
    media_type = media_type.lower()

    if media_type == "movie":
        dest_dir = base_output_dir / "Movies"

    elif media_type == "audiobook":
        dest_dir = base_output_dir / "Audiobooks"

    elif media_type == "show":
        show_title = metadata.get("show_title", "Unknown Show").strip()
        season_number = metadata.get("season_number", 1)
        season_str = f"Season {int(season_number):02d}"
        dest_dir = base_output_dir / "Shows" / show_title / season_str

    else:
        logging.warning(f"Unsupported media type '{media_type}'. Skipping.")
        return None

    if dry_run:
        logging.info(f"[DRY RUN] Would use/create output directory: {dest_dir}")
    else:
        dest_dir.mkdir(parents=True, exist_ok=True)
        logging.info(f"Created or confirmed output directory: {dest_dir}")

    return dest_dir

def is_safe_to_trash(path: Path) -> bool:
    try:
        path = path.resolve()
        system_drive = Path(path.anchor).resolve()  # e.g., "C:\", "/"

        # 1. Block root of OS
        if path == system_drive:
            logging.warning(f"Refusing to trash system root: {path}")
            return False

        # 2. Define allowed base folders (Windows known user folders)
        user_home = Path.home()
        safe_folders = [
            user_home / "Documents",
            user_home / "Desktop",
            user_home / "Downloads",
            user_home / "Pictures",
            user_home / "Music",
            user_home / "Videos"
        ]
        safe_folders = [p.resolve() for p in safe_folders if p.exists()]

        # 3. Allow if in any of the safe user folders
        for safe in safe_folders:
            if safe in path.parents:
                logging.debug(f"Safe: {safe}")
                return True

        # 4. Allow if file is within a folder whose name includes "MediaMender"
        for parent in path.parents:
            logging.debug(f"Parent: {parent}")
            if "mediamender" in parent.name.lower():
                return True

        logging.warning(f"Refusing to trash file outside of safe zones: {path}")
        return False

    except Exception as e:
        logging.warning(f"Could not verify safety for {path}: {e}")
        return False
