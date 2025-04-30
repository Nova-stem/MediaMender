# src/processing/common_utils.py

import os
import re
import subprocess
from pathlib import Path
from typing import Optional
import string
from spellchecker import SpellChecker
from tmdbv3api import TMDb, Movie, TV
from src.preferences import get_tmdb_api_key

_ignored_names_cache = None

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
spellchecker = SpellChecker(distance=1)


tmdb = TMDb()
tmdb.api_key = get_tmdb_api_key() or ""
tmdb.language = 'en'
movie_search = Movie()
tv_search = TV()


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

    # Lowercase for normalization
    normalized = name.lower()

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

    # 5. Title assembly
    tokens = normalized.split()
    title_tokens = [
        t for t in tokens
        if not re.match(r's\d{1,2}e\d{1,2}', t)
        and not re.match(r'\d{3,4}p', t)
        and not re.match(r'^\d{4}$', t)
    ]

    if title_tokens:
        metadata["title"] = " ".join(word.capitalize() for word in title_tokens)

    return metadata


def validate_with_tmdb(metadata: dict, media_type: str = "movie") -> dict:
    """Validate and enrich metadata using TMDb."""
    query = metadata["title"]
    year = metadata.get("year")

    if media_type == "movie":
        results = movie_search.search(query)
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
        results = tv_search.search(query)
        if results:
            best = results[0]
            return {
                "title": best.name,
                "tmdb_id": best.id,
                "year": int(best.first_air_date.split('-')[0]) if best.first_air_date else None
            }

    return metadata  # fallback to original if nothing found