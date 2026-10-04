# `/mmf` media processing

This change is limited to `/mmf`. The old path passed every download to
Pillow and wrote a single `memify.webp`, so TGS/WebM could not be decoded,
animation could not survive, and concurrent requests shared an output name.

## Inputs and outputs

| Replied-to input | Output | `TOP;BOTTOM` |
| --- | --- | --- |
| Static WebP sticker, photo, image document | WebP document, as before | Supported |
| Animated TGS sticker | Animated VP9 WebM sticker | Supported on every output frame |
| Video WebM sticker | Animated VP9 WebM sticker | Supported on every output frame |

Sticker metadata (`is_animated`, `is_video`) determines the path first;
sticker MIME/filename and image-document MIME/filename provide fallbacks.
Unrelated video messages and documents are rejected. Static images keep
their original dimensions, with EXIF orientation applied.

Text uses the existing font choice (Arial on Windows, packaged `default.ttf`
otherwise), centered white fill and a black Pillow stroke. Measured wrapping
and font fitting keep top/bottom text inside portrait, landscape and small
frames. Text that cannot fit even at the smallest font receives a concise
error rather than being clipped.

## Runtime requirements

- Existing Pillow and Kurigram requirements are unchanged.
- `rlottie-python==1.3.8` is the only added dependency. Its native rlottie
  renderer reads the Lottie animation locally and supplies RGBA frames.
  Published wheels bundle the renderer on supported Windows/Linux platforms.
  The existing `/tiny` reference to `lottie_convert.py` was not an installed,
  reusable multi-frame rendering pipeline; `/tiny` is unchanged.
- Animated inputs require `ffmpeg` and `ffprobe` on `PATH`, including the
  `libvpx-vp9` decoder/encoder and PNG/overlay filters. Use a current FFmpeg
  supporting `-fps_mode` (tested with 8.0.1). The existing Dockerfile already
  installs FFmpeg; no binary or deployment change is added.

All rendering happens on the bot server. No conversion website or external
API receives media.

Renderer documentation: [rlottie-python](https://rlottie-python.readthedocs.io/en/latest/rlottie_python.html).
Output constraints follow [Telegram's sticker requirements](https://core.telegram.org/stickers):
VP9 WebM, no audio, at most 30 FPS and 3 seconds, one side 512 pixels and the
other at most 512, and at most 256 KiB. Transparency is retained through
RGBA/`yuva420p`; WebM decoding explicitly uses libvpx because FFmpeg's native
VP9 decoder drops the alpha plane.

## Local pipeline

1. Download into a unique `TemporaryDirectory` owned by the request.
2. For TGS, decompress JSON and render the entire timeline through rlottie
   into numbered transparent PNGs. Sample at the source rate capped at
   30 FPS, retaining the original duration. For WebM, ffprobe reads dimensions,
   frame rate and duration; libvpx decodes the original animation.
3. Draw one transparent text PNG using the same layout as static memes.
4. FFmpeg overlays that PNG throughout the animation and encodes WebM.
   Large sources are proportionally reduced; smaller sources receive
   transparent padding to satisfy the 512-pixel requirement without upscaling.
5. Await Kurigram `send_sticker` for animated output, or `send_document` for
   static WebP, before deleting the request directory.

The encoding command is assembled as a subprocess argument list; user text
is drawn into the PNG and never inserted into a shell/filter command.
Representative WebM command (dimensions/rate/duration come from the source):

```text
ffmpeg -hide_banner -loglevel error -nostdin -y -filter_complex_threads 1
  -c:v libvpx-vp9 -i source.webm
  -loop 1 -framerate 24 -i text.png
  -filter_complex "[0:v]fps=24,scale=512:256:flags=lanczos,format=rgba,pad=512:256:0:0:color=black@0[base];[base][1:v]overlay=0:0:shortest=1:format=auto,format=yuva420p[v]"
  -map [v] -an -c:v libvpx-vp9 -pix_fmt yuva420p -auto-alt-ref 0
  -b:v 0 -crf 32 -deadline good -cpu-used 4 -threads 2
  -t 1.0 -fps_mode passthrough memify.webm
```

TGS replaces the first input with
`-framerate <rate> -i frames/frame_%04d.png`.
Oversized output retries CRF 42, 52 and 63 without removing frames or changing
timing. If it still exceeds Telegram's limit, the command reports an error;
it never silently returns a static first frame.

Rendering runs in a worker thread with at most two `/mmf` jobs at once.
Request cancellation waits for that worker before cleanup. Downloads, frames,
overlay and final output are removed on success or failure. Actual exceptions
are logged through the repository logger; users receive concise status errors.

## Validation

```text
python -m unittest discover -s tests -p test_mmf.py -v
python -m unittest discover -s tests -v
```

The focused tests perform real local encoding/decoding, not just file-existence
checks. They cover static WebP/PNG, a moving 60 FPS TGS rendered into 30 frames
over one second, and moving landscape/portrait WebM at 24/12 FPS. They inspect
first, middle and last frames for visible top/bottom white text, black stroke,
movement and alpha, and verify frame counts, dimensions, duration, codec,
absence of audio and output size. Additional checks cover long text, small
sources without upscaling, concurrent requests, upload lifetime, failures,
corrupt TGS and cancellation cleanup.

Telegram network uploads are mocked in these tests; playback should also be
checked on the deployed bot with a real static, animated and video sticker
using `/mmf HELLO` and `/mmf TOP;BOTTOM`.
