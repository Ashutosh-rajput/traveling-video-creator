"""Video generation service.

Parses attraction-tagged scripts, generates per-segment TTS audio,
downloads media assets, and compiles a travel guide video using MoviePy.
"""

import io
import os
import re
import struct
import tempfile
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
)
from PIL import Image

from app.services.tts import generate_tts

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
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


def generate_segment_audios(segments: list[ScriptSegment]) -> bytes:
    """Generate TTS for each segment, store audio_bytes & duration,
    and return the combined WAV audio (with silence gaps)."""

    for seg in segments:
        seg.audio_bytes = generate_tts(seg.narration_text)
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

    for seg in segments:
        name = seg.attraction_name
        seg_dir = work_dir / _safe_dirname(name)
        seg_dir.mkdir(parents=True, exist_ok=True)
        media_map[name] = {"images": [], "videos": []}

        # Find matching pics
        matching_pics = [p for p in pics if _label_matches(p.get("label", ""), name)]
        for i, p in enumerate(matching_pics[:4]):  # Limit to 4 images per attraction
            ext = _url_ext(p["url"], "jpg")
            dest = seg_dir / f"img_{i}.{ext}"
            download_tasks.append((p["url"], dest, name, "images"))

        # Find matching videos
        matching_vids = [v for v in videos if _label_matches(v.get("label", ""), name)]
        for i, v in enumerate(matching_vids[:2]):  # Limit to 2 videos per attraction
            ext = _url_ext(v["url"], "mp4")
            dest = seg_dir / f"vid_{i}.{ext}"
            download_tasks.append((v["url"], dest, name, "videos"))

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
    return label.lower().strip() == attraction_name.lower().strip()


def _url_ext(url: str, default: str = "jpg") -> str:
    path = url.split("?")[0].split("#")[0]
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else default
    return ext if ext in ("jpg", "jpeg", "png", "webp", "mp4", "webm", "mov") else default


# ---------------------------------------------------------------------------
# 4. Video Compilation
# ---------------------------------------------------------------------------

def _image_to_clip(image_path: Path, duration: float) -> ImageClip:
    """Create an ImageClip from an image file, resized to target resolution."""
    img = Image.open(image_path).convert("RGB")
    img = img.resize((VIDEO_WIDTH, VIDEO_HEIGHT), Image.LANCZOS)
    # Save to temp file for moviepy
    temp_path = image_path.parent / f"{image_path.stem}_resized.jpg"
    img.save(temp_path, quality=90)
    clip = ImageClip(str(temp_path)).with_duration(duration)
    return clip


def _video_to_clip(video_path: Path, duration: float) -> VideoFileClip:
    """Load a video clip, resize and trim/loop to target duration."""
    try:
        clip = VideoFileClip(str(video_path))
        clip = clip.resized((VIDEO_WIDTH, VIDEO_HEIGHT))

        if clip.duration >= duration:
            clip = clip.subclipped(0, duration)
        else:
            # Loop the clip to fill duration
            repeats = int(duration / clip.duration) + 1
            from moviepy import concatenate_videoclips as concat
            clip = concat([clip] * repeats).subclipped(0, duration)

        return clip
    except Exception:
        # Fallback: create a black frame
        return ImageClip(
            _create_black_frame(), duration=duration
        )


def _create_black_frame() -> str:
    """Create a temporary black frame image and return its path."""
    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), (20, 20, 30))
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    img.save(tmp.name, quality=90)
    return tmp.name


def compile_video(
    segments: list[ScriptSegment],
    media_map: dict[str, dict],
    combined_audio_path: str,
    output_path: str,
) -> str:
    """Compile the final travel guide video.

    For each segment, creates visual clips matching the segment's audio
    duration, then concatenates everything with crossfades and overlays
    the combined voiceover audio.

    Returns the output file path.
    """
    segment_clips = []

    for seg in segments:
        duration = seg.audio_duration + SILENCE_GAP  # include the gap
        if seg is segments[-1]:
            duration = seg.audio_duration  # no gap after last segment

        media = media_map.get(seg.attraction_name, {"images": [], "videos": []})
        clip = _build_segment_clip(media, duration)
        segment_clips.append(clip)

    if not segment_clips:
        raise ValueError("No video segments could be created.")

    # Concatenate with crossfade transitions
    if len(segment_clips) > 1:
        final_video = concatenate_videoclips(
            segment_clips,
            method="compose",
        )
    else:
        final_video = segment_clips[0]

    # Overlay the combined voiceover audio
    voiceover = AudioFileClip(combined_audio_path)
    final_video = final_video.with_audio(voiceover)

    # Write the output
    final_video.write_videofile(
        output_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        logger=None,
    )

    # Cleanup
    final_video.close()
    voiceover.close()
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

    Returns:
        Raw bytes of the compiled MP4 video.
    """
    # Create working directory
    work_dir = Path(tempfile.mkdtemp(prefix="travel_video_"))
    output_dir = Path("data/output_videos")
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Step 1: Parse script
        segments = parse_script_segments(script)
        if not segments:
            raise ValueError("No attraction segments found in the script. Ensure the script contains [attraction: ...] markers.")

        # Step 2: Generate TTS audio for each segment
        combined_audio = generate_segment_audios(segments)
        audio_path = str(work_dir / "voiceover.wav")
        Path(audio_path).write_bytes(combined_audio)

        # Step 3: Download media
        media_map = download_media_for_segments(segments, pics, videos, work_dir)

        # Step 4: Compile video
        output_path = str(output_dir / "travel_guide.mp4")
        compile_video(segments, media_map, audio_path, output_path)

        # Step 5: Return video bytes
        return Path(output_path).read_bytes()

    finally:
        # Cleanup temp dir (keep output)
        import shutil
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass
