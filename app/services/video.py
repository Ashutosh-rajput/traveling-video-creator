"""Video generation service.

Parses attraction-tagged scripts, generates per-segment TTS audio,
downloads media assets, and compiles a travel guide video using MoviePy.
"""

import contextvars
import io
import os
import re
import struct
import tempfile
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import numpy as np
from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
)
from moviepy.video.fx import CrossFadeIn
from PIL import Image, ImageDraw, ImageFont

from app.services.tts import generate_tts

_FONT_PATHS_BOLD = [
    ("C:/Windows/Fonts/seguibl.ttf", 0),  # Segoe UI Black (Super premium bold look)
    ("C:/Windows/Fonts/segoeuib.ttf", 0), # Segoe UI Bold
    ("C:/Windows/Fonts/Nirmala.ttc", 1),  # Nirmala UI Bold
    ("C:/Windows/Fonts/trebucbd.ttf", 0), # Trebuchet MS Bold
    ("C:/Windows/Fonts/ariblk.ttf", 0),   # Arial Black
    ("C:/Windows/Fonts/arialbd.ttf", 0),  # Arial Bold
    ("C:/Windows/Fonts/arial.ttf", 0),
]
_FONT_PATHS_REGULAR = [
    ("C:/Windows/Fonts/segoeui.ttf", 0),
    ("C:/Windows/Fonts/Nirmala.ttc", 0),  # Nirmala UI Regular
    ("C:/Windows/Fonts/arial.ttf", 0),
]


def _get_font_paths(text: str, bold: bool = True) -> list[tuple[str, int]]:
    """Get the appropriate font path chain depending on whether the text has Indic/non-ASCII characters."""
    if any(ord(c) > 127 for c in text):
        return [("C:/Windows/Fonts/Nirmala.ttc", 1 if bold else 0)] + (_FONT_PATHS_BOLD if bold else _FONT_PATHS_REGULAR)
    return _FONT_PATHS_BOLD if bold else _FONT_PATHS_REGULAR


def _draw_highlighted_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    cx: int,
    cy: int,
    base_color=(255, 255, 255, 255),
    highlight_color=(255, 210, 60, 255),
    stroke_width=4,
    stroke_fill=(0, 0, 0, 255)
):
    """Draw text word-by-word centered at (cx, cy) with key travel terms highlighted in bright yellow."""
    words = text.split()
    if not words:
        return
        
    # Keywords to highlight (case-insensitive)
    highlight_keywords = {
        "amazing", "beautiful", "wonderful", "stunning", "magical", "historical", "ancient",
        "secret", "hidden", "journey", "explore", "discover", "history", "fort", "palace",
        "river", "view", "views", "experience", "experience,", "adventure", "spot", "spots",
        "must-visit", "popular", "gorgeous", "breathtaking", "vibrant", "paradise", "famous",
        "temple", "beach", "beaches", "monument", "monuments", "royal", "culture", "heritage"
    }

    # Auto-highlight capitalized proper nouns (attractions/cities)
    exclude_caps = {"I", "A", "The", "In", "On", "At", "To", "Of", "And", "This", "That", "Is", "Are", "Was", "Were", "With", "For", "From", "By", "An", "It", "Its"}

    space_width = draw.textbbox((0, 0), " ", font=font)[2]
    
    word_data = []
    total_width = 0
    for w in words:
        clean_word = re.sub(r"[^\w]", "", w)
        is_highlight = False
        if clean_word.lower() in highlight_keywords:
            is_highlight = True
        elif clean_word and clean_word[0].isupper() and clean_word not in exclude_caps:
            is_highlight = True
            
        bbox = draw.textbbox((0, 0), w, font=font)
        ww = bbox[2] - bbox[0]
        wh = bbox[3] - bbox[1]
        
        word_data.append({
            "text": w,
            "width": ww,
            "height": wh,
            "highlight": is_highlight
        })
        total_width += ww
        
    total_width += space_width * (len(words) - 1)
    
    start_x = cx - total_width // 2
    
    for wd in word_data:
        w_text = wd["text"]
        w_width = wd["width"]
        w_height = wd["height"]
        
        fill_color = highlight_color if wd["highlight"] else base_color
        ty = cy - w_height // 2
        
        # 1. Draw outer black drop-shadow for heavy legibility over any bright background
        draw.text((start_x + 3, ty + 3), w_text, font=font, fill=(0, 0, 0, 200), stroke_width=stroke_width, stroke_fill=(0, 0, 0, 200))
        # 2. Draw outline stroke + inner filled text
        draw.text((start_x, ty), w_text, font=font, fill=fill_color, stroke_width=stroke_width, stroke_fill=stroke_fill)
        
        start_x += w_width + space_width


def _load_font(paths: list[tuple[str, int]], size: int) -> ImageFont.FreeTypeFont:
    """Try each font path and index in order; fall back to PIL default."""
    for p, idx in paths:
        try:
            return ImageFont.truetype(p, size, index=idx)
        except Exception:
            continue
    return ImageFont.load_default()

# ---------------------------------------------------------------------------
# import contextvars

