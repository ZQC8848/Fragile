"""Turn the teacher's tagged echo of a single-box input into character spans on the original text.

The relabel prompt asks the teacher to repeat the player's text verbatim and wrap each part in
<S i=N>…</S> (speech, N = the index of the teacher's speech unit), <A>…</A> (action) or <E>…</E>
(expression). This module

  * parses the tags into spans on the echoed text,
  * checks that the echo, with tags stripped, equals the original once both are normalised
    (quote style, full-width punctuation and whitespace are ignored), and
  * maps the spans back onto the original, trimming quotation marks and spaces off their edges
    (quotes are tagged O, as the teacher drops them from speech).

When the echo does not match, `fuzzy_find` locates a channel's text inside the original instead.
Standard library only.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from .labels import TAG_CHANNEL
from .textnorm import normalize, normalize_with_map

_TAG = re.compile(r"<(/?)([SAE])(?:\s+i\s*=\s*\"?(\d+)\"?)?\s*>")
_EDGE = set(" \t\r\n\"'“”‘’「」『』")


@dataclass
class Span:
    channel: str  # speech | action | expression
    start: int
    end: int
    unit: int | None = None  # speech unit index from <S i=N>

    def as_dict(self) -> dict:
        return {"channel": self.channel, "start": self.start, "end": self.end, "unit": self.unit}


class TagError(ValueError):
    pass


def parse_tagged(tagged: str) -> tuple[str, list[Span]]:
    """(plain text, spans on the plain text). Raises TagError on nesting or unbalanced tags."""
    plain: list[str] = []
    spans: list[Span] = []
    open_tag: tuple[str, int, int | None] | None = None
    pos = 0
    for m in _TAG.finditer(tagged):
        plain.append(tagged[pos:m.start()])
        pos = m.end()
        closing, tag, idx = m.group(1) == "/", m.group(2), m.group(3)
        here = sum(len(p) for p in plain)
        if not closing:
            if open_tag is not None:
                raise TagError("nested tag")
            open_tag = (tag, here, int(idx) if idx is not None else None)
        else:
            if open_tag is None or open_tag[0] != tag:
                raise TagError("unbalanced tag")
            spans.append(Span(TAG_CHANNEL[tag], open_tag[1], here, open_tag[2]))
            open_tag = None
    plain.append(tagged[pos:])
    if open_tag is not None:
        raise TagError("unclosed tag")
    return "".join(plain), spans


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start] in _EDGE:
        start += 1
    while end > start and text[end - 1] in _EDGE:
        end -= 1
    return start, end


def align_tagged(original: str, tagged: str) -> list[Span] | None:
    """Spans on `original`, or None when the echo is not the original (after normalisation)."""
    try:
        plain, spans = parse_tagged(tagged)
    except TagError:
        return None
    n_orig, map_orig = normalize_with_map(original)
    n_plain, map_plain = normalize_with_map(plain)
    if n_orig != n_plain:
        return None
    out: list[Span] = []
    for sp in spans:
        ks = [k for k, p in enumerate(map_plain) if sp.start <= p < sp.end]
        if not ks:
            continue
        start, end = _trim(original, map_orig[ks[0]], map_orig[ks[-1]] + 1)
        if start < end:
            out.append(Span(sp.channel, start, end, sp.unit))
    out.sort(key=lambda s: s.start)
    for a, b in zip(out, out[1:]):
        if b.start < a.end:
            return None
    return out


def fuzzy_find(original: str, needle: str, threshold: float = 0.75) -> tuple[int, int] | None:
    """Locate `needle` (one channel's text, in the original language) inside `original`.

    Exact match on the normalised strings first, then the best difflib window. Returns original offsets.
    """
    needle_n = normalize(needle).strip("\"' ")
    if not needle_n:
        return None
    n_orig, map_orig = normalize_with_map(original)
    k = n_orig.find(needle_n)
    if k < 0:
        best, best_k, best_len = 0.0, -1, 0
        L = len(needle_n)
        for length in {max(1, int(L * f)) for f in (0.8, 0.9, 1.0, 1.1, 1.2)}:
            for i in range(0, max(1, len(n_orig) - length + 1)):
                r = difflib.SequenceMatcher(None, n_orig[i:i + length], needle_n, autojunk=False).ratio()
                if r > best:
                    best, best_k, best_len = r, i, length
        if best < threshold:
            return None
        k, L = best_k, best_len
    else:
        L = len(needle_n)
    start, end = _trim(original, map_orig[k], map_orig[k + L - 1] + 1)
    return (start, end) if start < end else None


_SENT = re.compile(r"[^.!?。！？…]+[.!?。！？…]*")


def split_sentences(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Sentence spans inside text[start:end], trimmed."""
    out = []
    for m in _SENT.finditer(text, start, end):
        s, e = _trim(text, m.start(), m.end())
        if s < e:
            out.append((s, e))
    return out


def assign_units(original: str, spans: list[Span], units: list[dict]) -> tuple[list[tuple[int, int] | None], str]:
    """Character span for each teacher unit, and how it was found.

    Speech units use their <S i=N> index when every speech unit got exactly one; otherwise speech spans are
    split into sentences and matched in order when the counts agree, and a lone speech unit takes all of the
    speech. Action and expression units take the union of their channel's spans. Returns (spans, method);
    a None entry means that unit could not be placed.
    """
    out: list[tuple[int, int] | None] = [None] * len(units)
    by_channel: dict[str, list[Span]] = {"speech": [], "action": [], "expression": []}
    for sp in spans:
        by_channel[sp.channel].append(sp)
    speech_units = [i for i, u in enumerate(units) if u.get("channel") == "speech" and u.get("act") != "silence"]
    method = "indexed"
    indexed = {sp.unit: (sp.start, sp.end) for sp in by_channel["speech"] if sp.unit is not None}
    if speech_units and sorted(indexed) == list(range(len(speech_units))):
        for j, ui in enumerate(speech_units):
            out[ui] = indexed[j]
    elif speech_units:
        method = "ordered"
        sents = [s for sp in by_channel["speech"] for s in split_sentences(original, sp.start, sp.end)]
        if len(sents) == len(speech_units):
            for ui, s in zip(speech_units, sents):
                out[ui] = s
        elif len(speech_units) == 1 and by_channel["speech"]:
            out[speech_units[0]] = (by_channel["speech"][0].start, by_channel["speech"][-1].end)
        else:
            method = "unplaced"
    for i, u in enumerate(units):
        ch = u.get("channel")
        if ch in ("action", "expression") and by_channel[ch]:
            out[i] = (by_channel[ch][0].start, by_channel[ch][-1].end)
    return out, method
