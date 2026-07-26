import os
from ..logging import LOGGER

BASE_DIR = os.getcwd()
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
COUPLE_DIR = os.path.join(BASE_DIR, "couples")
CACHE_DIR = os.path.join(BASE_DIR, "cache")


def _cleanup_stale_partial_downloads() -> None:
    removed = 0
    removed_bytes = 0
    try:
        entries = os.listdir(DOWNLOAD_DIR)
    except FileNotFoundError:
        return

    for name in entries:
        if not name.endswith(".downloading"):
            continue
        path = os.path.join(DOWNLOAD_DIR, name)
        if not os.path.isfile(path):
            continue
        try:
            removed_bytes += os.path.getsize(path)
            os.remove(path)
            removed += 1
        except OSError:
            continue

    if removed:
        LOGGER(__name__).info(
            "Removed %s stale partial download files (%s bytes).",
            removed,
            removed_bytes,
        )


def dirr():
    for file in os.listdir():
        if file.lower().endswith((".jpg", ".jpeg", ".png")):
            os.remove(file)

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(COUPLE_DIR, exist_ok=True)
    _cleanup_stale_partial_downloads()

    LOGGER(__name__).info("Directories Updated.")
