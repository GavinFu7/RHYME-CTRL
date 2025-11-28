import re
from collections import Counter
from typing import List, Optional, Tuple, Dict

import pronouncing

# Words we never want to treat as rhymed content
STOP_WORDS = {"a", "an", "the"}

# Regex to split a line into words and punctuation
WORD_RE = re.compile(r"\w+'\w+|\w+|[^\w\s]")


def tokenize_line(line: str) -> List[dict]:
    """
    Tokenize a single line into a list of tokens.

    Each token is:
      {
        "text": original text,
        "is_word": bool,
        "group": None or int (rhyme family id),
        "phones": Optional[List[str]],
        "rhyme_tail": Optional[str],
        "surface_prefix": Optional[str],
        "surface_tail": Optional[str],
        "head_key": Optional[str],  # multi-syllable-ish head rhyme key
      }
    """
    raw_tokens = WORD_RE.findall(line.rstrip("\n"))
    tokens: List[dict] = []
    for tok in raw_tokens:
        is_word = bool(re.match(r"\w", tok))
        tokens.append(
            {
                "text": tok,
                "is_word": is_word,
                "group": None,
                "phones": None,
                "rhyme_tail": None,
                "surface_prefix": None,
                "surface_tail": None,
                "head_key": None,
            }
        )
    return tokens


def phones_for_word(word: str) -> Optional[List[str]]:
    """
    Return a list of ARPABET phones for the word, or None if unknown.
    """
    word = word.lower()
    word = re.sub(r"[^a-z']+", "", word)
    if not word:
        return None

    phones_list = pronouncing.phones_for_word(word)
    if not phones_list:
        return None

    return phones_list[0].split()


def base_phone(phone: str) -> str:
    """
    Strip stress digits from a phone, e.g. AH1 -> AH.
    """
    return re.sub(r"\d", "", phone)


def last_stressed_vowel_index(phones: List[str]) -> Optional[int]:
    """
    Return the index of the last stressed vowel in the phones, or None.
    """
    for i in range(len(phones) - 1, -1, -1):
        if re.search(r"[AEIOU].*\d", phones[i]):
            return i
    return None


def first_stressed_vowel_index(phones: List[str]) -> Optional[int]:
    """
    Return the index of the first stressed vowel in the phones, or None.
    """
    for i, ph in enumerate(phones):
        if re.search(r"[AEIOU].*\d", ph):
            return i
    return None


def rhyme_tail_phones(phones: List[str]) -> List[str]:
    """
    Return the subsequence of phones that represents the rhyme "tail":

      - From the last stressed vowel to the end, if any stressed vowel exists.
      - Otherwise, just the last 2 phones (or all, if <2).
    """
    idx = last_stressed_vowel_index(phones)
    if idx is not None:
        return phones[idx:]
    if len(phones) >= 2:
        return phones[-2:]
    return phones[:]


def head_rhyme_phones(phones: List[str]) -> List[str]:
    """
    Return a short sequence capturing the "head" rhyme region:

      - From the first stressed vowel backwards by up to 1 phone,
        and forwards by up to 2 phones.

    This is a coarse approximation to multi-syllable head patterns,
    useful for chains like foolishly / cluelessly / buffoonishly.
    """
    if not phones:
        return []
    idx = first_stressed_vowel_index(phones)
    if idx is None:
        idx = 0
    start = max(0, idx - 1)
    end = min(len(phones), idx + 3)
    return phones[start:end]


def last_stressed_vowel(phones: List[str]) -> Optional[str]:
    """
    Return the base form of the last stressed vowel, or None.
    """
    idx = last_stressed_vowel_index(phones)
    if idx is None:
        return None
    return base_phone(phones[idx])


def longest_common_suffix(a: List[str], b: List[str]) -> int:
    """Return length of longest common suffix between two lists."""
    max_len = min(len(a), len(b))
    common = 0
    for i in range(1, max_len + 1):
        if a[-i] == b[-i]:
            common += 1
        else:
            break
    return common


def longest_common_prefix(a: List[str], b: List[str]) -> int:
    """Return length of longest common prefix between two lists."""
    max_len = min(len(a), len(b))
    common = 0
    for i in range(max_len):
        if a[i] == b[i]:
            common += 1
        else:
            break
    return common


