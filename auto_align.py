import re
import difflib
import whisper
from typing import List, Dict, Optional
from pypinyin import pinyin, Style


def normalize_token(t: str) -> str:
    """
    Normalize a token for comparison:
      - lowercase
      - strip non-alphanumeric
    """
    t = t.lower()
    t = re.sub(r"[^a-z]+", "", t)
    return t


def transcribe_with_words(
    audio_path: str,
    lyrics_text: str,
    model_name: str = "small",
    language: str = "en",
):
    """
    Run Whisper on the audio and return segments with word-level timings if available.

    Requires a recent version of openai-whisper that supports word_timestamps=True.
    """

    prompt = None
    if language == "yue":
        sentence = re.split(r'[\s,.!?;:()，。！？；：（）]+', lyrics_text.replace('\n', ' '))
        sentence = list(set(filter(None, sentence)))
        if len(sentence) > 70:
            sentence = sentence[:70]        
        prompt = " ".join(sentence)

    model = whisper.load_model(model_name)
    result = model.transcribe(
        audio_path,
        language=language,
        word_timestamps=True,
        initial_prompt=prompt,
        condition_on_previous_text=False,
        temperature=0.0,
    )

    return result


def build_asr_word_sequence(whisper_result, language: str = "en") -> List[Dict]:
    """
    Flatten Whisper segments into a sequence of ASR words:

      [
        {"raw": "give", "norm": "give", "start": 12.34, "end": 12.50},
        ...
      ]
    """
    words: List[Dict] = []

    for seg in whisper_result.get("segments", []):
        for w in seg.get("words", []):
            raw = w.get("word", "").strip()
            if not raw:
                continue
            pinyin_str = ''
            if language == "yue":
                # pinyin returns a list of lists, need to flatten it
                pinyin_list = pinyin(raw, style=Style.TONE3, heteronym=False)
                pinyin_str = " ".join([p[0] if p else "" for p in pinyin_list])
                norm = normalize_token(pinyin_str)
            else:
                norm = normalize_token(raw)
            if not norm:
                continue

            words.append(
                {
                    "raw": raw,
                    "norm": norm,
                    "start": float(w["start"]),
                    "end": float(w["end"]),
                }
            )

    return words


def build_lyrics_word_sequence(lyrics_text: str, language: str = "en") -> List[Dict]:
    """
    Flatten lyrics into a word sequence with line + index information:

      [
        {"raw": "Give", "norm": "give", "line": 0, "idx_in_line": 0},
        ...
      ]

    We'll align this sequence to the ASR word sequence.
    """
    lines = lyrics_text.splitlines()
    words: List[Dict] = []

    for li, line in enumerate(lines):
        # consider the line "empty" if stripped is empty
        stripped = line.strip()
        if not stripped:
            continue
        # split on whitespace (you can make this smarter if needed)

        if language == "yue":
            raw_tokens = list(stripped)
            for wi, raw in enumerate(raw_tokens):
                # pinyin returns a list of lists, need to flatten it
                pinyin_list = pinyin(raw, style=Style.TONE3, heteronym=False)
                pinyin_str = " ".join([p[0] if p else "" for p in pinyin_list])
                norm = normalize_token(pinyin_str)
                if not norm:
                    continue

                words.append(
                    {
                        "raw": raw,
                        "norm": norm,
                        "line": li,
                        "idx_in_line": wi,
                    }
                )
        else:
            raw_tokens = stripped.split()
            for wi, raw in enumerate(raw_tokens):
                norm = normalize_token(raw)
                if not norm:
                    continue

                words.append(
                    {
                        "raw": raw,
                        "norm": norm,
                        "line": li,
                        "idx_in_line": wi,
                    }
                )

    return words


