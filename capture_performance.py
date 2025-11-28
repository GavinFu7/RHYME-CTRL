#!/usr/bin/env python3
"""
capture_performance.py

Capture the /perform HTML view frame-by-frame using Playwright,
then combine frames + audio into a video using ffmpeg.

This script:

  - Navigates to the provided URL (typically /perform).
  - Uploads the specified audio file.
  - Pastes lyrics from a .txt file into the textarea.
  - Clicks "Upload & Perform".
  - Waits for the synced view to render.
  - Steps through time, calling window.rhymePlayer.setTime(t) to
    update highlighting.
  - Screenshots each frame and uses ffmpeg to build an MP4.

Requirements:
  pip install playwright moviepy
  python -m playwright install chromium
  ffmpeg installed on your system.

Usage:

  # In one terminal:
  source .venv/bin/activate
  python3 app.py

  # In another terminal:
  source .venv/bin/activate
  python3 capture_performance.py \
    --url "http://127.0.0.1:5001/perform" \
    --audio static/uploads/your_track.mp3 \
    --lyrics-file lyrics.txt \
    --fps 30 \
    --frames frames_perf \
    --out thieves_perf_from_html.mp4
"""

import argparse
import math
import os
import subprocess
from pathlib import Path

from moviepy.editor import AudioFileClip
from playwright.sync_api import sync_playwright


def get_duration(audio_path: str) -> float:
    clip = AudioFileClip(audio_path)
    d = float(clip.duration)
    clip.close()
    return d


def capture_frames(url: str, audio_path: str, lyrics_path: str, duration: float, fps: int, out_dir: str):
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    frame_count = int(math.ceil(duration * fps))

    with open(lyrics_path, "r", encoding="utf-8") as f:
        lyrics_text = f.read()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 1280, "height": 720},
            device_scale_factor=1,
        )
        page.goto(url)
        # Allow base page to load
        page.wait_for_timeout(2000)

        # Fill lyrics and upload audio through the form
        page.fill("textarea#lyrics", lyrics_text)
        page.set_input_files("input#audio", audio_path)

        # Click "Upload & Perform"
        page.click("text=Upload & Perform")

        # Wait for the synced view to show up (audio player + perf words)
        page.wait_for_selector("audio#audio-player")
        page.wait_for_selector(".perf-word")

        # Let layout settle
        page.wait_for_timeout(1500)

        for i in range(frame_count):
            t = i / fps
            # Set time & update the view via rhymePlayer
            page.evaluate(
                """(t) => {
                    if (window.rhymePlayer) {
                      window.rhymePlayer.setTime(t);
                    }
                }""",
                t,
            )
            # Small delay for layout/paints
            page.wait_for_timeout(20)
            frame_path = out_path / f"frame_{i:05d}.png"
            page.screenshot(path=str(frame_path), full_page=False)

        browser.close()


def build_video_from_frames(frames_dir: str, audio_path: str, out_path: str, fps: int):
    frames_pattern = str(Path(frames_dir) / "frame_%05d.png")
    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(fps),
        "-i",
        frames_pattern,
        "-i",
        audio_path,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        out_path,
    ]
    subprocess.run(cmd, check=True)


def main():
    parser = argparse.ArgumentParser(description="Capture performance view as video.")
    parser.add_argument("--url", required=True, help="URL of /perform view")
    parser.add_argument("--audio", required=True, help="Path to audio file (mp3)")
    parser.add_argument("--lyrics-file", required=True, help="Path to lyrics .txt file")
    parser.add_argument("--fps", type=int, default=30, help="Frames per second")
    parser.add_argument("--frames", default="frames_perf", help="Directory for PNG frames")
    parser.add_argument(
        "--out", required=True, help="Output video path (e.g., thieves_perf_from_html.mp4)"
    )
    args = parser.parse_args()

    if not os.path.exists(args.audio):
        raise FileNotFoundError(f"Audio file not found: {args.audio}")
    if not os.path.exists(args.lyrics_file):
        raise FileNotFoundError(f"Lyrics file not found: {args.lyrics_file}")

    duration = get_duration(args.audio)
    capture_frames(args.url, args.audio, args.lyrics_file, duration, args.fps, args.frames)
    build_video_from_frames(args.frames, args.audio, args.out, args.fps)


if __name__ == "__main__":
    main()