def rhyme_similarity(p1: List[str], p2: List[str]) -> float:
    """
    Compute a rhyme similarity score in [0, 1].

    Components:
      - stressed vowel match (strong)
      - tail similarity (suffix of phones)
      - head-phones similarity (multi-syllable head rhyme)
    """
    if not p1 or not p2:
        return 0.0

    v1 = last_stressed_vowel(p1)
    v2 = last_stressed_vowel(p2)

    # Vowel nucleus
    vowel_score = 0.0
    if v1 and v2 and v1 == v2:
        vowel_score = 0.65

    # Tail similarity
    t1 = [base_phone(ph) for ph in rhyme_tail_phones(p1)]
    t2 = [base_phone(ph) for ph in rhyme_tail_phones(p2)]
    if t1 and t2:
        tail_common = longest_common_suffix(t1, t2)
        tail_score = tail_common / max(len(t1), len(t2))
    else:
        tail_score = 0.0

    # Head similarity (multi-syllable head rhyme)
    h1 = [base_phone(ph) for ph in head_rhyme_phones(p1)]
    h2 = [base_phone(ph) for ph in head_rhyme_phones(p2)]
    if h1 and h2:
        head_common = longest_common_prefix(h1, h2)
        head_score = head_common / max(len(h1), len(h2))
    else:
        head_score = 0.0

    score = vowel_score + 0.25 * tail_score + 0.15 * head_score
    return min(1.0, score)


# Bigger high-contrast palette (24 colors)
PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
    "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
    "#bcbd22", "#17becf", "#ff6f61", "#6b5b95",
    "#88b04b", "#f7cac9", "#92a8d1", "#955251",
    "#b565a7", "#009b77", "#dd4124", "#45b8ac",
    "#e6b333", "#4a4e4d", "#0e9aa7", "#b3cde0",
]


def surface_split_for_rhyme(word: str, phones: Optional[List[str]]) -> Tuple[str, str]:
    """
    Heuristic mapping from word + phones -> (prefix, rhyme-tail substring).

    This version uses a proportional mapping based on the location of the
    last stressed vowel in phoneme space, so the colored segment tends to
    cover multiple letters/syllables (not just final 'e' or 'y').
    """
    if not word:
        return "", ""

    w = word
    n_chars = len(w)
    if n_chars == 0:
        return "", ""

    # Use phones if available to approximate where the tail begins
    if phones:
        idx = last_stressed_vowel_index(phones)
        if idx is None:
            idx = len(phones) - 2 if len(phones) >= 2 else 0
        # fraction of phones before stressed vowel
        frac = idx / max(len(phones), 1)
        char_start = int(round(frac * n_chars))
        # keep at least 1 char in tail
        char_start = min(char_start, n_chars - 1)
        return w[:char_start], w[char_start:]

    # Fallback: use last vowel letter
    vowels = set("aeiouyAEIOUY")
    last_vowel_index = None
    for i in range(n_chars - 1, -1, -1):
        if w[i] in vowels:
            last_vowel_index = i
            break

    if last_vowel_index is None:
        return "", w

    return w[:last_vowel_index], w[last_vowel_index:]


