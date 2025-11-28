#!/usr/bin/env python3
"""
render_video.py

Render a karaoke-style lyric video from:

  - an audio file (mp3/wav)
  - a JSON alignment file exported from Finetune mode

The result shows:
  - A single line centered near the top.
  - Each word in that line highlighted (colored) as it is spoken,
    using rhyme groups and emphasis from the JSON.

Usage:
  python3 render_video.py \
    --audio static/uploads/Mos-Def-on-Thieves-in-the-Night-Verse-2_Media_ouW9xezYVCY_001_1080p.mp3 \
    --json alignment.json \
    --out output_colored.mp4
"""

import argparse
import json
import os

from moviepy.editor import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    TextClip,
)
from moviepy.config import change_settings

# IMPORTANT: point MoviePy to your ImageMagick binary (IM7 via Homebrew).
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
    """Map a numeric rhyme group id to a hex color (or white if none)."""
    if group_id is None:
        return "white"
    try:
        g = int(group_id)
    except Exception:
        return "white"
    return PALETTE[g % len(PALETTE)]


def load_alignment(json_path: str):
    """Load alignment JSON exported from Finetune mode."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def build_video(
    audio_path: str,
    alignment: list,
    output_path: str,
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
):
    """Build and write the lyric video using MoviePy."""
    audio = AudioFileClip(audio_path)
    duration = audio.duration

    # Background
    bg = ColorClip(size=(width, height), color=(0, 0, 0), duration=duration)
    clips = [bg]

    y_line = int(height * 0.35)  # vertical position for the bar
    epsilon = 0.03               # min gap between words to avoid overlap
    base_fontsize = 42

    for line in alignment:
        words = line.get("words", [])
        if not words:
            continue

        # Reconstruct full line text
        line_text = " ".join(w["text"] for w in words)
        line_start = float(line.get("start", 0.0))
        line_end = float(line.get("end", line_start))
        if line_end <= line_start:
            line_end = line_start + 0.2

        # Base white line, visible for the whole bar
        base_line_clip = TextClip(
            line_text,
            fontsize=base_fontsize,
            color="white",
            method="caption",
            size=(width - 160, None),
            align="center",
        )
        line_w, line_h = base_line_clip.size
        base_x = (width - line_w) // 2
        base_line_clip = base_line_clip.set_position((base_x, y_line)).set_start(
            line_start
        ).set_end(line_end)
        clips.append(base_line_clip)

        # For each word, create a colored overlay at its approximate position
        for j, w in enumerate(words):
            w_start = float(w.get("start", 0.0))
            w_end = float(w.get("end", w_start))

            # Clamp end time so words don't overlap too much
            if j < len(words) - 1:
                next_start = float(words[j + 1].get("start", w_end))
                if next_start > w_start:
                    w_end = min(w_end, next_start - epsilon)
            if w_end <= w_start:
                w_end = w_start + 0.05

            text = w["text"]
            group_id = w.get("group")
            base_color = group_to_color(group_id)
            emph = int(w.get("emphasis", 0))

            # Emphasis tweaks (stroke + size)
            stroke_color = None
            stroke_width = 0
            fontsize = 48
            if emph == 1:
                stroke_color = "white"
                stroke_width = 1
            elif emph == 2:
                stroke_color = "white"
                stroke_width = 2
                fontsize = 56

            # Prefix text up to this word, to estimate its x-position
            prefix_text = " ".join(ww["text"] for ww in words[:j])
            if prefix_text:
                prefix_text += " "

            if prefix_text:
                prefix_clip = TextClip(
                    prefix_text,
                    fontsize=base_fontsize,
                    color="white",
                    method="caption",
                    size=(width - 160, None),
                    align="center",
                )
                prefix_w, _ = prefix_clip.size
            else:
                prefix_w = 0

            # Word clip (colored) overlaid where the word lives in the line
            word_clip = TextClip(
                text,
                fontsize=fontsize,
                color=base_color,
                method="caption",
                size=(width - 160, None),
                align="west",  # IM7-safe: gravity West, not "left"
                stroke_color=stroke_color,
                stroke_width=stroke_width,
            )
            word_w, word_h = word_clip.size

            word_x = base_x + prefix_w
            word_y = y_line

            word_clip = (
                word_clip.set_position((word_x, word_y))
                .set_start(w_start)
                .set_end(w_end)
            )

            clips.append(word_clip)

    video = CompositeVideoClip(clips).set_audio(audio)
    video = video.set_duration(duration)

    # Write out the final video
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
        description="Render karaoke-style lyric video from alignment JSON."
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
        help="Path to output video file (e.g., output_colored.mp4)",
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
    build_video(
        audio_path=args.audio,
        alignment=alignment,
        output_path=args.out,
        width=args.width,
        height=args.height,
        fps=args.fps,
    )


if __name__ == "__main__":
    main()
