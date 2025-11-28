from flask import Flask, render_template, request, url_for, make_response
from werkzeug.utils import secure_filename
import os
import whisper

from rhyme_core import process_lyrics, process_entries_with_rhymes
from auto_align import auto_align_lyrics_to_audio
from storage import init_db, new_session_id, save_track, list_tracks, load_track

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ALLOWED_AUDIO = {"mp3", "wav", "m4a", "ogg"}

init_db()

SESSION_COOKIE_NAME = "rhyme_session_id"


def allowed_file(filename, allowed_exts):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_exts


def get_session_id():
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if not sid:
        sid = new_session_id()
    return sid


# ---------- Routes ----------


@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/text", methods=["GET", "POST"])
def text_mode():
    """
    Text-only rhyme explorer with 3 views:
      - whole words
      - sub-words
      - phonemes
    """
    highlighted = None
    group_to_color = None
    lyrics = ""
    threshold = 0.6

    if request.method == "POST":
        lyrics = request.form.get("lyrics", "")
        try:
            threshold = float(request.form.get("threshold", "0.6"))
        except ValueError:
            threshold = 0.6
        threshold = max(0.0, min(1.0, threshold))

        if lyrics.strip():
            highlighted, group_to_color = process_lyrics(lyrics, threshold)

    return render_template(
        "index.html",
        lyrics=lyrics,
        threshold=threshold,
        highlighted=highlighted,
        group_to_color=group_to_color,
    )


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/auto", methods=["GET", "POST"])
def auto_mode():
    """
    Auto-align mode:

      - Upload audio
      - Paste lyrics
      - Whisper aligns each line
      - We colorize rhyme families on a static synced view.
    """
    entries = None
    group_to_color = None
    audio_url = None
    lyrics = ""
    threshold = 0.6
    error = None

    session_id = get_session_id()

    if request.method == "POST":
        lyrics = request.form.get("lyrics", "")
        try:
            threshold = float(request.form.get("threshold", "0.6"))
        except ValueError:
            threshold = 0.6
        threshold = max(0.0, min(1.0, threshold))

        audio_file = request.files.get("audio")
        if not audio_file or audio_file.filename == "":
            error = "Please upload an audio file."
        elif not allowed_file(audio_file.filename, ALLOWED_AUDIO):
            error = "Unsupported audio format."

        if not error and not lyrics.strip():
            error = "Please paste the lyrics."

        if not error:
            audio_name = secure_filename(audio_file.filename)
            audio_path = os.path.join(app.config["UPLOAD_FOLDER"], audio_name)
            audio_file.save(audio_path)

            try:
                # auto_align returns line entries with start/end/text/words
                entries = auto_align_lyrics_to_audio(
                    audio_path=audio_path,
                    lyrics_text=lyrics,
                    model_name="small",
                    language="en",
                )
            except Exception as e:
                error = f"Whisper failed: {e}"

            if entries and not error:
                # For auto mode we only care about line text & timings for rhyme
                entries_for_rhyme = [
                    {"start": e["start"], "text": e["text"]} for e in entries
                ]
                entries_with_tokens, group_to_color = process_entries_with_rhymes(
                    entries_for_rhyme, threshold=threshold
                )

                for entry, rhyme_entry in zip(entries, entries_with_tokens):
                    entry["tokens"] = rhyme_entry.get("tokens", [])
                    entry["start"] = rhyme_entry.get("start", entry.get("start", 0.0))
                    entry["end"] = rhyme_entry.get("end", entry.get("end", 0.0))

                audio_url = url_for("static", filename=f"uploads/{audio_name}")

                save_track(
                    session_id=session_id,
                    mode="auto",
                    audio_filename=audio_name,
                    lyrics=lyrics,
                    threshold=threshold,
                    entries=entries,
                )
            elif not error:
                error = "Could not align any lyrics to the audio."

    resp = make_response(
        render_template(
            "auto.html",
            error=error,
            lyrics=lyrics,
            threshold=threshold,
            entries=entries,
            group_to_color=group_to_color,
            audio_url=audio_url,
        )
    )
    resp.set_cookie(SESSION_COOKIE_NAME, session_id, httponly=True, samesite="Lax")
    return resp


