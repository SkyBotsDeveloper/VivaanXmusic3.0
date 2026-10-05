# Playback thumbnail assets

Created with the built-in ImageGen tool. `design-reference.png` is the visual
concept; `cinematic-template.png` is the runtime neutral lighting plate. Fonts
are the existing fonts from the user-provided Ruhu reference project.

The renderer keys the template's two green apertures, fills them with actual song
artwork and requester/bot photos, and recolors the neutral plate from the song's
dominant accents using Ruhu's palette algorithm. Bright cores stay near white;
frames, bloom, smoke, halo, icons and waveform all follow the new palette. The
waveform is decorative, and the timeline starts at 00:00. No image-generation
service is called during playback.

Set `USE_NEON_THUMBNAILS = False` in `utils/thumbnails.py` to restore the prior
renderer. New cards have a separate cache namespace.

## Concept prompt

Use case: ui-mockup
Asset type: finished 16:9 Telegram music bot playback thumbnail design reference, flat front view, full bleed 1280x720 proportions.
Input image 1 is ONLY a visual reference for the quality of luminous lighting and the information needed; create a new more polished composition for VivaanXMusic, not a copy.
Primary request: design a gorgeous premium cinematic music playback card, more attractive and refined than the reference, with strong artwork-derived neon edge lighting, rich blurred dark album-colored background, tasteful glints, and crisp legible typography.
Composition: upper left a large album artwork slot with an elegant slightly tilted rounded square bevel frame, luminous fine double rim and soft realistic bloom. Preserve a landscape song image within this slot with tasteful blurred fill rather than losing faces. Upper right a beautiful large circular requester portrait inside orbital luminous rings, small music-note medallion. Leave clear breathing room in the center. Lower third is a wide smoked glass player panel with sculpted rounded corners and a thin flowing illuminated edge, subtle frosted reflection, small microphone icon tile at left, song information center-left, refined waveform at right, a delicate timeline along the bottom.
Text (verbatim): "VivaanXMusic" top right; "NOW PLAYING" small above the player; "Adele | 3B views" small in the panel; "Hello" large bold white title; "Official Video" small rounded badge; "00:00" left and "6:07" right near the timeline.
Lighting: example palette uses cool cyan/turquoise with warmer pale-gold secondary glints; real implementation will recolor lights per artwork. Light should be bright with believable bloom, elegant rather than gaudy. Glass should remain dark so the title is readable even on phone-size previews. A few tiny luminous motes only, no messy space backdrop.
Style: high fidelity shippable music card with a sophisticated cohesive 2D rendered aesthetic, chrome-glass rim with organic flowing accents; exceptional polish and hierarchy. Not a generic flat dashboard with two boxes.
Constraints: exactly one thumbnail, no phone/browser mockup, no extra panels, no random labels, no watermark, no giant play button, no rendered fake buttons. All edges within the canvas. Use the input artist picture as representative album content and an anonymous graceful silhouette avatar if needed. Practical clean shapes reproducible with Pillow and masks.

## Template prompt

Use case: precise-object-edit
Edit target: the supplied generated Vivaan music card. Produce the reusable production template for this EXACT design, preserving all frame geometry, dimensions, realistic light bloom, glass, highlights, flowing light ribbons, microphone icon, music note medallion, waveform, timeline and glints exactly in their current locations.
Change only the variable content:
1. Replace all pixels inside the tilted album artwork frame (including the artist picture) with a perfectly flat opaque pure chroma green RGB(0,255,0) shape filling ONLY the usable inner aperture up to its inner edge. Keep the luminous bevel/rim/glow untouched.
2. Replace all pixels inside the round avatar aperture with the same perfectly flat opaque chroma green RGB(0,255,0), right up to its inner edge. Keep the orbital rings and outside note medallion untouched.
3. Remove ALL text: brand, NOW PLAYING, channel/views, Hello, Official Video badge text and badge background, elapsed/duration labels. Leave those areas empty dark glass/background, so code can put new text there.
4. Make every remaining visible pixel grayscale (neutral white/silver light and charcoal black glass/background). Only the TWO chroma green apertures may retain any color. This is essential so code can recolor the lighting per song. Preserve luminous shading, dramatic realistic soft bloom, reflections, smoke, wave/ribbon softness; do not flatten the lighting.
5. Timeline must be a thin neutral dim track with its bright playhead dot at the FAR LEFT, matching a newly started song at 00:00. No halfway progress.
Important: identical outer composition, 16:9, no extra text or objects. Green areas must be uniform with no faces, texture, gradients, gloss, shadows, light ribbons or antialias colors across their interiors. Maintain the original crisp silhouette boundaries. This is a template asset, not a new redesign.
