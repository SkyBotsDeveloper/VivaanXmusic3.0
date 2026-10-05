"""Keyless SFW anime providers with supported-category discovery."""

import threading
import time

import requests


HEADERS = {"User-Agent": "VivaanXMusicBot/1.0 (https://github.com/SkyBotsDeveloper/VivaanXmusic3.0)"}
NEKOS_API = "https://nekos.best/api/v2"
NEKOSIA_API = "https://api.nekosia.cat/api/v1/images"
_categories = {"waifu": "png", "neko": "png"}
_categories_expire = 0
_categories_lock = threading.Lock()


def _supported_categories():
    global _categories, _categories_expire
    with _categories_lock:
        if time.monotonic() >= _categories_expire:
            try:
                response = requests.get(f"{NEKOS_API}/endpoints", headers=HEADERS, timeout=10)
                response.raise_for_status()
                payload = response.json()
                categories = {tag: info["format"] for tag, info in payload.items()
                              if isinstance(info, dict) and info.get("format") in {"png", "jpg", "gif"}}
                if categories:
                    _categories = categories
                    _categories_expire = time.monotonic() + 3600
                else:
                    _categories_expire = time.monotonic() + 60
            except (requests.RequestException, ValueError, AttributeError):
                _categories_expire = time.monotonic() + 60
        return dict(_categories)


def get_waifu_data(tag):
    requested_tag = (tag or "waifu").strip().lower() or "waifu"
    categories = _supported_categories()
    # Nekosia supplies the maid category used by /waifu without arguments.
    if requested_tag == "maid":
        image = _nekosia_image("maid")
        if image:
            return image
    for category in dict.fromkeys((requested_tag, "waifu")):
        if category not in categories:
            continue
        try:
            response = requests.get(f"{NEKOS_API}/{category}", headers=HEADERS, timeout=10)
            response.raise_for_status()
            results = response.json().get("results") or []
            if results and str(results[0].get("url", "")).startswith("https://"):
                return {"images": [{"url": results[0]["url"], "tag": category,
                                    "format": categories[category]}], "source": "nekos.best"}
        except (requests.RequestException, ValueError, AttributeError):
            continue
    return _nekosia_image("random")


def _nekosia_image(category):
    try:
        response = requests.get(f"{NEKOSIA_API}/{category}", params={"rating": "safe"},
                                headers=HEADERS, timeout=10)
        response.raise_for_status()
        payload = response.json()
        image = payload.get("image", {}).get("original", {})
        if payload.get("success") and payload.get("rating") == "safe" and str(image.get("url", "")).startswith("https://"):
            return {"images": [{"url": image["url"], "tag": payload.get("category", "waifu"),
                                "format": image.get("extension", "png")}], "source": "nekosia.cat"}
    except (requests.RequestException, ValueError, AttributeError):
        pass
    return None