@app.route("/perform", methods=["GET", "POST"])
def perform_mode():
    """
    Performance mode:

      - Upload audio
      - Paste lyrics
      - Whisper gives word-level timestamps
      - We align lyrics words -> ASR words and use per-word timings
      - View highlights words in sync with the audio
    """
    entries = None
    group_to_color = None
    audio_url = None
    lyrics = ""
    threshold = 0.6
    error = None

    session_id = get_session_id()

    if request.method == "POST":
        lyrics = request.form.get("lyrics", "")
        try:
            threshold = float(request.form.get("threshold", "0.6"))
        except ValueError:
            threshold = 0.6
        threshold = max(0.0, min(1.0, threshold))

        audio_file = request.files.get("audio")
        if not audio_file or audio_file.filename == "":
            error = "Please upload an audio file."
        elif not allowed_file(audio_file.filename, ALLOWED_AUDIO):
            error = "Unsupported audio format."

        if not error and not lyrics.strip():
            error = "Please paste the lyrics."

        if not error:
            audio_name = secure_filename(audio_file.filename)
            audio_path = os.path.join(app.config["UPLOAD_FOLDER"], audio_name)
            audio_file.save(audio_path)

            try:
                entries = auto_align_lyrics_to_audio(
                    audio_path=audio_path,
                    lyrics_text=lyrics,
                    model_name="small",
                    language="en",
                )
            except Exception as e:
                error = f"Whisper failed: {e}"

            if entries and not error:
                entries_for_rhyme = [
                    {"start": e["start"], "text": e["text"]} for e in entries
                ]
                entries_with_tokens, group_to_color = process_entries_with_rhymes(
                    entries_for_rhyme, threshold=threshold
                )
            elif not error:
                error = "Could not align any lyrics to the audio."

            if entries and not error:
                for entry, rhyme_entry in zip(entries, entries_with_tokens):
                    tokens = rhyme_entry.get("tokens", [])
                    asr_words = entry.get("words", [])

                    line_start = float(entry.get("start", 0.0))
                    line_end = float(entry.get("end", line_start))

                    def safe_time(val, default):
                        try:
                            return float(val) if val is not None else float(default)
                        except Exception:
                            return float(default)

                    word_token_indices = [
                        i for i, t in enumerate(tokens) if t.get("is_word")
                    ]

                    for j, ti in enumerate(word_token_indices):
                        if j < len(asr_words):
                            w = asr_words[j]
                            w_start = safe_time(w.get("start"), line_start)
                            w_end = safe_time(w.get("end"), max(line_start, line_end))
                        else:
                            w_start = line_start
                            w_end = line_end or line_start

                        tokens[ti]["w_start"] = w_start
                        tokens[ti]["w_end"] = w_end

                    entry["tokens"] = tokens
                    entry["start"] = line_start
                    entry["end"] = line_end

                audio_url = url_for("static", filename=f"uploads/{audio_name}")

                save_track(
                    session_id=session_id,
                    mode="perform",
                    audio_filename=audio_name,
                    lyrics=lyrics,
                    threshold=threshold,
                    entries=entries,
                )

    resp = make_response(
        render_template(
            "perform.html",
            error=error,
            lyrics=lyrics,
            threshold=threshold,
            entries=entries,
            group_to_color=group_to_color,
            audio_url=audio_url,
        )
    )
    resp.set_cookie(SESSION_COOKIE_NAME, session_id, httponly=True, samesite="Lax")
    return resp


