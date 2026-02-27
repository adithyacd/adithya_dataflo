def _format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format."""
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def print_alert(keyword: str, timestamp: float, context: str):
    ts = _format_timestamp(timestamp)
    print(f'\U0001f6a8 ALERT | Time: {ts} | Keyword: "{keyword}" | Context: "{context}"')
