import re
import unicodedata
from typing import Iterable


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