@app.route("/finetune", methods=["GET", "POST"])
def finetune_mode():
    """
    Finetune mode:

      - Same backend as performance mode (word-level timings)
      - No offset slider – instead, lets you manually mark emphasis levels
        for words in the UI, then export JSON.
    """
    entries = None
    group_to_color = None
    audio_url = None
    lyrics = ""
    threshold = 0.6
    error = None

    session_id = get_session_id()

    if request.method == "POST":
        lyrics = request.form.get("lyrics", "")
        try:
            threshold = float(request.form.get("threshold", "0.6"))
        except ValueError:
            threshold = 0.6
        threshold = max(0.0, min(1.0, threshold))

        audio_file = request.files.get("audio")
        if not audio_file or audio_file.filename == "":
            error = "Please upload an audio file."
        elif not allowed_file(audio_file.filename, ALLOWED_AUDIO):
            error = "Unsupported audio format."

        if not error and not lyrics.strip():
            error = "Please paste the lyrics."

        if not error:
            audio_name = secure_filename(audio_file.filename)
            audio_path = os.path.join(app.config["UPLOAD_FOLDER"], audio_name)
            audio_file.save(audio_path)

            try:
                entries = auto_align_lyrics_to_audio(
                    audio_path=audio_path,
                    lyrics_text=lyrics,
                    model_name="small",
                    language="en",
                )
            except Exception as e:
                error = f"Whisper failed: {e}"

            if entries and not error:
                entries_for_rhyme = [
                    {"start": e["start"], "text": e["text"]} for e in entries
                ]
                entries_with_tokens, group_to_color = process_entries_with_rhymes(
                    entries_for_rhyme, threshold=threshold
                )
            elif not error:
                error = "Could not align any lyrics to the audio."

            if entries and not error:
                for entry, rhyme_entry in zip(entries, entries_with_tokens):
                    tokens = rhyme_entry.get("tokens", [])
                    asr_words = entry.get("words", [])

                    line_start = float(entry.get("start", 0.0))
                    line_end = float(entry.get("end", line_start))

                    def safe_time(val, default):
                        try:
                            return float(val) if val is not None else float(default)
                        except Exception:
                            return float(default)

                    word_token_indices = [
                        i for i, t in enumerate(tokens) if t.get("is_word")
                    ]

                    for j, ti in enumerate(word_token_indices):
                        if j < len(asr_words):
                            w = asr_words[j]
                            w_start = safe_time(w.get("start"), line_start)
                            w_end = safe_time(w.get("end"), max(line_start, line_end))
                        else:
                            w_start = line_start
                            w_end = line_end or line_start

                        tokens[ti]["w_start"] = w_start
                        tokens[ti]["w_end"] = w_end
                        # UI manages emphasis client-side via data-emphasis

                    entry["tokens"] = tokens
                    entry["start"] = line_start
                    entry["end"] = line_end

                audio_url = url_for("static", filename=f"uploads/{audio_name}")

                save_track(
                    session_id=session_id,
                    mode="finetune",
                    audio_filename=audio_name,
                    lyrics=lyrics,
                    threshold=threshold,
                    entries=entries,
                )

    resp = make_response(
        render_template(
            "finetune.html",
            error=error,
            lyrics=lyrics,
            threshold=threshold,
            entries=entries,
            group_to_color=group_to_color,
            audio_url=audio_url,
        )
    )
    resp.set_cookie(SESSION_COOKIE_NAME, session_id, httponly=True, samesite="Lax")
    return resp


@app.route("/transcribe", methods=["GET", "POST"])
def transcribe_mode():
    """
    Transcribe mode:

      - Upload audio
      - Whisper transcribes the lyrics
      - Shows them in a textarea for editing / copy-paste
    """
    lyrics = ""
    audio_url = None
    error = None

    if request.method == "POST":
        audio_file = request.files.get("audio")
        if not audio_file or audio_file.filename == "":
            error = "Please upload an audio file."
        elif not allowed_file(audio_file.filename, ALLOWED_AUDIO):
            error = "Unsupported audio format."
        else:
            audio_name = secure_filename(audio_file.filename)
            audio_path = os.path.join(app.config["UPLOAD_FOLDER"], audio_name)
            audio_file.save(audio_path)
            audio_url = url_for("static", filename=f"uploads/{audio_name}")

            try:
                model = whisper.load_model("small")
                result = model.transcribe(audio_path, language="en")
                segments = result.get("segments", [])
                lines = [
                    seg.get("text", "").strip()
                    for seg in segments
                    if seg.get("text", "").strip()
                ]
                lyrics = "\n".join(lines)
            except Exception as e:
                error = f"Whisper transcription failed: {e}"

    return render_template(
        "transcribe.html",
        error=error,
        lyrics=lyrics,
        audio_url=audio_url,
    )