def align_word_sequences(
    lyric_words: List[Dict],
    asr_words: List[Dict],
) -> Dict[int, Optional[int]]:
    """
    Align lyric word sequence to ASR word sequence using difflib.SequenceMatcher.

    Returns:
      mapping: lyric_global_index -> asr_global_index (or None if no match)
    """

    lyric_norms = [w["norm"] for w in lyric_words]
    asr_norms = [w["norm"] for w in asr_words]

    sm = difflib.SequenceMatcher(None, asr_norms, lyric_norms)
    mapping: Dict[int, Optional[int]] = {i: None for i in range(len(lyric_words))}

    for tag, j1, j2, i1, i2 in sm.get_opcodes():
        if tag in ("equal", "replace"):
            # align as many as min(len1, len2), ignore extras
            length = min(i2 - i1, j2 - j1)
            for k in range(length):
                li = i1 + k
                aj = j1 + k
                mapping[li] = aj
        # 'delete' => lyrics-only; mapping stays None
        # 'insert' => asr-only; nothing to do

    return mapping


def auto_align_lyrics_to_audio(
    audio_path: str,
    lyrics_text: str,
    model_name: str = "small",
    language: str = "en",
) -> List[Dict]:
    """
    High-level helper to get line + word-level timings:

      audio_path + lyrics_text
      -> Whisper word timestamps
      -> alignment to lyrics
      -> entries: [
           {
             "start": float, "end": float, "text": line_text,
             "words": [
               {"raw": "Give", "start": 12.34, "end": 12.50},
               ...
             ]
           },
           ...
         ]
    """
    # 1. Transcribe with word-level timestamps
    result = transcribe_with_words(audio_path, lyrics_text=lyrics_text, model_name=model_name, language=language)
    asr_words = build_asr_word_sequence(result, language=language)
    lyric_words = build_lyrics_word_sequence(lyrics_text, language=language)

    if not asr_words or not lyric_words:
        # Fallback: no words -> empty entries
        return []

    # 2. Align sequences
    mapping = align_word_sequences(lyric_words, asr_words)

    # 3. Build per-line structures, assigning times where we have matches
    #    First organize lyric words by line & idx_in_line
    lines = lyrics_text.splitlines()
    # line_index -> list of (idx_in_line, lyric_global_idx)
    line_buckets: Dict[int, List[Tuple[int, int]]] = {}
    for li, w in enumerate(lyric_words):
        line_idx = w["line"]
        if line_idx not in line_buckets:
            line_buckets[line_idx] = []
        line_buckets[line_idx].append((w["idx_in_line"], li))

    entries: List[Dict] = []

    for line_idx, line_text in enumerate(lines):
        # Build the list of words in this line
        raw_tokens = line_text.strip().split() if line_text.strip() else []
        words_for_line: List[Dict] = []

        if line_idx in line_buckets:
            idx_and_global = sorted(line_buckets[line_idx], key=lambda x: x[0])
            for idx_in_line, glob_idx in idx_and_global:
                lw = lyric_words[glob_idx]
                asr_idx = mapping.get(glob_idx)
                if asr_idx is not None:
                    aw = asr_words[asr_idx]
                    words_for_line.append(
                        {
                            "raw": lw["raw"],
                            "start": float(aw["start"]),
                            "end": float(aw["end"]),
                        }
                    )
                else:
                    # no aligned ASR word
                    words_for_line.append(
                        {
                            "raw": lw["raw"],
                            "start": None,
                            "end": None,
                        }
                    )
        # If no words or no matches, we still create an entry
        if words_for_line:
            # derive line start/end from min/max of known word times
            known_starts = [w["start"] for w in words_for_line if w["start"] is not None]
            known_ends = [w["end"] for w in words_for_line if w["end"] is not None]
            if known_starts and known_ends:
                line_start = min(known_starts)
                line_end = max(known_ends)
            else:
                line_start = 0.0
                line_end = 0.0
        else:
            line_start = 0.0
            line_end = 0.0

        entries.append(
            {
                "start": line_start,
                "end": line_end,
                "text": line_text,
                "words": words_for_line,
            }
        )

    return entries