# Thread-safe context variables for dynamic video resolution
_video_width_var = contextvars.ContextVar("video_width", default=1920)
_video_height_var = contextvars.ContextVar("video_height", default=1080)

def get_width() -> int:
    return _video_width_var.get()

def get_height() -> int:
    return _video_height_var.get()

FPS = 24
CROSSFADE_DURATION = 0.8  # seconds of cross-dissolve between segments
SILENCE_GAP = 0.6  # seconds of silence between attraction segments
MAX_DOWNLOAD_WORKERS = 6
DOWNLOAD_TIMEOUT = 30  # seconds per file


# ---------------------------------------------------------------------------
# 1. Script Parsing
# ---------------------------------------------------------------------------

class ScriptSegment:
    """One attraction's narration block."""

    def __init__(self, attraction_name: str, narration_text: str):
        self.attraction_name = attraction_name
        self.narration_text = narration_text
        self.audio_bytes: bytes | None = None
        self.audio_duration: float = 0.0

    def __repr__(self) -> str:
        return f"ScriptSegment({self.attraction_name!r}, words={len(self.narration_text.split())})"


_ATTRACTION_TAG_RE = re.compile(
    r"\[attraction:\s*(.+?)\]",
    re.IGNORECASE,
)


def parse_script_segments(script: str) -> list[ScriptSegment]:
    """Split a tagged script into ScriptSegment objects.

    Expected format:
        [attraction: Lalbagh Botanical Garden]
        We start our morning at the stunning Lalbagh...
        [attraction: Bangalore Palace]
        Now, let us step into royalty...
    """
    parts = _ATTRACTION_TAG_RE.split(script)
    # parts alternates: [before_first_tag, name1, text1, name2, text2, ...]
    segments: list[ScriptSegment] = []

    # If there is text before the first tag, treat it as an "Intro" segment
    preamble = parts[0].strip()
    if preamble:
        segments.append(ScriptSegment("Intro", preamble))

    # Walk pairs: (name, text)
    for i in range(1, len(parts), 2):
        name = parts[i].strip()
        text = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if text:
            segments.append(ScriptSegment(name, text))

    return segments


# ---------------------------------------------------------------------------
# 2. TTS Audio Generation (per segment)
# ---------------------------------------------------------------------------

