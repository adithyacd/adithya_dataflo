import asyncio
import json
from typing import Callable, Awaitable

import websockets

from config import (
    DEEPGRAM_API_KEY,
    DEEPGRAM_WS_URL,
    CHUNK_SIZE,
    MAX_RECONNECT_ATTEMPTS,
    RECONNECT_BASE_DELAY,
)
from audio_extractor import start_ffmpeg, read_audio_chunks


class DeepgramTranscriber:
    def __init__(self, source: str, on_transcript: Callable[[dict], Awaitable[None]], pause_event: asyncio.Event | None = None, realtime: bool = False):
        self.source = source
        self.on_transcript = on_transcript
        self._pause_event = pause_event
        self._realtime = realtime
        self._ws = None
        self._ffmpeg_process = None

    async def run(self):
        """Connect to Deepgram and stream audio, with auto-reconnect."""
        attempt = 0
        while attempt < MAX_RECONNECT_ATTEMPTS:
            try:
                await self._session()
                break  # clean exit (source ended)
            except (websockets.ConnectionClosed, ConnectionError, OSError) as exc:
                attempt += 1
                if attempt >= MAX_RECONNECT_ATTEMPTS:
                    print(f"[transcriber] Max reconnect attempts reached. Last error: {exc}")
                    raise
                delay = RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
                print(f"[transcriber] Connection lost ({exc}). Reconnecting in {delay}s (attempt {attempt}/{MAX_RECONNECT_ATTEMPTS})...")
                await asyncio.sleep(delay)
            finally:
                await self._cleanup()

    async def _session(self):
        """Single streaming session: start FFmpeg, connect WS, send+receive in parallel."""
        self._ffmpeg_process = await start_ffmpeg(self.source)

        extra_headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
        self._ws = await websockets.connect(
            DEEPGRAM_WS_URL,
            additional_headers=extra_headers,
            ping_interval=20,
            ping_timeout=10,
        )
        print("[transcriber] Connected to Deepgram.")

        await asyncio.gather(
            self._send_audio(),
            self._receive_transcripts(),
        )

    async def _send_audio(self):
        """Read PCM chunks from FFmpeg and forward them as binary WS frames."""
        async for chunk in read_audio_chunks(self._ffmpeg_process, CHUNK_SIZE, self._pause_event, self._realtime):
            await self._ws.send(chunk)

        # Signal end-of-stream so Deepgram flushes remaining audio
        await self._ws.send(b"")
        print("[transcriber] Finished sending audio.")

    async def _receive_transcripts(self):
        """Receive transcript JSON messages and invoke the callback."""
        async for message in self._ws:
            data = json.loads(message)

            # Deepgram sends various message types; we care about Results
            if data.get("type") != "Results":
                continue

            channel = data.get("channel", {})
            alternatives = channel.get("alternatives", [])
            if not alternatives:
                continue

            best = alternatives[0]
            transcript_text = best.get("transcript", "").strip()
            if not transcript_text:
                continue

            is_final = data.get("is_final", False)

            # Extract start timestamp from the first word if available
            words = best.get("words", [])
            start_time = words[0]["start"] if words else data.get("start", 0.0)

            await self.on_transcript({
                "text": transcript_text,
                "is_final": is_final,
                "start": start_time,
                "words": words,
            })

    async def _cleanup(self):
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._ffmpeg_process:
            try:
                self._ffmpeg_process.kill()
                self._ffmpeg_process.wait()
            except Exception:
                pass
            self._ffmpeg_process = None
