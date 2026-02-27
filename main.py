import argparse
import asyncio
import signal
import sys

from transcriber import DeepgramTranscriber
from keyword_monitor import check_keywords
from alert_manager import print_alert
from config import DEEPGRAM_API_KEY


def parse_args():
    parser = argparse.ArgumentParser(
        description="Real-time video transcription and keyword alert system"
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Video source: local file (mp4), RTMP URL, HLS (.m3u8), YouTube Live URL, or 'webcam'",
    )
    parser.add_argument(
        "--keywords",
        required=True,
        help='Comma-separated keywords to monitor (e.g. "fire,alert,emergency")',
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    if not DEEPGRAM_API_KEY or DEEPGRAM_API_KEY == "your_key_here":
        print("Error: Set a valid DEEPGRAM_API_KEY in your .env file.")
        sys.exit(1)

    keywords = [kw.strip() for kw in args.keywords.split(",") if kw.strip()]
    if not keywords:
        print("Error: Provide at least one keyword.")
        sys.exit(1)

    print(f"[main] Source: {args.source}")
    print(f"[main] Keywords: {keywords}")
    print("[main] Starting transcription... Press Ctrl+C to stop.\n")

    async def on_transcript(result: dict):
        text = result["text"]
        start = result["start"]
        is_final = result["is_final"]
        label = "FINAL" if is_final else "INTERIM"
        print(f"  [{label}] {text}")

        matches = check_keywords(text, keywords)
        for m in matches:
            print_alert(keyword=m["keyword"], timestamp=start, context=text)

    transcriber = DeepgramTranscriber(source=args.source, on_transcript=on_transcript)

    try:
        await transcriber.run()
    except KeyboardInterrupt:
        pass

    print("\n[main] Stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[main] Interrupted.")
