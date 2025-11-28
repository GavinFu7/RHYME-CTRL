#!/usr/bin/env python3
"""
capture_video.py

Capture the /capture cinematic view frame-by-frame using Playwright,
then combine frames + audio into a polished video using ffmpeg.

This script:
  - Navigates to the /capture endpoint (or any given URL)
  - Uploads audio + lyrics and submits the form to generate the capture view
  - Waits for window.capturePlayer.setTime to be available
  - Steps through time, calling capturePlayer.setTime(t) to update
  - Screenshots each frame at 1280x720
  - Uses ffmpeg to build the final MP4 with audio

Requirements:
  pip install playwright moviepy
  python -m playwright install chromium
  ffmpeg installed on your system.

Usage:

  # 1) In one terminal, run the Flask app (with /capture route wired to capture.html)
  source .venv/bin/activate
  python3 app.py

  # 2) In another terminal, run this script:
  source .venv/bin/activate
  python3 capture_video.py \
    --url "http://127.0.0.1:5001/capture" \
    --audio static/uploads/Mos-Def-on-Thieves-in-the-Night-Verse-2_Media_ouW9xezYVCY_001_1080p.mp3 \
    --lyrics-file lyrics.txt \
    --title "Mos Def — Thieves in the Night (Verse 2)" \
    --fps 30 \
    --frames frames_capture \
    --out output_cinematic.mp4
"""

import argparse
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from moviepy.editor import AudioFileClip
from playwright.sync_api import sync_playwright


def log(*args):
    print("[capture_video]", *args, flush=True)


def get_duration(audio_path: str) -> float:
    """Get audio duration in seconds using MoviePy."""
    clip = AudioFileClip(audio_path)
    duration = float(clip.duration)
    clip.close()
    log(f"Audio duration: {duration:.2f}s")
    return duration


def prepare_capture_view(
    page,
    url: str,
    audio_path: str,
    lyrics_path: Optional[str],
    title: Optional[str],
    threshold: float,
):
    """
    Load the /capture page, fill the form (audio+lyrics+title+threshold),
    submit it, and wait until the cinematic view is ready and
    window.capturePlayer is available.
    """
    log("Navigating to capture URL:", url)
    page.goto(url)
    page.wait_for_timeout(1500)  # base load

    # Fill lyrics textarea if provided
    if lyrics_path is not None:
        log("Filling lyrics from:", lyrics_path)
        with open(lyrics_path, "r", encoding="utf-8") as f:
            lyrics_text = f.read()
        page.fill("textarea#lyrics", lyrics_text)

    # Upload audio file
    log("Uploading audio:", audio_path)
    page.set_input_files("input#audio", audio_path)

    # Optional title
    if title:
        try:
            log("Setting title:", title)
            page.fill("input#title", title)
        except Exception as e:
            log("Warning: could not set title:", e)

    # Rhyme threshold (if field exists)
    try:
        page.fill("input#threshold", str(threshold))
    except Exception:
        pass

    # Submit the form ("Generate Capture View" button)
    log("Clicking 'Generate Capture View'...")
    page.click("text=Generate Capture View")

    # Wait for the cinematic capture view to appear.
    # We don't care if audio is visible; we only need capturePlayer.
    log("Waiting for capturePlayer.setTime to become available...")
    page.wait_for_function(
        "() => window.capturePlayer && typeof window.capturePlayer.setTime === 'function'",
        timeout=60000,
    )
    log("capturePlayer is ready.")

    # Small extra delay for fonts/layout
    page.wait_for_timeout(2000)


