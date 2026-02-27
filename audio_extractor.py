import asyncio
import re
import shutil
import subprocess
from config import SAMPLE_RATE, CHANNELS, CHUNK_SIZE


def _is_youtube_url(source: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", source, re.IGNORECASE))


def _resolve_youtube_url(source: str) -> str:
    """Use yt-dlp to resolve a YouTube Live URL to its actual stream URL."""
    result = subprocess.run(
        ["yt-dlp", "--get-url", "-f", "best", source],
        capture_output=True, text=True, check=True,
    )
    url = result.stdout.strip().splitlines()[0]
    return url


def _detect_source_type(source: str) -> str:
    if source.startswith("rtmp://"):
        return "rtmp"
    if source.endswith(".m3u8") or "m3u8" in source:
        return "hls"
    if source in ("webcam", "0", "/dev/video0"):
        return "webcam"
    if _is_youtube_url(source):
        return "youtube"
    return "file"


def _build_ffmpeg_input_args(source: str) -> list[str]:
    """Build the input portion of the FFmpeg command based on source type."""
    source_type = _detect_source_type(source)

    if source_type == "youtube":
        resolved = _resolve_youtube_url(source)
        return ["-i", resolved]

    if source_type == "webcam":
        if shutil.which("ffmpeg") and __import__("sys").platform == "win32":
            return ["-f", "dshow", "-i", "video=Integrated Camera"]
        return ["-f", "v4l2", "-i", "/dev/video0"]

    # file, rtmp, hls all pass the source directly
    return ["-i", source]


async def start_ffmpeg(source: str) -> asyncio.subprocess.Process:
    """
    Launch FFmpeg as an async subprocess that pipes raw PCM audio to stdout.
    No intermediate file is written.
    """
    input_args = _build_ffmpeg_input_args(source)

    cmd = [
        "ffmpeg",
        *input_args,
        "-f", "s16le",
        "-ar", str(SAMPLE_RATE),
        "-ac", str(CHANNELS),
        "-loglevel", "quiet",
        "pipe:1",
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return process


async def read_audio_chunks(process: asyncio.subprocess.Process, chunk_size: int = CHUNK_SIZE):
    """Async generator that yields fixed-size audio chunks from FFmpeg stdout."""
    while True:
        chunk = await process.stdout.read(chunk_size)
        if not chunk:
            break
        yield chunk
