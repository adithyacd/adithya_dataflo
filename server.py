import asyncio
import json
import os
import threading
import uuid
import traceback

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from transcriber import DeepgramTranscriber
from keyword_monitor import check_keywords
from alert_manager import _format_timestamp

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI()


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "index.html"))


@app.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "video.mp4")[1]
    name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, name)
    with open(path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)
    return {"filename": name, "url": f"/videos/{name}"}


@app.get("/videos/{filename}")
async def serve_video(filename: str):
    path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.isfile(path):
        return HTMLResponse("Not found", status_code=404)
    return FileResponse(path, media_type="video/mp4")


@app.get("/browse")
async def browse_file():
    """Open a native file picker on the server machine and return the selected path."""
    result = {"path": ""}

    def _pick():
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Select video file",
            filetypes=[("Video files", "*.mp4 *.mkv *.avi *.mov *.webm *.flv"), ("All files", "*.*")],
        )
        root.destroy()
        result["path"] = path or ""

    t = threading.Thread(target=_pick)
    t.start()
    t.join()
    return JSONResponse(result)


@app.get("/local-video")
async def serve_local_video(path: str):
    """Serve a local file so the browser <video> element can load it."""
    if not os.path.isfile(path):
        return HTMLResponse("Not found", status_code=404)
    return FileResponse(path)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    source: str | None = None
    keywords: list[str] = []
    pause_event = asyncio.Event()
    task: asyncio.Task | None = None

    async def _send(msg: dict):
        try:
            await ws.send_json(msg)
        except Exception:
            pass

    async def on_transcript(result: dict):
        text = result["text"]
        start_time = result["start"]
        is_final = result["is_final"]

        await _send({
            "type": "transcript",
            "text": text,
            "is_final": is_final,
            "start": start_time,
            "timestamp": _format_timestamp(start_time),
        })

        if is_final:
            for m in check_keywords(text, keywords):
                await _send({
                    "type": "alert",
                    "keyword": m["keyword"],
                    "timestamp": _format_timestamp(start_time),
                    "start": start_time,
                    "context": text,
                    "match_type": m["match_type"],
                })

    async def run_pipeline():
        try:
            transcriber = DeepgramTranscriber(
                source=source,
                on_transcript=on_transcript,
                pause_event=pause_event,
                realtime=False,
            )
            await transcriber.run()
            await _send({"type": "status", "status": "finished"})
        except asyncio.CancelledError:
            pass
        except Exception:
            traceback.print_exc()
            await _send({"type": "status", "status": "error"})

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            action = msg.get("action")

            if action == "init":
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

                source = msg.get("source", "")
                keywords = [k.strip() for k in msg.get("keywords", []) if k.strip()]
                pause_event.clear()
                await _send({"type": "status", "status": "ready"})

            elif action == "start":
                if not source:
                    await _send({"type": "status", "status": "error", "detail": "No source set"})
                    continue
                if task and not task.done():
                    continue
                pause_event.clear()
                task = asyncio.create_task(run_pipeline())
                await _send({"type": "status", "status": "running"})

            elif action == "pause":
                pause_event.set()
                await _send({"type": "status", "status": "paused"})

            elif action == "resume":
                pause_event.clear()
                await _send({"type": "status", "status": "running"})

            elif action == "stop":
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                    task = None
                pause_event.clear()
                await _send({"type": "status", "status": "stopped"})

    except WebSocketDisconnect:
        pass
    finally:
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
