import asyncio
import json
import subprocess
from typing import Callable, Awaitable

import websockets

from config import (
    DEEPGRAM_API_KEY,
    DEEPGRAM_WS_URL,
    CHUNK_SIZE,
    BATCH_SPEED_FACTOR,
    RECEIVE_TIMEOUT,
    MAX_RECONNECT_ATTEMPTS,
    RECONNECT_BASE_DELAY,
)
from audio_extractor import start_ffmpeg, read_audio_chunks

KEEPALIVE_MSG = json.dumps({"type": "KeepAlive"})
CLOSE_STREAM_MSG = json.dumps({"type": "CloseStream"})


def _ws_is_open(ws) -> bool:
    try:
        return ws is not None and ws.state.name == "OPEN"
    except Exception:
        return False


class DeepgramTranscriber:
    def __init__(
        self,
        source: str,
        on_transcript: Callable[[dict], Awaitable[None]],
        pause_event: asyncio.Event | None = None,
        speed_factor: float = BATCH_SPEED_FACTOR,
    ):
        self.source = source
        self.on_transcript = on_transcript
        self._pause_event = pause_event
        self._speed_factor = speed_factor
        self._ws = None
        self._ffmpeg_process: subprocess.Popen | None = None
        self._audio_done = asyncio.Event()

    async def run(self):
        """Start FFmpeg once, then stream to Deepgram with auto-reconnect on WS drops."""
        self._ffmpeg_process = await start_ffmpeg(self.source)
        try:
            await self._stream_with_reconnect()
        finally:
            await self._kill_ffmpeg()

    async def _stream_with_reconnect(self):
        attempt = 0
        while attempt < MAX_RECONNECT_ATTEMPTS:
            try:
                await self._connect_deepgram()
                self._audio_done.clear()
                await asyncio.gather(
                    self._send_audio(),
                    self._receive_transcripts(),
                    self._keepalive_loop(),
                )
                return
            except (websockets.ConnectionClosed, ConnectionError, OSError) as exc:
                attempt += 1
                await self._close_ws()
                if self._ffmpeg_process and self._ffmpeg_process.poll() is not None:
                    print("[transcriber] FFmpeg finished and connection lost — not reconnecting.")
                    return
                if attempt >= MAX_RECONNECT_ATTEMPTS:
                    print(f"[transcriber] Max reconnect attempts reached. Last error: {exc}")
                    raise
                delay = RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
                print(f"[transcriber] Connection lost ({exc}). Reconnecting in {delay}s (attempt {attempt}/{MAX_RECONNECT_ATTEMPTS})...")
                await asyncio.sleep(delay)

    async def _connect_deepgram(self):
        extra_headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
        self._ws = await websockets.connect(
            DEEPGRAM_WS_URL,
            additional_headers=extra_headers,
            ping_interval=20,
            ping_timeout=60,
            close_timeout=10,
        )
        print("[transcriber] Connected to Deepgram.")

    async def _send_audio(self):
        """Read PCM chunks from FFmpeg and forward them as binary WS frames."""
        chunks_sent = 0
        try:
            async for chunk in read_audio_chunks(
                self._ffmpeg_process,
                CHUNK_SIZE,
                self._pause_event,
                speed_factor=self._speed_factor,
            ):
                if _ws_is_open(self._ws):
                    await self._ws.send(chunk)
                    chunks_sent += 1
                else:
                    print("[transcriber] WS closed while sending audio.")
                    break
        except (websockets.ConnectionClosed, ConnectionError):
            raise
        except Exception as e:
            print(f"[transcriber] Send error: {e}")

        self._audio_done.set()
        print(f"[transcriber] Finished sending audio ({chunks_sent} chunks). Sending CloseStream.")

        if _ws_is_open(self._ws):
            try:
                await self._ws.send(CLOSE_STREAM_MSG)
            except Exception:
                pass

    async def _receive_transcripts(self):
        """Receive transcript JSON messages and invoke the callback."""
        last_result_time = asyncio.get_event_loop().time()

        try:
            async for message in self._ws:
                data = json.loads(message)
                msg_type = data.get("type", "")

                if msg_type == "Results":
                    last_result_time = asyncio.get_event_loop().time()

                    channel = data.get("channel", {})
                    alternatives = channel.get("alternatives", [])
                    if not alternatives:
                        continue

                    best = alternatives[0]
                    transcript_text = best.get("transcript", "").strip()
                    if not transcript_text:
                        continue

                    is_final = data.get("is_final", False)
                    words = best.get("words", [])
                    start_time = words[0]["start"] if words else data.get("start", 0.0)

                    await self.on_transcript({
                        "text": transcript_text,
                        "is_final": is_final,
                        "start": start_time,
                        "words": words,
                    })

                elif msg_type == "Metadata" and self._audio_done.is_set():
                    print("[transcriber] Received final Metadata after CloseStream.")
                    break

                if self._audio_done.is_set():
                    idle = asyncio.get_event_loop().time() - last_result_time
                    if idle > RECEIVE_TIMEOUT:
                        print(f"[transcriber] No results for {RECEIVE_TIMEOUT}s after audio done — finishing.")
                        break

        except websockets.ConnectionClosed:
            if not self._audio_done.is_set():
                raise
        print("[transcriber] Finished receiving transcripts.")

    async def _keepalive_loop(self):
        """Send KeepAlive messages so Deepgram doesn't time out the connection."""
        while not self._audio_done.is_set():
            await asyncio.sleep(5)
            if self._pause_event and self._pause_event.is_set() and _ws_is_open(self._ws):
                try:
                    await self._ws.send(KEEPALIVE_MSG)
                except Exception:
                    break

    async def _close_ws(self):
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def _kill_ffmpeg(self):
        if self._ffmpeg_process:
            loop = asyncio.get_running_loop()
            try:
                self._ffmpeg_process.terminate()
                try:
                    await asyncio.wait_for(
                        loop.run_in_executor(None, self._ffmpeg_process.wait),
                        timeout=3.0
                    )
                except asyncio.TimeoutError:
                    self._ffmpeg_process.kill()
            except Exception:
                pass
            self._ffmpeg_process = None