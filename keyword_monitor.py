from rapidfuzz import fuzz
from config import FUZZY_THRESHOLD


def check_keywords(
    transcript: str,
    keywords: list[str],
    threshold: int = FUZZY_THRESHOLD,
) -> list[dict]:
    """
    Check a transcript string against a list of keywords.
    Returns a list of matches with keyword, match type, and score.
    Exact matches take priority; a keyword matched exactly won't also appear as fuzzy.
    """
    results = []
    transcript_lower = transcript.lower()
    exact_matched = set()

    for kw in keywords:
        if kw.lower() in transcript_lower:
            results.append({"keyword": kw, "match_type": "exact", "score": 100})
            exact_matched.add(kw.lower())

    for kw in keywords:
        if kw.lower() in exact_matched:
            continue
        score = fuzz.partial_ratio(kw.lower(), transcript_lower)
        if score >= threshold:
            results.append({"keyword": kw, "match_type": "fuzzy", "score": score})

    return results