def group_rhymes(lines_tokens: List[List[dict]], threshold: float = 0.6):
    """
    Assign rhyme family ids ("group") to word tokens in-place with locality.

    Greedy grouping using rhyme_similarity with prototype phones per group,
    plus a position-based locality penalty so nearby rhymes are favored.
    """
    groups: Dict[int, Dict[str, object]] = {}
    next_gid = 0

    # word_refs: (global_pos, line_index, token_index, phones)
    word_refs: List[Tuple[int, int, int, List[str]]] = []

    pos = 0
    for li, line in enumerate(lines_tokens):
        for ti, tok in enumerate(line):
            if not tok["is_word"]:
                continue

            if tok["text"].lower() in STOP_WORDS:
                continue

            phones = phones_for_word(tok["text"])
            if phones is None:
                continue

            # enrich token
            tok["phones"] = phones

            tail_phones = rhyme_tail_phones(phones)
            tok["rhyme_tail"] = " ".join(tail_phones) if tail_phones else ""

            # head key (for possible use later / inspection)
            hphones = head_rhyme_phones(phones)
            tok["head_key"] = " ".join([base_phone(ph) for ph in hphones])

            sprefix, stail = surface_split_for_rhyme(tok["text"], phones)
            tok["surface_prefix"] = sprefix
            tok["surface_tail"] = stail or tok["text"]

            word_refs.append((pos, li, ti, phones))
            pos += 1

    if not word_refs:
        return []

    max_pos = word_refs[-1][0]

    def locality_penalty(cur_pos: int, positions: List[int]) -> float:
        """
        Simple locality penalty in [0, 1]: 0 for same position, up to ~1 for far away.
        """
        if not positions:
            return 0.0
        nearest = min(abs(cur_pos - p) for p in positions)
        if max_pos == 0:
            return 0.0
        return nearest / max_pos  # 0 (close) .. 1 (furthest apart)

    alpha = 0.3  # how much to penalize distance

    for pos, li, ti, phones in word_refs:
        best_gid = None
        best_effective = 0.0

        for gid, info in groups.items():
            proto = info["proto"]
            positions = info["positions"]
            sim = rhyme_similarity(phones, proto)
            if sim < 0.4:  # very weak match: skip
                continue
            pen = locality_penalty(pos, positions)
            effective = sim - alpha * pen
            if effective > best_effective:
                best_effective = effective
                best_gid = gid

        if best_gid is None or best_effective < threshold:
            # Create new group
            gid = next_gid
            next_gid += 1
            groups[gid] = {"proto": phones, "positions": [pos]}
        else:
            gid = best_gid
            groups[gid]["positions"].append(pos)

        lines_tokens[li][ti]["group"] = gid

    return list(groups.keys())


def filter_small_groups(lines_tokens: List[List[dict]], min_size: int = 3) -> None:
    """
    Drop rhyme groups that appear fewer than min_size times.
    """
    counts = Counter()
    for line in lines_tokens:
        for tok in line:
            gid = tok.get("group")
            if gid is not None:
                counts[gid] += 1

    for line in lines_tokens:
        for tok in line:
            gid = tok.get("group")
            if gid is not None and counts[gid] < min_size:
                tok["group"] = None


def assign_colors(lines_tokens: List[List[dict]]) -> Dict[int, str]:
    """
    Build a mapping {group_id -> color_hex} based on the PALETTE,
    only for actually-used groups.
    """
    used_groups = []
    for line in lines_tokens:
        for tok in line:
            gid = tok.get("group")
            if gid is not None and gid not in used_groups:
                used_groups.append(gid)

    return {gid: PALETTE[i % len(PALETTE)] for i, gid in enumerate(sorted(used_groups))}


# ---------- Public helpers used by app.py ----------


def process_lyrics(text: str, threshold: float = 0.6):
    """
    Text-only pipeline:

      input: raw lyrics string
      output: (lines_tokens, group_to_color)
    """
    lines = text.splitlines()
    lines_tokens = [tokenize_line(line) for line in lines]

    # Step 1: assign rhyme groups (with locality awareness)
    group_rhymes(lines_tokens, threshold=threshold)

    # Step 2: keep only real families
    filter_small_groups(lines_tokens, min_size=3)

    # Step 3: color them
    group_to_color = assign_colors(lines_tokens)

    return lines_tokens, group_to_color


def process_entries_with_rhymes(entries, threshold: float = 0.6):
    """
    Timed entries pipeline (for auto-align mode):

      input: entries = [{ "start": float, "text": str }, ...]
      output: (entries_with_tokens, group_to_color)
    """
    lines_tokens = [tokenize_line(e["text"]) for e in entries]

    # Step 1: assign rhyme groups
    group_rhymes(lines_tokens, threshold=threshold)

    # Step 2: keep only real families
    filter_small_groups(lines_tokens, min_size=3)

    # Step 3: color them
    group_to_color = assign_colors(lines_tokens)

    # Attach tokens back to entries
    for entry, tokens in zip(entries, lines_tokens):
        entry["tokens"] = tokens

    return entries, group_to_color
