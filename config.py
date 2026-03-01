import os
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")

SAMPLE_RATE = 16000
CHANNELS = 1
ENCODING = "linear16"
CHUNK_SIZE = 8000  # ~250ms of 16kHz 16-bit mono audio

DEEPGRAM_WS_URL = (
    "wss://api.deepgram.com/v1/listen"
    f"?encoding={ENCODING}"
    f"&sample_rate={SAMPLE_RATE}"
    f"&channels={CHANNELS}"
    "&interim_results=true"
    "&punctuate=true"
    "&word_timestamps=true"
    "&endpointing=300"
    "&utterance_end_ms=1500"
    "&model=nova-2"
    "&smart_format=true"
    "&vad_events=true"
)

BATCH_SPEED_FACTOR = 3.0
RECEIVE_TIMEOUT = 30

FUZZY_THRESHOLD = 85

MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_BASE_DELAY = 1  # seconds
