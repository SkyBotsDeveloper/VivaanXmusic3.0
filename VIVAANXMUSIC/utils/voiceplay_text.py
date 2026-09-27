from difflib import SequenceMatcher
import re
import unicodedata
from typing import Iterable, Optional


_FILLER_PATTERNS = (
    r"\b(?:hey|hi|hello|ok(?:ay)?|please|pls)\b",
    r"\b(?:can|could|would)\s+you\b",
    r"\b(?:play|put\s+on|queue|search(?:\s+for)?|listen\s+to)\b",
    r"\b(?:the\s+)?(?:next\s+)?(?:song|music|track)\b",
    r"\b(?:for\s+me|for\s+us|now)\b",
    r"\b(?:gaana|gana|ganaa|song|music)\b",
    r"\b(?:bajao|baja\s*do|bajaa\s*do|laga\s*do|lagao|chalao|chala\s*do|suna\s*do)\b",
    r"\b(?:play\s*karo|queue\s*karo)\b",
    r"(?:चलाओ|चला\s*दो|लगाओ|लगा\s*दो|बजाओ|बजा\s*दो|सुना\s*दो|गाना|गीत)",
)


def normalize_transcript(value: str) -> str:
    value = "".join(
        character
        if (
            character.isalnum()
            or character.isspace()
            or character in "_'&+.-"
            or unicodedata.category(character).startswith("M")
        )
        else " "
        for character in str(value or "")
    )
    return re.sub(r"\s+", " ", value).strip()


def song_query_candidates(transcript: str) -> list[str]:
    """Return cleaned and raw search candidates, preserving title words."""
    raw = normalize_transcript(transcript).strip(" .,-")
    if not raw:
        return []

    cleaned = raw
    for pattern in _FILLER_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,-")

    candidates: Iterable[str] = (cleaned, raw)
    result: list[str] = []
    for candidate in candidates:
        if len(candidate) < 2:
            continue
        if candidate.casefold() not in {item.casefold() for item in result}:
            result.append(candidate)
    return result


def rank_transcripts(
    alternatives: Iterable[tuple[str, Optional[float], int, int]],
) -> list[str]:
    """Rank and deduplicate transcripts from one or more recognition locales."""
    ranked: list[tuple[float, int, int, str]] = []
    for transcript, confidence, locale_index, alternative_index in alternatives:
        transcript = str(transcript or "").strip()
        if not transcript:
            continue
        score = (
            float(confidence)
            if confidence is not None
            else max(0.05, 0.25 - (alternative_index * 0.02))
        )
        if locale_index == 0:
            score += 0.02
        ranked.append((score, -locale_index, -alternative_index, transcript))

    result: list[str] = []
    seen: set[str] = set()
    for _, _, _, transcript in sorted(ranked, reverse=True):
        key = transcript.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(transcript)
    return result


def song_title_similarity(left: str, right: str) -> float:
    """Compare search-result titles while ignoring common video-label noise."""
    noise = {
        "audio",
        "full",
        "latest",
        "lyrics",
        "lyrical",
        "official",
        "song",
        "video",
    }

    def variants(value: str) -> list[str]:
        value = unicodedata.normalize("NFKC", str(value or "")).casefold()
        pieces = re.split(r"\s*(?:\||-|–|—|\(|\[)\s*", value)
        result = []
        for piece in [value, *pieces]:
            words = re.findall(r"[\w]+", piece, flags=re.UNICODE)
            cleaned = " ".join(word for word in words if word not in noise).strip()
            if cleaned and cleaned not in result:
                result.append(cleaned)
        return result

    left_variants = variants(left)
    right_variants = variants(right)
    if not left_variants or not right_variants:
        return 0.0
    return max(
        SequenceMatcher(None, left_item, right_item).ratio()
        for left_item in left_variants
        for right_item in right_variants
    )
