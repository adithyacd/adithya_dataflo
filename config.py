import os
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")

SAMPLE_RATE = 16000
CHANNELS = 1
ENCODING = "linear16"
CHUNK_SIZE = 4000  # ~125ms of 16kHz 16-bit mono audio

DEEPGRAM_WS_URL = (
    "wss://api.deepgram.com/v1/listen"
    f"?encoding={ENCODING}"
    f"&sample_rate={SAMPLE_RATE}"
    f"&channels={CHANNELS}"
    "&interim_results=true"
    "&punctuate=true"
    "&word_timestamps=true"
)

FUZZY_THRESHOLD = 85

MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_BASE_DELAY = 1  # seconds