@app.route("/capture", methods=["GET", "POST"])
def capture_mode():
    """
    Capture mode — a clean, cinematic view optimized for video recording.
    
    This view:
      - Has no UI chrome (no headers, forms, navigation)
      - Is exactly 1280x720 for direct frame capture
      - Features dramatic word highlighting with rhyme colors
      - Exposes window.capturePlayer.setTime(t) for frame-by-frame capture
    
    Usage:
      1. POST with audio file + lyrics to set up the view
      2. Or GET with ?track_id=N to load from saved track
      3. Use capture_video.py to record frames
    """
    entries = None
    audio_url = None
    title = None
    error = None
    
    # Check if loading from a saved track
    track_id = request.args.get("track_id")
    if track_id:
        try:
            track_data = load_track(int(track_id))
            if track_data:
                entries = track_data.get("entries", [])
                audio_filename = track_data.get("audio_filename")
                if audio_filename:
                    audio_url = url_for("static", filename=f"uploads/{audio_filename}")
                title = f"Track #{track_id}"
        except Exception as e:
            error = f"Could not load track: {e}"
    
    # Handle POST for new capture setup
    if request.method == "POST":
        lyrics = request.form.get("lyrics", "")
        title = request.form.get("title", "")
        threshold = 0.6
        try:
            threshold = float(request.form.get("threshold", "0.6"))
        except ValueError:
            pass
        threshold = max(0.0, min(1.0, threshold))

        audio_file = request.files.get("audio")
        if not audio_file or audio_file.filename == "":
            error = "Please upload an audio file."
        elif not allowed_file(audio_file.filename, ALLOWED_AUDIO):
            error = "Unsupported audio format."

        if not error and not lyrics.strip():
            error = "Please paste the lyrics."

        if not error:
            audio_name = secure_filename(audio_file.filename)
            audio_path = os.path.join(app.config["UPLOAD_FOLDER"], audio_name)
            audio_file.save(audio_path)

            raw_entries = None  # Initialize before try block
            try:
                raw_entries = auto_align_lyrics_to_audio(
                    audio_path=audio_path,
                    lyrics_text=lyrics,
                    model_name="small",
                    language="en",
                )
            except Exception as e:
                error = f"Whisper failed: {e}"

            if raw_entries and not error:
                entries_for_rhyme = [
                    {"start": e["start"], "text": e["text"]} for e in raw_entries
                ]
                entries_with_tokens, group_to_color = process_entries_with_rhymes(
                    entries_for_rhyme, threshold=threshold
                )

                # Build capture-friendly entries structure
                entries = []
                for entry, rhyme_entry in zip(raw_entries, entries_with_tokens):
                    tokens = rhyme_entry.get("tokens", [])
                    asr_words = entry.get("words", [])
                    
                    line_start = float(entry.get("start", 0.0))
                    line_end = float(entry.get("end", line_start))

                    def safe_time(val, default):
                        try:
                            return float(val) if val is not None else float(default)
                        except Exception:
                            return float(default)

                    # Build words list for capture template
                    words = []
                    word_token_indices = [i for i, t in enumerate(tokens) if t.get("is_word")]
                    
                    for j, ti in enumerate(word_token_indices):
                        tok = tokens[ti]
                        if j < len(asr_words):
                            w = asr_words[j]
                            w_start = safe_time(w.get("start"), line_start)
                            w_end = safe_time(w.get("end"), line_end)
                        else:
                            w_start = line_start
                            w_end = line_end

                        words.append({
                            "text": tok["text"],
                            "start": w_start,
                            "end": w_end,
                            "group": tok.get("group"),
                            "emphasis": 0,
                        })

                    entries.append({
                        "start": line_start,
                        "end": line_end,
                        "words": words,
                    })

                audio_url = url_for("static", filename=f"uploads/{audio_name}")

    return render_template(
        "capture.html",
        entries=entries,
        audio_url=audio_url,
        title=title,
        error=error,
    )


@app.route("/tracks")
def tracks_list():
    tracks = list_tracks(limit=20)
    return render_template("tracks.html", tracks=tracks)


@app.route("/tracks/<int:track_id>")
def track_detail(track_id):
    data = load_track(track_id)
    if data is None:
        return "Track not found", 404
    return render_template("track_detail.html", track=data)


if __name__ == "__main__":
    app.run(debug=True, port=5001)