def _wav_duration(raw_wav: bytes) -> float:
    """Return duration in seconds of a WAV byte string."""
    try:
        buf = io.BytesIO(raw_wav)
        with wave.open(buf, "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate == 0:
                return 0.0
            return frames / rate
    except Exception:
        # Fallback: try to compute from raw size assuming 16-bit mono
        header_size = 44
        data_size = len(raw_wav) - header_size
        if data_size <= 0:
            return 0.0
        # Assume 24 kHz, 16-bit, mono
        return data_size / (24000 * 2)


def generate_segment_audios(
    segments: list[ScriptSegment],
    speaker: str | None = None,
    language_code: str | None = None,
) -> bytes:
    """Generate TTS for each segment, store audio_bytes & duration,
    and return the combined WAV audio (with silence gaps)."""

    for seg in segments:
        seg.audio_bytes = generate_tts(
            seg.narration_text,
            speaker=speaker,
            language_code=language_code,
        )
        seg.audio_duration = _wav_duration(seg.audio_bytes)

    # Combine all WAV segments into one continuous WAV with silence gaps
    return _combine_wavs(segments)


def _combine_wavs(segments: list[ScriptSegment]) -> bytes:
    """Concatenate WAV segments with silence gaps into a single WAV file."""
    if not segments:
        return b""

    # Read first WAV to get params
    first_buf = io.BytesIO(segments[0].audio_bytes)
    with wave.open(first_buf, "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()

    silence_frames = int(framerate * SILENCE_GAP)
    silence_bytes = b"\x00" * (silence_frames * n_channels * sampwidth)

    all_frames = bytearray()
    cumulative_time = 0.0
    for idx, seg in enumerate(segments):
        buf = io.BytesIO(seg.audio_bytes)
        with wave.open(buf, "rb") as wf:
            raw = wf.readframes(wf.getnframes())
        # Update segment start time
        seg._start_time = cumulative_time
        all_frames.extend(raw)
        cumulative_time += seg.audio_duration

        # Add silence gap between segments (not after the last one)
        if idx < len(segments) - 1:
            all_frames.extend(silence_bytes)
            cumulative_time += SILENCE_GAP

    # Write combined WAV
    output = io.BytesIO()
    with wave.open(output, "wb") as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(framerate)
        wf.writeframes(bytes(all_frames))

    return output.getvalue()


# ---------------------------------------------------------------------------
# 3. Media Downloading
# ---------------------------------------------------------------------------

def _download_file(url: str, dest: Path) -> bool:
    """Download a file from URL to local path. Returns True on success."""
    try:
        with httpx.Client(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
        return True
    except Exception:
        return False


def download_media_for_segments(
    segments: list[ScriptSegment],
    pics: list[dict],
    videos: list[dict],
    work_dir: Path,
) -> dict[str, dict]:
    """Download media grouped by attraction name.

    Returns:
        {
            "Lalbagh Botanical Garden": {
                "images": [Path(...), ...],
                "videos": [Path(...), ...],
            },
            ...
        }
    """
    media_map: dict[str, dict] = {}
    download_tasks: list[tuple] = []

    # Set of attraction names in this script (excluding Intro)
    attraction_names = {seg.attraction_name.lower().strip() for seg in segments if seg.attraction_name != "Intro"}

    import logging
    logger = logging.getLogger(__name__)

    for seg in segments:
        name = seg.attraction_name
        seg_dir = work_dir / _safe_dirname(name)
        seg_dir.mkdir(parents=True, exist_ok=True)
        media_map[name] = {"images": [], "videos": []}

        if name == "Intro":
            # Try to find general city media (labels that are not in other attractions)
            matching_pics = [p for p in pics if p.get("label", "").lower().strip() not in attraction_names]
            matching_vids = [v for v in videos if v.get("label", "").lower().strip() not in attraction_names]

            if matching_pics or matching_vids:
                logger.info(f"[Video Gen] Found distinct city media for 'Intro' segment ({len(matching_vids)} videos, {len(matching_pics)} images).")
            # If no general media found, fallback to first attraction's media
            if not matching_pics and not matching_vids and len(segments) > 1:
                first_attraction = segments[1].attraction_name
                logger.info(f"[Video Gen] No distinct city media found for 'Intro'. Falling back to first attraction media: '{first_attraction}'.")
                matching_pics = [p for p in pics if _label_matches(p.get("label", ""), first_attraction)]
                matching_vids = [v for v in videos if _label_matches(v.get("label", ""), first_attraction)]
        else:
            matching_pics = [p for p in pics if _label_matches(p.get("label", ""), name)]
            matching_vids = [v for v in videos if _label_matches(v.get("label", ""), name)]

        logger.info(f"[Video Gen] Queueing downloads for segment '{name}': {len(matching_vids[:2])} videos, {len(matching_pics[:4])} images.")

        # Limit and download
        for i, p in enumerate(matching_pics[:4]):  # Limit to 4 images per attraction
            ext = _url_ext(p["url"], "jpg")
            dest = seg_dir / f"img_{i}.{ext}"
            download_tasks.append((p["url"], dest, name, "images"))

        for i, v in enumerate(matching_vids[:2]):  # Limit to 2 videos per attraction
            ext = _url_ext(v["url"], "mp4")
            dest = seg_dir / f"vid_{i}.{ext}"
            download_tasks.append((v["url"], dest, name, "videos"))

    logger.info(f"[Video Gen] Downloading {len(download_tasks)} media assets concurrently...")

    # Download concurrently
    with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as pool:
        futures = {}
        for url, dest, name, media_type in download_tasks:
            fut = pool.submit(_download_file, url, dest)
            futures[fut] = (dest, name, media_type)

        for fut in as_completed(futures):
            dest, name, media_type = futures[fut]
            if fut.result():
                media_map[name][media_type].append(dest)

    return media_map


def _safe_dirname(name: str) -> str:
    return re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "_")[:50]


def _label_matches(label: str, attraction_name: str) -> bool:
    label = label.lower().strip()
    name = attraction_name.lower().strip()
    # Exact match, or one contains the other (handles shortened/extended names)
    return label == name or name in label or label in name


def _url_ext(url: str, default: str = "jpg") -> str:
    path = url.split("?")[0].split("#")[0]
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else default
    return ext if ext in ("jpg", "jpeg", "png", "webp", "mp4", "webm", "mov") else default


# ---------------------------------------------------------------------------
# 4. Video Compilation
# ---------------------------------------------------------------------------

def _image_to_clip(image_path: Path, duration: float) -> ImageClip:
    """Create an ImageClip from an image file, center-cropped and resized to target resolution."""
    img = Image.open(image_path).convert("RGB")
    
    # Target resolution
    target_w = get_width()
    target_h = get_height()
    
    # Aspect fill calculation
    src_w, src_h = img.size
    src_aspect = src_w / src_h
    tgt_aspect = target_w / target_h

    if src_aspect > tgt_aspect:
        # Source is wider than target. Scale based on height.
        new_h = target_h
        new_w = int(target_h * src_aspect)
        img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = (new_w - target_w) // 2
        right = left + target_w
        img_cropped = img_resized.crop((left, 0, right, target_h))
    else:
        # Source is taller than target. Scale based on width.
        new_w = target_w
        new_h = int(target_w / src_aspect)
        img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        top = (new_h - target_h) // 2
        bottom = top + target_h
        img_cropped = img_resized.crop((0, top, target_w, bottom))

    # Save to temp file for moviepy
    temp_path = image_path.parent / f"{image_path.stem}_resized.jpg"
    img_cropped.save(temp_path, quality=90)
    clip = ImageClip(str(temp_path)).with_duration(duration)
    return clip


def _video_to_clip(video_path: Path, duration: float) -> VideoFileClip:
    """Load a video clip, resize with center crop and trim/loop to target duration."""
    try:
        clip = VideoFileClip(str(video_path))
        
        target_w = get_width()
        target_h = get_height()
        src_w, src_h = clip.w, clip.h
        
        # Scale to cover target dimensions
        scale = max(target_w / src_w, target_h / src_h)
        new_w = int(src_w * scale)
        new_h = int(src_h * scale)
        
        # Ensure dimensions are even (required by some encoders)
        if new_w % 2 != 0: new_w += 1
        if new_h % 2 != 0: new_h += 1
        
        # Resize
        clip = clip.resized((new_w, new_h))
        
        # Center crop using Crop effect
        x_center = new_w // 2
        y_center = new_h // 2
        from moviepy.video.fx import Crop
        clip = clip.with_effects([Crop(x_center=x_center, y_center=y_center, width=target_w, height=target_h)])

        if clip.duration >= duration:
            clip = clip.subclipped(0, duration)
        else:
            # Loop the clip to fill duration
            repeats = int(duration / clip.duration) + 1
            from moviepy import concatenate_videoclips as concat
            clip = concat([clip] * repeats).subclipped(0, duration)

        return clip
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[Video Gen] Video clip conversion failed: {e}")
        # Fallback: create a black frame
        return ImageClip(
            _create_black_frame(), duration=duration
        )


def _create_black_frame() -> str:
    """Create a temporary black frame image and return its path."""
    img = Image.new("RGB", (get_width(), get_height()), (20, 20, 30))
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    img.save(tmp.name, quality=90)
    return tmp.name


def _create_title_overlay_clip(city_name: str, num_attractions: int, duration: float) -> ImageClip:
    """Create a styled title text overlay for the intro segment.

    Renders 3 lines like:
        TOP 5 PLACES
        TO VISIT IN
        GOA
    on a semi-transparent dark gradient bar, using PIL.
    Returns a MoviePy ImageClip (RGBA) sized to VIDEO_WIDTH x VIDEO_HEIGHT.
    """
    overlay = Image.new("RGBA", (get_width(), get_height()), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    city_upper = city_name.upper()
    line1 = f"TOP {num_attractions} PLACES"
    line2 = "TO VISIT IN"
    line3 = city_upper

    bar_right = get_width() * 2 // 3  # cover left 2/3 of screen
    max_text_width = bar_right - 120  # max boundary

    # Load initial fonts using dynamic Indic language detection
    font_paths = _get_font_paths(city_name, bold=True)
    font_big = _load_font(font_paths, 160)
    font_mid = _load_font(font_paths, 110)
    font_city = _load_font(font_paths, 200)

    # Dynamic scaling for Line 1
    w1 = draw.textbbox((0, 0), line1, font=font_big)[2]
    if w1 > max_text_width:
        font_big = _load_font(font_paths, int(160 * (max_text_width / w1)))

    # Dynamic scaling for Line 2
    w2 = draw.textbbox((0, 0), line2, font=font_mid)[2]
    if w2 > max_text_width:
        font_mid = _load_font(font_paths, int(110 * (max_text_width / w2)))

    # Dynamic scaling for Line 3 (City name)
    w3 = draw.textbbox((0, 0), line3, font=font_city)[2]
    if w3 > max_text_width:
        new_size = int(200 * (max_text_width / w3))
        font_city = _load_font(font_paths, max(new_size, 50))

    pad = 60
    # Measure heights with final fonts
    h1 = draw.textbbox((0, 0), line1, font=font_big)[3]
    h2 = draw.textbbox((0, 0), line2, font=font_mid)[3]
    h3 = draw.textbbox((0, 0), line3, font=font_city)[3]
    total_text_h = h1 + h2 + h3 + pad * 3

    bar_top    = get_height() // 2 - total_text_h // 2 - pad
    bar_bottom = get_height() // 2 + total_text_h // 2 + pad
    bar_left   = 0

    # Draw semi-transparent dark gradient bar
    for x in range(bar_left, bar_right):
        alpha = int(210 * (1 - (x / bar_right) ** 2))
        draw.rectangle([(x, bar_top), (x + 1, bar_bottom)], fill=(0, 0, 0, alpha))

    # Draw each line centred on the bar's left portion
    cx = bar_right // 2
    y = bar_top + pad

    # Line 1 — white
    w1 = draw.textbbox((0, 0), line1, font=font_big)[2]
    draw.text((cx - w1 // 2, y), line1, font=font_big, fill=(255, 255, 255, 240))
    y += h1 + pad // 2

    # Line 2 — light grey
    w2 = draw.textbbox((0, 0), line2, font=font_mid)[2]
    draw.text((cx - w2 // 2, y), line2, font=font_mid, fill=(210, 210, 210, 220))
    y += h2 + pad // 2

    # Line 3 — golden accent
    w3 = draw.textbbox((0, 0), line3, font=font_city)[2]
    # Drop shadow
    draw.text((cx - w3 // 2 + 4, y + 4), line3, font=font_city, fill=(80, 50, 0, 180))
    draw.text((cx - w3 // 2, y), line3, font=font_city, fill=(255, 210, 60, 255))

    # Convert RGBA PIL image → numpy array → ImageClip
    arr = np.array(overlay)
    clip = ImageClip(arr, is_mask=False).with_duration(duration)
    return clip


def _render_subtitle_image(text: str) -> str:
    """Render a subtitle line onto a transparent canvas and save as temporary PNG."""
    overlay = Image.new("RGBA", (get_width(), get_height()), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    # Modern Segoe UI bold size 52 with dynamic Indic language detection
    font_paths = _get_font_paths(text, bold=True)
    font = _load_font(font_paths, 52)
    
    # Measure text size and scale down if too wide
    max_sub_width = get_width() - 100  # 50px margin on each side
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    if tw > max_sub_width:
        font = _load_font(font_paths, int(52 * (max_sub_width / tw)))
    
    # Position centered horizontally, 82% height vertically
    cx = get_width() // 2
    cy = int(get_height() * 0.82)
    
    # Draw subtitle word-by-word with stroke and shadow highlighting keywords
    _draw_highlighted_text(draw, text, font, cx, cy)
    
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    overlay.save(tmp.name)
    return tmp.name


def _create_subtitle_clips(text: str, audio_duration: float) -> list:
    """Split segment text into short phrases and create animated timed caption clips."""
    # Pre-clean tags if any
    text = re.sub(r"\[.*?\]", "", text).strip()
    words = text.split()
    if not words or audio_duration <= 0.1:
        return []

    num_words = len(words)
    seconds_per_word = audio_duration / num_words

    # Group words into chunks of ~6 words
    chunks = []
    chunk_size = 6
    for i in range(0, num_words, chunk_size):
        chunk_words = words[i:i + chunk_size]
        chunk_text = " ".join(chunk_words)
        
        start_t = i * seconds_per_word
        end_t = min((i + len(chunk_words)) * seconds_per_word, audio_duration)
        chunks.append((chunk_text, start_t, end_t))

    subtitle_clips = []
    for chunk_text, start_t, end_t in chunks:
        clip_dur = end_t - start_t
        if clip_dur <= 0.1:
            continue
        try:
            img_path = _render_subtitle_image(chunk_text)
            # Timed caption clip with premium zoom pop-in transition in MoviePy v2
            sub_clip = (ImageClip(img_path)
                        .with_start(start_t)
                        .with_duration(clip_dur)
                        .resized(lambda t: 1.0 + 0.12 * np.exp(-18 * t)))
            subtitle_clips.append(sub_clip)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"[Video Gen] Failed to render subtitle chunk '{chunk_text}': {e}")
            
    return subtitle_clips


def ensure_transition_sounds():
    """Ensure that the data/transition_sounds directory and default sounds exist."""
    import os
    import numpy as np
    import wave
    from pathlib import Path
    import logging
    
    sound_dir = Path("data/transition_sounds")
    sound_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate whoosh.wav
    whoosh_path = sound_dir / "whoosh.wav"
    if not whoosh_path.exists():
        try:
            duration = 1.5
            sample_rate = 44100
            t = np.linspace(0, duration, int(sample_rate * duration))
            
            # White noise
            noise = np.random.normal(0, 0.15, len(t))
            # Resonant sweep frequency from 150Hz to 1200Hz to 150Hz
            freq = 150 + 1050 * np.sin(np.pi * t / duration)
            phase = 2 * np.pi * np.cumsum(freq) / sample_rate
            sweep = np.sin(phase) * 0.15
            
            # Gaussian envelope
            envelope = np.exp(-((t - duration/2) / (duration/4.5))**2)
            audio = (noise + sweep) * envelope
            audio = np.clip(audio, -1.0, 1.0)
            audio_ints = (audio * 32767).astype(np.int16)
            
            with wave.open(str(whoosh_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(audio_ints.tobytes())
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to generate whoosh.wav: {e}")

    # Generate click.wav (Camera snap)
    click_path = sound_dir / "click.wav"
    if not click_path.exists():
        try:
            duration = 0.25
            sample_rate = 44100
            t = np.linspace(0, duration, int(sample_rate * duration))
            
            noise = np.random.normal(0, 0.25, len(t)) * np.exp(-t * 50)
            click = np.sin(2 * np.pi * 1800 * t) * 0.3 * np.exp(-t * 120)
            release = np.random.normal(0, 0.15, len(t)) * np.exp(-np.maximum(0, t - 0.08) * 60)
            
            audio = noise + click + release
            audio = np.clip(audio, -1.0, 1.0)
            audio_ints = (audio * 32767).astype(np.int16)
            
            with wave.open(str(click_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(audio_ints.tobytes())
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to generate click.wav: {e}")

    # Generate glitch.wav (Sci-fi buzz)
    glitch_path = sound_dir / "glitch.wav"
    if not glitch_path.exists():
        try:
            duration = 0.8
            sample_rate = 44100
            t = np.linspace(0, duration, int(sample_rate * duration))
            
            audio = np.zeros_like(t)
            num_steps = 12
            step_len = len(t) // num_steps
            for i in range(num_steps):
                start = i * step_len
                end = min((i + 1) * step_len, len(t))
                f = np.random.choice([100, 300, 800, 2000, 4000])
                mode = np.random.choice(["sq", "ns", "sn"])
                vol = np.random.choice([0.0, 0.1, 0.2, 0.35])
                sub_t = t[start:end]
                if mode == "sq":
                    audio[start:end] = np.sign(np.sin(2 * np.pi * f * sub_t)) * vol
                elif mode == "ns":
                    audio[start:end] = np.random.normal(0, vol * 0.7, end - start)
                else:
                    audio[start:end] = np.sin(2 * np.pi * f * sub_t) * vol
            
            audio = np.clip(audio, -1.0, 1.0)
            audio_ints = (audio * 32767).astype(np.int16)
            
            with wave.open(str(glitch_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(audio_ints.tobytes())
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to generate glitch.wav: {e}")


def _render_attraction_title_image(name: str) -> str:
    from PIL import Image, ImageDraw
    import tempfile
    
    w = get_width()
    h = get_height()
    
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    # Choose font size depending on text length and Indic language detection
    font_paths = _get_font_paths(name, bold=True)
    font_size = 64
    font = _load_font(font_paths, font_size)
    
    # Scale down if too wide
    max_text_w = w - 160
    bbox = draw.textbbox((0, 0), name, font=font)
    tw = bbox[2] - bbox[0]
    if tw > max_text_w:
        font = _load_font(font_paths, int(font_size * (max_text_w / tw)))
        bbox = draw.textbbox((0, 0), name, font=font)
        tw = bbox[2] - bbox[0]
        
    th = bbox[3] - bbox[1]
    
    # Center text horizontally, and place it slightly above center
    cx = w // 2
    cy = h // 2 - 50
    
    # Draw a premium semi-transparent black background strip behind the title for better contrast
    strip_h = th + 40
    draw.rectangle([(0, cy - strip_h // 2), (w, cy + strip_h // 2)], fill=(0, 0, 0, 110))
    
    # Draw outline/stroke + main text
    draw.text((cx - tw // 2 + 3, cy - th // 2 + 3), name, font=font, fill=(0, 0, 0, 200))
    draw.text((cx - tw // 2, cy - th // 2), name, font=font, fill=(255, 255, 255, 255))
    
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    overlay.save(tmp.name)
    return tmp.name


def compile_video(
    segments: list[ScriptSegment],
    media_map: dict[str, dict],
    combined_audio_path: str,
    output_path: str,
    city_name: str = "",
    music_mood: str = "none",
    music_volume: float = 0.5,
    transition_style: str = "none",
    transition_sound: str = "none",
) -> str:
    """Compile the final travel guide video.

    For each segment, creates visual clips matching the segment's audio
    duration (plus gap if applicable), then concatenates everything and
    overlays the combined voiceover audio, dynamic transitions, and background music.
    """
    import os
    import numpy as np
    from moviepy.video.fx import FadeIn, FadeOut
    
    ensure_transition_sounds()
    
    segment_clips = []
    num_attractions = sum(1 for s in segments if s.attraction_name != "Intro")

    # Record voiceover play intervals for audio ducking
    voiceover_intervals = []

    for idx, seg in enumerate(segments):
        is_intro = (seg.attraction_name == "Intro")
        narr_dur = seg.audio_duration
        
        # Voiceover plays from current timeline position to end of narration text audio
        voiceover_intervals.append((seg._start_time, seg._start_time + narr_dur))
        
        # Determine visual clip duration
        if is_intro:
            clip_dur = narr_dur
        else:
            clip_dur = SILENCE_GAP + narr_dur
            
        # Build main attraction clip
        media = media_map.get(seg.attraction_name, {"images": [], "videos": []})
        clip = _build_segment_clip(media, clip_dur)

        # Generate and composite subtitle caption clips on top of this segment
        sub_clips = _create_subtitle_clips(seg.narration_text, narr_dur)
        if sub_clips:
            # Shift subtitle start times by SILENCE_GAP for non-intro clips
            shift = 0.0 if is_intro else SILENCE_GAP
            shifted_subs = []
            for sub in sub_clips:
                shifted_subs.append(sub.with_start(sub.start + shift))
            try:
                clip = CompositeVideoClip([clip] + shifted_subs)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"[Video Gen] Subtitle overlay failed for '{seg.attraction_name}': {e}")

        # Title overlay for Intro vs Attraction segments
        if is_intro:
            if city_name:
                try:
                    title = _create_title_overlay_clip(city_name, num_attractions, narr_dur)
                    clip = CompositeVideoClip([clip, title])
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"[Video Gen] Title overlay failed: {e}")
        else:
            # Render and overlay the attraction name intro animation directly on the media clip
            if transition_style and transition_style.lower() != "none":
                try:
                    title_img = _render_attraction_title_image(seg.attraction_name)
                    title_dur = min(3.0, clip_dur)
                    
                    title_clip = ImageClip(title_img).with_start(0).with_duration(title_dur)
                    
                    if transition_style.lower() == "fade":
                        title_clip = title_clip.with_effects([FadeIn(duration=0.5), FadeOut(duration=0.5)])
                    elif transition_style.lower() == "zoom":
                        title_clip = title_clip.resized(lambda t: 1.0 + 0.05 * t)
                        title_clip = title_clip.with_effects([FadeIn(duration=0.5), FadeOut(duration=0.5)])
                    elif transition_style.lower() == "slide":
                        w_val = get_width()
                        def slide_pos(t):
                            if t < 0.4:
                                x = -w_val * (1.0 - (t / 0.4))
                            elif t > (title_dur - 0.4):
                                x = w_val * ((t - (title_dur - 0.4)) / 0.4)
                            else:
                                x = 0.0
                            return (x, 'center')
                        title_clip = title_clip.with_position(slide_pos)
                        title_clip = title_clip.with_effects([FadeIn(duration=0.2), FadeOut(duration=0.2)])
                        
                    clip = CompositeVideoClip([clip, title_clip])
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).error(f"[Video Gen] Attraction title overlay creation failed: {e}")

        segment_clips.append(clip)

    if not segment_clips:
        raise ValueError("No video segments could be created.")

    # Concatenate clips
    if len(segment_clips) > 1:
        final_video = concatenate_videoclips(
            segment_clips,
            method="compose",
        )
    else:
        final_video = segment_clips[0]

    # Overlay the combined voiceover audio
    voiceover = AudioFileClip(combined_audio_path)
    
    # Process transition sound effects
    sfx_clips = []
    if transition_sound and transition_sound.lower() != "none":
        sfx_path = f"data/transition_sounds/{transition_sound.lower()}.wav"
        if os.path.exists(sfx_path):
            try:
                for idx, seg in enumerate(segments):
                    if idx == 0:
                        continue # No transition before Intro
                    # Gap starts at the beginning of the segment visual clip
                    gap_start = seg._start_time - SILENCE_GAP
                    sfx_clip = AudioFileClip(sfx_path).with_start(gap_start)
                    sfx_clips.append(sfx_clip)
                import logging
                logging.getLogger(__name__).info(f"[Video Gen] Created {len(sfx_clips)} transition sound overlays ('{transition_sound}').")
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"[Video Gen] Failed to load transition sound overlays: {e}")

    # Process background music if selected
    bg_music = None
    mixed_audio = None
    if music_mood and music_mood.lower() != "none":
        music_file = None
        for ext in [".mp3", ".wav"]:
            test_path = f"data/background_music/{music_mood.lower()}{ext}"
            if os.path.exists(test_path):
                music_file = test_path
                break
        if music_file and os.path.exists(music_file):
            try:
                bg_clip = AudioFileClip(music_file)
                from moviepy.audio.fx import AudioLoop
                bg_music = bg_clip.with_effects([AudioLoop(duration=final_video.duration)])
                
                def ducking_filter(gf, t):
                    if isinstance(t, np.ndarray):
                        factors = np.ones(t.shape) * music_volume
                        for start, end in voiceover_intervals:
                            in_interval = (t >= start) & (t <= end)
                            factors[in_interval] = 0.25 * music_volume
                        frames = gf(t)
                        if len(frames.shape) > 1:
                            return factors[:, np.newaxis] * frames
                        return factors * frames
                    else:
                        factor = music_volume
                        for start, end in voiceover_intervals:
                            if start <= t <= end:
                                factor = 0.25 * music_volume
                                break
                        return factor * gf(t)
                
                bg_music = bg_music.transform(ducking_filter)
                
                audio_elements = [voiceover]
                if bg_music:
                    audio_elements.append(bg_music)
                audio_elements.extend(sfx_clips)
                
                mixed_audio = CompositeAudioClip(audio_elements)
                final_video = final_video.with_audio(mixed_audio)
                import logging
                logging.getLogger(__name__).info(f"[Video Gen] Dynamic background music '{music_mood}' layered.")
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"[Video Gen] Failed to overlay background music: {e}")
                fallback_audio = CompositeAudioClip([voiceover] + sfx_clips)
                final_video = final_video.with_audio(fallback_audio)
        else:
            import logging
            logging.getLogger(__name__).warning(f"[Video Gen] Background music track not found: {music_file}")
            fallback_audio = CompositeAudioClip([voiceover] + sfx_clips)
            final_video = final_video.with_audio(fallback_audio)
    else:
        fallback_audio = CompositeAudioClip([voiceover] + sfx_clips)
        final_video = final_video.with_audio(fallback_audio)

    # Write the output
    final_video.write_videofile(
        output_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        threads=8,
        preset="ultrafast",
        logger=None,
        ffmpeg_params=["-pix_fmt", "yuv420p"]
    )

    # Cleanup to prevent file locks
    final_video.close()
    voiceover.close()
    if bg_music:
        bg_music.close()
    if mixed_audio:
        mixed_audio.close()
    for sfx_c in sfx_clips:
        sfx_c.close()
    for clip in segment_clips:
        clip.close()

    return output_path


def _build_segment_clip(media: dict, duration: float):
    """Build a visual clip for one attraction segment from its media."""
    video_paths = media.get("videos", [])
    image_paths = media.get("images", [])

    sub_clips = []
    remaining = duration

    # Use video clips first
    for vpath in video_paths:
        if remaining <= 0:
            break
        try:
            clip = _video_to_clip(vpath, min(remaining, duration / max(len(video_paths), 1)))
            sub_clips.append(clip)
            remaining -= clip.duration
        except Exception:
            continue

    # Fill remaining time with images
    if remaining > 0 and image_paths:
        per_image = remaining / len(image_paths)
        for ipath in image_paths:
            if remaining <= 0:
                break
            try:
                clip = _image_to_clip(ipath, min(per_image, remaining))
                sub_clips.append(clip)
                remaining -= clip.duration
            except Exception:
                continue

    # Fallback: black frame
    if not sub_clips or remaining > 0.5:
        black = ImageClip(_create_black_frame()).with_duration(max(remaining, duration))
        sub_clips.append(black)

    return concatenate_videoclips(sub_clips, method="compose")


# ---------------------------------------------------------------------------
# 5. Main Entry Point
# ---------------------------------------------------------------------------

def generate_travel_video(
    script: str,
    pics: list[dict],
    videos: list[dict],
    city_name: str = "",
    aspect_ratio: str = "horizontal",
    speaker: str | None = None,
    language_code: str | None = None,
    music_mood: str = "none",
    music_volume: float = 0.5,
    transition_style: str = "none",
    transition_sound: str = "none",
) -> bytes:
    """End-to-end travel guide video generation.

    1. Parse script into attraction segments
    2. Generate TTS audio for each segment
    3. Download matching media assets
    4. Compile and render the final video
    5. Return the video bytes

    Args:
        script: The video_script with [attraction: ...] markers.
        pics: List of {"url": ..., "label": ...} photo assets.
        videos: List of {"url": ..., "label": ...} video assets.
        city_name: The destination city name for the title overlay.
        aspect_ratio: "horizontal" (16:9) or "portrait" (9:16).
        speaker: Optional custom speaker override name.
        language_code: Optional custom target language code.
        music_mood: Background music mood selection.

    Returns:
        Raw bytes of the compiled MP4 video.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Set dynamic resolution in context variables (thread-safe)
    if aspect_ratio.lower() == "portrait":
        logger.info("[Video Gen] Configuring portrait resolution (1080x1920)")
        w_token = _video_width_var.set(1080)
        h_token = _video_height_var.set(1920)
    else:
        logger.info("[Video Gen] Configuring horizontal resolution (1920x1080)")
        w_token = _video_width_var.set(1920)
        h_token = _video_height_var.set(1080)

    # Auto-detect city name from general media labels if not provided
    if not city_name:
        attraction_names = set()
        # Try to find a label that looks like a city (not matching any specific attraction)
        for asset in list(pics) + list(videos):
            label = asset.get("label", "").strip()
            if label:
                attraction_names.add(label)
        # The city label is often the shortest / most general label
        if attraction_names:
            city_name = min(attraction_names, key=len)
        logger.info(f"[Video Gen] Auto-detected city name: '{city_name}'")

    # Create working directory
    work_dir = Path(tempfile.mkdtemp(prefix="travel_video_"))
    output_dir = Path("data/output_videos")
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Step 1: Parse script
        logger.info("[Video Gen] Step 1/5 — Parsing script segments...")
        segments = parse_script_segments(script)
        if not segments:
            raise ValueError("No attraction segments found in the script. Ensure the script contains [attraction: ...] markers.")
        seg_names = [s.attraction_name for s in segments]
        logger.info(f"[Video Gen] Found {len(segments)} segments: {seg_names}")

        # Step 2: Generate TTS audio for each segment
        logger.info(f"[Video Gen] Step 2/5 — Generating TTS audio for {len(segments)} segments (speaker={speaker}, lang={language_code})...")
        combined_audio = generate_segment_audios(segments, speaker=speaker, language_code=language_code)
        total_dur = sum(s.audio_duration for s in segments)
        audio_path = str(work_dir / "voiceover.wav")
        Path(audio_path).write_bytes(combined_audio)
        logger.info(f"[Video Gen] TTS done. Total voiceover duration: {total_dur:.1f}s")

        # Step 3: Download media
        logger.info(f"[Video Gen] Step 3/5 — Downloading media assets for {len(segments)} segments...")
        media_map = download_media_for_segments(segments, pics, videos, work_dir)
        for seg_name, assets in media_map.items():
            logger.info(f"[Video Gen]   '{seg_name}': {len(assets['videos'])} videos, {len(assets['images'])} images downloaded.")

        # Step 4: Compile video
        output_path = str(output_dir / "travel_guide.mp4")
        logger.info(f"[Video Gen] Step 4/5 — Compiling video timeline with MoviePy (preset=ultrafast, aspect_ratio={aspect_ratio}, title='{city_name}', music_mood='{music_mood}', music_volume={music_volume}, transition_style='{transition_style}', transition_sound='{transition_sound}')...")
        compile_video(
            segments, 
            media_map, 
            audio_path, 
            output_path, 
            city_name=city_name, 
            music_mood=music_mood, 
            music_volume=music_volume,
            transition_style=transition_style,
            transition_sound=transition_sound
        )

        # Step 5: Return video bytes
        size_mb = Path(output_path).stat().st_size / (1024 * 1024)
        logger.info(f"[Video Gen] Step 5/5 — Done! Output: '{output_path}' ({size_mb:.1f} MB). Returning video bytes.")
        return Path(output_path).read_bytes()

    finally:
        # Reset context variables
        _video_width_var.reset(w_token)
        _video_height_var.reset(h_token)
        # Cleanup temp dir (keep output)
        import shutil
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass
