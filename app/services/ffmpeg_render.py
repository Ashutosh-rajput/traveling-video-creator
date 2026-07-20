"""Fast ffmpeg-based render engine.

Replaces the MoviePy compile with native ffmpeg assembly:
  1. Each segment's media is pre-rendered to a normalized cut (Ken-Burns on
     images via `zoompan`, scale/crop/trim on videos), all at the target
     resolution / fps / pixel format.
  2. Cuts are concatenated with the concat demuxer (`-c copy`, no re-encode).
  3. Animated captions + titles are emitted as an ASS subtitle file (karaoke-
     style keyword highlight + scale pop, rendered natively by libass) and
     burned in the single final pass.
  4. Voiceover + optional background music (side-chain ducked) + transition SFX
     are mixed with ffmpeg audio filters.

This keeps the animated look while avoiding MoviePy's per-frame Python loop,
which is the main reason renders were slow. `compile_video_ffmpeg` mirrors the
signature of `video.compile_video`; on any failure the caller falls back to it.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from app.core.config import settings
from app.services.video import (
    FPS,
    SILENCE_GAP,
    CAPTION_THEMES,
    _caption_theme_var,
    _ffmpeg_exe,
    _ffmpeg_trim_scale,
    get_height,
    get_width,
)

logger = logging.getLogger(__name__)

# Mirror of the keyword-highlight rules used by the MoviePy caption renderer so
# the ASS captions highlight the same words.
_HIGHLIGHT_KEYWORDS = {
    "amazing", "beautiful", "wonderful", "stunning", "magical", "historical", "ancient",
    "secret", "hidden", "journey", "explore", "discover", "history", "fort", "palace",
    "river", "view", "views", "experience", "adventure", "spot", "spots",
    "must-visit", "popular", "gorgeous", "breathtaking", "vibrant", "paradise", "famous",
    "temple", "beach", "beaches", "monument", "monuments", "royal", "culture", "heritage",
}
_EXCLUDE_CAPS = {
    "I", "A", "The", "In", "On", "At", "To", "Of", "And", "This", "That", "Is", "Are",
    "Was", "Were", "With", "For", "From", "By", "An", "It", "Its",
}


def _run(cmd: list[str], cwd: str | None = None, timeout: int = 300) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=cwd)
        if r.returncode != 0:
            return False, (r.stderr or b"").decode("utf-8", "ignore")[-800:]
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, str(e)


# --------------------------------------------------------------------------- #
# Visual cuts
# --------------------------------------------------------------------------- #

def _kenburns_image(ffmpeg: str, src: Path, out: Path, duration: float, w: int, h: int) -> bool:
    """Ken-Burns (slow zoom) a still image into a target-sized clip via ffmpeg."""
    frames = max(1, round(duration * FPS))
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
        f"scale={w * 2}:{h * 2},"
        f"zoompan=z='min(zoom+0.0015,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={w}x{h}:fps={FPS},"
        f"unsharp=3:3:0.5:3:3:0,setsar=1"
    )
    cmd = [
        ffmpeg, "-y", "-loop", "1", "-i", str(src), "-t", f"{duration:.3f}",
        "-vf", vf, "-r", str(FPS),
        "-c:v", "libx264", "-preset", "fast", "-crf", str(settings.render_crf),
        "-pix_fmt", "yuv420p", "-an",
        str(out),
    ]
    ok, err = _run(cmd, timeout=180)
    if not ok:
        logger.warning("[ffmpeg] Ken-Burns failed for %s: %s", src, err)
    return ok and out.exists() and out.stat().st_size > 0


def _black_cut(ffmpeg: str, out: Path, duration: float, w: int, h: int) -> bool:
    cmd = [
        ffmpeg, "-y", "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={FPS}",
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", str(settings.render_crf), "-pix_fmt", "yuv420p",
        str(out),
    ]
    ok, _ = _run(cmd, timeout=60)
    return ok and out.exists()


def _build_cuts(ffmpeg: str, segments, media_map, cuts_dir: Path, w: int, h: int) -> list[Path]:
    """Render one normalized cut per media item, filling each segment's duration.

    Mirrors _build_segment_clip: videos take the segment if present (split
    evenly), else images (split evenly), else a black fill.
    """
    cuts: list[Path] = []
    for s_idx, seg in enumerate(segments):
        is_intro = seg.attraction_name == "Intro"
        clip_dur = seg.audio_duration if is_intro else SILENCE_GAP + seg.audio_duration
        media = media_map.get(seg.attraction_name, {"images": [], "videos": []})
        vids = media.get("videos", [])
        imgs = media.get("images", [])

        items: list[tuple[Path, bool]] = []
        if vids:
            items = [(Path(v), False) for v in vids]
        elif imgs:
            items = [(Path(i), True) for i in imgs]

        if not items:
            out = cuts_dir / f"cut_{s_idx}_black.mp4"
            if _black_cut(ffmpeg, out, clip_dur, w, h):
                cuts.append(out)
            continue

        per = max(0.4, clip_dur / len(items))
        for m_idx, (path, is_img) in enumerate(items):
            out = cuts_dir / f"cut_{s_idx}_{m_idx}.mp4"
            ok = (
                _kenburns_image(ffmpeg, path, out, per, w, h)
                if is_img
                else _ffmpeg_trim_scale(path, out, per, w, h)
            )
            if ok:
                cuts.append(out)
            else:
                # Keep the timeline intact with a black fill on failure.
                bout = cuts_dir / f"cut_{s_idx}_{m_idx}_black.mp4"
                if _black_cut(ffmpeg, bout, per, w, h):
                    cuts.append(bout)
    return cuts


def _concat_cuts(ffmpeg: str, cuts: list[Path], work_dir: Path, w: int, h: int) -> Path | None:
    if not cuts:
        return None
    list_file = work_dir / "concat.txt"
    list_file.write_text(
        "".join(f"file '{c.resolve().as_posix()}'\n" for c in cuts), encoding="utf-8"
    )
    concat_out = work_dir / "concat.mp4"
    # Try stream copy first (instant); re-encode only if params mismatch.
    ok, err = _run(
        [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(concat_out)],
        timeout=300,
    )
    if not ok:
        logger.warning("[ffmpeg] concat -c copy failed, re-encoding: %s", err)
        ok, err = _run(
            [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
             "-c:v", "libx264", "-preset", "fast", "-crf", str(settings.render_crf),
             "-pix_fmt", "yuv420p", "-r", str(FPS), str(concat_out)],
            timeout=600,
        )
    if not ok:
        logger.error("[ffmpeg] concat failed: %s", err)
        return None
    return concat_out


# --------------------------------------------------------------------------- #
# ASS captions + titles
# --------------------------------------------------------------------------- #

def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _ass_style_color(rgba) -> str:
    r, g, b = rgba[0], rgba[1], rgba[2]
    a = rgba[3] if len(rgba) > 3 else 255
    return f"&H{255 - a:02X}{b:02X}{g:02X}{r:02X}"


def _ass_inline_color(rgb) -> str:
    return f"&H{rgb[2]:02X}{rgb[1]:02X}{rgb[0]:02X}&"


def _is_highlight(word: str) -> bool:
    clean = re.sub(r"[^\w]", "", word)
    if clean.lower() in _HIGHLIGHT_KEYWORDS:
        return True
    return bool(clean) and clean[0].isupper() and clean not in _EXCLUDE_CAPS


def _sanitize(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def _build_ass(segments, city_name: str, transition_style: str, w: int, h: int) -> str:
    theme = CAPTION_THEMES.get(_caption_theme_var.get(), CAPTION_THEMES["Neon Yellow (Default)"])
    base = _ass_inline_color(theme["base_color"])
    highlight = _ass_inline_color(theme["highlight_color"])
    cap_primary = _ass_style_color(theme["base_color"])
    cap_outline = _ass_style_color(theme["stroke_color"])
    cap_shadow = _ass_style_color(theme["shadow_color"])
    outline_w = theme["stroke_width"]
    shadow_d = max(theme["shadow_offset"][0], theme["shadow_offset"][1])
    font = theme["font_family"]
    cap_size = theme["font_size"]

    cap_cx, cap_cy = w // 2, int(h * 0.82)
    show_titles = bool(transition_style) and transition_style.lower() != "none"

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {w}\n"
        f"PlayResY: {h}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Caption,{font},{cap_size},{cap_primary},{cap_primary},{cap_outline},{cap_shadow},"
        f"-1,0,0,0,100,100,0,0,1,{outline_w},{shadow_d},5,40,40,40,1\n"
        f"Style: Title,{font},64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,4,3,5,40,40,40,1\n"
        f"Style: TitleBig,{font},92,&H003CD2FF,&H003CD2FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,5,4,5,40,40,40,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines: list[str] = []
    timeline = 0.0
    for seg in segments:
        is_intro = seg.attraction_name == "Intro"
        narr = seg.audio_duration
        clip_dur = narr if is_intro else SILENCE_GAP + narr
        narr_start = timeline + (0.0 if is_intro else SILENCE_GAP)

        # Captions (chunks of ~6 words, evenly timed across the narration)
        text = re.sub(r"\[.*?\]", "", seg.narration_text).strip()
        words = text.split()
        if words and narr > 0.1:
            spw = narr / len(words)
            for i in range(0, len(words), 6):
                chunk = words[i:i + 6]
                start = narr_start + i * spw
                end = narr_start + min((i + len(chunk)) * spw, narr)
                if end - start <= 0.1:
                    continue
                parts = []
                for word in chunk:
                    sw = _sanitize(word)
                    if _is_highlight(word):
                        parts.append(f"{{\\c{highlight}}}{sw}{{\\c{base}}}")
                    else:
                        parts.append(sw)
                prefix = f"{{\\an5\\pos({cap_cx},{cap_cy})\\fscx112\\fscy112\\t(0,180,\\fscx100\\fscy100)}}"
                lines.append(
                    f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,{prefix}{' '.join(parts)}"
                )

        # Attraction title cards. The intro title is the rich PIL overlay added
        # by the caller via ffmpeg overlay (not ASS), to match the legacy look.
        if not is_intro and show_titles:
            prefix = f"{{\\an5\\pos({w // 2},{h // 2 - 50})\\fad(400,400)}}"
            lines.append(
                f"Dialogue: 1,{_ass_time(timeline)},{_ass_time(timeline + min(3.0, clip_dur))},Title,,0,0,0,,{prefix}{_sanitize(seg.attraction_name)}"
            )

        timeline += clip_dur

    return header + "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Audio
# --------------------------------------------------------------------------- #

def _resolve_media_file(folder: str, stem: str) -> str | None:
    p = Path(folder)
    if not p.exists():
        return None
    for f in p.iterdir():
        if f.stem.lower() == stem.lower() and f.suffix.lower() in (".mp3", ".wav"):
            return str(f)
    return None


def _build_audio(ffmpeg: str, work_dir: Path, voice_path: str, video_dur: float,
                 music_mood: str, music_volume: float, transition_sound: str, segments) -> str:
    """Mix voiceover + optional ducked music + transition SFX. Best-effort:
    returns the plain voiceover path if mixing isn't needed or fails."""
    want_music = bool(music_mood) and music_mood.lower() != "none"
    want_sfx = bool(transition_sound) and transition_sound.lower() != "none"
    if not want_music and not want_sfx:
        return voice_path

    try:
        music_path = _resolve_media_file("data/background_music", music_mood) if want_music else None
        sfx_path = _resolve_media_file("data/transition_sounds", transition_sound) if want_sfx else None

        inputs = ["-i", voice_path]
        idx = 1
        music_idx = None
        if music_path:
            inputs += ["-stream_loop", "-1", "-i", music_path]
            music_idx = idx
            idx += 1

        sfx_inputs: list[tuple[int, float]] = []
        if sfx_path:
            timeline = 0.0
            for i, seg in enumerate(segments):
                is_intro = seg.attraction_name == "Intro"
                clip_dur = seg.audio_duration if is_intro else SILENCE_GAP + seg.audio_duration
                if i > 0 and not is_intro:
                    inputs += ["-i", sfx_path]
                    sfx_inputs.append((idx, timeline))
                    idx += 1
                timeline += clip_dur

        filt = ["[0:a]aformat=sample_rates=44100:channel_layouts=stereo[voice]"]
        mix = []
        if music_idx is not None:
            filt.append("[voice]asplit=2[voicemain][voicekey]")
            filt.append(f"[{music_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={music_volume}[musv]")
            filt.append("[musv][voicekey]sidechaincompress=threshold=0.02:ratio=8:attack=5:release=250[musd]")
            mix = ["[voicemain]", "[musd]"]
        else:
            mix = ["[voice]"]
        for si, t in sfx_inputs:
            ms = int(t * 1000)
            filt.append(f"[{si}:a]aformat=sample_rates=44100:channel_layouts=stereo,adelay={ms}|{ms},volume=0.8[sfx{si}]")
            mix.append(f"[sfx{si}]")
        filt.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0[aout]")

        out = work_dir / "final_audio.m4a"
        cmd = [
            ffmpeg, "-y", *inputs, "-filter_complex", ";".join(filt),
            "-map", "[aout]", "-t", f"{video_dur:.3f}",
            "-c:a", "aac", "-b:a", "160k", str(out),
        ]
        ok, err = _run(cmd, timeout=300)
        if ok and out.exists() and out.stat().st_size > 0:
            return str(out)
        logger.warning("[ffmpeg] audio mix failed, using plain voiceover: %s", err)
    except Exception as e:  # noqa: BLE001
        logger.warning("[ffmpeg] audio mix error, using plain voiceover: %s", e)
    return voice_path


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def compile_video_ffmpeg(
    segments,
    media_map,
    combined_audio_path: str,
    output_path: str,
    city_name: str = "",
    music_mood: str = "none",
    music_volume: float = 0.5,
    transition_style: str = "none",
    transition_sound: str = "none",
) -> str:
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        raise RuntimeError("ffmpeg binary not available")

    w, h = get_width(), get_height()
    work_dir = Path(combined_audio_path).parent
    cuts_dir = work_dir / "cuts"
    cuts_dir.mkdir(parents=True, exist_ok=True)

    if city_name:
        from app.services.video import set_generation_progress
        set_generation_progress(city_name, "rendering", 60, "Rendering video (ffmpeg)...")

    # 1. Visual cuts → concat
    cuts = _build_cuts(ffmpeg, segments, media_map, cuts_dir, w, h)
    concat_out = _concat_cuts(ffmpeg, cuts, work_dir, w, h)
    if not concat_out:
        raise RuntimeError("ffmpeg produced no visual track")

    # 2. Captions + titles (ASS), written into work_dir so the ass filter can
    # reference it by basename (avoids Windows path-escaping issues).
    ass_path = work_dir / "subs.ass"
    ass_path.write_text(_build_ass(segments, city_name, transition_style, w, h), encoding="utf-8")

    # 3. Audio
    video_dur = sum(
        (s.audio_duration if s.attraction_name == "Intro" else SILENCE_GAP + s.audio_duration)
        for s in segments
    )
    audio_path = _build_audio(
        ffmpeg, work_dir, combined_audio_path, video_dur,
        music_mood, music_volume, transition_sound, segments,
    )

    # 4. Final pass: burn captions + (rich PIL) intro title + mux audio.
    if city_name:
        from app.services.video import set_generation_progress
        set_generation_progress(city_name, "rendering", 90, "Burning captions and muxing audio...")

    # Rich intro title overlay (reuses the legacy PIL renderer) faded over the
    # intro segment — restores the original "TOP N PLACES / TO VISIT IN / CITY" look.
    intro_seg = segments[0] if segments and segments[0].attraction_name == "Intro" else None
    intro_png = None
    if intro_seg is not None and city_name:
        try:
            from app.services.video import _render_intro_title_image
            n = sum(1 for s in segments if s.attraction_name != "Intro")
            intro_png = _render_intro_title_image(city_name, n)
            # Show the poster title for the first 3 seconds of the intro (or the
            # whole intro if it is shorter).
            intro_end = min(3.0, float(intro_seg.audio_duration))
        except Exception as e:  # noqa: BLE001
            logger.warning("[ffmpeg] intro title render failed: %s", e)
            intro_png = None

    inputs = ["-i", str(concat_out.resolve()), "-i", str(Path(audio_path).resolve())]
    if intro_png:
        # Loop the still title into a short video stream so the alpha fade can
        # animate. A single-frame image input would collapse to the fade-in's
        # first (transparent) frame and stay invisible.
        title_stream_dur = intro_end + 0.6
        inputs += [
            "-loop", "1", "-framerate", str(FPS), "-t", f"{title_stream_dur:.2f}",
            "-i", str(Path(intro_png).resolve()),
        ]
        fade_out_st = max(0.0, intro_end - 0.5)
        fc = (
            f"[2:v]format=rgba,fade=t=in:st=0:d=0.5:alpha=1,fade=t=out:st={fade_out_st:.2f}:d=0.5:alpha=1[title];"
            f"[0:v][title]overlay=enable='between(t,0,{intro_end:.2f})'[ov];"
            f"[ov]ass=subs.ass[v]"
        )
        video_args = ["-filter_complex", fc, "-map", "[v]"]
    else:
        video_args = ["-vf", "ass=subs.ass", "-map", "0:v"]

    cmd = [
        ffmpeg, "-y", *inputs,
        *video_args, "-map", "1:a", "-shortest",
        "-c:v", "libx264", "-preset", settings.render_preset, "-crf", str(settings.render_crf),
        "-pix_fmt", "yuv420p",
        "-profile:v", "high", "-level", "4.2", "-x264-params", "ref=4:bframes=3",
        "-threads", str(settings.render_threads),
        "-c:a", "aac", "-b:a", settings.render_audio_bitrate, "-ar", "44100", "-movflags", "+faststart",
        str(Path(output_path).resolve()),
    ]
    ok, err = _run(cmd, cwd=str(work_dir), timeout=900)
    if not ok:
        raise RuntimeError(f"ffmpeg final mux failed: {err}")
    return output_path
