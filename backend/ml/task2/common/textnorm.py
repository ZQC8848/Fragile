"""Text normalisation that remembers where every character came from.

The teacher may change quote styles, full-width punctuation or whitespace when it echoes the player's
text. Comparing normalised strings makes those differences invisible, and the index map lets offsets in
the normalised string be mapped back onto the original input.
"""

from __future__ import annotations

import unicodedata

#: quotes folded to their ASCII form before comparing
_QUOTES = {
    "“": '"', "”": '"', "„": '"', "‟": '"', "「": '"', "」": '"', "『": '"', "』": '"',
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
}


def _fold(ch: str) -> str:
    ch = _QUOTES.get(ch, ch)
    return unicodedata.normalize("NFKC", ch)


def normalize(text: str) -> str:
    return normalize_with_map(text)[0]


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    """(normalised text, index map): out[i] came from text[index_map[i]].

    Folds quotes, applies NFKC per character, turns every whitespace run into one space and strips the ends.
    """
    out: list[str] = []
    idx: list[int] = []
    pending_space = -1
    for i, ch in enumerate(text):
        if ch.isspace():
            if out and pending_space < 0:
                pending_space = i
            continue
        if pending_space >= 0:
            out.append(" ")
            idx.append(pending_space)
            pending_space = -1
        for c in _fold(ch):
            out.append(c)
            idx.append(i)
    return "".join(out), idx


def strip_quotes(text: str) -> str:
    t = normalize(text)
    return t.strip('"\'').strip()