def capture_frames(
    url: str,
    audio_path: str,
    lyrics_path: Optional[str],
    title: Optional[str],
    duration: float,
    fps: int,
    out_dir: str,
    threshold: float = 0.6,
    headful: bool = False,
):
    """
    Drive the /capture page through time, capturing PNG frames at each
    timestamp using window.capturePlayer.setTime(t).
    """
    out_path = Path(out_dir)

    # Clean out old frames if present
    if out_path.exists():
        shutil.rmtree(out_path)
    out_path.mkdir(parents=True, exist_ok=True)
    log("Frames directory:", out_path)

    frame_count = int(math.ceil(duration * fps))
    log(f"Capturing {frame_count} frames at {fps} fps")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headful)
        page = browser.new_page(
            viewport={"width": 1280, "height": 720},
            device_scale_factor=1,
        )

        # 1) Load and prepare the capture view
        prepare_capture_view(
            page, url, audio_path, lyrics_path, title, threshold
        )

        # 2) If capturePlayer exposes its own duration, prefer that
        try:
            duration_in_page = page.evaluate(
                "() => window.capturePlayer.getDuration && window.capturePlayer.getDuration()"
            )
            if duration_in_page:
                duration = float(duration_in_page)
                frame_count = int(math.ceil(duration * fps))
                log(f"Using capturePlayer duration: {duration:.2f}s, {frame_count} frames")
        except Exception as e:
            log("Warning: could not read capturePlayer.getDuration():", e)

        # 3) Actually capture frames
        for i in range(frame_count):
            t = i / fps
            if i % 50 == 0 or i == frame_count - 1:
                log(f"Capturing frame {i+1}/{frame_count} at t={t:.2f}s")

            page.evaluate(
                "(t) => { if (window.capturePlayer) { window.capturePlayer.setTime(t); } }",
                t,
            )
            page.wait_for_timeout(20)
            frame_path = out_path / f"frame_{i:05d}.png"
            page.screenshot(path=str(frame_path), full_page=False)

        # Optional debug screenshot of the last state
        debug_path = out_path / "debug_last.png"
        page.screenshot(path=str(debug_path), full_page=False)
        log("Saved debug screenshot:", debug_path)

        browser.close()
        log("Browser closed.")


def build_video(frames_dir: str, audio_path: str, out_path: str, fps: int):
    """
    Combine frames and audio into a final MP4 using ffmpeg.
    """
    frames_pattern = str(Path(frames_dir) / "frame_%05d.png")
    log("Building video with ffmpeg...")
    cmd = [
        "ffmpeg",
        "-y",
        "-framerate", str(fps),
        "-i", frames_pattern,
        "-i", audio_path,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    log("Video written to:", out_path)


def main():
    parser = argparse.ArgumentParser(
        description="Capture /capture cinematic view as video."
    )
    parser.add_argument("--url", required=True, help="URL of /capture view")
    parser.add_argument("--audio", required=True, help="Path to audio file (mp3)")
    parser.add_argument(
        "--lyrics-file", help="Path to lyrics .txt file", default=None
    )
    parser.add_argument("--title", help="Optional title", default=None)
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.6,
        help="Rhyme threshold for capture form (default: 0.6)",
    )
    parser.add_argument("--fps", type=int, default=30, help="Frames per second")
    parser.add_argument(
        "--frames",
        default="frames_capture",
        help="Directory for PNG frames (default: frames_capture)",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output video path (e.g., output_cinematic.mp4)",
    )
    parser.add_argument(
        "--keep-frames",
        action="store_true",
        help="Keep PNG frames instead of deleting them",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Run Playwright with a visible browser window for debugging.",
    )
    args = parser.parse_args()

    if not os.path.exists(args.audio):
        raise FileNotFoundError(f"Audio file not found: {args.audio}")
    if args.lyrics_file and not os.path.exists(args.lyrics_file):
        raise FileNotFoundError(f"Lyrics file not found: {args.lyrics_file}")

    # 1) Determine duration from audio
    duration = get_duration(args.audio)

    # 2) Capture frames from the cinematic capture view
    capture_frames(
        url=args.url,
        audio_path=args.audio,
        lyrics_path=args.lyrics_file,
        title=args.title,
        duration=duration,
        fps=args.fps,
        out_dir=args.frames,
        threshold=args.threshold,
        headful=args.headful,
    )

    # 3) Check we actually captured frames
    frame_files = list(Path(args.frames).glob("frame_*.png"))
    if not frame_files:
        log("ERROR: No frames were captured. Check debug_last.png in", args.frames)
        return

    # 4) Combine frames + audio into MP4
    build_video(args.frames, args.audio, args.out, args.fps)

    # 5) Cleanup if not requested to keep
    if not args.keep_frames:
        shutil.rmtree(args.frames)
        log(f"Cleaned up {args.frames}/")


if __name__ == "__main__":
    main()
