#!/usr/bin/env python3
"""
render_scroll_video.py

Render a scrolling, rhyme-colored lyric video from:

  - an audio file (mp3/wav)
  - a JSON alignment file exported from Finetune mode

Each word is colored by its rhyme group and the entire block of text scrolls
upward over time, so rhyme families remain visible across multiple lines
(similar to the YouTube example you showed).

Usage:
  python3 render_scroll_video.py \
    --audio static/uploads/Mos-Def-on-Thieves-in-the-Night-Verse-2_Media_ouW9xezYVCY_001_1080p.mp3 \
    --json alignment.json \
    --out output_scroll.mp4
"""

import argparse
import json
import os

from moviepy.editor import AudioFileClip, ColorClip, CompositeVideoClip, TextClip
from moviepy.config import change_settings

# Point MoviePy to your ImageMagick binary (IM7 via Homebrew).
change_settings({"IMAGEMAGICK_BINARY": "/opt/homebrew/bin/magick"})

# Same palette as in rhyme_core.py
PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
    "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
    "#bcbd22", "#17becf", "#ff6f61", "#6b5b95",
    "#88b04b", "#f7cac9", "#92a8d1", "#955251",
    "#b565a7", "#009b77", "#dd4124", "#45b8ac",
    "#e6b333", "#4a4e4d", "#0e9aa7", "#b3cde0",
]


def group_to_color(group_id):
    """Map a numeric rhyme group id to a hex color (or black if none)."""
    if group_id is None:
        return "black"
    try:
        g = int(group_id)
    except Exception:
        return "black"
    return PALETTE[g % len(PALETTE)]


def load_alignment(json_path: str):
    """Load alignment JSON exported from Finetune mode."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def build_scroll_video(
    audio_path: str,
    alignment: list,
    output_path: str,
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
):
    """
    Build a video where:

      - All lines are visible as colored text.
      - The entire block scrolls upward over time.
      - Vertical speed is tied to line start times (approximate).
    """
    audio = AudioFileClip(audio_path)
    duration = audio.duration

    # Light background similar to YouTube-style
    bg = ColorClip(size=(width, height), color=(245, 245, 245), duration=duration)
    clips = [bg]

    # Extract line start times to set scroll speed
    line_starts = [float(line.get("start", 0.0)) for line in alignment]
    line_starts = [t for t in line_starts if t is not None]
    line_starts.sort()
    if len(line_starts) >= 2:
        gaps = [b - a for a, b in zip(line_starts, line_starts[1:]) if b > a]
        avg_gap = sum(gaps) / len(gaps) if gaps else 2.0
    else:
        avg_gap = 2.0

    line_spacing = 54  # pixels between lines
    scroll_px_per_sec = line_spacing / avg_gap  # pixels per second

    # Vertical anchor: where the "current" line passes through
    anchor_y = int(height * 0.55)

    fontsize = 40

    for line in alignment:
        words = line.get("words", [])
        if not words:
            continue

        line_start = float(line.get("start", 0.0))

        # Build colored line by composing per-word clips
        word_clips = []
        x_offsets = []

        # First pass: measure prefix widths
        for j, w in enumerate(words):
            prefix_text = " ".join(ww["text"] for ww in words[:j])
            if prefix_text:
                prefix_text += " "

            if prefix_text:
                prefix_clip = TextClip(
                    prefix_text,
                    fontsize=fontsize,
                    color="black",
                    method="caption",
                    size=(width - 160, None),
                    align="center",
                )
                prefix_w, _ = prefix_clip.size
            else:
                prefix_w = 0
            x_offsets.append(prefix_w)

        # Second pass: word clips with colors/emphasis
        for (x_off, w) in zip(x_offsets, words):
            color = group_to_color(w.get("group"))
            text = w["text"]
            emph = int(w.get("emphasis", 0))

            stroke_color = None
            stroke_width = 0
            fsize = fontsize
            if emph == 1:
                stroke_color = "black"
                stroke_width = 1
            elif emph == 2:
                stroke_color = "black"
                stroke_width = 2
                fsize = fontsize + 6

            word_clip = TextClip(
                text,
                fontsize=fsize,
                color=color,
                method="caption",
                size=(width - 160, None),
                align="west",  # IM7-safe gravity
                stroke_color=stroke_color,
                stroke_width=stroke_width,
            )
            word_clips.append((word_clip, x_off))

        # Determine full line width to center it
        if word_clips:
            last_clip, last_offset = word_clips[-1]
            last_w, _ = last_clip.size
            line_width = last_offset + last_w
        else:
            line_width = 0

        base_x = (width - line_width) // 2

        # Combine word clips into a single line clip at y=0
        line_elements = []
        max_h = 0
        for clip, x_off in word_clips:
            cw, ch = clip.size
            max_h = max(max_h, ch)
            line_elements.append(clip.set_position((base_x + x_off, 0)))
        if max_h == 0:
            max_h = line_spacing

        line_clip = CompositeVideoClip(line_elements, size=(width, max_h))

        # Position function: scroll upward over time
        def make_pos(s=line_start):
            def pos(t):
                y = anchor_y - (t - s) * scroll_px_per_sec
                return (0, y)
            return pos

        # Visible for the whole duration; we just move it
        line_clip = (
            line_clip.set_start(0)
            .set_end(duration)
            .set_position(make_pos())
        )

        clips.append(line_clip)

    video = CompositeVideoClip(clips).set_audio(audio)
    video = video.set_duration(duration)

    video.write_videofile(
        output_path,
        fps=fps,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile="temp-audio.m4a",
        remove_temp=True,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Render scrolling rhyme-colored lyric video from alignment JSON."
    )
    parser.add_argument(
        "--audio",
        required=True,
        help="Path to audio file (mp3/wav/flac)",
    )
    parser.add_argument(
        "--json",
        required=True,
        help="Path to alignment JSON exported from Finetune mode",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Path to output video file (e.g., output_scroll.mp4)",
    )
    parser.add_argument(
        "--width", type=int, default=1280, help="Video width (default: 1280)"
    )
    parser.add_argument(
        "--height", type=int, default=720, help="Video height (default: 720)"
    )
    parser.add_argument("--fps", type=int, default=30, help="Frames per second")

    args = parser.parse_args()

    if not os.path.exists(args.audio):
        raise FileNotFoundError(f"Audio file not found: {args.audio}")
    if not os.path.exists(args.json):
        raise FileNotFoundError(f"JSON file not found: {args.json}")

    alignment = load_alignment(args.json)
    build_scroll_video(
        audio_path=args.audio,
        alignment=alignment,
        output_path=args.out,
        width=args.width,
        height=args.height,
        fps=args.fps,
    )


if __name__ == "__main__":
    main()
