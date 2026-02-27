import subprocess
import sys
from pathlib import Path

video_path = sys.argv[1]
output_path = Path(video_path).with_suffix(".mp3")

subprocess.run(["ffmpeg", "-i", video_path, "-vn", "-y", str(output_path)], check=True)

print(f"Audio saved to: {output_path}")
