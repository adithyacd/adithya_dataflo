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


async def start_ffmpeg(source: str) -> subprocess.Popen:
    """
    Launch FFmpeg as a subprocess that pipes raw PCM audio to stdout.
    Uses subprocess.Popen for Windows compatibility (works with any
    asyncio event loop type, unlike asyncio.create_subprocess_exec
    which requires ProactorEventLoop on Windows).
    """
    input_args = _build_ffmpeg_input_args(source)

    cmd = [
        "ffmpeg",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        *input_args,
        "-f", "s16le",
        "-ar", str(SAMPLE_RATE),
        "-ac", str(CHANNELS),
        "-loglevel", "warning",
        "pipe:1",
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=None,
    )
    return process


async def read_audio_chunks(
    process: subprocess.Popen,
    chunk_size: int = CHUNK_SIZE,
    pause_event: asyncio.Event | None = None,
    realtime: bool = False,
):
    """Async generator that yields fixed-size audio chunks from FFmpeg stdout.

    Reads are offloaded to a thread executor so they don't block the event loop.
    pause_event: when set, reading is suspended until cleared.
    realtime:    when True, paces output to match wall-clock playback speed.
    """
    chunk_duration = chunk_size / (SAMPLE_RATE * 2 * CHANNELS) if realtime else 0
    loop = asyncio.get_running_loop()

    while True:
        if pause_event is not None and pause_event.is_set():
            await asyncio.sleep(0.05)
            continue
        t0 = loop.time()
        chunk = await loop.run_in_executor(None, process.stdout.read, chunk_size)
        if not chunk:
            break
        yield chunk
        if chunk_duration > 0:
            elapsed = loop.time() - t0
            remaining = chunk_duration - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
