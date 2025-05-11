#src/system/async_utils.py

import asyncio
import logging
import re
from pathlib import Path
from urllib.request import urlopen

def parse_percent_from_output(line: str) -> float | None:
    """
    Attempts to parse a percentage value from a line of text.
    Example match: '... 37.2% ...'
    """
    match = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", line)
    if match:
        return float(match.group(1))
    return None


async def stream_subprocess(
    cmd: list[str],
    on_output=None,
    on_progress=None,
    on_complete=None,
    on_error=None,
    logger=None,
    progress_range=(0, 100)
):
    """
    Runs a subprocess asynchronously and streams stdout line by line.

    Args:
        cmd: List of command arguments to execute
        on_output: function(line: str) → called for each output line
        on_progress: function(percent: float) → receives mapped percent (0–100 default)
        on_complete: function(exit_code: int)
        on_error: function(msg: str)
        logger: optional logger (DryRunLoggingAdapter supported)
        progress_range: tuple (start_percent, end_percent)
    """
    logger = logger or logging.getLogger(__name__)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        assert proc.stdout
        async for line in proc.stdout:
            decoded = line.decode(errors="ignore").strip()

            if on_output:
                on_output(decoded)
            else:
                logger.info(decoded)

            if on_progress:
                percent = parse_percent_from_output(decoded)
                if percent is not None:
                    start, end = progress_range
                    mapped = start + (percent / 100.0) * (end - start)
                    on_progress(mapped)

        exit_code = await proc.wait()
        if on_complete:
            on_complete(exit_code)
        return exit_code

    except Exception as e:
        msg = f"Subprocess failed: {e}"
        if on_error:
            on_error(msg)
        logger.error(msg)
        return -1


def stream_download(
    url: str,
    dest_path: Path,
    chunk_size: int = 8192,
    on_progress=None,
    logger=None
) -> bool:
    """
    Streams a file download from a URL to disk with optional progress callback.

    Args:
        url: URL to download
        dest_path: Where to save the file
        chunk_size: Number of bytes to read per chunk
        on_progress: function(bytes_read: int, total: int)
        logger: optional logger

    Returns:
        True if download completed successfully, False otherwise
    """
    logger = logger or logging.getLogger(__name__)

    try:
        with urlopen(url) as response, open(dest_path, 'wb') as out_file:
            total_size = int(response.info().get("Content-Length", -1))
            bytes_read = 0

            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                out_file.write(chunk)
                bytes_read += len(chunk)

                if on_progress:
                    on_progress(bytes_read, total_size)
                elif total_size > 0:
                    percent = (bytes_read / total_size) * 100
                    logger.info(f"Downloaded {percent:.1f}%")

        return True

    except Exception as e:
        logger.error(f"Download failed: {e}")
        return False

async def run_subprocess_capture(cmd: list[str], logger=None) -> str:
    """
    Runs a subprocess and returns the captured stdout as a string.
    Designed for non-interactive CLI tools like `nvidia-smi`.
    """
    logger = logger or logging.getLogger(__name__)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await proc.communicate()
        return stdout.decode(errors="ignore")
    except Exception as e:
        logger.error(f"Command failed: {cmd} — {e}")
        return ""

async def make_executable(path: Path, logger=None):
    """
    Ensures a file is marked executable (chmod +x).
    Safe to call cross-platform (no-op on Windows).
    """
    logger = logger or logging.getLogger(__name__)
    if not path.exists():
        logger.warning(f"File not found for chmod: {path}")
        return False

    # Skip chmod on Windows
    if Path(path).suffix.lower() == ".exe" or Path(path).drive:
        logger.info(f"Skipping chmod on Windows: {path}")
        return True

    return await stream_subprocess(["chmod", "+x", str(path)], logger=logger) == 0