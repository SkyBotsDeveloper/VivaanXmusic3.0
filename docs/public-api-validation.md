# Public provider repair and validation

Checked on 5 October 2026 from the local Windows connection. These are backend
checks, not certification of every Telegram command or future public-service uptime.
No bot, database or voice chat was started. Only synthetic inputs were uploaded.

## Changes

| Feature | Active implementation | Validation / limitation |
| --- | --- | --- |
| Text chat aliases | `Harley-ml/SmolLM2_Chat`, native Gradio `/respond`, CPU; 1.7B model with 360M fallback | All ten aliases generated real answers. Both model sizes tested. Responses show the actual SmolLM2 engine; these aliases do not provide proprietary GPT/Claude/Gemini models. |
| `/getdraw` image generation | `Manjushri/SDXL-Turbo-CPU`, native `/genie`; FLUX Schnell secondary | CPU generation returned a valid 512×512 image matching the prompt. FLUX remains quota limited; it is not claimed as a verified available fallback. |
| `/rmbg` | CPU Spaces `schroneko/transparent-background` and `amirgame197/Remove-background`, native `/predict`; existing local fallback | Both providers produced images with a transparent alpha channel. Public output is normalized to PNG. |
| `/upscale` | Existing local enlargement/sharpening | Output dimensions doubled. This is not equivalent to neural super-resolution. No reliable anonymous remote AI upscaler was verified. |
| `/editimg`, `/imgedit`, `/nanoedit` | Local supported edits first; CPU SDXL image-to-image for single-image styles; existing Qwen routes retained with corrected contracts | Grayscale and watercolor edits tested. The CPU queue needed a longer timeout. Arbitrary multi-image edits and face swaps remain provider/queue limited. |
| `/genvid` | Native HF text-video providers and optional previously configured Replicate routes; playable local backup | Text and reference-image requests produced valid four-second H.264 clips. Latest tests used the static-image backup, not AI motion. The caption explicitly says this. An earlier zeroscope job generated actual motion; that does not establish unlimited availability. |
| `/movie` | Wikipedia search/overview plus optional Wikidata metadata | Inception and Sholay returned matching titles, release dates, casts, genres, runtimes and box office. Ratings are `N/A`; no rating is fabricated. |
| `/waifu` | Supported-category discovery from nekos.best; keyless Nekosia maid/default fallback | Maid photo, hug animation and unsupported-tag fallback downloaded and decoded. Unsupported categories use a correctly labeled generic image; they are not restored as exact categories. |
| `/tgm`, `/tgt`, `/telegraph` | Catbox, then TempFile | Both passed upload and full byte-for-byte download checks. Runtime validates the returned link's prefix and available total-size metadata before reporting success. |
| `/ig`, `/insta`, `/fb`, `/facebook`, `/snap`, `/snapchat` | Installed yt-dlp extracts public media first; existing direct/API fallbacks remain | Instagram, Facebook and Snapchat public examples returned actual downloadable video bytes. Referer/User-Agent headers are preserved without forwarding login cookies. Private, deleted and login-required posts remain unavailable without credentials. |
| `/tiktok`, `/tt`, `/x`, `/twitter` | Existing dedicated providers retained | Valid TikTok and X examples returned downloadable media. A removed/non-media fixture cannot establish an API outage. |
| `/q` | Working quote.yuri.ly endpoints and existing local renderer | Live WEBP generation passed; failed bot.lyo.su route removed from the active list. |
| `/cute`, queue detail card | Bundled local media instead of inaccessible Telegra.ph assets | Cute replacement is a four-second clip rendered from the existing couple asset, not the original remote video. Queue uses existing welcome.png. Rich buttons and callbacks remain unchanged. |
| Resso links in play commands | Explicit unavailable-source response | The existing Resso backend already returned `False`. Guarding that result avoids unpacking failure and points to supported song inputs; it does not revive Resso. |

Failed, paid, paused or opaque routes were removed from active selection: old
Elite/Airforce/legacy chat, legacy image generation, Arimagex processing,
Fixart/Vheer/VidForge/Alava video, bot.lyo.su quote, Litterbox/tmpfiles/Uguu upload,
and the TLS-broken Cobalt discovery registry. Useful helper definitions were
retained where practical. Uguu initially worked but later returned a media host
with a mismatched TLS certificate; TLS validation was not disabled.

The new providers use their public SDK/API interfaces without requiring a user
key, login or verification. No Pollinations provider or proxy was added. No
requirements, database, permission, Rich UI builder, callback data or handler
registration was changed.

## Checks and reproduction

Final run: **101/101 offline regression tests and 31/31 live checks passed**.
An additional pinned-SDK run verified the 360M chat fallback. The 31 live checks
include image-processing and static-video fallbacks; this count does not mean
every legacy API, advanced model or Telegram command was certified as working.

Use the repository's declared dependencies, including Kurigram 2.2.26,
gradio_client 2.6.0, rlottie-python 1.3.8 and yt-dlp 2026.7.4.

```powershell
python -m unittest discover -s tests -v
python scripts/check_public_providers.py --output "$env:TEMP\vivaan-public-providers.json"
```

The live checker imports utilities without bot startup or credentials. It checks
real inference, decoded media, upload/download equality, movie title matching,
alpha transparency and FFprobe video validity. `--skip-ai` omits additional remote
inference jobs; it still checks background removal and the reference-image backup.
Run it sparingly: third-party queues and quotas are shared. A passing static video
check reports `Local backup` as its provider and is not a motion-generation check.

Offline tests exercise fallback routing, malformed output rejection, cache-file
ownership, current base64 editor contracts, preview2 dropdown serialization,
actual local image processing and playable backup video. Existing Rich UI,
navigation, animated meme, voice policy, STT contract and autoplay tests also run.
Python syntax and imports were checked, and `git diff --check` passed.

## Remaining limits

Free public services have no guaranteed uptime, quotas or identical output
quality. No verified keyless replacement was found for reliable advanced face
swaps, unrestricted AI video motion or neural super-resolution. These limitations
are preserved honestly rather than represented as successful equivalent output.

Authenticated Telegram, MongoDB, Groq STT, Spotify API, ESSE, configured YouTube
proxy/downloader, Replicate and Heroku checks still need deployment credentials.
Those integrations were not classified as broken and were not replaced. Earlier
checks passed YouTube search/formats/media bytes, SoundCloud extraction, Spotify
public oEmbed, iTunes, lyrics providers, translation, Google speech recognition,
Google TTS and Edge TTS. Backend success does not prove Telegram delivery or live
voice-chat playback from the deployed server.
