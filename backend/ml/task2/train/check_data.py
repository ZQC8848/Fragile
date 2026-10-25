"""Check that character spans survive the round trip to subword-token tags and back (needed for the token head).

For every single-box example with segmentation labels: tag each mDeBERTa token by the channel covering most
of its characters, then turn the token tags back into character spans and compare with the original spans
(both trimmed of spaces and quotes). Reports the share of examples that round-trip exactly.

    python -m task2.train.check_data --examples DATA/examples/train.jsonl --tokenizer microsoft/mdeberta-v3-base
"""

from __future__ import annotations

import argparse
from collections import Counter

from transformers import AutoTokenizer

from .data import char_tags, load_jsonl

EDGE = set(" \t\n\"'“”‘’「」")


def token_tags(offsets, ctags):
    out = []
    for s, e in offsets:
        if e <= s:
            out.append("O")
            continue
        c = Counter(ctags[s:e]).most_common(1)[0][0]
        out.append(c)
    return out


def back_to_chars(n, offsets, ttags):
    ct = ["O"] * n
    for (s, e), t in zip(offsets, ttags):
        for i in range(s, e):
            ct[i] = t
    return ct


def canon(text, tags):
    return [t if not text[i] in EDGE else "O" for i, t in enumerate(tags)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", required=True)
    ap.add_argument("--tokenizer", default="microsoft/mdeberta-v3-base")
    args = ap.parse_args()
    tok = AutoTokenizer.from_pretrained(args.tokenizer)
    exs = [e for e in load_jsonl(args.examples) if e["mask"]["seg"]]
    ok, bad = 0, []
    lens = []
    for e in exs:
        text = e["text"]
        ct = char_tags(text, e["segments"])
        enc = tok(text, return_offsets_mapping=True, add_special_tokens=False)
        lens.append(len(enc["input_ids"]))
        rt = back_to_chars(len(text), enc["offset_mapping"], token_tags(enc["offset_mapping"], ct))
        if canon(text, rt) == canon(text, ct):
            ok += 1
        else:
            bad.append(e)
    n = len(exs)
    print(f"{n} segmented examples; exact round trip {ok}/{n} = {ok / n:.1%}" if n else "no segmented examples")
    if lens:
        lens.sort()
        print(f"player-text tokens: median {lens[len(lens) // 2]}, p95 {lens[int(0.95 * (len(lens) - 1))]}, max {lens[-1]}")
    for e in bad[:10]:
        print("  mismatch:", e["ex_id"], repr(e["text"][:120]))


if __name__ == "__main__":
    main()
